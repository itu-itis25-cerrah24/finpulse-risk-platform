"""Tests for the correlated Monte Carlo engine and the stress-testing module."""

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
from services.market_service import MarketService, NewsHeadline, PricePoint, Quote
from services.monte_carlo import (
    PERCENTILES,
    DriftModel,
    cholesky_with_jitter,
    convert_to_usd,
    covariance_matrix,
    log_returns,
    percentile_bands,
    run_monte_carlo,
    simulate_portfolio_paths,
    summarize_terminal_values,
)
from services.stress_test import (
    PRESET_SCENARIOS,
    Holding,
    MarketSegment,
    Scenario,
    ShockSet,
    run_stress_test,
    segment_for_symbol,
    shock_holding,
)

# ---------------------------------------------------------------------------
# Log-returns, FX conversion, covariance
# ---------------------------------------------------------------------------


def test_log_returns_of_price_matrix() -> None:
    prices = np.array([[100.0, 10.0], [110.0, 10.0], [99.0, 20.0]])
    expected = np.array([[np.log(1.1), 0.0], [np.log(0.9), np.log(2.0)]])
    np.testing.assert_allclose(log_returns(prices), expected)


def test_log_returns_validation() -> None:
    assert log_returns(np.array([[1.0, 2.0]])).shape == (0, 2)
    with pytest.raises(ValueError):
        log_returns(np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        log_returns(np.array([[1.0], [0.0]]))


def test_convert_to_usd_divides_by_fx_on_common_dates() -> None:
    prices = [("2025-01-01", 300.0), ("2025-01-02", 330.0), ("2025-01-03", 360.0)]
    fx = [("2025-01-01", 30.0), ("2025-01-03", 36.0)]  # TRY per USD; no quote on 01-02
    assert convert_to_usd(prices, fx) == [("2025-01-01", 10.0), ("2025-01-03", 10.0)]


def test_covariance_matrix_is_two_dimensional_for_one_asset() -> None:
    cov = covariance_matrix(np.array([[0.01], [-0.01], [0.02]]))
    assert cov.shape == (1, 1)
    assert cov[0, 0] == pytest.approx(np.var([0.01, -0.01, 0.02], ddof=1))


# ---------------------------------------------------------------------------
# Cholesky with jitter fallback
# ---------------------------------------------------------------------------


def test_cholesky_positive_definite_needs_no_jitter() -> None:
    cov = np.array([[0.04, 0.006], [0.006, 0.09]])
    chol, jitter = cholesky_with_jitter(cov)
    assert jitter == 0.0
    np.testing.assert_allclose(chol @ chol.T, cov)
    assert np.allclose(chol, np.tril(chol))  # lower-triangular


def test_cholesky_falls_back_on_perfectly_collinear_assets() -> None:
    cov = np.array([[1.0, 1.0], [1.0, 1.0]])  # rank 1: plain Cholesky fails
    with pytest.raises(np.linalg.LinAlgError):
        np.linalg.cholesky(cov)

    chol, jitter = cholesky_with_jitter(cov)
    assert 0 < jitter < 1e-6
    np.testing.assert_allclose(chol @ chol.T, cov, atol=1e-6)


def test_cholesky_handles_linear_combination_of_assets() -> None:
    rng = np.random.default_rng(0)
    a, b = rng.normal(0, 0.01, 50), rng.normal(0, 0.02, 50)
    returns = np.column_stack([a, b, a + b])  # third asset is exactly collinear
    cov = covariance_matrix(returns)

    chol, jitter = cholesky_with_jitter(cov)
    assert jitter >= 0
    np.testing.assert_allclose(chol @ chol.T, cov, atol=1e-8)


def test_cholesky_handles_single_zero_variance_asset() -> None:
    chol, jitter = cholesky_with_jitter(np.array([[0.0]]))
    assert jitter > 0
    assert chol.shape == (1, 1)
    assert chol[0, 0] == pytest.approx(np.sqrt(jitter))


def test_cholesky_single_asset_is_volatility() -> None:
    chol, jitter = cholesky_with_jitter(0.04)  # scalars are promoted to 1x1
    assert jitter == 0.0
    assert chol[0, 0] == pytest.approx(0.2)


def test_cholesky_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        cholesky_with_jitter(np.ones((2, 3)))
    with pytest.raises(ValueError):
        cholesky_with_jitter(np.array([[np.nan]]))


# ---------------------------------------------------------------------------
# GBM path simulation
# ---------------------------------------------------------------------------


def _returns_fixture(seed: int = 1, n: int = 60) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cov = np.array([[0.0004, 0.0002], [0.0002, 0.0009]])
    return rng.multivariate_normal([0.0005, -0.0003], cov, size=n)


def test_simulation_is_deterministic_with_seed() -> None:
    returns = _returns_fixture()
    first = run_monte_carlo([1000.0, 500.0], returns, horizon_days=30, simulations=500, seed=42)
    second = run_monte_carlo([1000.0, 500.0], returns, horizon_days=30, simulations=500, seed=42)
    other = run_monte_carlo([1000.0, 500.0], returns, horizon_days=30, simulations=500, seed=7)

    np.testing.assert_array_equal(first.paths_percentiles, second.paths_percentiles)
    assert first.summary == second.summary
    assert not np.array_equal(first.paths_percentiles, other.paths_percentiles)


def test_zero_volatility_paths_follow_drift_exactly() -> None:
    rng = np.random.default_rng(0)
    drift = np.array([0.01, -0.02])
    paths = simulate_portfolio_paths([100.0, 50.0], drift, np.zeros((2, 2)), 5, 3, rng)

    days = np.arange(6)
    expected = 100 * np.exp(0.01 * days) + 50 * np.exp(-0.02 * days)
    for path in paths:
        np.testing.assert_allclose(path, expected)


def test_cholesky_factor_transmits_correlation() -> None:
    """Two equal-weight assets: rho = -1 nets out, rho = +1 doubles the dispersion."""
    sigma = 0.02
    spreads = {}
    for rho in (-1.0, 1.0):
        cov = sigma**2 * np.array([[1.0, rho], [rho, 1.0]])
        chol, _ = cholesky_with_jitter(cov)
        paths = simulate_portfolio_paths([100.0, 100.0], [0.0, 0.0], chol, 1, 4000, np.random.default_rng(3))
        spreads[rho] = float(np.std(paths[:, 1]))

    assert spreads[1.0] == pytest.approx(200 * sigma, rel=0.05)
    # Perfect hedge: the linear shocks cancel; only the tiny convexity term
    # 100·(eˣ + e⁻ˣ − 2) ≈ 100·x² survives, i.e. < 2% of the rho = +1 dispersion.
    assert spreads[-1.0] < 0.02 * spreads[1.0]


def test_antithetic_draws_are_mirrored() -> None:
    """With zero drift, path i and its antithetic twin have log-growth of opposite sign."""
    paths = simulate_portfolio_paths([100.0], [0.0], np.array([[0.02]]), 3, 6, np.random.default_rng(5))
    log_growth = np.log(paths[:, 1:] / 100.0)
    np.testing.assert_allclose(log_growth[:3], -log_growth[3:])

    odd = simulate_portfolio_paths([100.0], [0.0], np.array([[0.02]]), 3, 5, np.random.default_rng(5))
    assert odd.shape == (5, 4)


def test_simulation_rejects_mismatched_dimensions() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_portfolio_paths([1.0, 2.0], [0.0], np.eye(2), 5, 10, rng)
    with pytest.raises(ValueError):
        simulate_portfolio_paths([1.0], [0.0], np.eye(1), 0, 10, rng)


def test_percentile_bands_are_ordered_and_start_at_initial_value() -> None:
    result = run_monte_carlo([1000.0, 500.0], _returns_fixture(), horizon_days=60, simulations=1000, seed=42)
    bands = result.paths_percentiles

    assert bands.shape == (len(PERCENTILES), 61)
    np.testing.assert_allclose(bands[:, 0], 1500.0)
    assert np.all(np.diff(bands, axis=0) >= 0)  # p5 <= p25 <= p50 <= p75 <= p95 every day
    assert bands[-1, -1] - bands[0, -1] > bands[-1, 1] - bands[0, 1]  # the fan widens with time


def test_percentile_bands_of_known_values() -> None:
    paths = np.arange(1, 101, dtype=float).reshape(100, 1)
    np.testing.assert_allclose(percentile_bands(paths, [5, 50, 95])[:, 0], [5.95, 50.5, 95.05])


def test_zero_drift_model_is_a_martingale() -> None:
    result = run_monte_carlo(
        [1000.0, 500.0], _returns_fixture(), horizon_days=20, simulations=5000, seed=11, drift_model=DriftModel.ZERO
    )
    np.testing.assert_allclose(result.drift, -0.5 * result.volatility**2)
    assert result.summary.expected_value == pytest.approx(1500.0, rel=0.01)


def test_run_monte_carlo_requires_enough_observations() -> None:
    with pytest.raises(ValueError):
        run_monte_carlo([100.0], np.zeros((3, 1)), horizon_days=10, simulations=100)
    with pytest.raises(ValueError):
        run_monte_carlo([100.0, 50.0], np.zeros((10, 1)), horizon_days=10, simulations=100)


# ---------------------------------------------------------------------------
# VaR / CVaR summary
# ---------------------------------------------------------------------------


def test_terminal_summary_hand_calculated() -> None:
    terminal = np.arange(51, 151, dtype=float)  # P&L of -49 ... +50 on a 100 start
    summary = summarize_terminal_values(100.0, terminal)

    assert summary.var == pytest.approx(44.05)  # linear-interpolated 5th percentile
    assert summary.cvar == pytest.approx(47.0)  # mean of -49 ... -45
    assert summary.probability_of_loss_pct == pytest.approx(49.0)
    assert summary.expected_value == pytest.approx(100.5)
    assert summary.expected_return_pct == pytest.approx(0.5)
    assert summary.median_value == pytest.approx(100.5)


@pytest.mark.parametrize("seed", range(10))
def test_cvar_is_never_below_var(seed: int) -> None:
    terminal = np.random.default_rng(seed).lognormal(mean=0, sigma=0.3, size=777) * 100
    summary = summarize_terminal_values(100.0, terminal)
    assert summary.cvar >= summary.var


def test_cvar_is_not_below_var_in_full_simulation() -> None:
    result = run_monte_carlo([1000.0, 500.0], _returns_fixture(), horizon_days=90, simulations=1000, seed=42)
    assert result.summary.cvar >= result.summary.var > 0
    assert 0 <= result.summary.probability_of_loss_pct <= 100


def test_terminal_summary_validation() -> None:
    with pytest.raises(ValueError):
        summarize_terminal_values(100.0, [])
    with pytest.raises(ValueError):
        summarize_terminal_values(100.0, [90.0, 110.0], confidence=1.0)


# ---------------------------------------------------------------------------
# Stress testing
# ---------------------------------------------------------------------------

US_HOLDING = Holding("AAPL", 1000.0, "USD")
BIST_HOLDING = Holding("THYAO.IS", 500.0, "TRY")


def test_segment_for_symbol() -> None:
    assert segment_for_symbol("thyao.is") is MarketSegment.BIST_EQUITY
    assert segment_for_symbol("AAPL") is MarketSegment.US_EQUITY


def test_fx_shock_hits_only_lira_holdings() -> None:
    shocks = ShockSet(usd_try_shock_pct=25)
    assert shock_holding(US_HOLDING, shocks).pnl_usd == 0.0

    impact = shock_holding(BIST_HOLDING, shocks)
    assert impact.pnl_pct == pytest.approx(-20.0)  # 1 / 1.25 - 1
    assert impact.value_after_usd == pytest.approx(400.0)
    assert impact.fx_shock_pct == 25


def test_lira_appreciation_lifts_bist_value() -> None:
    impact = shock_holding(BIST_HOLDING, ShockSet(usd_try_shock_pct=-20))
    assert impact.pnl_pct == pytest.approx(25.0)


def test_equity_and_fx_shocks_compound_for_bist() -> None:
    impact = shock_holding(BIST_HOLDING, ShockSet(bist_equity_shock_pct=-10, usd_try_shock_pct=20))
    assert impact.pnl_pct == pytest.approx((0.9 / 1.2 - 1) * 100)
    assert impact.equity_shock_pct == -10


def test_us_equity_shock_and_wipe_out() -> None:
    assert shock_holding(US_HOLDING, ShockSet(us_equity_shock_pct=-30)).value_after_usd == 700.0
    assert shock_holding(US_HOLDING, ShockSet(us_equity_shock_pct=-100)).value_after_usd == 0.0
    assert shock_holding(US_HOLDING, ShockSet(bist_equity_shock_pct=-50)).pnl_usd == 0.0


@pytest.mark.parametrize("scenario", list(Scenario))
def test_every_preset_reconciles(scenario: Scenario) -> None:
    shocks = PRESET_SCENARIOS[scenario].shocks
    result = run_stress_test([US_HOLDING, BIST_HOLDING], shocks)

    us_expected = 1000 * (1 + shocks.us_equity_shock_pct / 100)
    bist_expected = 500 * (1 + shocks.bist_equity_shock_pct / 100) / (1 + shocks.usd_try_shock_pct / 100)
    assert result.total_before_usd == 1500.0
    assert result.total_after_usd == pytest.approx(us_expected + bist_expected, abs=0.01)
    assert result.total_pnl_usd == pytest.approx(result.total_after_usd - 1500.0, abs=0.01)
    assert result.total_pnl_pct == pytest.approx(result.total_pnl_usd / 1500 * 100, abs=0.01)
    assert result.total_pnl_usd < 0  # every preset is a downside scenario for this book
    assert result.worst_hit_symbol == min(result.impacts, key=lambda i: i.pnl_usd).symbol


def test_lira_crisis_worst_hit_is_bist_holding() -> None:
    result = run_stress_test([US_HOLDING, BIST_HOLDING], PRESET_SCENARIOS[Scenario.USD_TRY_SPIKE].shocks)
    assert result.worst_hit_symbol == "THYAO.IS"
    assert result.impacts[0].pnl_usd == 0.0


def test_stress_test_without_losses_or_holdings() -> None:
    rally = run_stress_test([US_HOLDING], ShockSet(us_equity_shock_pct=10))
    assert rally.worst_hit_symbol is None
    assert rally.total_pnl_pct == pytest.approx(10.0)

    empty = run_stress_test([], ShockSet(us_equity_shock_pct=-10))
    assert empty.total_before_usd == 0.0
    assert empty.total_pnl_pct is None


def test_invalid_shocks_are_rejected() -> None:
    with pytest.raises(ValueError):
        ShockSet(us_equity_shock_pct=-101)
    with pytest.raises(ValueError):
        ShockSet(usd_try_shock_pct=-100)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

USD_TRY = 40.0
QUOTES = {
    "AAPL": Quote("AAPL", price=100.0, previous_close=101.0, change_pct=-0.99, currency="USD"),
    "MSFT": Quote("MSFT", price=200.0, previous_close=199.0, change_pct=0.5, currency="USD"),
    "THYAO.IS": Quote("THYAO.IS", price=400.0, previous_close=390.0, change_pct=2.56, currency="TRY"),
    "NOHIST": Quote("NOHIST", price=10.0, previous_close=10.0, change_pct=0.0, currency="USD"),
}
HISTORY = {
    "AAPL": [100, 102, 101, 104, 103, 106, 105, 108, 107, 110],
    "MSFT": [200, 204, 202, 208, 206, 212, 210, 216, 214, 220],  # exactly 2x AAPL: collinear
    "THYAO.IS": [380, 372, 390, 385, 401, 395, 410, 398, 405, 400],
    "TRY=X": [38.0, 38.2, 38.5, 38.4, 38.9, 39.2, 39.4, 39.6, 39.8, 40.0],
}


class SimulationMarket(MarketService):
    def get_quote(self, symbol: str) -> Quote:
        return QUOTES.get(symbol, Quote.unavailable(symbol))

    def get_history(self, symbol: str) -> list[PricePoint]:
        closes = HISTORY.get(symbol, [])
        start = date.today() - timedelta(days=len(closes) - 1)
        return [PricePoint((start + timedelta(days=i)).isoformat(), float(c)) for i, c in enumerate(closes)]

    def get_news(self, symbol: str) -> list[NewsHeadline]:
        return []

    def get_fx_rate_to_usd(self, currency: str | None) -> float | None:
        return {"USD": 1.0, "TRY": 1 / USD_TRY}.get(currency or "")


@pytest.fixture
def lab() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    market = SimulationMarket()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_market_service] = lambda: market
    yield TestClient(app), factory
    app.dependency_overrides.clear()
    engine.dispose()


def _hold(factory: sessionmaker[Session], *positions: tuple[str, float]) -> None:
    with factory() as db:
        db.add_all(WatchlistItem(symbol=s, shares=n, avg_cost=1.0) for s, n in positions)
        db.commit()


def test_monte_carlo_endpoint_is_deterministic(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10), ("THYAO.IS", 100))
    url = "/api/portfolio/monte-carlo?days=30&simulations=500&seed=42"

    first = client.get(url)
    assert first.status_code == 200, first.text
    body = first.json()
    assert client.get(url).json() == body

    assert body["initial_value"] == pytest.approx(1000 + 100 * 400 / USD_TRY)
    assert len(body["bands"]) == 31
    assert body["bands"][0]["p50"] == body["initial_value"]
    for band in body["bands"]:
        assert band["p5"] <= band["p25"] <= band["p50"] <= band["p75"] <= band["p95"]
    assert body["cvar_95_simulated"] >= body["var_95_simulated"]
    assert body["observations"] == 9
    assert {h["symbol"]: h["fx_adjusted"] for h in body["holdings"]} == {"AAPL": True, "THYAO.IS": True}
    assert sum(h["weight_pct"] for h in body["holdings"]) == pytest.approx(100, abs=0.02)

    other_seed = client.get("/api/portfolio/monte-carlo?days=30&simulations=500&seed=43").json()
    assert other_seed["bands"] != body["bands"]


def test_monte_carlo_single_asset_and_collinear_portfolios(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10))
    single = client.get("/api/portfolio/monte-carlo?days=10&simulations=200&seed=1")
    assert single.status_code == 200, single.text
    assert [h["symbol"] for h in single.json()["holdings"]] == ["AAPL"]

    _hold(factory, ("MSFT", 5))  # same returns as AAPL -> singular covariance
    collinear = client.get("/api/portfolio/monte-carlo?days=10&simulations=200&seed=1")
    assert collinear.status_code == 200, collinear.text
    assert collinear.json()["cholesky_jitter"] >= 0


def test_monte_carlo_excludes_symbols_without_history(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10), ("NOHIST", 3), ("ZZZZ", 1))
    body = client.get("/api/portfolio/monte-carlo?days=5&simulations=100&seed=0").json()
    assert body["excluded_symbols"] == ["NOHIST", "ZZZZ"]
    assert body["initial_value"] == 1000.0


def test_monte_carlo_errors(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = lab
    assert client.get("/api/portfolio/monte-carlo").status_code == 422  # empty portfolio
    assert client.get("/api/portfolio/monte-carlo?simulations=10").status_code == 422
    assert client.get("/api/portfolio/monte-carlo?days=0").status_code == 422
    assert client.get("/api/portfolio/monte-carlo?drift=bogus").status_code == 422


def test_stress_scenarios_endpoint(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = lab
    body = client.get("/api/portfolio/stress-test/scenarios").json()
    assert [s["key"] for s in body] == [s.value for s in Scenario]


@pytest.mark.parametrize("scenario", list(Scenario))
def test_stress_test_presets_endpoint(lab: tuple[TestClient, sessionmaker[Session]], scenario: Scenario) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10), ("THYAO.IS", 100))
    response = client.post("/api/portfolio/stress-test", json={"scenario": scenario.value})
    assert response.status_code == 200, response.text
    body = response.json()

    shocks = PRESET_SCENARIOS[scenario].shocks
    assert body["label"] == PRESET_SCENARIOS[scenario].label
    assert body["total_before_usd"] == 2000.0
    by_symbol = {p["symbol"]: p for p in body["positions"]}
    assert by_symbol["AAPL"]["pnl_pct"] == pytest.approx(shocks.us_equity_shock_pct)
    expected_bist = ((1 + shocks.bist_equity_shock_pct / 100) / (1 + shocks.usd_try_shock_pct / 100) - 1) * 100
    assert by_symbol["THYAO.IS"]["pnl_pct"] == pytest.approx(expected_bist, abs=0.01)
    assert by_symbol["THYAO.IS"]["segment"] == "BIST_EQUITY"
    assert body["total_pnl_usd"] == pytest.approx(sum(p["pnl_usd"] for p in body["positions"]), abs=0.02)


def test_stress_test_custom_fx_shock(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = lab
    _hold(factory, ("AAPL", 10), ("THYAO.IS", 100), ("ZZZZ", 1))
    body = client.post("/api/portfolio/stress-test", json={"usd_try_shock_pct": 25}).json()

    assert body["scenario"] is None
    assert body["label"] == "Custom shocks"
    by_symbol = {p["symbol"]: p for p in body["positions"]}
    assert by_symbol["AAPL"]["pnl_usd"] == 0.0
    assert by_symbol["THYAO.IS"]["value_after_usd"] == pytest.approx(800.0)
    assert body["total_pnl_usd"] == pytest.approx(-200.0)
    assert body["total_pnl_pct"] == pytest.approx(-10.0)
    assert body["worst_hit_symbol"] == "THYAO.IS"
    assert body["excluded_symbols"] == ["ZZZZ"]


def test_stress_test_validation(lab: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = lab
    post = client.post
    assert post("/api/portfolio/stress-test", json={"scenario": "covid_crash", "us_equity_shock_pct": -5}).status_code == 422
    assert post("/api/portfolio/stress-test", json={"scenario": "alien_invasion"}).status_code == 422
    assert post("/api/portfolio/stress-test", json={"usd_try_shock_pct": -100}).status_code == 422
    assert post("/api/portfolio/stress-test", json={"us_equity_shock_pct": -150}).status_code == 422
    empty = post("/api/portfolio/stress-test", json={})
    assert empty.status_code == 200
    assert empty.json()["positions"] == []
