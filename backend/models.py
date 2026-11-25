"""SQLAlchemy ORM models."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WatchlistItem(Base):
    """A position tracked in the user's portfolio."""

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    risk_threshold_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    def __repr__(self) -> str:
        return f"<WatchlistItem {self.symbol} shares={self.shares} avg_cost={self.avg_cost}>"


class RiskAlert(Base):
    """A risk event raised by the alert engine for a given symbol."""

    __tablename__ = "risk_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    def __repr__(self) -> str:
        return f"<RiskAlert {self.symbol} {self.alert_type} {self.severity}>"
