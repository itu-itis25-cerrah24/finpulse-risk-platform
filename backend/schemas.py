"""Pydantic request/response schemas (API contract)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.alert_service import AlertSeverity, AlertType
from services.risk_engine import DailyRiskFlag, RiskLevel, SentimentLabel

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
