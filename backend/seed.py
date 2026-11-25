"""Default watchlist seeded on first startup."""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import WatchlistItem

logger = logging.getLogger(__name__)

# (symbol, shares, avg_cost, risk_threshold_pct) - illustrative demo positions.
DEFAULT_WATCHLIST: list[tuple[str, float, float, float]] = [
    ("THYAO.IS", 100, 280.00, 4.0),
    ("ASELS.IS", 150, 120.00, 4.0),
    ("AAPL", 20, 190.00, 3.0),
    ("NVDA", 25, 110.00, 4.0),
]


def seed_default_watchlist(db: Session) -> int:
    """Insert the default positions only if the watchlist is empty. Returns rows added."""
    if db.scalar(select(func.count()).select_from(WatchlistItem)):
        return 0

    db.add_all(
        WatchlistItem(symbol=symbol, shares=shares, avg_cost=avg_cost, risk_threshold_pct=threshold)
        for symbol, shares, avg_cost, threshold in DEFAULT_WATCHLIST
    )
    db.commit()
    logger.info("Seeded %d default watchlist items", len(DEFAULT_WATCHLIST))
    return len(DEFAULT_WATCHLIST)
