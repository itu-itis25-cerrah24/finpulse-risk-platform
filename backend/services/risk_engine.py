"""Quantitative risk engine.

Pure, side-effect-free functions (no I/O) so every metric is trivially unit
testable. All percentage outputs are expressed in percent (e.g. ``23.5`` means
23.5%), not as fractions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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
