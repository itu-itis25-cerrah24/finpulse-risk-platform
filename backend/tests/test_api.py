"""API tests using an in-memory database and a fake (offline) market data provider."""

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (register tables)
from database import Base, get_db
from main import app, get_market_service
from services.market_service import MarketService, NewsHeadline, PricePoint, Quote

FAKE_QUOTES = {
    "AAPL": Quote("AAPL", price=100.0, previous_close=110.0, change_pct=-9.0909, currency="USD"),
    "MSFT": Quote("MSFT", price=400.0, previous_close=398.0, change_pct=0.5025, currency="USD"),
}

FAKE_HISTORY = {
    "AAPL": [120, 125, 118, 110, 112, 105, 110, 100],
    "MSFT": [300, 330, 297, 270, 280, 260, 270, 250],  # moves almost in lock-step with AAPL
    "SPY": [500, 505, 500, 495, 498, 494, 497, 492],
}


class FakeMarketService(MarketService):
    """Deterministic market data so API tests never touch the network."""

    def get_quote(self, symbol: str) -> Quote:
        return FAKE_QUOTES.get(symbol, Quote.unavailable(symbol))

    def get_history(self, symbol: str) -> list[PricePoint]:
        closes = FAKE_HISTORY.get(symbol)
        if closes is None:
            return []
        # Dates end today so window-based endpoints (benchmark) include every point.
        start = date.today() - timedelta(days=len(closes) - 1)
        return [
            PricePoint(date=(start + timedelta(days=i)).isoformat(), close=float(c)) for i, c in enumerate(closes)
        ]

    def get_news(self, symbol: str) -> list[NewsHeadline]:
        if symbol != "AAPL":
            return []
        return [
            NewsHeadline(title="Apple shares crash after terrible earnings miss"),
            NewsHeadline(title="Regulators launch fraud investigation into supplier"),
        ]

    def get_fx_rate_to_usd(self, currency: str | None) -> float | None:
        return 1.0 if currency == "USD" else None


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    fake_market = FakeMarketService()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_market_service] = lambda: fake_market
    # Not used as a context manager, so the lifespan (real DB init + seeding) is skipped.
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _add(client: TestClient, symbol: str = "AAPL") -> dict:
    response = client.post(
        "/api/portfolio", json={"symbol": symbol, "shares": 10, "avg_cost": 90, "risk_threshold_pct": 3}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_add_and_list_portfolio(client: TestClient) -> None:
    created = _add(client, "aapl")  # symbol is normalized to upper case
    assert created["symbol"] == "AAPL"

    body = client.get("/api/portfolio").json()
    assert body["summary"]["position_count"] == 1
    assert body["summary"]["total_value"] == 1000.0
    assert body["summary"]["total_pnl"] == 100.0

    position = body["positions"][0]
    assert position["daily_flag"] == "HIGH_DROP"
    assert position["sentiment"]["label"] == "BEARISH"
    assert 0 <= position["risk_score"] <= 100


def test_duplicate_symbol_is_rejected(client: TestClient) -> None:
    _add(client)
    response = client.post("/api/portfolio", json={"symbol": "AAPL", "shares": 1, "avg_cost": 1})
    assert response.status_code == 409


def test_unknown_symbol_is_rejected(client: TestClient) -> None:
    response = client.post("/api/portfolio", json={"symbol": "ZZZZ", "shares": 1, "avg_cost": 1})
    assert response.status_code == 404


def test_invalid_payload_is_rejected(client: TestClient) -> None:
    response = client.post("/api/portfolio", json={"symbol": "AAPL", "shares": -5, "avg_cost": 1})
    assert response.status_code == 422


def test_delete_position(client: TestClient) -> None:
    created = _add(client)
    assert client.delete(f"/api/portfolio/{created['id']}").status_code == 204
    assert client.delete(f"/api/portfolio/{created['id']}").status_code == 404


def test_stock_history(client: TestClient) -> None:
    body = client.get("/api/stock/AAPL/history").json()
    assert len(body["history"]) == 8
    assert len(body["headlines"]) == 2
    assert body["quant"]["max_drawdown_pct"] < 0
    assert client.get("/api/stock/ZZZZ/history").status_code == 404


def test_alerts_are_generated_once_per_day(client: TestClient) -> None:
    _add(client)
    first = client.get("/api/alerts").json()
    alert_types = {a["alert_type"] for a in first}
    assert {"HIGH_DROP", "BEARISH_SENTIMENT"} <= alert_types

    second = client.get("/api/alerts").json()
    assert len(second) == len(first)  # de-duplicated


def test_correlation_matrix_endpoint(client: TestClient) -> None:
    _add(client, "AAPL")
    _add(client, "MSFT")
    body = client.get("/api/portfolio/correlation").json()

    assert body["symbols"] == ["AAPL", "MSFT"]
    assert body["observations"] == 7
    assert body["matrix"][0][0] == 1.0
    assert body["matrix"][0][1] == body["matrix"][1][0]
    assert body["matrix"][0][1] > 0.9
    assert body["high_correlation_pairs"][0]["symbol_a"] == "AAPL"


def test_correlation_matrix_for_empty_portfolio(client: TestClient) -> None:
    body = client.get("/api/portfolio/correlation").json()
    assert body["symbols"] == []
    assert body["matrix"] == []
    assert body["average_correlation"] is None


def test_benchmark_comparison_endpoint(client: TestClient) -> None:
    body = client.get("/api/stock/AAPL/benchmark?days=30").json()

    assert body["benchmark_symbol"] == "SPY"
    assert body["points"][0] == {"date": body["points"][0]["date"], "asset_pct": 0.0, "benchmark_pct": 0.0}
    assert body["asset_return_pct"] == pytest.approx(-16.67, abs=0.01)  # 120 -> 100
    assert body["benchmark_return_pct"] == pytest.approx(-1.6, abs=0.01)  # 500 -> 492
    assert body["excess_return_pct"] == pytest.approx(-15.07, abs=0.01)


def test_benchmark_comparison_errors(client: TestClient) -> None:
    assert client.get("/api/stock/ZZZZ/benchmark").status_code == 404
    # BIST symbols compare against XU100.IS, which the fake provider does not serve.
    FAKE_HISTORY["TEST.IS"] = [10, 11, 12]
    try:
        assert client.get("/api/stock/TEST.IS/benchmark").status_code == 503
    finally:
        del FAKE_HISTORY["TEST.IS"]
    assert client.get("/api/stock/AAPL/benchmark?days=1").status_code == 422
