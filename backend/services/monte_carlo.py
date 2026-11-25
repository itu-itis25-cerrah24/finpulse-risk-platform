"""Correlated Monte Carlo simulation of portfolio value.

Each holding follows a Geometric Brownian Motion (GBM) whose daily log-return
drift and covariance are estimated from history. Cross-asset correlation is
preserved by colouring independent standard-normal draws with the Cholesky
factor ``L`` of the covariance matrix (``Σ = L Lᵀ``), so the simulated shocks
``L z`` have exactly covariance ``Σ``.

Everything here is pure NumPy with no I/O, so the maths is unit-testable with
a fixed random seed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import ArrayLike, NDArray

from services.risk_engine import DatedPrices

DEFAULT_CONFIDENCE = 0.95
PERCENTILES: tuple[int, ...] = (5, 25, 50, 75, 95)
MIN_SIMULATION_OBSERVATIONS = 5
INITIAL_JITTER = 1e-10
MAX_JITTER_ATTEMPTS = 10


class DriftModel(StrEnum):
    """How the expected daily log-return of each asset is set."""

    HISTORICAL = "historical"  # sample mean of historical log-returns
    ZERO = "zero"  # μ = 0: prices are martingales, only volatility drives the fan


# ---------------------------------------------------------------------------
# Input preparation
# ---------------------------------------------------------------------------


def convert_to_usd(prices: DatedPrices, fx_per_usd: DatedPrices) -> list[tuple[str, float]]:
    """Convert a local-currency price series to USD using a same-day FX series.

    ``fx_per_usd`` follows Yahoo's ``<CCY>=X`` quoting: units of local
    currency per 1 USD (e.g. ``TRY=X`` ≈ 41). Only dates present in both
    series are kept, so a BIST holding's USD returns include lira moves.
    """
    fx_lookup = {date: rate for date, rate in fx_per_usd if rate > 0}
    return [(date, price / fx_lookup[date]) for date, price in prices if date in fx_lookup]


def log_returns(prices: ArrayLike) -> NDArray[np.float64]:
    """Daily log-returns ``ln(Pₜ / Pₜ₋₁)`` of a ``(n_dates, n_assets)`` price matrix."""
    p = np.asarray(prices, dtype=float)
    if p.ndim != 2:
        raise ValueError("prices must be a 2-D (dates x assets) array")
    if p.shape[0] < 2:
        return np.empty((0, p.shape[1]), dtype=float)
    if np.any(p <= 0):
        raise ValueError("prices must be strictly positive")
    return np.diff(np.log(p), axis=0)


def covariance_matrix(returns: ArrayLike) -> NDArray[np.float64]:
    """Sample covariance (ddof=1) of the columns; always returned as 2-D."""
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2 or r.shape[0] < 2:
        raise ValueError("need a 2-D returns matrix with at least two observations")
    return np.atleast_2d(np.cov(r, rowvar=False, ddof=1))


def cholesky_with_jitter(
    covariance: ArrayLike,
    initial_jitter: float = INITIAL_JITTER,
    max_attempts: int = MAX_JITTER_ATTEMPTS,
) -> tuple[NDArray[np.float64], float]:
    """Lower-triangular ``L`` with ``L Lᵀ ≈ Σ``, plus the diagonal jitter used.

    A sample covariance is only positive *semi*-definite: collinear holdings,
    a zero-variance series or fewer observations than assets make it singular
    and ``np.linalg.cholesky`` fails. In that case a small ridge ``εI`` (scaled
    to the average variance) is added and grown tenfold until it factorises.
    """
    cov = np.atleast_2d(np.asarray(covariance, dtype=float))
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError("covariance must be a square matrix")
    if not np.all(np.isfinite(cov)):
        raise ValueError("covariance contains non-finite values")
    cov = (cov + cov.T) / 2  # remove floating-point asymmetry

    try:
        return np.linalg.cholesky(cov), 0.0
    except np.linalg.LinAlgError:
        pass

    scale = float(np.mean(np.abs(np.diag(cov)))) or 1.0
    jitter = initial_jitter * scale
    identity = np.eye(cov.shape[0])
    for _ in range(max_attempts):
        try:
            return np.linalg.cholesky(cov + jitter * identity), jitter
        except np.linalg.LinAlgError:
            jitter *= 10
    raise np.linalg.LinAlgError("covariance matrix could not be regularised into a positive-definite matrix")


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def simulate_portfolio_paths(
    initial_values: ArrayLike,
    drift: ArrayLike,
    cholesky_factor: ArrayLike,
    horizon_days: int,
    simulations: int,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Simulate total portfolio value under correlated GBM.

    For every step and path: ``ln Sₜ₊₁ = ln Sₜ + drift + L z`` with
    ``z ~ N(0, I)``. ``drift`` is the per-asset daily log-return drift, i.e.
    GBM's ``μ − ½σ²`` term.

    Antithetic variates: every draw ``z`` is paired with ``−z``, so the shocks
    are exactly symmetric and the sampling noise of the mean is reduced at no
    extra cost.

    Returns a ``(simulations, horizon_days + 1)`` array whose first column is
    today's value. Steps are generated one day at a time, so memory stays
    ``O(simulations × (assets + horizon))`` rather than a full 3-D tensor.
    """
    values0 = np.asarray(initial_values, dtype=float)
    mu = np.asarray(drift, dtype=float)
    chol = np.atleast_2d(np.asarray(cholesky_factor, dtype=float))
    n_assets = values0.shape[0]
    if mu.shape != (n_assets,) or chol.shape != (n_assets, n_assets):
        raise ValueError("initial_values, drift and cholesky_factor dimensions do not match")
    if horizon_days < 1 or simulations < 1:
        raise ValueError("horizon_days and simulations must be positive")

    half = (simulations + 1) // 2
    paths = np.empty((simulations, horizon_days + 1), dtype=float)
    paths[:, 0] = values0.sum()
    log_growth = np.zeros((simulations, n_assets), dtype=float)
    for day in range(1, horizon_days + 1):
        z = rng.standard_normal((half, n_assets))
        shocks = np.vstack([z, -z])[:simulations] @ chol.T
        log_growth += mu + shocks
        paths[:, day] = (values0 * np.exp(log_growth)).sum(axis=1)
    return paths


def percentile_bands(paths: ArrayLike, percentiles: Sequence[int] = PERCENTILES) -> NDArray[np.float64]:
    """Cross-sectional percentiles per day: shape ``(len(percentiles), n_days)``."""
    return np.percentile(np.asarray(paths, dtype=float), list(percentiles), axis=0)


@dataclass(frozen=True)
class TerminalSummary:
    initial_value: float
    expected_value: float
    median_value: float
    expected_return_pct: float
    var: float  # loss at the confidence level, in currency (positive = loss)
    cvar: float  # mean loss beyond VaR (Expected Shortfall); always >= var
    probability_of_loss_pct: float


def summarize_terminal_values(
    initial_value: float,
    terminal_values: ArrayLike,
    confidence: float = DEFAULT_CONFIDENCE,
) -> TerminalSummary:
    """VaR, CVaR (Expected Shortfall) and loss probability of the horizon P&L.

    VaR is the ``(1 − confidence)`` quantile of P&L, sign-flipped so a loss is
    positive. CVaR averages every outcome at or below that quantile, which is
    why ``CVaR ≥ VaR`` holds by construction.
    """
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")
    terminal = np.asarray(terminal_values, dtype=float)
    if terminal.size == 0:
        raise ValueError("terminal_values is empty")

    pnl = terminal - initial_value
    cutoff = float(np.quantile(pnl, 1 - confidence))
    tail = pnl[pnl <= cutoff]
    expected = float(terminal.mean())
    return TerminalSummary(
        initial_value=initial_value,
        expected_value=expected,
        median_value=float(np.median(terminal)),
        expected_return_pct=(expected / initial_value - 1) * 100 if initial_value else 0.0,
        var=-cutoff,
        cvar=-float(tail.mean()),
        probability_of_loss_pct=float(np.mean(pnl < 0) * 100),
    )


@dataclass(frozen=True)
class MonteCarloResult:
    paths_percentiles: NDArray[np.float64]  # (len(PERCENTILES), horizon + 1)
    summary: TerminalSummary
    drift: NDArray[np.float64]  # daily log drift actually simulated, per asset
    volatility: NDArray[np.float64]  # daily log-return σ, per asset
    jitter: float


def run_monte_carlo(
    initial_values: ArrayLike,
    returns: ArrayLike,
    horizon_days: int,
    simulations: int,
    seed: int | None = None,
    drift_model: DriftModel = DriftModel.HISTORICAL,
    confidence: float = DEFAULT_CONFIDENCE,
) -> MonteCarloResult:
    """Estimate GBM parameters from historical log-returns and simulate.

    ``returns`` is a ``(n_observations, n_assets)`` matrix of daily
    log-returns aligned with ``initial_values`` (current USD value per asset).
    With ``DriftModel.ZERO`` the drift is set to ``−½σ²`` so that the
    expected price is flat (μ = 0) and only dispersion remains.
    """
    r = np.asarray(returns, dtype=float)
    values0 = np.asarray(initial_values, dtype=float)
    if r.ndim != 2 or r.shape[1] != values0.shape[0]:
        raise ValueError("returns must be (observations x assets) and match initial_values")
    if r.shape[0] < MIN_SIMULATION_OBSERVATIONS:
        raise ValueError(f"need at least {MIN_SIMULATION_OBSERVATIONS} return observations")

    cov = covariance_matrix(r)
    chol, jitter = cholesky_with_jitter(cov)
    variance = np.diag(cov)
    drift = r.mean(axis=0) if drift_model is DriftModel.HISTORICAL else -0.5 * variance

    rng = np.random.default_rng(seed)
    paths = simulate_portfolio_paths(values0, drift, chol, horizon_days, simulations, rng)
    return MonteCarloResult(
        paths_percentiles=percentile_bands(paths),
        summary=summarize_terminal_values(float(values0.sum()), paths[:, -1], confidence),
        drift=drift,
        volatility=np.sqrt(variance),
        jitter=jitter,
    )
