"""Tests for the Markowitz optimiser (pure functions and API endpoint)."""

from collections.abc import Iterator
from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (register tables)
from database import Base, get_db
from main import app, get_market_service
from models import WatchlistItem
from schemas import RebalanceAction
from services.market_service import MarketService, NewsHeadline, PricePoint, Quote
from services.optimizer import (
    MIN_EIGENVALUE_RATIO,
    AnnualizedMoments,
    annualized_moments,
    cloud_indices,
    efficient_frontier_indices,
    normalize_weights,
    optimize_portfolio,
    portfolio_stats,
    regularize_covariance,
    sample_weights,
)
from services.portfolio_service import rebalancing_plan
from services.risk_engine import RISK_FREE_RATE_ANNUAL


def _returns(seed: int = 3, n: int = 80) -> np.ndarray:
    """Three assets with distinct risk/return profiles and some correlation."""
    rng = np.random.default_rng(seed)
    cov = np.array(
        [
            [0.00010, 0.00004, 0.00002],
            [0.00004, 0.00040, 0.00010],
            [0.00002, 0.00010, 0.00090],
        ]
    )
    return rng.multivariate_normal([0.0004, 0.0010, 0.0006], cov, size=n)


def _moments(mean: list[float], vols: list[float], corr: float = 0.0) -> AnnualizedMoments:
    sd = np.array(vols)
    corr_matrix = np.array([[1.0, corr], [corr, 1.0]])
    return AnnualizedMoments(mean=np.array(mean), covariance=np.outer(sd, sd) * corr_matrix, jitter=0.0)


# ---------------------------------------------------------------------------
# Moments and weights
# ---------------------------------------------------------------------------


def test_annualized_moments_scale_by_252() -> None:
    r = _returns()
    moments = annualized_moments(r)
    np.testing.assert_allclose(moments.mean, r.mean(axis=0) * 252)
    np.testing.assert_allclose(moments.covariance, np.cov(r, rowvar=False) * 252)
    assert moments.jitter == 0.0


def test_annualized_moments_regularise_singular_covariance() -> None:
    a = _returns()[:, 0]
    cash = np.zeros_like(a)  # zero-variance holding: the covariance is exactly singular
    moments = annualized_moments(np.column_stack([a, cash]))
    assert moments.jitter > 0
    np.linalg.cholesky(moments.covariance)  # now positive definite


@pytest.mark.parametrize("rounding_error", [-1e-18, 0.0, 1e-18])
def test_regularize_covariance_floors_smallest_eigenvalue(rounding_error: float) -> None:
    """Rank-1 matrix whose zero eigenvalue is nudged as different BLAS builds would round it."""
    v = np.array([0.01, 0.02, 0.03])
    cov = np.outer(v, v) + rounding_error * np.eye(3)

    regularised, ridge = regularize_covariance(cov)
    floor = MIN_EIGENVALUE_RATIO * np.mean(np.diag(cov))
    assert ridge > 0
    assert np.linalg.eigvalsh(regularised)[0] == pytest.approx(floor, rel=1e-6)
    np.linalg.cholesky(regularised)
    np.linalg.cholesky(regularised * 252)  # annualising keeps it positive definite


def test_regularize_covariance_leaves_well_conditioned_matrix_unchanged() -> None:
    cov = np.array([[0.04, 0.006], [0.006, 0.09]])
    regularised, ridge = regularize_covariance(cov)
    assert ridge == 0.0
    np.testing.assert_array_equal(regularised, cov)
    with pytest.raises(ValueError):
        regularize_covariance(np.ones((2, 3)))


def test_normalize_weights() -> None:
    np.testing.assert_allclose(normalize_weights([2, 1, 1]), [0.5, 0.25, 0.25])
    np.testing.assert_allclose(normalize_weights([-1, 1]), [0.0, 1.0])  # negatives clipped (long-only)
    with pytest.raises(ValueError):
        normalize_weights([0, 0])


def test_sample_weights_are_long_only_and_fully_invested() -> None:
    rng = np.random.default_rng(1)
    current = np.array([0.7, 0.2, 0.1])
    weights = sample_weights(3, 500, rng, anchors=current)

    assert weights.shape == (500, 3)
    assert np.all(weights >= 0)
    np.testing.assert_allclose(weights.sum(axis=1), 1.0)
    np.testing.assert_allclose(weights[0], current)  # current allocation first
    np.testing.assert_allclose(weights[1:4], np.eye(3))  # corners
    np.testing.assert_allclose(weights[4], [1 / 3] * 3)  # equal weight


def test_sample_weights_are_deterministic() -> None:
    first = sample_weights(4, 200, np.random.default_rng(42))
    second = sample_weights(4, 200, np.random.default_rng(42))
    np.testing.assert_array_equal(first, second)


def test_sample_weights_validation() -> None:
    with pytest.raises(ValueError):
        sample_weights(0, 10, np.random.default_rng(0))


# ---------------------------------------------------------------------------
# Scoring and frontier
# ---------------------------------------------------------------------------


def test_portfolio_stats_hand_calculated() -> None:
    moments = _moments([0.10, 0.20], [0.20, 0.30])
    stats = portfolio_stats([[0.5, 0.5], [1.0, 0.0]], moments)

    expected_vol = np.sqrt(0.25 * 0.04 + 0.25 * 0.09)
    np.testing.assert_allclose(stats.returns, [0.15, 0.10])
    np.testing.assert_allclose(stats.volatility, [expected_vol, 0.20])
    np.testing.assert_allclose(stats.sharpe, [(0.15 - RISK_FREE_RATE_ANNUAL) / expected_vol, (0.10 - 0.04) / 0.20])


def test_portfolio_stats_zero_volatility_has_no_sharpe() -> None:
    moments = _moments([0.05, 0.05], [0.0, 0.0])
    assert np.isnan(portfolio_stats([[1.0, 0.0]], moments).sharpe[0])


def test_efficient_frontier_keeps_only_undominated_points() -> None:
    vol = np.array([0.10, 0.12, 0.15, 0.15, 0.20, 0.25])
    ret = np.array([0.05, 0.04, 0.08, 0.07, 0.06, 0.12])
    # index 1 (more risk, less return than 0), 3 (same risk as 2, less return), 4 (dominated by 2)
    assert efficient_frontier_indices(ret, vol).tolist() == [0, 2, 5]


def test_efficient_frontier_is_thinned() -> None:
    vol = np.linspace(0.1, 0.5, 500)
    ret = np.linspace(0.0, 0.3, 500)  # every point efficient
    idx = efficient_frontier_indices(ret, vol, max_points=50)
    assert len(idx) <= 50
    assert idx[0] == 0 and idx[-1] == 499


def test_cloud_indices() -> None:
    assert cloud_indices(10).tolist() == list(range(10))
    sampled = cloud_indices(4000, 300)
    assert len(sampled) == 300
    assert sampled[0] == 0 and sampled[-1] == 3999


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------


def test_optimization_is_deterministic_with_seed() -> None:
    current = [0.5, 0.3, 0.2]
    first = optimize_portfolio(current, _returns(), samples=2000, seed=42)
    second = optimize_portfolio(current, _returns(), samples=2000, seed=42)
    other = optimize_portfolio(current, _returns(), samples=2000, seed=7)

    np.testing.assert_array_equal(first.max_sharpe.weights, second.max_sharpe.weights)
    np.testing.assert_array_equal(first.min_volatility.weights, second.min_volatility.weights)
    np.testing.assert_array_equal(first.cloud.returns, second.cloud.returns)
    assert not np.array_equal(first.cloud.returns, other.cloud.returns)


def test_optimal_weights_are_valid_and_dominate_current() -> None:
    result = optimize_portfolio([0.5, 0.3, 0.2], _returns(), samples=4000, seed=42)

    for point in (result.current, result.max_sharpe, result.min_volatility):
        assert np.all(point.weights >= 0)
        assert point.weights.sum() == pytest.approx(1.0)

    assert result.min_volatility.volatility <= result.current.volatility
    assert result.max_sharpe.sharpe is not None and result.min_volatility.sharpe is not None
    assert result.max_sharpe.sharpe >= result.min_volatility.sharpe
    assert result.max_sharpe.sharpe >= result.current.sharpe  # type: ignore[operator]
    assert result.samples == 4000


def test_frontier_is_monotonic_and_contains_min_volatility() -> None:
    result = optimize_portfolio([0.4, 0.4, 0.2], _returns(), samples=3000, seed=1)
    assert np.all(np.diff(result.frontier.volatility) >= 0)
    assert np.all(np.diff(result.frontier.returns) > 0)
    assert result.frontier.volatility[0] == pytest.approx(result.min_volatility.volatility)
    assert len(result.cloud.returns) == 300


def test_min_volatility_matches_closed_form_for_two_assets() -> None:
    """Uncorrelated assets: w₁* = σ₂² / (σ₁² + σ₂²)."""
    rng = np.random.default_rng(9)
    returns = np.column_stack([rng.normal(0, 0.01, 2000), rng.normal(0, 0.02, 2000)])
    returns -= returns.mean(axis=0)  # equal (zero) means
    result = optimize_portfolio([0.5, 0.5], returns, samples=5000, seed=0)

    var1, var2 = np.var(returns, axis=0, ddof=1)
    rho = np.corrcoef(returns, rowvar=False)[0, 1]
    cov12 = rho * np.sqrt(var1 * var2)
    analytic = (var2 - cov12) / (var1 + var2 - 2 * cov12)
    assert result.min_volatility.weights[0] == pytest.approx(analytic, abs=0.01)


def test_single_asset_returns_current_allocation() -> None:
    result = optimize_portfolio([1.0], _returns()[:, :1], samples=4000, seed=42)
    for point in (result.current, result.max_sharpe, result.min_volatility):
        np.testing.assert_allclose(point.weights, [1.0])
    assert result.max_sharpe.volatility == result.current.volatility
    assert result.samples == 1
    assert len(result.frontier.returns) == 1


def test_collinear_portfolio_does_not_crash() -> None:
    a = _returns()[:, 0]
    # Identical columns: λ_min is 0 up to rounding, so the eigenvalue floor always applies.
    result = optimize_portfolio([0.5, 0.5], np.column_stack([a, a]), samples=500, seed=0)
    assert result.moments.jitter > 0
    np.linalg.cholesky(result.moments.covariance)  # strictly positive definite on every BLAS
    assert result.min_volatility.weights.sum() == pytest.approx(1.0)
    # Every mix of two identical assets has the same risk/return.
    np.testing.assert_allclose(result.cloud.volatility, result.current.volatility, rtol=1e-6)


def test_optimizer_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError):
        optimize_portfolio([0.5, 0.5], _returns(), samples=100)


def test_rebalancing_plan() -> None:
    rows = rebalancing_plan(["A", "B", "C"], np.array([0.5, 0.3, 0.2]), np.array([0.2, 0.3004, 0.4996]), 10_000)
    by_symbol = {r.symbol: r for r in rows}

    assert by_symbol["A"].action is RebalanceAction.SELL
    assert by_symbol["A"].delta_usd == pytest.approx(-3000.0)
    assert by_symbol["B"].action is RebalanceAction.HOLD  # 0.04 pp is below the tolerance
    assert by_symbol["C"].action is RebalanceAction.BUY
    assert by_symbol["C"].delta_weight_pct == pytest.approx(29.96)
    assert sum(r.delta_usd for r in rows) == pytest.approx(0.0, abs=0.01)  # self-financing


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

QUOTES = {
    "AAPL": Quote("AAPL", price=100.0, previous_close=100.0, change_pct=0.0, currency="USD"),
    "MSFT": Quote("MSFT", price=200.0, previous_close=200.0, change_pct=0.0, currency="USD"),
    "THYAO.IS": Quote("THYAO.IS", price=400.0, previous_close=400.0, change_pct=0.0, currency="TRY"),
}
HISTORY = {
    "AAPL": [100, 102, 101, 104, 103, 106, 105, 108, 107, 110],
    "MSFT": [200, 198, 203, 201, 199, 205, 204, 202, 207, 206],
    "THYAO.IS": [380, 372, 390, 385, 401, 395, 410, 398, 405, 400],
    "TRY=X": [38.0, 38.2, 38.5, 38.4, 38.9, 39.2, 39.4, 39.6, 39.8, 40.0],
}


class OptimizerMarket(MarketService):
    def get_quote(self, symbol: str) -> Quote:
        return QUOTES.get(symbol, Quote.unavailable(symbol))

    def get_history(self, symbol: str) -> list[PricePoint]:
        closes = HISTORY.get(symbol, [])
        start = date.today() - timedelta(days=len(closes) - 1)
        return [PricePoint((start + timedelta(days=i)).isoformat(), float(c)) for i, c in enumerate(closes)]

    def get_news(self, symbol: str) -> list[NewsHeadline]:
        return []

    def get_fx_rate_to_usd(self, currency: str | None) -> float | None:
        return {"USD": 1.0, "TRY": 1 / 40.0}.get(currency or "")


@pytest.fixture
def lab() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    market = OptimizerMarket()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_market_service] = lambda: market
    yield TestClient(app), factory
    app.dependency_overrides.clear()
    engine.dispose()


def _hold(factory: sessionmaker[Session], *positions: tuple[str, float]) -> None:
    with factory() as db:
        db.add_all(WatchlistItem(symbol=s, shares=n, avg_cost=1.0) for s, n in positions)
        db.commit()


def test_optimize_endpoint(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10), ("MSFT", 5), ("THYAO.IS", 100))  # $1000 each
    url = "/api/portfolio/optimize?samples=1000&seed=42"

    response = client.get(url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert client.get(url).json() == body  # deterministic

    assert body["total_value_usd"] == 3000.0
    assert [w["weight_pct"] for w in body["current_portfolio"]["weights"]] == pytest.approx([33.33] * 3, abs=0.01)
    for key in ("current_portfolio", "max_sharpe", "min_volatility"):
        weights = [w["weight_pct"] for w in body[key]["weights"]]
        assert all(w >= 0 for w in weights)
        assert sum(weights) == pytest.approx(100.0, abs=0.05)

    assert body["min_volatility"]["volatility_pct"] <= body["current_portfolio"]["volatility_pct"]
    assert body["max_sharpe"]["sharpe_ratio"] >= body["min_volatility"]["sharpe_ratio"]
    assert 0 < len(body["frontier_cloud"]) <= 300
    assert len(body["efficient_frontier"]) >= 1
    assert body["risk_free_rate_pct"] == 4.0

    for target in ("max_sharpe", "min_volatility"):
        rows = body["rebalancing"][target]
        assert [r["symbol"] for r in rows] == ["AAPL", "MSFT", "THYAO.IS"]
        assert sum(r["delta_usd"] for r in rows) == pytest.approx(0.0, abs=0.05)
        for row in rows:
            assert row["delta_weight_pct"] == pytest.approx(row["target_weight_pct"] - row["current_weight_pct"], abs=0.02)


def test_optimize_endpoint_single_holding(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10))
    body = client.get("/api/portfolio/optimize?seed=1").json()

    assert body["samples"] == 1
    for key in ("current_portfolio", "max_sharpe", "min_volatility"):
        assert body[key]["weights"] == [{"symbol": "AAPL", "weight_pct": 100.0}]
    assert body["rebalancing"]["max_sharpe"][0]["action"] == "HOLD"
    assert body["rebalancing"]["max_sharpe"][0]["delta_usd"] == 0.0


def test_optimize_endpoint_errors(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    assert client.get("/api/portfolio/optimize").status_code == 422  # empty portfolio
    _hold(factory, ("AAPL", 10))
    assert client.get("/api/portfolio/optimize?samples=10").status_code == 422
    assert client.get("/api/portfolio/optimize?samples=50000").status_code == 422
    assert client.get("/api/portfolio/optimize?seed=-1").status_code == 422
