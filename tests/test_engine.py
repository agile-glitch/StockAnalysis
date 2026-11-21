from datetime import timedelta

from stockanalysis.engine import Engine
from stockanalysis.providers import CachedProvider, ProviderError
from stockanalysis.providers.demo import DemoProvider

from .conftest import TODAY


def test_scan_analyses_every_watched_symbol(engine, db):
    status = engine.scan()
    assert status["last_scan"] and not status["scanning"] and status["last_error"] is None
    overview = engine.overview()
    assert [w["symbol"] for w in overview["watchlist"]] == db.watchlist()
    for row in overview["watchlist"]:
        assert row["price"] > 0 and -100 <= row["score"] <= 100
        assert row["action"] in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    nvda = engine.analyses["NVDA"]
    assert {s["key"] for s in nvda["signals"]} == {
        "trend", "momentum", "high52", "pullback", "macd", "earnings", "insiders", "news"}
    assert abs(sum(s["points"] for s in nvda["signals"]) - nvda["score"]) < 0.5
    assert len(nvda["chart"]["dates"]) == len(nvda["chart"]["close"]) == 260


def test_first_scan_notifies_actionable_signals_and_rescans_do_not_repeat(engine, db):
    engine.scan()
    first = db.notifications()
    titles = [n["title"] for n in first]
    assert any(t.startswith("NVDA: Strong buy") or t.startswith("NVDA: Buy") for t in titles)
    assert any("Sell" in t for t in titles)
    assert db.unread_count() == len(first) > 0
    engine.scan(force=True)
    assert len(db.notifications()) == len(first)


def test_signal_change_raises_an_alert(engine, db):
    engine.scan()
    db.clear_notifications()
    # Pretend the stock was a Hold on the previous scan.
    engine.analyses["NVDA"] = {**engine.analyses["NVDA"], "action": "hold", "direction": "neutral",
                               "bar_date": "2026-11-18"}
    engine.refresh_symbol("NVDA")
    alerts = [n for n in db.notifications() if n["kind"] == "signal"]
    assert len(alerts) == 1 and "(was Hold)" in alerts[0]["title"] and alerts[0]["tone"] == "bullish"
    assert "Why:" in alerts[0]["body"]


def test_budget_change_resizes_trades_without_new_alerts(engine, db):
    engine.scan()
    before = engine.analyses["GOOGL"]["plan"]["shares"]
    count = len(db.notifications())
    db.update_settings({"budget": 50_000})
    engine.scan(notify=False)
    after = engine.analyses["GOOGL"]["plan"]
    assert after["shares"] > before and after["budget"] == 50_000
    assert len(db.notifications()) == count


def test_stop_hit_on_a_held_position_alerts_once(engine, db):
    engine.scan()
    price = engine.analyses["AAPL"]["price"]
    db.set_position("AAPL", 10, price * 1.1, stop=price * 1.05)
    engine.scan()
    engine.scan()
    hits = [n for n in db.notifications() if n["kind"] == "stop_hit"]
    assert len(hits) == 1 and hits[0]["tone"] == "bearish" and "AAPL" in hits[0]["title"]
    assert engine.overview()["budget"]["invested"] == round(10 * price * 1.1, 2)


def test_insider_and_earnings_alerts(db):
    class Scripted(DemoProvider):
        def earnings(self, symbol):
            return [
                {"date": (TODAY + timedelta(days=3)).isoformat(), "eps_estimate": 1.0, "eps_actual": None, "surprise_pct": None},
                {"date": (TODAY - timedelta(days=88)).isoformat(), "eps_estimate": 1.0, "eps_actual": 1.2, "surprise_pct": 20.0},
            ]

        def insiders(self, symbol):
            return [{"date": (TODAY - timedelta(days=d)).isoformat(), "insider": name, "position": "Director",
                     "kind": "buy", "shares": 1000, "value": 250_000.0, "text": "Purchase"}
                    for d, name in ((2, "DOE JANE"), (6, "ROE RICHARD"), (30, "POE EDGAR"))]

    engine = Engine(db, CachedProvider(Scripted(today=TODAY)), today_fn=lambda: TODAY)
    engine.refresh_symbol("AAPL")
    kinds = [n["kind"] for n in db.notifications()]
    assert kinds.count("insider_buy") == 2          # only the two within the last 14 days
    assert kinds.count("insider_cluster") == 1
    assert kinds.count("earnings_soon") == 1
    soon = next(n for n in db.notifications() if n["kind"] == "earnings_soon")
    assert "in 3 days" in soon["title"] and soon["tone"] == "warning"
    assert engine.analyses["AAPL"]["earnings"]["days_until"] == 3


def test_unknown_symbol_is_reported_and_partial_outages_degrade(engine, db, provider):
    db.add_symbol("ZZZZZZ9")
    engine.scan()
    assert "error" in engine.summary("ZZZZZZ9")
    assert "ZZZZZZ9" in engine.status["last_error"]

    def broken(symbol, count=12):
        raise ProviderError("news is down")
    provider.inner.news = broken
    provider.invalidate()
    analysis = engine.refresh_symbol("AAPL", notify=False)
    assert analysis["news"] == [] and "news is down" in analysis["problems"]
    assert analysis["price"] > 0
    assert not next(s for s in analysis["signals"] if s["key"] == "news")["available"]


def test_feeds(engine):
    engine.scan()
    news = engine.news_feed()
    assert news and all("symbol" in n for n in news)
    assert news == sorted(news, key=lambda n: n["published"], reverse=True)
    calendar = engine.earnings_calendar()
    dates = [r["next_date"] for r in calendar if r["next_date"]]
    assert dates == sorted(dates)
    assert all(t["kind"] in ("buy", "sell", "other") for t in engine.insider_feed())


def test_trailing_stop_tracks_best_close_since_buying_and_alerts(engine, db):
    import time as _time
    engine.scan()
    a = engine.analyses["TSLA"]                      # a falling stock in the demo data
    closes = a["chart"]["close"]
    # Bought a year ago at the price back then.
    db.set_position("TSLA", 10, closes[0], stop=None)
    with db._lock:
        db._conn.execute("UPDATE positions SET opened_at = ? WHERE symbol = 'TSLA'", (_time.time() - 365 * 86400,))
        db._conn.commit()
    db.clear_notifications()
    cur = engine.refresh_symbol("TSLA")
    plan = cur["plan"]
    peak = max(c for c in closes if c is not None)
    assert plan["trailing_stop_pct"] == 20.0
    assert abs(plan["peak_close"] - peak) / peak < 0.02
    assert abs(plan["trailing_stop"] - peak * 0.8) < 0.05 * peak
    hits = [n for n in db.notifications() if n["kind"] == "trailing_stop_hit"]
    assert (cur["price"] <= plan["trailing_stop"]) == bool(hits)
    assert not [n for n in db.notifications() if n["kind"] == "chandelier_exit"]
    # Stocks you don't own get no trailing stop.
    assert "trailing_stop" not in engine.analyses["AAPL"]["plan"]
