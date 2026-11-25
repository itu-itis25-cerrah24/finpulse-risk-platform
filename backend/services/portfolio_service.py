"""Portfolio analytics: combines market data with the risk engine.

Keeps the HTTP layer thin: endpoints only load rows from the database and hand
them to the functions in this module.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from models import WatchlistItem
from schemas import (
    HeadlineOut,
    PortfolioOut,
    PortfolioSummaryOut,
    PositionOut,
    PricePointOut,
    QuantMetricsOut,
    SentimentOut,
    StockHistoryOut,
)
from services.market_service import MarketService, NewsHeadline
from services.risk_engine import (
    QuantMetrics,
    SentimentSummary,
    analyze_headlines,
    calculate_position_pnl,
    calculate_risk_score,
    classify_daily_change,
    classify_risk_level,
    compute_quant_metrics,
)

MAX_PARALLEL_FETCHES = 8


@dataclass(frozen=True)
class PositionInput:
    """Plain, thread-safe copy of a watchlist row (ORM objects stay in the request thread)."""

    id: int
    symbol: str
    shares: float
    avg_cost: float
    risk_threshold_pct: float

    @classmethod
    def from_model(cls, item: WatchlistItem) -> PositionInput:
        return cls(
            id=item.id,
            symbol=item.symbol,
            shares=item.shares,
            avg_cost=item.avg_cost,
            risk_threshold_pct=item.risk_threshold_pct,
        )


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _quant_out(metrics: QuantMetrics) -> QuantMetricsOut:
    return QuantMetricsOut(
        annualized_volatility_pct=metrics.annualized_volatility_pct,
        var_95_pct=metrics.var_95_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        observations=metrics.observations,
    )


def _sentiment_out(summary: SentimentSummary) -> SentimentOut:
    return SentimentOut(label=summary.label, score=summary.score, headline_count=summary.headline_count)


def _headlines_out(news: list[NewsHeadline], summary: SentimentSummary) -> list[HeadlineOut]:
    return [
        HeadlineOut(
            title=item.title,
            publisher=item.publisher,
            link=item.link,
            published_at=item.published_at,
            sentiment_score=scored.compound,
            sentiment_label=scored.label,
        )
        for item, scored in zip(news, summary.headlines, strict=True)
    ]


def _score(metrics: QuantMetrics, change_pct: float | None, sentiment: SentimentSummary) -> float:
    return calculate_risk_score(
        volatility_pct=metrics.annualized_volatility_pct,
        var_95_pct=metrics.var_95_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        daily_change_pct=change_pct,
        # With no headlines there is no sentiment signal, so leave it out of the blend.
        sentiment_score=sentiment.score if sentiment.headline_count else None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_position(position: PositionInput, market: MarketService) -> PositionOut:
    snapshot = market.get_snapshot(position.symbol)
    quote = snapshot.quote

    metrics = compute_quant_metrics([p.close for p in snapshot.history])
    sentiment = analyze_headlines([h.title for h in snapshot.news])
    risk_score = _score(metrics, quote.change_pct, sentiment)
    cost_basis = round(position.shares * position.avg_cost, 2)

    market_value = pnl = pnl_pct = fx_rate = market_value_usd = pnl_usd = None
    if quote.price is not None:
        position_pnl = calculate_position_pnl(position.shares, position.avg_cost, quote.price)
        market_value = position_pnl.market_value
        pnl = position_pnl.unrealized_pnl
        pnl_pct = position_pnl.unrealized_pnl_pct
        fx_rate = market.get_fx_rate_to_usd(quote.currency)
        if fx_rate is not None:
            market_value_usd = round(market_value * fx_rate, 2)
            pnl_usd = round(pnl * fx_rate, 2)

    return PositionOut(
        id=position.id,
        symbol=position.symbol,
        shares=position.shares,
        avg_cost=position.avg_cost,
        risk_threshold_pct=position.risk_threshold_pct,
        currency=quote.currency,
        data_available=quote.is_available,
        price=quote.price,
        previous_close=quote.previous_close,
        daily_change_pct=None if quote.change_pct is None else round(quote.change_pct, 2),
        daily_flag=classify_daily_change(quote.change_pct, position.risk_threshold_pct),
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pnl=pnl,
        unrealized_pnl_pct=pnl_pct,
        fx_rate_to_usd=fx_rate,
        market_value_usd=market_value_usd,
        unrealized_pnl_usd=pnl_usd,
        quant=_quant_out(metrics),
        sentiment=_sentiment_out(sentiment),
        risk_score=risk_score,
        risk_level=classify_risk_level(risk_score),
    )


def summarize_portfolio(positions: list[PositionOut]) -> PortfolioSummaryOut:
    """Aggregate USD-denominated totals and a market-value-weighted risk score.

    Positions without a live price or FX rate are excluded from the totals but
    still counted in ``position_count``.
    """
    priced = [p for p in positions if p.market_value_usd is not None and p.unrealized_pnl_usd is not None]

    total_value = sum(p.market_value_usd for p in priced)  # type: ignore[misc]
    total_pnl = sum(p.unrealized_pnl_usd for p in priced)  # type: ignore[misc]
    total_cost = total_value - total_pnl
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else None

    if total_value > 0:
        weighted = sum(p.risk_score * p.market_value_usd for p in priced) / total_value  # type: ignore[operator]
    elif positions:
        weighted = sum(p.risk_score for p in positions) / len(positions)
    else:
        weighted = None

    return PortfolioSummaryOut(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=None if total_pnl_pct is None else round(total_pnl_pct, 2),
        weighted_risk_score=None if weighted is None else round(weighted, 1),
        risk_level=None if weighted is None else classify_risk_level(weighted),
        position_count=len(positions),
        priced_position_count=len(priced),
        as_of=datetime.now(timezone.utc),
    )


def build_portfolio(items: list[WatchlistItem], market: MarketService) -> PortfolioOut:
    """Analyze every position concurrently (I/O-bound) and build the summary."""
    inputs = [PositionInput.from_model(item) for item in items]
    if not inputs:
        return PortfolioOut(summary=summarize_portfolio([]), positions=[])

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(inputs))) as pool:
        positions = list(pool.map(lambda p: analyze_position(p, market), inputs))

    return PortfolioOut(summary=summarize_portfolio(positions), positions=positions)


def build_stock_detail(symbol: str, market: MarketService) -> StockHistoryOut | None:
    """Price history, scored headlines and quant metrics for one symbol.

    Returns ``None`` when no market data at all could be retrieved.
    """
    snapshot = market.get_snapshot(symbol)
    quote = snapshot.quote
    if not quote.is_available and not snapshot.history:
        return None

    metrics = compute_quant_metrics([p.close for p in snapshot.history])
    sentiment = analyze_headlines([h.title for h in snapshot.news])
    risk_score = _score(metrics, quote.change_pct, sentiment)

    return StockHistoryOut(
        symbol=symbol,
        currency=quote.currency,
        price=quote.price,
        previous_close=quote.previous_close,
        daily_change_pct=None if quote.change_pct is None else round(quote.change_pct, 2),
        history=[PricePointOut(date=p.date, close=p.close) for p in snapshot.history],
        headlines=_headlines_out(snapshot.news, sentiment),
        sentiment=_sentiment_out(sentiment),
        quant=_quant_out(metrics),
        risk_score=risk_score,
        risk_level=classify_risk_level(risk_score),
    )
