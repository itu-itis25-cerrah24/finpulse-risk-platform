"""Unit tests for date alignment, correlation and benchmark comparison."""

import math

import numpy as np
import pytest

from services.risk_engine import (
    BIST_BENCHMARK,
    US_BENCHMARK,
    align_prices,
    align_returns,
    average_pairwise_correlation,
    benchmark_for_symbol,
    beta,
    compare_to_benchmark,
    correlation_matrix,
    correlation_pairs,
    cumulative_return_pct,
)


def _series(prices: list[float], start_day: int = 1) -> list[tuple[str, float]]:
    return [(f"2026-03-{start_day + i:02d}", p) for i, p in enumerate(prices)]


def _prices_from_returns(returns: list[float], start: float = 100.0) -> list[float]:
    prices = [start]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return prices


# ---------------------------------------------------------------------------
# Date alignment
# ---------------------------------------------------------------------------


def test_align_prices_keeps_only_common_dates() -> None:
    bist = [("2026-03-02", 10.0), ("2026-03-03", 11.0), ("2026-03-04", 12.0)]
    us = [("2026-03-03", 200.0), ("2026-03-04", 210.0), ("2026-03-05", 220.0)]  # 03-02 US holiday
    dates, matrix = align_prices({"THYAO.IS": bist, "AAPL": us})
    assert dates == ["2026-03-03", "2026-03-04"]
    np.testing.assert_allclose(matrix, [[11.0, 200.0], [12.0, 210.0]])


def test_align_prices_sorts_dates_and_drops_invalid_prices() -> None:
    a = [("2026-03-03", 2.0), ("2026-03-01", 1.0), ("2026-03-02", float("nan"))]
    b = [("2026-03-01", 5.0), ("2026-03-02", 6.0), ("2026-03-03", 7.0)]
    dates, matrix = align_prices({"A": a, "B": b})
    assert dates == ["2026-03-01", "2026-03-03"]
    np.testing.assert_allclose(matrix[:, 0], [1.0, 2.0])


def test_align_returns_computes_returns_on_aligned_prices() -> None:
    aligned = align_returns({"A": _series([100, 110, 99]), "B": _series([50, 50, 55])})
    assert aligned.symbols == ["A", "B"]
    assert aligned.dates == ["2026-03-02", "2026-03-03"]
    assert aligned.observations == 2
    np.testing.assert_allclose(aligned.returns, [[0.10, 0.0], [-0.10, 0.10]])


def test_align_returns_with_no_overlap_is_empty() -> None:
    aligned = align_returns({"A": _series([1, 2, 3], start_day=1), "B": _series([1, 2, 3], start_day=10)})
    assert aligned.observations == 0
    assert aligned.returns.shape == (0, 2)


# ---------------------------------------------------------------------------
# Pearson correlation
# ---------------------------------------------------------------------------


def test_correlation_of_proportional_returns_is_one() -> None:
    a = np.array([0.01, -0.02, 0.03, 0.005, -0.01])
    corr = correlation_matrix(np.column_stack([a, 3 * a]))
    np.testing.assert_allclose(corr, [[1.0, 1.0], [1.0, 1.0]])


def test_correlation_of_mirrored_returns_is_minus_one() -> None:
    a = np.array([0.01, -0.02, 0.03, 0.005, -0.01])
    corr = correlation_matrix(np.column_stack([a, -a]))
    assert corr[0, 1] == pytest.approx(-1.0)


def test_correlation_matches_hand_calculation() -> None:
    # x = [1,2,3,4], y = [2,1,4,3]: sample cov = 1.0, sample var = 5/3 each => r = 0.6
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([2.0, 1.0, 4.0, 3.0])
    corr = correlation_matrix(np.column_stack([x, y]))
    assert corr[0, 1] == pytest.approx(0.6)
    assert corr[1, 0] == pytest.approx(0.6)  # symmetric


def test_correlation_with_zero_variance_series_is_undefined() -> None:
    a = np.array([0.01, -0.02, 0.03, 0.005])
    corr = correlation_matrix(np.column_stack([a, np.zeros(4)]))
    assert math.isnan(corr[0, 1])
    assert corr[0, 0] == 1.0 and corr[1, 1] == 1.0


def test_correlation_requires_minimum_observations() -> None:
    corr = correlation_matrix([[0.01, 0.02], [0.02, 0.01]])
    assert math.isnan(corr[0, 1])


def test_correlation_rejects_one_dimensional_input() -> None:
    with pytest.raises(ValueError):
        correlation_matrix([0.01, 0.02, 0.03])


def test_correlation_pairs_are_unique_and_sorted() -> None:
    matrix = np.array([[1.0, 0.2, 0.9], [0.2, 1.0, -0.4], [0.9, -0.4, 1.0]])
    pairs = correlation_pairs(["A", "B", "C"], matrix)
    assert [(p.symbol_a, p.symbol_b) for p in pairs] == [("A", "C"), ("A", "B"), ("B", "C")]
    assert pairs[0].correlation == pytest.approx(0.9)


def test_average_pairwise_correlation_ignores_diagonal_and_nan() -> None:
    matrix = np.array([[1.0, 0.2, np.nan], [0.2, 1.0, 0.6], [np.nan, 0.6, 1.0]])
    assert average_pairwise_correlation(matrix) == pytest.approx(0.4)
    assert average_pairwise_correlation(np.array([[1.0]])) is None


# ---------------------------------------------------------------------------
# Benchmark comparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("THYAO.IS", BIST_BENCHMARK), ("asels.is", BIST_BENCHMARK), ("AAPL", US_BENCHMARK), ("NVDA", US_BENCHMARK)],
)
def test_benchmark_for_symbol(symbol: str, expected: str) -> None:
    assert benchmark_for_symbol(symbol) == expected


def test_cumulative_return_starts_at_zero() -> None:
    np.testing.assert_allclose(cumulative_return_pct([100, 110, 99]), [0.0, 10.0, -1.0])


def test_beta_of_leveraged_returns() -> None:
    bench = np.array([0.01, -0.02, 0.015, 0.005, -0.01])
    assert beta(2 * bench, bench) == pytest.approx(2.0)
    assert beta(bench, np.zeros(5)) is None


def test_compare_to_benchmark_rebases_both_series() -> None:
    bench_returns = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02]
    asset_returns = [2 * r for r in bench_returns]
    asset = _series(_prices_from_returns(asset_returns, 50.0))
    benchmark = _series(_prices_from_returns(bench_returns, 400.0))

    result = compare_to_benchmark(asset, benchmark)

    assert result.asset_cumulative_pct[0] == 0.0
    assert result.benchmark_cumulative_pct[0] == 0.0
    assert result.observations == len(bench_returns)
    assert result.beta == pytest.approx(2.0)
    assert result.correlation == pytest.approx(1.0)
    expected_bench = (np.prod([1 + r for r in bench_returns]) - 1) * 100
    assert result.benchmark_return_pct == pytest.approx(expected_bench, abs=0.01)
    assert result.excess_return_pct == pytest.approx(result.asset_return_pct - result.benchmark_return_pct)


def test_compare_to_benchmark_respects_window_start() -> None:
    asset = _series([100, 50, 60, 66])  # 03-01 .. 03-04
    benchmark = _series([10, 10, 11, 12])
    result = compare_to_benchmark(asset, benchmark, start_date="2026-03-02")
    assert result.dates[0] == "2026-03-02"
    assert result.asset_return_pct == pytest.approx(32.0)  # 50 -> 66
    assert result.benchmark_return_pct == pytest.approx(20.0)  # 10 -> 12
    assert result.excess_return_pct == pytest.approx(12.0)


def test_compare_to_benchmark_without_overlap() -> None:
    result = compare_to_benchmark(_series([1, 2], start_day=1), _series([1, 2], start_day=20))
    assert result.observations == 0
    assert result.asset_return_pct is None
    assert result.asset_cumulative_pct == []
