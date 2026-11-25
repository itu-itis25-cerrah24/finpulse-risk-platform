"""Quantitative risk engine.

Pure, side-effect-free functions (no I/O) so every metric is trivially unit
testable. All percentage outputs are expressed in percent (e.g. ``23.5`` means
23.5%), not as fractions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache

import numpy as np
from numpy.typing import ArrayLike, NDArray
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_ANNUAL = 0.04
VAR_CONFIDENCE = 0.95
SENTIMENT_NEUTRAL_BAND = 0.05  # VADER's recommended +/- 0.05 compound cut-off

# Composite risk score configuration --------------------------------------
# Each raw metric is linearly scaled to 0-100, saturating at its "cap", then
# blended with the weights below. Missing metrics are dropped and the
# remaining weights are re-normalized.
RISK_SCORE_WEIGHTS: dict[str, float] = {
    "volatility": 0.30,
    "var": 0.25,
    "drawdown": 0.20,
    "daily_move": 0.10,
    "sentiment": 0.15,
}
VOLATILITY_CAP_PCT = 60.0  # 60% annualized vol => maximum volatility risk
VAR_CAP_PCT = 5.0  # 5% one-day VaR => maximum tail risk
DRAWDOWN_CAP_PCT = 40.0  # 40% peak-to-trough => maximum drawdown risk
DAILY_MOVE_CAP_PCT = 10.0  # 10% absolute daily move => maximum event risk
NEUTRAL_RISK_SCORE = 50.0  # returned when no inputs are available at all

LOW_RISK_UPPER = 35.0
MODERATE_RISK_UPPER = 65.0


class DailyRiskFlag(StrEnum):
    HIGH_DROP = "HIGH_DROP"
    HIGH_SPIKE = "HIGH_SPIKE"
    NORMAL = "NORMAL"


class SentimentLabel(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# Return series
# ---------------------------------------------------------------------------


def _clean_prices(prices: ArrayLike) -> NDArray[np.float64]:
    arr = np.asarray(prices, dtype=float)
    return arr[np.isfinite(arr) & (arr > 0)]


def compute_daily_returns(prices: ArrayLike) -> NDArray[np.float64]:
    """Simple daily returns r_t = P_t / P_{t-1} - 1."""
    arr = _clean_prices(prices)
    if arr.size < 2:
        return np.empty(0, dtype=float)
    return np.diff(arr) / arr[:-1]


# ---------------------------------------------------------------------------
# Quant metrics
# ---------------------------------------------------------------------------


def annualized_volatility(returns: ArrayLike) -> float | None:
    """Sample std-dev of daily returns scaled by sqrt(252), in %."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return None
    return float(np.std(r, ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100)


def historical_var(returns: ArrayLike, confidence: float = VAR_CONFIDENCE) -> float | None:
    """One-day historical Value at Risk, reported as a positive loss in %.

    The (1 - confidence) empirical quantile of the return distribution is the
    loss threshold that is only exceeded on the worst 5% of days. If even that
    tail is a gain, VaR is floored at 0.
    """
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return None
    cutoff = float(np.percentile(r, (1 - confidence) * 100))
    return max(0.0, -cutoff) * 100


def max_drawdown(prices: ArrayLike) -> float | None:
    """Largest peak-to-trough decline of the price path, as a negative % (or 0)."""
    arr = _clean_prices(prices)
    if arr.size < 2:
        return None
    running_peak = np.maximum.accumulate(arr)
    drawdowns = arr / running_peak - 1.0
    return float(drawdowns.min() * 100) + 0.0  # "+ 0.0" normalizes -0.0 to 0.0


def sharpe_ratio(returns: ArrayLike, risk_free_rate: float = RISK_FREE_RATE_ANNUAL) -> float | None:
    """Annualized Sharpe ratio: mean daily excess return / std-dev x sqrt(252)."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return None
    std = float(np.std(r, ddof=1))
    if std == 0:
        return None
    daily_excess = float(r.mean()) - risk_free_rate / TRADING_DAYS_PER_YEAR
    return daily_excess / std * math.sqrt(TRADING_DAYS_PER_YEAR)


@dataclass(frozen=True)
class QuantMetrics:
    annualized_volatility_pct: float | None
    var_95_pct: float | None
    max_drawdown_pct: float | None
    sharpe_ratio: float | None
    observations: int


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def compute_quant_metrics(prices: Sequence[float]) -> QuantMetrics:
    """All quant metrics for a closing-price series."""
    returns = compute_daily_returns(prices)
    return QuantMetrics(
        annualized_volatility_pct=_round(annualized_volatility(returns)),
        var_95_pct=_round(historical_var(returns)),
        max_drawdown_pct=_round(max_drawdown(prices)),
        sharpe_ratio=_round(sharpe_ratio(returns), 3),
        observations=int(returns.size),
    )


# ---------------------------------------------------------------------------
# Position-level analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionPnL:
    market_value: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_pnl_pct: float | None


def calculate_position_pnl(shares: float, avg_cost: float, price: float) -> PositionPnL:
    market_value = shares * price
    cost_basis = shares * avg_cost
    pnl = market_value - cost_basis
    pnl_pct = pnl / cost_basis * 100 if cost_basis else None
    return PositionPnL(
        market_value=round(market_value, 2),
        cost_basis=round(cost_basis, 2),
        unrealized_pnl=round(pnl, 2),
        unrealized_pnl_pct=_round(pnl_pct),
    )


def classify_daily_change(change_pct: float | None, threshold_pct: float) -> DailyRiskFlag:
    """Flag a daily move whose magnitude reaches the position's threshold."""
    if change_pct is None:
        return DailyRiskFlag.NORMAL
    if change_pct <= -abs(threshold_pct):
        return DailyRiskFlag.HIGH_DROP
    if change_pct >= abs(threshold_pct):
        return DailyRiskFlag.HIGH_SPIKE
    return DailyRiskFlag.NORMAL


# ---------------------------------------------------------------------------
# News sentiment (VADER)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadlineSentiment:
    title: str
    compound: float
    label: SentimentLabel


@dataclass(frozen=True)
class SentimentSummary:
    label: SentimentLabel
    score: float
    headline_count: int
    headlines: list[HeadlineSentiment] = field(default_factory=list)


@lru_cache(maxsize=1)
def _get_analyzer() -> SentimentIntensityAnalyzer:
    """Load the VADER lexicon once per process."""
    return SentimentIntensityAnalyzer()


def label_from_compound(compound: float) -> SentimentLabel:
    if compound >= SENTIMENT_NEUTRAL_BAND:
        return SentimentLabel.BULLISH
    if compound <= -SENTIMENT_NEUTRAL_BAND:
        return SentimentLabel.BEARISH
    return SentimentLabel.NEUTRAL


def analyze_headlines(headlines: Sequence[str]) -> SentimentSummary:
    """Score each headline and aggregate to a mean compound score + label."""
    analyzer = _get_analyzer()
    scored: list[HeadlineSentiment] = []
    for title in headlines:
        compound = float(analyzer.polarity_scores(title)["compound"])
        scored.append(HeadlineSentiment(title=title, compound=round(compound, 4), label=label_from_compound(compound)))

    if not scored:
        return SentimentSummary(label=SentimentLabel.NEUTRAL, score=0.0, headline_count=0)

    mean = float(np.mean([h.compound for h in scored]))
    return SentimentSummary(
        label=label_from_compound(mean),
        score=round(mean, 4),
        headline_count=len(scored),
        headlines=scored,
    )


# ---------------------------------------------------------------------------
# Composite risk score
# ---------------------------------------------------------------------------


def _scale_to_100(value: float, cap: float) -> float:
    """Linearly map [0, cap] to [0, 100], clamping outside that range."""
    return float(np.clip(value / cap, 0.0, 1.0) * 100)


def calculate_risk_score(
    volatility_pct: float | None,
    var_95_pct: float | None,
    max_drawdown_pct: float | None,
    daily_change_pct: float | None,
    sentiment_score: float | None,
) -> float:
    """Blend the individual risk factors into a single 0-100 score.

    Higher means riskier. Bearish sentiment (compound -> -1) adds risk and
    bullish sentiment (compound -> +1) removes it.
    """
    components: dict[str, float] = {}
    if volatility_pct is not None:
        components["volatility"] = _scale_to_100(volatility_pct, VOLATILITY_CAP_PCT)
    if var_95_pct is not None:
        components["var"] = _scale_to_100(var_95_pct, VAR_CAP_PCT)
    if max_drawdown_pct is not None:
        components["drawdown"] = _scale_to_100(abs(max_drawdown_pct), DRAWDOWN_CAP_PCT)
    if daily_change_pct is not None:
        components["daily_move"] = _scale_to_100(abs(daily_change_pct), DAILY_MOVE_CAP_PCT)
    if sentiment_score is not None:
        clipped = float(np.clip(sentiment_score, -1.0, 1.0))
        components["sentiment"] = (1.0 - clipped) / 2.0 * 100

    if not components:
        return NEUTRAL_RISK_SCORE

    total_weight = sum(RISK_SCORE_WEIGHTS[name] for name in components)
    score = sum(RISK_SCORE_WEIGHTS[name] * value for name, value in components.items()) / total_weight
    return round(float(np.clip(score, 0.0, 100.0)), 1)


def classify_risk_level(score: float) -> RiskLevel:
    if score < LOW_RISK_UPPER:
        return RiskLevel.LOW
    if score < MODERATE_RISK_UPPER:
        return RiskLevel.MODERATE
    return RiskLevel.HIGH


# ---------------------------------------------------------------------------
# Cross-asset analytics: date alignment, correlation, benchmark comparison
# ---------------------------------------------------------------------------

DatedPrices = Sequence[tuple[str, float]]
"""A price series as ``(ISO date, close)`` pairs."""

MIN_CORRELATION_OBSERVATIONS = 3
HIGH_CORRELATION_THRESHOLD = 0.70
US_BENCHMARK = "SPY"
BIST_BENCHMARK = "XU100.IS"


def align_prices(price_series: Mapping[str, DatedPrices]) -> tuple[list[str], NDArray[np.float64]]:
    """Inner-join several price series on their common dates.

    Different exchanges have different holidays (e.g. BIST vs NYSE), so returns
    are only comparable over dates on which *every* instrument traded.

    Returns the sorted common dates and a ``(n_dates, n_symbols)`` price matrix
    whose columns follow the mapping's iteration order.
    """
    symbols = list(price_series)
    if not symbols:
        return [], np.empty((0, 0), dtype=float)

    lookups = [
        {date: float(price) for date, price in price_series[s] if math.isfinite(price) and price > 0}
        for s in symbols
    ]
    common = sorted(set.intersection(*(set(lookup) for lookup in lookups)))
    if not common:
        return [], np.empty((0, len(symbols)), dtype=float)

    matrix = np.array([[lookup[date] for lookup in lookups] for date in common], dtype=float)
    return common, matrix


@dataclass(frozen=True)
class AlignedReturns:
    symbols: list[str]
    dates: list[str]  # the end date of each daily return
    returns: NDArray[np.float64]  # shape (n_observations, n_symbols)

    @property
    def observations(self) -> int:
        return int(self.returns.shape[0])


def align_returns(price_series: Mapping[str, DatedPrices]) -> AlignedReturns:
    """Daily simple returns computed on date-aligned prices, so every row
    measures the same calendar interval for every symbol."""
    dates, prices = align_prices(price_series)
    symbols = list(price_series)
    if len(dates) < 2:
        return AlignedReturns(symbols=symbols, dates=[], returns=np.empty((0, len(symbols)), dtype=float))
    returns = prices[1:] / prices[:-1] - 1.0
    return AlignedReturns(symbols=symbols, dates=dates[1:], returns=returns)


def correlation_matrix(returns: ArrayLike) -> NDArray[np.float64]:
    """Pairwise Pearson correlation of the columns of a returns matrix.

    Entries that are undefined (zero-variance series or fewer than
    ``MIN_CORRELATION_OBSERVATIONS`` rows) are ``NaN``; the diagonal is 1.
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2:
        raise ValueError("returns must be a 2-D (observations x symbols) array")

    n_symbols = r.shape[1]
    if n_symbols == 0:
        return np.empty((0, 0), dtype=float)
    if r.shape[0] < MIN_CORRELATION_OBSERVATIONS:
        corr = np.full((n_symbols, n_symbols), np.nan)
    else:
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.atleast_2d(np.corrcoef(r, rowvar=False))
        corr = np.clip(corr, -1.0, 1.0)  # guard against floating-point overshoot; NaN is preserved
    np.fill_diagonal(corr, 1.0)
    return corr


@dataclass(frozen=True)
class CorrelationPair:
    symbol_a: str
    symbol_b: str
    correlation: float


def correlation_pairs(symbols: Sequence[str], matrix: ArrayLike) -> list[CorrelationPair]:
    """Unique off-diagonal pairs (upper triangle), most correlated first."""
    m = np.asarray(matrix, dtype=float)
    pairs = [
        CorrelationPair(symbols[i], symbols[j], float(m[i, j]))
        for i in range(len(symbols))
        for j in range(i + 1, len(symbols))
        if math.isfinite(m[i, j])
    ]
    return sorted(pairs, key=lambda p: p.correlation, reverse=True)


def average_pairwise_correlation(matrix: ArrayLike) -> float | None:
    """Mean of the defined off-diagonal correlations (a diversification gauge)."""
    m = np.asarray(matrix, dtype=float)
    if m.shape[0] < 2:
        return None
    upper = m[np.triu_indices(m.shape[0], k=1)]
    upper = upper[np.isfinite(upper)]
    return float(upper.mean()) if upper.size else None


def benchmark_for_symbol(symbol: str) -> str:
    """BIST 100 for Borsa Istanbul listings (``.IS``), S&P 500 ETF otherwise."""
    return BIST_BENCHMARK if symbol.strip().upper().endswith(".IS") else US_BENCHMARK


def cumulative_return_pct(prices: ArrayLike) -> NDArray[np.float64]:
    """Cumulative % return relative to the first price (first element is 0)."""
    arr = np.asarray(prices, dtype=float)
    if arr.size == 0:
        return np.empty(0, dtype=float)
    return (arr / arr[0] - 1.0) * 100


def beta(asset_returns: ArrayLike, benchmark_returns: ArrayLike) -> float | None:
    """Sensitivity of the asset to the benchmark: Cov(a, b) / Var(b)."""
    a = np.asarray(asset_returns, dtype=float)
    b = np.asarray(benchmark_returns, dtype=float)
    if a.shape != b.shape or a.size < 2:
        return None
    variance = float(np.var(b, ddof=1))
    if variance == 0:
        return None
    return float(np.cov(a, b, ddof=1)[0, 1]) / variance


@dataclass(frozen=True)
class BenchmarkComparison:
    dates: list[str]
    asset_cumulative_pct: list[float]
    benchmark_cumulative_pct: list[float]
    asset_return_pct: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None
    beta: float | None
    correlation: float | None
    observations: int


def compare_to_benchmark(
    asset: DatedPrices,
    benchmark: DatedPrices,
    start_date: str | None = None,
) -> BenchmarkComparison:
    """Rebase an asset and its benchmark to 0% at the first common date on or
    after ``start_date`` and compute relative-performance statistics."""
    if start_date is not None:
        asset = [(d, p) for d, p in asset if d >= start_date]
        benchmark = [(d, p) for d, p in benchmark if d >= start_date]

    dates, prices = align_prices({"asset": asset, "benchmark": benchmark})
    if len(dates) < 2:
        return BenchmarkComparison(dates, [], [], None, None, None, None, None, 0)

    asset_cum = cumulative_return_pct(prices[:, 0])
    bench_cum = cumulative_return_pct(prices[:, 1])
    returns = prices[1:] / prices[:-1] - 1.0
    corr = correlation_matrix(returns)[0, 1]

    # Excess is derived from the rounded totals so the three reported figures always reconcile.
    asset_total = round(float(asset_cum[-1]), 2)
    bench_total = round(float(bench_cum[-1]), 2)
    beta_value = beta(returns[:, 0], returns[:, 1])
    return BenchmarkComparison(
        dates=dates,
        asset_cumulative_pct=[round(float(v), 4) for v in asset_cum],
        benchmark_cumulative_pct=[round(float(v), 4) for v in bench_cum],
        asset_return_pct=asset_total,
        benchmark_return_pct=bench_total,
        excess_return_pct=round(asset_total - bench_total, 2),
        beta=_round(beta_value, 3),
        correlation=round(float(corr), 3) if math.isfinite(corr) else None,
        observations=int(returns.shape[0]),
    )
