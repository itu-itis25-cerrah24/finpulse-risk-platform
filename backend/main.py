"""FinPulse API - Quantitative Portfolio Risk & Market Sentiment Terminal."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal, get_db, init_db
from models import RiskAlert, WatchlistItem
from schemas import AlertOut, PortfolioOut, StockHistoryOut, WatchlistCreate, WatchlistItemOut
from seed import seed_default_watchlist
from services.alert_service import refresh_alerts
from services.market_service import MarketService, market_service
from services.portfolio_service import build_portfolio, build_stock_detail

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
CORS_ORIGINS = [o.strip() for o in os.getenv("FINPULSE_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    with SessionLocal() as db:
        seed_default_watchlist(db)
    yield


app = FastAPI(
    title="FinPulse API",
    description="Quantitative portfolio risk metrics, live market data and news sentiment.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_market_service() -> MarketService:
    """Dependency hook so tests can inject a fake market data provider."""
    return market_service


def _load_watchlist(db: Session) -> list[WatchlistItem]:
    return list(db.scalars(select(WatchlistItem).order_by(WatchlistItem.id)))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/portfolio", response_model=PortfolioOut, tags=["portfolio"])
def get_portfolio(
    db: Session = Depends(get_db),
    market: MarketService = Depends(get_market_service),
) -> PortfolioOut:
    """All positions with live prices, quant metrics, sentiment and a portfolio summary."""
    portfolio = build_portfolio(_load_watchlist(db), market)
    refresh_alerts(db, portfolio.positions)
    return portfolio


@app.post(
    "/api/portfolio",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    tags=["portfolio"],
)
def add_position(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
    market: MarketService = Depends(get_market_service),
) -> WatchlistItem:
    """Add a stock to the watchlist after confirming the ticker has market data."""
    if db.scalar(select(WatchlistItem).where(WatchlistItem.symbol == payload.symbol)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{payload.symbol} is already in the portfolio")

    if not market.get_quote(payload.symbol).is_available:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No market data found for symbol {payload.symbol}")

    item = WatchlistItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/portfolio/{item_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["portfolio"])
def delete_position(item_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Watchlist item {item_id} not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/stock/{symbol}/history", response_model=StockHistoryOut, tags=["market"])
def get_stock_history(
    symbol: str,
    market: MarketService = Depends(get_market_service),
) -> StockHistoryOut:
    """90-day price history, scored news headlines and quant metrics for one symbol."""
    detail = build_stock_detail(symbol.strip().upper(), market)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No market data found for symbol {symbol}")
    return detail


@app.get("/api/alerts", response_model=list[AlertOut], tags=["alerts"])
def get_alerts(
    limit: int = Query(50, ge=1, le=500),
    refresh: bool = Query(True, description="Re-evaluate alert rules against live data first"),
    db: Session = Depends(get_db),
    market: MarketService = Depends(get_market_service),
) -> list[RiskAlert]:
    """Most recent risk alerts, newest first."""
    if refresh:
        portfolio = build_portfolio(_load_watchlist(db), market)
        refresh_alerts(db, portfolio.positions)
    stmt = select(RiskAlert).order_by(RiskAlert.created_at.desc(), RiskAlert.id.desc()).limit(limit)
    return list(db.scalars(stmt))
