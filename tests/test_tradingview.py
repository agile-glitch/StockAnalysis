import pytest
from fastapi.testclient import TestClient

from stockanalysis import tactics as T
from stockanalysis import tradingview as tv
from stockanalysis.db import Database
from stockanalysis.providers import CachedProvider
from stockanalysis.providers.demo import DemoProvider
from stockanalysis.server import create_app

from .conftest import TODAY


@pytest.fixture
def client():
    db = Database(":memory:")
    app = create_app(db=db, provider=CachedProvider(DemoProvider(today=TODAY)), background=False)
    with TestClient(app) as c:
        c.db = db
        yield c
    db.close()


def test_pine_script_for_every_tactic():
    for key in T.TACTICS:
        code = tv.pine_script(key, {})
        assert code.startswith("//@version=5")
        assert 'strategy("StockAnalysis: ' + T.describe(key, {}) in code
        assert "commission_value=0.1" in code and 'strategy.entry("Long", strategy.long)' in code
        assert 'strategy.close("Long")' in code
    code = tv.pine_script("ma_cross", {"fast": 20, "slow": 100, "ema": 1})
    assert "input.int(20," in code and "input.int(100," in code and "input.bool(true," in code
    assert "not leave" in tv.pine_script("donchian", {})       # exit wins on the same bar, as in the app
    assert "ta.stdev(close, n, false)" in tv.pine_script("bollinger_reversion", {})


def test_chart_studies_match_the_tactic():
    assert tv.studies("price_ma", {"n": 150}) == [{"id": tv.STUDY_SMA, "inputs": {"length": 150}}]
    assert [s["inputs"]["length"] for s in tv.studies("ma_cross", {"fast": 10, "slow": 50})] == [10, 50]
    assert tv.studies("bollinger_breakout", {"n": 30, "k": 1.5})[0]["inputs"] == {"length": 30, "stdDev": 1.5}
    assert tv.studies("macd", {})[0]["id"].startswith("MACD")
    assert all(s["id"] == tv.STUDY_EMA for s in tv.studies("macd", {"fast": 19, "slow": 39}))
    assert len(tv.studies(None)) == 3
    assert tv.tv_symbol("BRK-B") == "BRK.B" and tv.tv_symbol("^GSPC") == "SP:SPX"


def test_alert_parsing():
    a = tv.parse_alert('{"ticker": "NYSE:BRK.B", "action": "sell", "price": "450", "message": "Crossed below the 200-day"}')
    assert a["symbol"] == "BRK-B" and a["tone"] == "bearish" and "450" in a["body"]
    b = tv.parse_alert("MSFT long signal from my strategy")
    assert b["symbol"] == "MSFT" and b["tone"] == "bullish"
    c = tv.parse_alert("Price alert hit")
    assert c["symbol"] is None and c["tone"] == "info" and c["title"] == "Price alert hit"
    assert tv.parse_alert("")["body"]


def test_webhook_needs_the_token_and_creates_alerts(client):
    setup = client.get("/api/tradingview/setup").json()
    token = setup["webhook_path"].split("token=")[1]
    assert len(token) >= 20 and "{{ticker}}" in setup["message"]
    assert client.post("/api/webhooks/tradingview", content="hi").status_code == 403
    assert client.post("/api/webhooks/tradingview?token=wrong", content="hi").status_code == 403
    body = '{"ticker":"NASDAQ:NVDA","action":"buy","price":"123.4","title":"NVDA breakout","message":"Donchian 55"}'
    assert client.post(f"/api/webhooks/tradingview?token={token}", content=body).json() == {"ok": True}
    client.post(f"/api/webhooks/tradingview?token={token}", content=body)          # a retry is not a new alert
    alerts = [n for n in client.db.notifications() if n["kind"] == "tradingview"]
    assert len(alerts) == 1 and alerts[0]["symbol"] == "NVDA" and alerts[0]["tone"] == "bullish"
    assert alerts[0]["title"] == "NVDA breakout"
    assert client.post(f"/api/webhooks/tradingview?token={token}", content="x" * 20_000).status_code == 413
    client.post("/api/tradingview/token")
    assert client.post(f"/api/webhooks/tradingview?token={token}", content=body).status_code == 403


def test_tunnelled_requests_only_reach_the_webhook(client):
    token = client.get("/api/tradingview/setup").json()["webhook_path"].split("token=")[1]
    relayed = {"X-Forwarded-For": "52.89.214.238"}
    assert client.get("/api/overview", headers=relayed).status_code == 403
    assert client.get("/api/positions", headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 403
    assert client.get("/", headers=relayed).status_code == 403
    ok = client.post(f"/api/webhooks/tradingview?token={token}", content="AAPL buy", headers=relayed)
    assert ok.status_code == 200
    assert client.get("/api/overview").status_code == 200                           # local use unaffected


def test_pine_and_studies_endpoints(client):
    code = client.get("/api/lab/pine", params={"tactic": "momentum", "params": '{"lookback": 126}'}).json()["code"]
    assert "input.int(126," in code
    assert client.get("/api/lab/pine", params={"tactic": "nope"}).status_code == 400
    st = client.get("/api/tradingview/studies", params={"symbol": "brk-b", "tactic": "price_ma", "params": '{"n": 50}'}).json()
    assert st["symbol"] == "BRK.B" and st["studies"][0]["inputs"]["length"] == 50
