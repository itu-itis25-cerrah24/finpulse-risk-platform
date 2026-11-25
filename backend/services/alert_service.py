"""Risk alert rules and persistence.

Rule evaluation is a pure function of an analyzed position; persistence
de-duplicates so the same (symbol, alert_type) is stored at most once per UTC
day, no matter how often the dashboard refreshes.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import RiskAlert
from services.risk_engine import DailyRiskFlag, SentimentLabel

if TYPE_CHECKING:  # avoid a runtime import cycle with schemas.py
    from schemas import PositionOut

HIGH_RISK_SCORE_THRESHOLD = 70.0
DEEP_DRAWDOWN_THRESHOLD_PCT = -25.0
CRITICAL_MOVE_MULTIPLIER = 2.0  # a drop of 2x the threshold escalates to CRITICAL

# Concurrent refreshes (several browser tabs, React StrictMode double-fetch)
# would otherwise both pass the "already raised today?" check and insert
# duplicates. Serializing the check-then-insert makes it atomic per process.
_persist_lock = threading.Lock()


class AlertSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertType(StrEnum):
    HIGH_DROP = "HIGH_DROP"
    HIGH_SPIKE = "HIGH_SPIKE"
    HIGH_RISK_SCORE = "HIGH_RISK_SCORE"
    BEARISH_SENTIMENT = "BEARISH_SENTIMENT"
    DEEP_DRAWDOWN = "DEEP_DRAWDOWN"


@dataclass(frozen=True)
class AlertCandidate:
    symbol: str
    alert_type: AlertType
    severity: AlertSeverity
    message: str


def evaluate_position_alerts(position: PositionOut) -> list[AlertCandidate]:
    """Apply every alert rule to one analyzed position."""
    if not position.data_available:
        return []

    alerts: list[AlertCandidate] = []
    symbol = position.symbol
    change = position.daily_change_pct
    threshold = position.risk_threshold_pct

    if position.daily_flag == DailyRiskFlag.HIGH_DROP and change is not None:
        severity = (
            AlertSeverity.CRITICAL
            if change <= -threshold * CRITICAL_MOVE_MULTIPLIER
            else AlertSeverity.HIGH
        )
        alerts.append(
            AlertCandidate(symbol, AlertType.HIGH_DROP, severity,
                           f"{symbol} fell {change:.2f}% today (threshold -{threshold:.2f}%).")
        )
    elif position.daily_flag == DailyRiskFlag.HIGH_SPIKE and change is not None:
        alerts.append(
            AlertCandidate(symbol, AlertType.HIGH_SPIKE, AlertSeverity.MEDIUM,
                           f"{symbol} jumped +{change:.2f}% today (threshold +{threshold:.2f}%).")
        )

    if position.risk_score >= HIGH_RISK_SCORE_THRESHOLD:
        alerts.append(
            AlertCandidate(symbol, AlertType.HIGH_RISK_SCORE, AlertSeverity.HIGH,
                           f"{symbol} composite risk score is {position.risk_score:.1f}/100.")
        )

    if position.sentiment.label == SentimentLabel.BEARISH:
        alerts.append(
            AlertCandidate(symbol, AlertType.BEARISH_SENTIMENT, AlertSeverity.MEDIUM,
                           f"News sentiment for {symbol} is bearish "
                           f"(score {position.sentiment.score:.2f} over {position.sentiment.headline_count} headlines).")
        )

    drawdown = position.quant.max_drawdown_pct
    if drawdown is not None and drawdown <= DEEP_DRAWDOWN_THRESHOLD_PCT:
        alerts.append(
            AlertCandidate(symbol, AlertType.DEEP_DRAWDOWN, AlertSeverity.MEDIUM,
                           f"{symbol} max drawdown over 90 days is {drawdown:.2f}%.")
        )

    return alerts


def persist_alerts(db: Session, candidates: Iterable[AlertCandidate]) -> list[RiskAlert]:
    """Store new alerts, skipping any (symbol, alert_type) already raised today."""
    with _persist_lock:
        return _persist_alerts_locked(db, candidates)


def _persist_alerts_locked(db: Session, candidates: Iterable[AlertCandidate]) -> list[RiskAlert]:
    start_of_day = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    existing = {
        (symbol, alert_type)
        for symbol, alert_type in db.execute(
            select(RiskAlert.symbol, RiskAlert.alert_type).where(RiskAlert.created_at >= start_of_day)
        )
    }

    created: list[RiskAlert] = []
    for candidate in candidates:
        key = (candidate.symbol, candidate.alert_type.value)
        if key in existing:
            continue
        existing.add(key)
        created.append(
            RiskAlert(
                symbol=candidate.symbol,
                alert_type=candidate.alert_type.value,
                severity=candidate.severity.value,
                message=candidate.message,
            )
        )

    if created:
        db.add_all(created)
        db.commit()
    return created


def refresh_alerts(db: Session, positions: Iterable[PositionOut]) -> list[RiskAlert]:
    """Evaluate all positions and persist any newly triggered alerts."""
    candidates = [alert for position in positions for alert in evaluate_position_alerts(position)]
    return persist_alerts(db, candidates)
