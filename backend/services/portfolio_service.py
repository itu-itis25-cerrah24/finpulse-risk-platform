"""Portfolio analytics: combines market data with the risk engine.

Keeps the HTTP layer thin: endpoints only load rows from the database and hand
them to the functions in this module.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from numpy.typing import NDArray

from models import WatchlistItem
from schemas import (
    AssetMomentsOut,
    BenchmarkOut,
    BenchmarkPointOut,
    CorrelationOut,
    CorrelationPairOut,
    FrontierPointOut,
    HeadlineOut,
    MonteCarloBandOut,
    MonteCarloOut,
    OptimizationOut,
    PortfolioOut,
    PortfolioPointOut,
    PortfolioSummaryOut,
    PositionOut,
    PricePointOut,
    QuantMetricsOut,
    RebalanceAction,
    RebalanceRowOut,
    RebalancingOut,
    ScenarioOut,
    SentimentOut,
    SimulatedHoldingOut,
    StockHistoryOut,
    StressImpactOut,
    StressTestOut,
    StressTestRequest,
    WeightOut,
)
from services.market_service import MarketService, NewsHeadline, PricePoint
from services.monte_carlo import (
    DEFAULT_CONFIDENCE,
    MIN_SIMULATION_OBSERVATIONS,
    DriftModel,
    convert_to_usd,
    log_returns,
    run_monte_carlo,
)
from services.risk_engine import (
    HIGH_CORRELATION_THRESHOLD,
    RISK_FREE_RATE_ANNUAL,
    TRADING_DAYS_PER_YEAR,
    QuantMetrics,
    SentimentSummary,
    align_prices,
    align_returns,
    analyze_headlines,
    average_pairwise_correlation,
    benchmark_for_symbol,
    compare_to_benchmark,
    correlation_matrix,
    correlation_pairs,
    calculate_position_pnl,
    calculate_risk_score,
    classify_daily_change,
    classify_risk_level,
    compute_quant_metrics,
)
from services.optimizer import DEFAULT_SAMPLES, PortfolioPoint, PortfolioStats, optimize_portfolio
from services.stress_test import PRESET_SCENARIOS, Holding, ScenarioDefinition, ShockSet, run_stress_test

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


# ---------------------------------------------------------------------------
# Correlation & benchmark
# ---------------------------------------------------------------------------


def _as_pairs(history: list[PricePoint]) -> list[tuple[str, float]]:
    return [(p.date, p.close) for p in history]


def build_correlation(items: list[WatchlistItem], market: MarketService) -> CorrelationOut:
    """Pearson correlation matrix of date-aligned daily returns across the portfolio."""
    symbols = [item.symbol for item in items]
    if symbols:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(symbols))) as pool:
            histories = dict(zip(symbols, pool.map(market.get_history, symbols), strict=True))
    else:
        histories = {}

    excluded = [s for s in symbols if not histories[s]]
    series = {s: _as_pairs(histories[s]) for s in symbols if histories[s]}
    aligned = align_returns(series)
    matrix = correlation_matrix(aligned.returns)

    def clean(value: float) -> float | None:
        return round(float(value), 4) if math.isfinite(value) else None

    average = average_pairwise_correlation(matrix)
    return CorrelationOut(
        symbols=aligned.symbols,
        matrix=[[clean(v) for v in row] for row in matrix],
        observations=aligned.observations,
        start_date=aligned.dates[0] if aligned.dates else None,
        end_date=aligned.dates[-1] if aligned.dates else None,
        average_correlation=None if average is None else round(average, 4),
        high_correlation_threshold=HIGH_CORRELATION_THRESHOLD,
        high_correlation_pairs=[
            CorrelationPairOut(symbol_a=p.symbol_a, symbol_b=p.symbol_b, correlation=round(p.correlation, 4))
            for p in correlation_pairs(aligned.symbols, matrix)
            if p.correlation > HIGH_CORRELATION_THRESHOLD
        ],
        excluded_symbols=excluded,
    )


class BenchmarkUnavailableError(Exception):
    """Raised when the benchmark index has no price history."""


def build_benchmark_comparison(symbol: str, window_days: int, market: MarketService) -> BenchmarkOut | None:
    """Rebase ``symbol`` and its benchmark to 0% at the start of the window.

    Returns ``None`` when the symbol itself has no history; raises
    ``BenchmarkUnavailableError`` when only the benchmark is missing.
    """
    asset_history = market.get_history(symbol)
    if not asset_history:
        return None

    benchmark_symbol = benchmark_for_symbol(symbol)
    benchmark_history = market.get_history(benchmark_symbol)
    if not benchmark_history:
        raise BenchmarkUnavailableError(f"No price history for benchmark {benchmark_symbol}")

    start_date = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    comparison = compare_to_benchmark(_as_pairs(asset_history), _as_pairs(benchmark_history), start_date)

    return BenchmarkOut(
        symbol=symbol,
        benchmark_symbol=benchmark_symbol,
        window_days=window_days,
        points=[
            BenchmarkPointOut(date=d, asset_pct=round(a, 2), benchmark_pct=round(b, 2))
            for d, a, b in zip(
                comparison.dates, comparison.asset_cumulative_pct, comparison.benchmark_cumulative_pct, strict=True
            )
        ],
        asset_return_pct=comparison.asset_return_pct,
        benchmark_return_pct=comparison.benchmark_return_pct,
        excess_return_pct=comparison.excess_return_pct,
        beta=comparison.beta,
        correlation=comparison.correlation,
        observations=comparison.observations,
    )


# ---------------------------------------------------------------------------
# Risk Lab: valuation, Monte Carlo, stress testing
# ---------------------------------------------------------------------------


class InsufficientDataError(Exception):
    """Raised when no holding has enough priced history to simulate."""


@dataclass(frozen=True)
class HoldingValuation:
    symbol: str
    currency: str | None
    value_usd: float | None


def _value_holding(position: PositionInput, market: MarketService) -> HoldingValuation:
    quote = market.get_quote(position.symbol)
    if quote.price is None:
        return HoldingValuation(position.symbol, quote.currency, None)
    fx_rate = market.get_fx_rate_to_usd(quote.currency)
    value = position.shares * quote.price * fx_rate if fx_rate is not None else None
    return HoldingValuation(position.symbol, quote.currency, value)


def _value_holdings(items: list[WatchlistItem], market: MarketService) -> list[HoldingValuation]:
    """Current USD market value of every position (``None`` when price or FX is missing)."""
    inputs = [PositionInput.from_model(item) for item in items]
    if not inputs:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(inputs))) as pool:
        return list(pool.map(lambda p: _value_holding(p, market), inputs))


def _fetch_histories(symbols: list[str], market: MarketService) -> dict[str, list[PricePoint]]:
    if not symbols:
        return {}
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(symbols))) as pool:
        return dict(zip(symbols, pool.map(market.get_history, symbols), strict=True))


def _fx_symbol(currency: str | None) -> str | None:
    """Yahoo FX pair for a non-USD currency (``TRY`` -> ``TRY=X``), ``None`` for USD."""
    code = (currency or "USD").upper()
    return None if code == "USD" else f"{code}=X"


@dataclass(frozen=True)
class UsdReturns:
    """Date-aligned USD log-returns of every priced holding with history."""

    symbols: list[str]
    values_usd: NDArray[np.float64]  # current market value per symbol
    dates: list[str]  # aligned price dates (one more than returns rows)
    returns: NDArray[np.float64]  # (observations, symbols)
    fx_adjusted: dict[str, bool]
    excluded_symbols: list[str]


def _usd_log_returns(items: list[WatchlistItem], market: MarketService) -> UsdReturns:
    """Shared input for the Monte Carlo engine and the optimiser.

    Non-USD holdings are converted to USD with the daily ``<CCY>=X`` close, so
    returns include currency risk. When no FX history is available a holding
    falls back to local-currency returns (``fx_adjusted=False``). Holdings
    without a price, FX rate or history are excluded.

    Raises ``InsufficientDataError`` below ``MIN_SIMULATION_OBSERVATIONS``
    aligned returns.
    """
    valuations = _value_holdings(items, market)
    priced = [v for v in valuations if v.value_usd is not None and v.value_usd > 0]

    fx_symbols = sorted({fx for v in priced if (fx := _fx_symbol(v.currency)) is not None})
    histories = _fetch_histories([v.symbol for v in priced] + fx_symbols, market)

    series: dict[str, list[tuple[str, float]]] = {}
    fx_adjusted: dict[str, bool] = {}
    value_by_symbol: dict[str, float] = {}
    for v in priced:
        prices = _as_pairs(histories[v.symbol])
        if not prices or v.value_usd is None:
            continue
        fx = _fx_symbol(v.currency)
        fx_history = _as_pairs(histories[fx]) if fx else []
        if fx_history:
            prices = convert_to_usd(prices, fx_history)
        series[v.symbol] = prices
        fx_adjusted[v.symbol] = fx is None or bool(fx_history)
        value_by_symbol[v.symbol] = v.value_usd

    dates, matrix = align_prices(series)
    if not series or len(dates) - 1 < MIN_SIMULATION_OBSERVATIONS:
        raise InsufficientDataError(
            f"Need at least {MIN_SIMULATION_OBSERVATIONS} date-aligned daily returns across priced holdings"
        )

    symbols = list(series)
    return UsdReturns(
        symbols=symbols,
        values_usd=np.array([value_by_symbol[s] for s in symbols]),
        dates=dates,
        returns=log_returns(matrix),
        fx_adjusted=fx_adjusted,
        excluded_symbols=[v.symbol for v in valuations if v.symbol not in series],
    )


def build_monte_carlo(
    items: list[WatchlistItem],
    market: MarketService,
    horizon_days: int,
    simulations: int,
    seed: int | None = None,
    drift_model: DriftModel = DriftModel.HISTORICAL,
) -> MonteCarloOut:
    """Correlated GBM simulation of total portfolio value in USD.

    Raises ``InsufficientDataError`` when fewer than
    ``MIN_SIMULATION_OBSERVATIONS`` aligned returns are available.
    """
    data = _usd_log_returns(items, market)
    symbols, returns, dates, fx_adjusted = data.symbols, data.returns, data.dates, data.fx_adjusted
    initial = data.values_usd
    result = run_monte_carlo(initial, returns, horizon_days, simulations, seed, drift_model)
    summary = result.summary
    total = summary.initial_value

    return MonteCarloOut(
        horizon_days=horizon_days,
        simulations=simulations,
        seed=seed,
        drift_model=drift_model,
        confidence=DEFAULT_CONFIDENCE,
        observations=int(returns.shape[0]),
        start_date=dates[0],
        end_date=dates[-1],
        cholesky_jitter=result.jitter,
        holdings=[
            SimulatedHoldingOut(
                symbol=symbol,
                value_usd=round(float(initial[i]), 2),
                weight_pct=round(float(initial[i]) / total * 100, 2),
                annualized_drift_pct=round(float(result.drift[i]) * TRADING_DAYS_PER_YEAR * 100, 2),
                annualized_volatility_pct=round(
                    float(result.volatility[i]) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 2
                ),
                fx_adjusted=fx_adjusted[symbol],
            )
            for i, symbol in enumerate(symbols)
        ],
        initial_value=round(total, 2),
        expected_value=round(summary.expected_value, 2),
        median_value=round(summary.median_value, 2),
        expected_return_pct=round(summary.expected_return_pct, 2),
        var_95_simulated=round(summary.var, 2),
        var_95_pct=round(summary.var / total * 100, 2),
        cvar_95_simulated=round(summary.cvar, 2),
        cvar_95_pct=round(summary.cvar / total * 100, 2),
        probability_of_loss_pct=round(summary.probability_of_loss_pct, 2),
        bands=[
            MonteCarloBandOut(
                day=day,
                p5=round(float(column[0]), 2),
                p25=round(float(column[1]), 2),
                p50=round(float(column[2]), 2),
                p75=round(float(column[3]), 2),
                p95=round(float(column[4]), 2),
            )
            for day, column in enumerate(result.paths_percentiles.T)
        ],
        excluded_symbols=data.excluded_symbols,
    )


REBALANCE_TOLERANCE_PCT = 0.05  # weight changes below this are reported as HOLD


def _weights_out(symbols: list[str], weights: NDArray[np.float64]) -> list[WeightOut]:
    return [WeightOut(symbol=s, weight_pct=round(float(w) * 100, 2)) for s, w in zip(symbols, weights, strict=True)]


def _point_out(symbols: list[str], point: PortfolioPoint) -> PortfolioPointOut:
    return PortfolioPointOut(
        expected_return_pct=round(point.expected_return * 100, 2),
        volatility_pct=round(point.volatility * 100, 2),
        sharpe_ratio=None if point.sharpe is None else round(point.sharpe, 3),
        weights=_weights_out(symbols, point.weights),
    )


def _frontier_out(stats: PortfolioStats) -> list[FrontierPointOut]:
    return [
        FrontierPointOut(
            expected_return_pct=round(float(r) * 100, 2),
            volatility_pct=round(float(v) * 100, 2),
            sharpe_ratio=round(float(s), 3) if math.isfinite(s) else None,
        )
        for r, v, s in zip(stats.returns, stats.volatility, stats.sharpe, strict=True)
    ]


def rebalancing_plan(
    symbols: list[str],
    current: NDArray[np.float64],
    target: NDArray[np.float64],
    total_value_usd: float,
) -> list[RebalanceRowOut]:
    """Per-symbol weight change and the USD trade needed to reach ``target``."""
    rows: list[RebalanceRowOut] = []
    for symbol, cur, tgt in zip(symbols, current, target, strict=True):
        delta = float(tgt - cur)
        delta_pct = delta * 100
        if abs(delta_pct) < REBALANCE_TOLERANCE_PCT:
            action = RebalanceAction.HOLD
        else:
            action = RebalanceAction.BUY if delta > 0 else RebalanceAction.SELL
        rows.append(
            RebalanceRowOut(
                symbol=symbol,
                current_weight_pct=round(float(cur) * 100, 2),
                target_weight_pct=round(float(tgt) * 100, 2),
                delta_weight_pct=round(delta_pct, 2),
                delta_usd=round(delta * total_value_usd, 2),
                action=action,
            )
        )
    return rows


def build_optimization(
    items: list[WatchlistItem],
    market: MarketService,
    samples: int = DEFAULT_SAMPLES,
    seed: int | None = None,
) -> OptimizationOut:
    """Markowitz long-only optimisation of the current holdings (USD returns)."""
    data = _usd_log_returns(items, market)
    total = float(data.values_usd.sum())
    current_weights = data.values_usd / total
    result = optimize_portfolio(current_weights, data.returns, samples, seed)
    symbols = data.symbols
    asset_vol = np.sqrt(np.diag(result.moments.covariance))

    return OptimizationOut(
        samples=result.samples,
        seed=seed,
        risk_free_rate_pct=RISK_FREE_RATE_ANNUAL * 100,
        observations=int(data.returns.shape[0]),
        start_date=data.dates[0],
        end_date=data.dates[-1],
        covariance_jitter=result.moments.jitter,
        total_value_usd=round(total, 2),
        assets=[
            AssetMomentsOut(
                symbol=s,
                value_usd=round(float(data.values_usd[i]), 2),
                expected_return_pct=round(float(result.moments.mean[i]) * 100, 2),
                volatility_pct=round(float(asset_vol[i]) * 100, 2),
            )
            for i, s in enumerate(symbols)
        ],
        current_portfolio=_point_out(symbols, result.current),
        max_sharpe=_point_out(symbols, result.max_sharpe),
        min_volatility=_point_out(symbols, result.min_volatility),
        frontier_cloud=_frontier_out(result.cloud),
        efficient_frontier=_frontier_out(result.frontier),
        rebalancing=RebalancingOut(
            max_sharpe=rebalancing_plan(symbols, result.current.weights, result.max_sharpe.weights, total),
            min_volatility=rebalancing_plan(symbols, result.current.weights, result.min_volatility.weights, total),
        ),
        excluded_symbols=data.excluded_symbols,
    )


def _scenario_out(definition: ScenarioDefinition) -> ScenarioOut:
    return ScenarioOut(
        key=definition.key,
        label=definition.label,
        description=definition.description,
        us_equity_shock_pct=definition.shocks.us_equity_shock_pct,
        bist_equity_shock_pct=definition.shocks.bist_equity_shock_pct,
        usd_try_shock_pct=definition.shocks.usd_try_shock_pct,
    )


def list_scenarios() -> list[ScenarioOut]:
    return [_scenario_out(definition) for definition in PRESET_SCENARIOS.values()]


def build_stress_test(items: list[WatchlistItem], market: MarketService, request: StressTestRequest) -> StressTestOut:
    """Revalue the portfolio in USD under a preset or custom set of shocks."""
    if request.scenario is not None:
        definition = PRESET_SCENARIOS[request.scenario]
        shocks, label = definition.shocks, definition.label
    else:
        shocks = ShockSet(
            us_equity_shock_pct=request.us_equity_shock_pct,
            bist_equity_shock_pct=request.bist_equity_shock_pct,
            usd_try_shock_pct=request.usd_try_shock_pct,
        )
        label = "Custom shocks"

    valuations = _value_holdings(items, market)
    holdings = [Holding(v.symbol, v.value_usd, v.currency) for v in valuations if v.value_usd is not None]
    result = run_stress_test(holdings, shocks)

    return StressTestOut(
        scenario=request.scenario,
        label=label,
        us_equity_shock_pct=shocks.us_equity_shock_pct,
        bist_equity_shock_pct=shocks.bist_equity_shock_pct,
        usd_try_shock_pct=shocks.usd_try_shock_pct,
        positions=[
            StressImpactOut(
                symbol=i.symbol,
                segment=i.segment,
                currency=i.currency,
                value_before_usd=i.value_before_usd,
                value_after_usd=i.value_after_usd,
                pnl_usd=i.pnl_usd,
                pnl_pct=i.pnl_pct,
                equity_shock_pct=i.equity_shock_pct,
                fx_shock_pct=i.fx_shock_pct,
            )
            for i in result.impacts
        ],
        total_before_usd=result.total_before_usd,
        total_after_usd=result.total_after_usd,
        total_pnl_usd=result.total_pnl_usd,
        total_pnl_pct=result.total_pnl_pct,
        worst_hit_symbol=result.worst_hit_symbol,
        excluded_symbols=[v.symbol for v in valuations if v.value_usd is None],
    )
