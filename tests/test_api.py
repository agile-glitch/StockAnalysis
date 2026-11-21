import pytest
from fastapi.testclient import TestClient

from stockanalysis.db import Database
from stockanalysis.providers import CachedProvider
from stockanalysis.providers.demo import DemoProvider
from stockanalysis.server import create_app

from stockanalysis.sec import SecClient

from .conftest import TODAY
from .sec_fakes import FakeEdgar
from .test_push import Recorder

PUSHES = Recorder()


@pytest.fixture
def client():
    db = Database(":memory:")
    edgar = FakeEdgar()
    sec_client = SecClient(lambda: db.get_settings()["sec_contact"], opener=edgar, per_second=1000)
    app = create_app(db=db, provider=CachedProvider(DemoProvider(today=TODAY)), background=False,
                     sec_client=sec_client, push_opener=PUSHES)
    app.state.engine._today_fn = lambda: TODAY
    app.state.engine.scan()
    with TestClient(app) as c:
        yield c
    db.close()


def test_overview_and_static_page(client):
    data = client.get("/api/overview").json()
    assert data["demo"] is True and len(data["watchlist"]) == 6
    assert data["budget"] == {"total": 10000.0, "invested": 0, "available": 10000.0}
    page = client.get("/")
    assert page.status_code == 200 and "StockAnalysis" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_stock_detail_and_backtest(client):
    stock = client.get("/api/stock/nvda").json()
    assert stock["symbol"] == "NVDA" and stock["plan"]["budget"] == 10000.0
    assert "ideas" in stock["options"] and len(stock["signals"]) == 8
    backtest = client.get("/api/stock/NVDA/backtest").json()
    assert backtest["available"] and backtest["trades"] >= 1
    assert client.get("/api/stock/NOPE99").status_code == 404
    assert client.get("/api/stock/bad symbol!").status_code == 400


def test_watchlist_add_and_remove(client):
    added = client.post("/api/watchlist", json={"symbol": "amd"})
    assert added.status_code == 200 and added.json()["symbol"] == "AMD" and added.json()["price"] > 0
    assert "AMD" in [w["symbol"] for w in client.get("/api/overview").json()["watchlist"]]
    assert client.post("/api/watchlist", json={"symbol": "TOOLONG1"}).status_code == 404
    assert client.post("/api/watchlist", json={"symbol": "$$$"}).status_code == 400
    assert client.delete("/api/watchlist/AMD").status_code == 200
    assert "AMD" not in [w["symbol"] for w in client.get("/api/overview").json()["watchlist"]]


def test_changing_the_budget_resizes_every_plan(client):
    before = client.get("/api/stock/GOOGL").json()["plan"]["shares"]
    res = client.put("/api/settings", json={"budget": 80000, "risk_per_trade_pct": 2})
    assert res.status_code == 200 and res.json()["budget"] == 80000
    plan = client.get("/api/stock/GOOGL").json()["plan"]
    assert plan["shares"] > before and plan["budget"] == 80000
    assert client.get("/api/overview").json()["budget"]["total"] == 80000


@pytest.mark.parametrize("body", [
    {"budget": 0}, {"budget": -5}, {"budget": "lots"}, {"risk_per_trade_pct": 50},
    {"option_risk_pct": 99}, {"refresh_minutes": 0}, {"made_up": 1},
    {"sec_contact": "no-email-here"}, {"sec_contact": "only@email.com"}, {"push_url": "ftp://x"},
    {"push_scope": "everything"}, {"insider_poll_minutes": 0}, {"insider_market_min_value": True},
])
def test_bad_settings_are_rejected(client, body):
    res = client.put("/api/settings", json=body)
    assert res.status_code == 400 and res.json()["detail"]
    assert client.get("/api/settings").json()["budget"] == 10000.0


def test_options_toggle(client):
    client.put("/api/settings", json={"options_enabled": False})
    assert client.get("/api/stock/NVDA").json()["options"]["ideas"] == []
    client.put("/api/settings", json={"options_enabled": True})
    assert client.get("/api/stock/NVDA").json()["options"]["enabled"] is True


def test_positions_reduce_available_cash(client):
    res = client.post("/api/positions", json={"symbol": "AAPL", "shares": 4, "entry_price": 500, "stop": 450})
    assert res.status_code == 200 and res.json()["stop"] == 450
    assert client.get("/api/overview").json()["budget"]["available"] == 8000.0
    rows = client.get("/api/positions").json()
    assert rows[0]["symbol"] == "AAPL" and rows[0]["pnl"] is not None
    assert client.get("/api/stock/AAPL").json()["position"]["shares"] == 4
    assert client.post("/api/positions", json={"symbol": "AAPL", "shares": 0, "entry_price": 500}).status_code == 422
    client.delete("/api/positions/AAPL")
    assert client.get("/api/positions").json() == []
    assert client.get("/api/overview").json()["budget"]["available"] == 10000.0


def test_notifications_flow(client):
    data = client.get("/api/notifications").json()
    assert data["unread"] == len(data["items"]) > 0
    newest = data["items"][0]["id"]
    assert client.get(f"/api/notifications?after_id={newest}").json()["items"] == []
    assert client.post("/api/notifications/read", json={"ids": [newest]}).json()["unread"] == data["unread"] - 1
    assert client.post("/api/notifications/read", json={}).json()["unread"] == 0
    assert client.delete("/api/notifications").json() == {"unread": 0}
    assert client.get("/api/notifications").json()["items"] == []


def test_feeds_and_search(client):
    assert client.get("/api/news").json()
    assert client.get("/api/earnings").json()
    assert client.get("/api/insiders").json()
    assert client.get("/api/search?q=apple").json()[0]["symbol"] == "AAPL"
    assert client.get("/api/search?q=").json() == []
    assert client.post("/api/scan").status_code == 200


def test_insider_settings_status_and_feeds(client):
    status = client.get("/api/insiders/status").json()
    assert status["configured"] is False and status["market_alerts"] is True
    assert client.post("/api/insiders/poll").status_code == 400
    res = client.put("/api/settings", json={"sec_contact": "Jane Doe jane@example.com",
                                             "insider_market_min_value": 250000, "insider_alert_sells": True})
    assert res.status_code == 200 and res.json()["sec_contact"] == "Jane Doe jane@example.com"
    status = client.get("/api/insiders/status").json()
    assert status["configured"] is True and status["last_poll"] and status["last_error"] is None
    assert client.get("/api/overview").json()["insiders"]["configured"] is True
    assert client.get("/api/insiders?scope=market").json() == []
    assert isinstance(client.get("/api/insiders").json(), list)


def test_push_test_endpoint(client):
    assert client.post("/api/push/test", json={}).status_code == 400          # nothing configured
    before = len(PUSHES.sent)
    assert client.post("/api/push/test", json={"url": "https://ntfy.sh/my-topic"}).json() == {"ok": True}
    assert len(PUSHES.sent) == before + 1
    bad = client.post("/api/push/test", json={"url": "https://ntfy.sh/"})
    assert bad.status_code == 400 and "ntfy" in bad.json()["detail"]
