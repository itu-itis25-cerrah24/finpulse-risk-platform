"""Unit tests for the quantitative risk engine (no network access required)."""

import math

import numpy as np
import pytest

from services.risk_engine import (
    DailyRiskFlag,
    RiskLevel,
    SentimentLabel,
    analyze_headlines,
    annualized_volatility,
    calculate_position_pnl,
    calculate_risk_score,
    classify_daily_change,
    classify_risk_level,
    compute_daily_returns,
    compute_quant_metrics,
    historical_var,
    max_drawdown,
    sharpe_ratio,
)

SQRT_252 = math.sqrt(252)


# ---------------------------------------------------------------------------
# Daily returns
# ---------------------------------------------------------------------------


def test_daily_returns_are_simple_percentage_changes() -> None:
    returns = compute_daily_returns([100.0, 110.0, 99.0])
    np.testing.assert_allclose(returns, [0.10, -0.10])


def test_daily_returns_ignore_invalid_prices() -> None:
    returns = compute_daily_returns([100.0, float("nan"), 0.0, 105.0])
    np.testing.assert_allclose(returns, [0.05])


def test_daily_returns_need_two_prices() -> None:
    assert compute_daily_returns([100.0]).size == 0


# ---------------------------------------------------------------------------
# Annualized volatility
# ---------------------------------------------------------------------------


def test_volatility_matches_hand_calculation() -> None:
    # mean = 0, sample variance = 4 * 0.01^2 / 3  =>  std = 0.011547
    returns = [0.01, -0.01, 0.01, -0.01]
    expected = math.sqrt(0.0004 / 3) * SQRT_252 * 100  # ~18.33%
    assert annualized_volatility(returns) == pytest.approx(expected)
    assert annualized_volatility(returns) == pytest.approx(18.3303, abs=1e-4)


def test_volatility_is_zero_for_constant_returns() -> None:
    assert annualized_volatility([0.005] * 30) == pytest.approx(0.0)


def test_volatility_requires_at_least_two_returns() -> None:
    assert annualized_volatility([0.01]) is None
    assert annualized_volatility([]) is None


# ---------------------------------------------------------------------------
# Historical VaR (95%)
# ---------------------------------------------------------------------------


def test_var_uses_fifth_percentile_of_returns() -> None:
    # 100 evenly spaced returns from -5.0% to +4.9%.
    # Linear-interpolated 5th percentile: rank 0.05 * 99 = 4.95
    #   -> -0.046 + 0.95 * 0.001 = -0.04505  =>  VaR = 4.505%
    returns = np.arange(-50, 50) / 1000
    assert historical_var(returns) == pytest.approx(4.505)


def test_var_is_reported_as_positive_loss() -> None:
    returns = [-0.03] * 10 + [0.01] * 90
    assert historical_var(returns) > 0


def test_var_is_floored_at_zero_when_tail_is_a_gain() -> None:
    assert historical_var([0.01, 0.02, 0.03, 0.04]) == 0.0


def test_var_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        historical_var([0.01, -0.01], confidence=1.5)


def test_var_with_no_data_is_none() -> None:
    assert historical_var([]) is None


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------


def test_max_drawdown_picks_worst_peak_to_trough() -> None:
    # 120 -> 90 is -25%; the later 130 -> 104 is only -20%.
    prices = [100, 120, 90, 95, 130, 104]
    assert max_drawdown(prices) == pytest.approx(-25.0)


def test_max_drawdown_is_zero_for_monotonic_rise() -> None:
    assert max_drawdown([100, 101, 105, 110]) == 0.0


def test_max_drawdown_handles_ongoing_decline() -> None:
    assert max_drawdown([200, 150, 100]) == pytest.approx(-50.0)


def test_max_drawdown_requires_two_prices() -> None:
    assert max_drawdown([100]) is None


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------


def test_sharpe_ratio_matches_hand_calculation() -> None:
    returns = [0.01, 0.02, 0.03]  # mean 0.02, sample std 0.01
    expected = (0.02 - 0.04 / 252) / 0.01 * SQRT_252
    assert sharpe_ratio(returns) == pytest.approx(expected)


def test_sharpe_ratio_undefined_for_zero_volatility() -> None:
    assert sharpe_ratio([0.01, 0.01, 0.01]) is None


# ---------------------------------------------------------------------------
# Aggregated metrics, P&L and flags
# ---------------------------------------------------------------------------


def test_compute_quant_metrics_bundles_all_metrics() -> None:
    prices = [100, 120, 90, 95, 130, 104]
    metrics = compute_quant_metrics(prices)
    assert metrics.observations == 5
    assert metrics.max_drawdown_pct == pytest.approx(-25.0)
    assert metrics.annualized_volatility_pct is not None and metrics.annualized_volatility_pct > 0
    assert metrics.var_95_pct is not None and metrics.var_95_pct > 0
    assert metrics.sharpe_ratio is not None


def test_compute_quant_metrics_with_insufficient_data() -> None:
    metrics = compute_quant_metrics([100])
    assert metrics.observations == 0
    assert metrics.annualized_volatility_pct is None
    assert metrics.var_95_pct is None
    assert metrics.max_drawdown_pct is None
    assert metrics.sharpe_ratio is None


def test_position_pnl() -> None:
    pnl = calculate_position_pnl(shares=10, avg_cost=100.0, price=125.0)
    assert pnl.market_value == 1250.0
    assert pnl.cost_basis == 1000.0
    assert pnl.unrealized_pnl == 250.0
    assert pnl.unrealized_pnl_pct == 25.0


@pytest.mark.parametrize(
    ("change", "threshold", "expected"),
    [
        (-5.0, 3.0, DailyRiskFlag.HIGH_DROP),
        (-3.0, 3.0, DailyRiskFlag.HIGH_DROP),
        (4.2, 3.0, DailyRiskFlag.HIGH_SPIKE),
        (1.5, 3.0, DailyRiskFlag.NORMAL),
        (-2.99, 3.0, DailyRiskFlag.NORMAL),
        (None, 3.0, DailyRiskFlag.NORMAL),
    ],
)
def test_classify_daily_change(change: float | None, threshold: float, expected: DailyRiskFlag) -> None:
    assert classify_daily_change(change, threshold) is expected


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


def test_sentiment_detects_bullish_headlines() -> None:
    summary = analyze_headlines(["Company reports record profits and strong growth, shares surge"])
    assert summary.label is SentimentLabel.BULLISH
    assert summary.score > 0


def test_sentiment_detects_bearish_headlines() -> None:
    summary = analyze_headlines(["Shares crash after fraud scandal and terrible losses"])
    assert summary.label is SentimentLabel.BEARISH
    assert summary.score < 0


def test_sentiment_without_headlines_is_neutral() -> None:
    summary = analyze_headlines([])
    assert summary.label is SentimentLabel.NEUTRAL
    assert summary.headline_count == 0


# ---------------------------------------------------------------------------
# Composite risk score
# ---------------------------------------------------------------------------


def test_risk_score_minimum_for_calm_bullish_stock() -> None:
    score = calculate_risk_score(
        volatility_pct=0.0, var_95_pct=0.0, max_drawdown_pct=0.0, daily_change_pct=0.0, sentiment_score=1.0
    )
    assert score == 0.0
    assert classify_risk_level(score) is RiskLevel.LOW


def test_risk_score_is_capped_at_100() -> None:
    score = calculate_risk_score(
        volatility_pct=150.0, var_95_pct=12.0, max_drawdown_pct=-80.0, daily_change_pct=-20.0, sentiment_score=-1.0
    )
    assert score == 100.0
    assert classify_risk_level(score) is RiskLevel.HIGH


def test_risk_score_midpoint_inputs_give_50() -> None:
    # Every component sits exactly at half of its cap => 50 regardless of weights.
    score = calculate_risk_score(
        volatility_pct=30.0, var_95_pct=2.5, max_drawdown_pct=-20.0, daily_change_pct=5.0, sentiment_score=0.0
    )
    assert score == 50.0
    assert classify_risk_level(score) is RiskLevel.MODERATE


def test_risk_score_applies_weights() -> None:
    # Only volatility is maxed (weight 0.30); everything else contributes 0.
    score = calculate_risk_score(
        volatility_pct=60.0, var_95_pct=0.0, max_drawdown_pct=0.0, daily_change_pct=0.0, sentiment_score=1.0
    )
    assert score == pytest.approx(30.0)


def test_risk_score_renormalizes_missing_inputs() -> None:
    score = calculate_risk_score(
        volatility_pct=30.0, var_95_pct=None, max_drawdown_pct=None, daily_change_pct=None, sentiment_score=None
    )
    assert score == 50.0


def test_risk_score_neutral_when_no_data() -> None:
    assert calculate_risk_score(None, None, None, None, None) == 50.0


def test_risk_score_increases_with_volatility() -> None:
    common = dict(var_95_pct=2.0, max_drawdown_pct=-10.0, daily_change_pct=1.0, sentiment_score=0.0)
    low = calculate_risk_score(volatility_pct=15.0, **common)
    high = calculate_risk_score(volatility_pct=45.0, **common)
    assert high > low
