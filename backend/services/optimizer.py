"""Markowitz mean-variance optimisation by long-only random portfolio search.

Instead of a quadratic-programming solver (which would need SciPy), the
long-only feasible set - the probability simplex ``{w : w ≥ 0, Σw = 1}`` - is
sampled densely with Dirichlet draws, every candidate is scored on annualised
return, volatility and Sharpe ratio, and the best candidates are picked. A
handful of anchors (every single-asset corner, equal weight and the current
allocation) are always included, so the reported optimum is never worse than
the portfolio the user already holds.

Pure NumPy, no I/O: fully deterministic for a given seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from services.monte_carlo import covariance_matrix
from services.risk_engine import RISK_FREE_RATE_ANNUAL, TRADING_DAYS_PER_YEAR

# Smallest allowed eigenvalue of the covariance, relative to the mean variance.
MIN_EIGENVALUE_RATIO = 1e-8
DEFAULT_SAMPLES = 4000
CLOUD_POINTS = 300
MAX_FRONTIER_POINTS = 60
# Half the draws use Dirichlet(1) (uniform on the simplex), half a sparse
# Dirichlet(0.3) that pushes mass towards edges and corners, where optima live.
UNIFORM_ALPHA = 1.0
SPARSE_ALPHA = 0.3


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnnualizedMoments:
    mean: NDArray[np.float64]  # annualised mean log-return per asset
    covariance: NDArray[np.float64]  # annualised covariance (jitter already added)
    jitter: float  # daily-scale ridge added so the smallest eigenvalue clears the floor


def regularize_covariance(
    covariance: ArrayLike,
    min_eigenvalue_ratio: float = MIN_EIGENVALUE_RATIO,
) -> tuple[NDArray[np.float64], float]:
    """Make a covariance matrix strictly positive definite on every platform.

    A sample covariance is only positive *semi*-definite: collinear or
    zero-variance holdings give a smallest eigenvalue of 0, which floating-point
    rounding turns into ±1e-18. Whether ``np.linalg.cholesky`` then succeeds
    depends on the BLAS build (e.g. OpenBLAS on Linux vs. Windows), so a
    pass/fail Cholesky probe is not a reliable test.

    Instead the smallest eigenvalue (``eigvalsh``, exact for symmetric
    matrices) is lifted to a floor of ``min_eigenvalue_ratio × mean variance``
    by adding a ridge ``εI``. Adding ``εI`` shifts every eigenvalue by exactly
    ``ε``, so the result has ``λ_min ≥ floor``: about eight orders of magnitude
    above rounding noise, yet far too small to move any reported statistic.
    Well-conditioned matrices are returned unchanged (ridge = 0).
    """
    cov = np.atleast_2d(np.asarray(covariance, dtype=float))
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError("covariance must be a square matrix")
    if not np.all(np.isfinite(cov)):
        raise ValueError("covariance contains non-finite values")
    cov = (cov + cov.T) / 2  # eigvalsh assumes exact symmetry

    scale = float(np.mean(np.abs(np.diag(cov)))) or 1.0
    floor = min_eigenvalue_ratio * scale
    smallest = float(np.linalg.eigvalsh(cov)[0])  # eigenvalues come back in ascending order
    if smallest >= floor:
        return cov, 0.0
    ridge = floor - smallest
    return cov + ridge * np.eye(cov.shape[0]), ridge


def annualized_moments(log_returns: ArrayLike, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> AnnualizedMoments:
    """Annualise the mean (× 252) and covariance (× 252) of daily log-returns.

    The daily covariance is regularised first (see ``regularize_covariance``),
    so a singular matrix from collinear or zero-variance holdings is made
    strictly positive definite. Scaling by 252 preserves that property.
    """
    r = np.asarray(log_returns, dtype=float)
    regularised, jitter = regularize_covariance(covariance_matrix(r))
    return AnnualizedMoments(
        mean=r.mean(axis=0) * periods_per_year,
        covariance=regularised * periods_per_year,
        jitter=jitter,
    )


def normalize_weights(weights: ArrayLike) -> NDArray[np.float64]:
    """Project a non-negative vector onto the simplex (sum to 1)."""
    w = np.clip(np.asarray(weights, dtype=float), 0.0, None)
    total = w.sum()
    if total <= 0:
        raise ValueError("weights must contain at least one positive value")
    return w / total


# ---------------------------------------------------------------------------
# Sampling and scoring
# ---------------------------------------------------------------------------


def sample_weights(
    n_assets: int,
    samples: int,
    rng: np.random.Generator,
    anchors: ArrayLike | None = None,
) -> NDArray[np.float64]:
    """``samples`` long-only weight vectors (rows), anchors first.

    Default anchors are every single-asset corner plus equal weight; extra
    ``anchors`` (e.g. the current allocation) are prepended. The remaining rows
    are Dirichlet draws, half uniform and half sparse.
    """
    if n_assets < 1 or samples < 1:
        raise ValueError("n_assets and samples must be positive")

    fixed = [np.eye(n_assets), np.full((1, n_assets), 1.0 / n_assets)]
    if anchors is not None:
        fixed.insert(0, np.atleast_2d(np.asarray(anchors, dtype=float)))
    anchor_rows = np.vstack(fixed)[:samples]

    remaining = samples - anchor_rows.shape[0]
    uniform = remaining // 2
    draws = np.vstack(
        [
            rng.dirichlet(np.full(n_assets, UNIFORM_ALPHA), size=uniform),
            rng.dirichlet(np.full(n_assets, SPARSE_ALPHA), size=remaining - uniform),
        ]
    )
    return np.vstack([anchor_rows, draws])


@dataclass(frozen=True)
class PortfolioStats:
    returns: NDArray[np.float64]  # annualised, as fractions
    volatility: NDArray[np.float64]
    sharpe: NDArray[np.float64]  # NaN where volatility is 0


def portfolio_stats(
    weights: ArrayLike,
    moments: AnnualizedMoments,
    risk_free_rate: float = RISK_FREE_RATE_ANNUAL,
) -> PortfolioStats:
    """Vectorised return ``wᵀμ``, volatility ``√(wᵀΣw)`` and Sharpe for each row of ``weights``."""
    w = np.atleast_2d(np.asarray(weights, dtype=float))
    returns = w @ moments.mean
    variance = np.einsum("ij,jk,ik->i", w, moments.covariance, w)
    volatility = np.sqrt(np.clip(variance, 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(volatility > 0, (returns - risk_free_rate) / volatility, np.nan)
    return PortfolioStats(returns=returns, volatility=volatility, sharpe=sharpe)


def efficient_frontier_indices(
    returns: ArrayLike,
    volatility: ArrayLike,
    max_points: int = MAX_FRONTIER_POINTS,
) -> NDArray[np.intp]:
    """Indices of the upper efficient frontier, ordered by increasing volatility.

    Walking from the lowest-volatility portfolio, a point is efficient when
    its return beats every lower-risk point: no other sample gives more
    return for the same or less risk. Long curves are thinned evenly.
    """
    ret = np.asarray(returns, dtype=float)
    vol = np.asarray(volatility, dtype=float)
    order = np.lexsort((-ret, vol))  # by volatility, then highest return first

    frontier: list[int] = []
    best = -np.inf
    for idx in order:
        if ret[idx] > best:
            frontier.append(int(idx))
            best = ret[idx]

    if len(frontier) > max_points:
        keep = np.unique(np.linspace(0, len(frontier) - 1, max_points).round().astype(int))
        frontier = [frontier[i] for i in keep]
    return np.asarray(frontier, dtype=np.intp)


def cloud_indices(n_samples: int, max_points: int = CLOUD_POINTS) -> NDArray[np.intp]:
    """Evenly spaced subset of the (randomly ordered) samples for plotting."""
    if n_samples <= max_points:
        return np.arange(n_samples, dtype=np.intp)
    return np.unique(np.linspace(0, n_samples - 1, max_points).round().astype(np.intp))


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioPoint:
    weights: NDArray[np.float64]
    expected_return: float
    volatility: float
    sharpe: float | None


@dataclass(frozen=True)
class OptimizationResult:
    moments: AnnualizedMoments
    current: PortfolioPoint
    max_sharpe: PortfolioPoint
    min_volatility: PortfolioPoint
    samples: int
    cloud: PortfolioStats  # downsampled candidates
    frontier: PortfolioStats  # efficient-frontier candidates, by increasing volatility


def _point(weights: NDArray[np.float64], stats: PortfolioStats, index: int) -> PortfolioPoint:
    sharpe = float(stats.sharpe[index])
    return PortfolioPoint(
        weights=weights[index],
        expected_return=float(stats.returns[index]),
        volatility=float(stats.volatility[index]),
        sharpe=sharpe if np.isfinite(sharpe) else None,
    )


def _subset(stats: PortfolioStats, idx: NDArray[np.intp]) -> PortfolioStats:
    return PortfolioStats(stats.returns[idx], stats.volatility[idx], stats.sharpe[idx])


def optimize_portfolio(
    current_weights: ArrayLike,
    log_returns: ArrayLike,
    samples: int = DEFAULT_SAMPLES,
    seed: int | None = None,
    risk_free_rate: float = RISK_FREE_RATE_ANNUAL,
) -> OptimizationResult:
    """Max-Sharpe and min-volatility long-only portfolios by simplex sampling.

    The current allocation is always the first candidate, so the reported
    optima satisfy ``min_volatility.volatility ≤ current.volatility`` and
    ``max_sharpe.sharpe ≥ current.sharpe`` by construction. With a single
    holding the only feasible portfolio is 100% in it, which is returned for
    all three points.
    """
    current = normalize_weights(current_weights)
    r = np.asarray(log_returns, dtype=float)
    if r.ndim != 2 or r.shape[1] != current.shape[0]:
        raise ValueError("log_returns must be (observations x assets) and match current_weights")

    moments = annualized_moments(r)
    n_assets = current.shape[0]
    rng = np.random.default_rng(seed)
    weights = current[np.newaxis, :] if n_assets == 1 else sample_weights(n_assets, samples, rng, anchors=current)
    stats = portfolio_stats(weights, moments, risk_free_rate)

    min_vol_idx = int(np.argmin(stats.volatility))
    finite = np.isfinite(stats.sharpe)
    max_sharpe_idx = int(np.argmax(np.where(finite, stats.sharpe, -np.inf))) if finite.any() else min_vol_idx

    return OptimizationResult(
        moments=moments,
        current=_point(weights, stats, 0),
        max_sharpe=_point(weights, stats, max_sharpe_idx),
        min_volatility=_point(weights, stats, min_vol_idx),
        samples=int(weights.shape[0]),
        cloud=_subset(stats, cloud_indices(weights.shape[0])),
        frontier=_subset(stats, efficient_frontier_indices(stats.returns, stats.volatility)),
    )
