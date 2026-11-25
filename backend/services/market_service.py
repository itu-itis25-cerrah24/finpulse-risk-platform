"""Market data access layer.

Wraps ``yfinance`` behind a small, typed API and memoizes every upstream call
in a thread-safe, in-memory TTL cache (5 minutes by default) so that repeated
dashboard refreshes are served instantly and Yahoo Finance is not hammered.

Failures never propagate to callers: every public method returns a well-defined
fallback (empty list / quote without price / ``None``) and failed lookups are
*not* cached, so the next request retries upstream.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

import yfinance as yf
from cachetools import TTLCache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
CACHE_MAX_SIZE = 512
HISTORY_LOOKBACK_DAYS = 90
MAX_HEADLINES = 10

T = TypeVar("T")
_MISSING = object()


class MarketDataError(Exception):
    """Raised internally when upstream returns no usable data."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PricePoint:
    date: str
    close: float


@dataclass(frozen=True)
class NewsHeadline:
    title: str
    publisher: str | None = None
    link: str | None = None
    published_at: str | None = None


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float | None
    previous_close: float | None
    change_pct: float | None
    currency: str | None

    @classmethod
    def unavailable(cls, symbol: str) -> Quote:
        return cls(symbol=symbol, price=None, previous_close=None, change_pct=None, currency=None)

    @property
    def is_available(self) -> bool:
        return self.price is not None


@dataclass(frozen=True)
class MarketSnapshot:
    quote: Quote
    history: list[PricePoint] = field(default_factory=list)
    news: list[NewsHeadline] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    """Convert to a finite float, or return ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_attr(obj: Any, name: str) -> Any:
    """Read an attribute that may trigger a network call or be missing."""
    try:
        return getattr(obj, name)
    except Exception:  # yfinance raises a wide variety of errors here
        return None


def _parse_news_item(item: Any) -> NewsHeadline | None:
    """Parse one yfinance news item, supporting both the legacy flat schema
    and the newer ``{"content": {...}}`` schema."""
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else item

    title = content.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    provider = content.get("provider")
    publisher = provider.get("displayName") if isinstance(provider, dict) else content.get("publisher")

    link: str | None = None
    for key in ("canonicalUrl", "clickThroughUrl"):
        url_obj = content.get(key)
        if isinstance(url_obj, dict) and isinstance(url_obj.get("url"), str):
            link = url_obj["url"]
            break
    if link is None and isinstance(content.get("link"), str):
        link = content["link"]

    published_at = content.get("pubDate") or content.get("displayTime")
    timestamp = content.get("providerPublishTime")
    if not published_at and isinstance(timestamp, (int, float)):
        published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    return NewsHeadline(
        title=title.strip(),
        publisher=publisher if isinstance(publisher, str) else None,
        link=link,
        published_at=str(published_at) if published_at else None,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MarketService:
    """Cached facade over yfinance for quotes, price history, news and FX."""

    def __init__(
        self,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        maxsize: int = CACHE_MAX_SIZE,
        ticker_factory: Callable[[str], Any] = yf.Ticker,
    ) -> None:
        self._cache: TTLCache[tuple[str, str], Any] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()  # TTLCache itself is not thread-safe
        self._ticker_factory = ticker_factory

    # -- public API ---------------------------------------------------------

    def get_quote(self, symbol: str) -> Quote:
        """Live price, previous close, daily % change and currency."""
        return self._get_or_load("quote", symbol, self._load_quote, Quote.unavailable(symbol))

    def get_history(self, symbol: str) -> list[PricePoint]:
        """Daily (adjusted) closing prices over the last 90 calendar days."""
        return self._get_or_load("history", symbol, self._load_history, [])

    def get_news(self, symbol: str) -> list[NewsHeadline]:
        """Most recent news headlines for the symbol."""
        return self._get_or_load("news", symbol, self._load_news, [])

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """Quote + history + news in a single call."""
        return MarketSnapshot(
            quote=self.get_quote(symbol),
            history=self.get_history(symbol),
            news=self.get_news(symbol),
        )

    def get_fx_rate_to_usd(self, currency: str | None) -> float | None:
        """How many USD one unit of ``currency`` is worth (e.g. TRY -> ~0.03)."""
        if not currency:
            return None
        code = currency.upper()
        if code == "USD":
            return 1.0
        return self._get_or_load("fx", code, self._load_fx_rate, None)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- caching ------------------------------------------------------------

    def _get_or_load(self, kind: str, symbol: str, loader: Callable[[str], T], fallback: T) -> T:
        key = (kind, symbol.upper())
        with self._lock:
            cached = self._cache.get(key, _MISSING)
        if cached is not _MISSING:
            return cached  # type: ignore[return-value]

        # The upstream call happens outside the lock so slow requests for one
        # symbol never block cache hits for other symbols.
        try:
            value = loader(symbol.upper())
        except Exception as exc:
            logger.warning("Market data lookup failed (%s, %s): %s", kind, symbol, exc)
            return fallback

        with self._lock:
            self._cache[key] = value
        return value

    # -- upstream loaders (may raise; never called directly by consumers) ----

    def _load_quote(self, symbol: str) -> Quote:
        ticker = self._ticker_factory(symbol)
        fast_info = _safe_attr(ticker, "fast_info")
        price = _safe_float(_safe_attr(fast_info, "last_price"))
        previous_close = _safe_float(_safe_attr(fast_info, "previous_close"))
        currency = _safe_attr(fast_info, "currency")

        if price is None or previous_close is None:
            closes = self._recent_closes(ticker)
            if price is None and closes:
                price = closes[-1]
            if previous_close is None and len(closes) >= 2:
                previous_close = closes[-2]

        if price is None:
            raise MarketDataError(f"No price available for {symbol}")

        change_pct = (
            (price - previous_close) / previous_close * 100 if previous_close else None
        )
        return Quote(
            symbol=symbol,
            price=round(price, 4),
            previous_close=round(previous_close, 4) if previous_close is not None else None,
            change_pct=round(change_pct, 4) if change_pct is not None else None,
            currency=currency if isinstance(currency, str) else None,
        )

    @staticmethod
    def _recent_closes(ticker: Any) -> list[float]:
        """Fallback when ``fast_info`` is incomplete: last few daily closes."""
        try:
            frame = ticker.history(period="5d", interval="1d", auto_adjust=False)
        except Exception:
            return []
        if frame is None or frame.empty or "Close" not in frame:
            return []
        return [c for c in (_safe_float(v) for v in frame["Close"]) if c is not None]

    def _load_history(self, symbol: str) -> list[PricePoint]:
        start = (datetime.now(timezone.utc) - timedelta(days=HISTORY_LOOKBACK_DAYS)).date()
        frame = self._ticker_factory(symbol).history(
            start=start.isoformat(), interval="1d", auto_adjust=True
        )
        if frame is None or frame.empty or "Close" not in frame:
            raise MarketDataError(f"No price history for {symbol}")

        points = [
            PricePoint(date=index.strftime("%Y-%m-%d"), close=round(close, 4))
            for index, raw in frame["Close"].items()
            if (close := _safe_float(raw)) is not None
        ]
        if not points:
            raise MarketDataError(f"Price history for {symbol} contained no valid closes")
        return points

    def _load_news(self, symbol: str) -> list[NewsHeadline]:
        raw_items = self._ticker_factory(symbol).news or []
        headlines = [h for item in raw_items if (h := _parse_news_item(item)) is not None]
        return headlines[:MAX_HEADLINES]  # an empty list is a valid, cacheable answer

    def _load_fx_rate(self, currency: str) -> float:
        # Yahoo's "<CCY>=X" pair is quoted as units of <CCY> per 1 USD.
        quote = self._load_quote(f"{currency}=X")
        if not quote.price or quote.price <= 0:
            raise MarketDataError(f"Invalid FX quote for {currency}")
        return 1.0 / quote.price


# Shared application-wide instance (one cache for the whole process).
market_service = MarketService()
