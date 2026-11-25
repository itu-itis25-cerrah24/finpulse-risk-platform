"""Pydantic request/response schemas (API contract)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.alert_service import AlertSeverity, AlertType
from services.monte_carlo import DriftModel
from services.risk_engine import DailyRiskFlag, RiskLevel, SentimentLabel
from services.stress_test import MarketSegment, Scenario

# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


class WatchlistCreate(BaseModel):
    symbol: str = Field(
        ...,
        min_length=1,
        max_length=20,
        pattern=r"^[A-Z0-9.\-=^]+$",
        examples=["AAPL", "THYAO.IS"],
    )
    shares: float = Field(..., gt=0, description="Number of shares held")
    avg_cost: float = Field(..., gt=0, description="Average cost per share in the instrument's currency")
    risk_threshold_pct: float = Field(
        3.0, gt=0, le=50, description="Absolute daily % move that triggers a HIGH_DROP / HIGH_SPIKE flag"
    )

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class WatchlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    shares: float
    avg_cost: float
    risk_threshold_pct: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Analytics building blocks
# ---------------------------------------------------------------------------


class QuantMetricsOut(BaseModel):
    annualized_volatility_pct: float | None = Field(None, description="Std-dev of daily returns x sqrt(252), in %")
    var_95_pct: float | None = Field(None, description="1-day historical VaR at 95% confidence, as a positive loss %")
    max_drawdown_pct: float | None = Field(None, description="Worst peak-to-trough decline, as a negative %")
    sharpe_ratio: float | None = Field(None, description="Annualized Sharpe ratio (4% risk-free rate)")
    observations: int = Field(0, description="Number of daily returns used")


class HeadlineOut(BaseModel):
    title: str
    publisher: str | None = None
    link: str | None = None
    published_at: str | None = None
    sentiment_score: float
    sentiment_label: SentimentLabel


class SentimentOut(BaseModel):
    label: SentimentLabel
    score: float = Field(..., description="Mean VADER compound score in [-1, 1]")
    headline_count: int


class PricePointOut(BaseModel):
    date: str
    close: float


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    id: int
    symbol: str
    shares: float
    avg_cost: float
    risk_threshold_pct: float
    currency: str | None
    data_available: bool

    price: float | None
    previous_close: float | None
    daily_change_pct: float | None
    daily_flag: DailyRiskFlag

    market_value: float | None
    cost_basis: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None

    fx_rate_to_usd: float | None
    market_value_usd: float | None
    unrealized_pnl_usd: float | None

    quant: QuantMetricsOut
    sentiment: SentimentOut
    risk_score: float
    risk_level: RiskLevel


class PortfolioSummaryOut(BaseModel):
    base_currency: str = "USD"
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float | None
    weighted_risk_score: float | None
    risk_level: RiskLevel | None
    position_count: int
    priced_position_count: int
    as_of: datetime


class PortfolioOut(BaseModel):
    summary: PortfolioSummaryOut
    positions: list[PositionOut]


# ---------------------------------------------------------------------------
# Single stock detail
# ---------------------------------------------------------------------------


class StockHistoryOut(BaseModel):
    symbol: str
    currency: str | None
    price: float | None
    previous_close: float | None
    daily_change_pct: float | None
    history: list[PricePointOut]
    headlines: list[HeadlineOut]
    sentiment: SentimentOut
    quant: QuantMetricsOut
    risk_score: float
    risk_level: RiskLevel


# ---------------------------------------------------------------------------
# Correlation & benchmark
# ---------------------------------------------------------------------------


class CorrelationPairOut(BaseModel):
    symbol_a: str
    symbol_b: str
    correlation: float


class CorrelationOut(BaseModel):
    symbols: list[str]
    matrix: list[list[float | None]] = Field(..., description="Pearson correlations; null where undefined")
    observations: int = Field(..., description="Number of date-aligned daily returns used")
    start_date: str | None
    end_date: str | None
    average_correlation: float | None = Field(None, description="Mean off-diagonal correlation")
    high_correlation_threshold: float
    high_correlation_pairs: list[CorrelationPairOut]
    excluded_symbols: list[str] = Field(default_factory=list, description="Symbols without price history")


class BenchmarkPointOut(BaseModel):
    date: str
    asset_pct: float
    benchmark_pct: float


class BenchmarkOut(BaseModel):
    symbol: str
    benchmark_symbol: str
    window_days: int
    points: list[BenchmarkPointOut]
    asset_return_pct: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None
    beta: float | None
    correlation: float | None
    observations: int


# ---------------------------------------------------------------------------
# Risk Lab: Monte Carlo simulation
# ---------------------------------------------------------------------------


class MonteCarloBandOut(BaseModel):
    day: int = Field(..., description="Trading days from today (0 = current value)")
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class SimulatedHoldingOut(BaseModel):
    symbol: str
    value_usd: float
    weight_pct: float
    annualized_drift_pct: float = Field(..., description="Simulated daily log drift x 252")
    annualized_volatility_pct: float
    fx_adjusted: bool = Field(..., description="Returns measured in USD (includes currency moves)")


class MonteCarloOut(BaseModel):
    horizon_days: int
    simulations: int
    seed: int | None
    drift_model: DriftModel
    confidence: float
    observations: int = Field(..., description="Date-aligned daily log-returns used for estimation")
    start_date: str
    end_date: str
    cholesky_jitter: float = Field(..., description="Diagonal ridge added to make the covariance factorisable")
    holdings: list[SimulatedHoldingOut]
    initial_value: float
    expected_value: float
    median_value: float
    expected_return_pct: float
    var_95_simulated: float = Field(..., description="95% horizon VaR in USD (positive = loss)")
    var_95_pct: float
    cvar_95_simulated: float = Field(..., description="95% Expected Shortfall in USD (>= VaR)")
    cvar_95_pct: float
    probability_of_loss_pct: float
    bands: list[MonteCarloBandOut]
    excluded_symbols: list[str] = Field(default_factory=list, description="No live price, FX rate or history")


# ---------------------------------------------------------------------------
# Risk Lab: stress testing
# ---------------------------------------------------------------------------

SHOCK_FIELDS = ("us_equity_shock_pct", "bist_equity_shock_pct", "usd_try_shock_pct")


class StressTestRequest(BaseModel):
    """Either a preset ``scenario`` or any combination of custom shocks (default 0)."""

    scenario: Scenario | None = None
    us_equity_shock_pct: float = Field(0.0, ge=-100, le=100)
    bist_equity_shock_pct: float = Field(0.0, ge=-100, le=100)
    usd_try_shock_pct: float = Field(0.0, gt=-100, le=300, description="% change in TRY per USD")

    @model_validator(mode="after")
    def preset_or_custom(self) -> "StressTestRequest":
        if self.scenario is not None and self.model_fields_set.intersection(SHOCK_FIELDS):
            raise ValueError("Provide either a preset scenario or custom shocks, not both")
        return self


class ScenarioOut(BaseModel):
    key: Scenario
    label: str
    description: str
    us_equity_shock_pct: float
    bist_equity_shock_pct: float
    usd_try_shock_pct: float


class StressImpactOut(BaseModel):
    symbol: str
    segment: MarketSegment
    currency: str | None
    value_before_usd: float
    value_after_usd: float
    pnl_usd: float
    pnl_pct: float
    equity_shock_pct: float
    fx_shock_pct: float


class StressTestOut(BaseModel):
    scenario: Scenario | None
    label: str
    us_equity_shock_pct: float
    bist_equity_shock_pct: float
    usd_try_shock_pct: float
    positions: list[StressImpactOut]
    total_before_usd: float
    total_after_usd: float
    total_pnl_usd: float
    total_pnl_pct: float | None
    worst_hit_symbol: str | None
    excluded_symbols: list[str] = Field(default_factory=list, description="No live price or FX rate")


# ---------------------------------------------------------------------------
# Risk Lab: Markowitz optimisation
# ---------------------------------------------------------------------------


class RebalanceAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class WeightOut(BaseModel):
    symbol: str
    weight_pct: float


class PortfolioPointOut(BaseModel):
    expected_return_pct: float = Field(..., description="Annualised mean log-return")
    volatility_pct: float = Field(..., description="Annualised volatility")
    sharpe_ratio: float | None = Field(None, description="(return - rf) / volatility")
    weights: list[WeightOut]


class FrontierPointOut(BaseModel):
    expected_return_pct: float
    volatility_pct: float
    sharpe_ratio: float | None


class AssetMomentsOut(BaseModel):
    symbol: str
    value_usd: float
    expected_return_pct: float
    volatility_pct: float


class RebalanceRowOut(BaseModel):
    symbol: str
    current_weight_pct: float
    target_weight_pct: float
    delta_weight_pct: float
    delta_usd: float = Field(..., description="Positive = buy, negative = sell")
    action: RebalanceAction


class RebalancingOut(BaseModel):
    max_sharpe: list[RebalanceRowOut]
    min_volatility: list[RebalanceRowOut]


class OptimizationOut(BaseModel):
    samples: int = Field(..., description="Candidate portfolios evaluated (including anchors)")
    seed: int | None
    risk_free_rate_pct: float
    observations: int
    start_date: str
    end_date: str
    covariance_jitter: float
    total_value_usd: float
    assets: list[AssetMomentsOut]
    current_portfolio: PortfolioPointOut
    max_sharpe: PortfolioPointOut
    min_volatility: PortfolioPointOut
    frontier_cloud: list[FrontierPointOut] = Field(..., description="Downsampled candidates for plotting")
    efficient_frontier: list[FrontierPointOut] = Field(..., description="Upper frontier, by increasing volatility")
    rebalancing: RebalancingOut
    excluded_symbols: list[str] = Field(default_factory=list, description="No live price, FX rate or history")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    alert_type: AlertType
    message: str
    severity: AlertSeverity
    created_at: datetime
