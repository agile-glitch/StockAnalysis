from datetime import date

import pandas as pd
import pytest

from stockanalysis.db import SettingsError
from stockanalysis.push import Pusher
from stockanalysis.trend_watch import TrendWatch, next_check, portfolio_history, signal, trend_friendly
from stockanalysis.validation.markets import FABER

from .conftest import TODAY, make_history
from .test_api import client  # noqa: F401  (shared fixture)


class FakeProvider:
    def __init__(self):
        self.frames = {}

    def history(self, symbol, period="2y"):
        return self.frames.get(symbol, make_history(n=600, seed=len(symbol)))


def crashed(month_start="2026-10-01"):
    """An uptrend that fell 40% from the start of the last completed month."""
    df = make_history(n=600, seed=3).copy()
    df.loc[df.index >= month_start, ["open", "high", "low", "close"]] *= 0.6
    return df


def notes(db, kind):
    return [n for n in db.notifications(limit=100) if n["kind"] == kind]


def test_signal_uses_last_completed_month_end():
    sig, held = signal(crashed())
    assert sig["decided_on"] == "2026-10-30"          # October's last trading day, not today
    assert not sig["holding"] and sig["since"] == "2026-10-30"
    assert sig["decided_close"] < sig["decided_average"]
    # A crash that started this month (November) does not count until November ends.
    sig2, _ = signal(crashed("2026-11-03"))
    assert sig2["holding"] and sig2["flip_pending"] and sig2["gap_pct"] < 0
    assert signal(make_history(n=100)) is None         # needs 10 months of history


def test_market_and_portfolio_alerts_fire_once_per_change(db):
    fake = FakeProvider()
    db.update_settings({"trend_alert_symbols": ["USO"]})
    watch = TrendWatch(db, fake, today_fn=lambda: TODAY)
    snap = watch.update(notify=True)
    assert snap["alerts"]["signals"]["USO"]["holding"]
    assert snap["portfolio"]["complete"] and len(snap["portfolio"]["holding"]) == len(FABER)
    assert not notes(db, "market_trend") and not notes(db, "trend_portfolio")   # first run only records

    fake.frames["USO"] = crashed()
    watch.update(notify=True)
    watch.update(notify=True)                          # no repeat
    alerts = notes(db, "market_trend")
    assert len(alerts) == 1 and alerts[0]["symbol"] == "USO" and alerts[0]["tone"] == "bearish"
    assert "below its 10-month average" in alerts[0]["body"] and "October" in alerts[0]["body"]
    assert not notes(db, "trend_portfolio")            # USO is not in the portfolio

    fake.frames["GLD"] = crashed()
    snap = watch.update(notify=True)
    port = notes(db, "trend_portfolio")
    assert len(port) == 1 and port[0]["title"] == "Trend portfolio: sell GLD"
    assert "$8,750 invested" in port[0]["body"]       # 7 of 8 slots of the $10,000 budget
    assert snap["portfolio"]["cash"] == 1250 and snap["portfolio"]["changes"][0]["sold"] == ["GLD"]

    db.update_settings({"trend_portfolio_alerts": False})
    del fake.frames["GLD"]
    watch.update(notify=True)
    assert len(notes(db, "trend_portfolio")) == 1      # switched off, but state still tracked
    assert sorted(db.get_state("trend_portfolio")) == sorted(FABER)


def test_trend_settings_validation(db):
    assert db.get_settings()["trend_alert_symbols"] is None
    assert db.update_settings({"trend_alert_symbols": ["gld", "GLD", "btc-usd", "GC=F"]})["trend_alert_symbols"] == \
        ["GLD", "BTC-USD", "GC=F"]
    with pytest.raises(SettingsError):
        db.update_settings({"trend_alert_symbols": ["not a ticker"]})
    with pytest.raises(SettingsError):
        db.update_settings({"trend_alert_symbols": "GLD"})
    assert db.update_settings({"trend_alert_symbols": None})["trend_alert_symbols"] is None
    assert db.update_settings({"trend_alert_symbols": []})["trend_alert_symbols"] == []


def test_defaults_skip_futures_and_next_check():
    picks = trend_friendly()
    assert picks and not any(s.endswith("=F") for s in picks)
    assert next_check(date(2026, 11, 19)) == "2026-11-30"
    assert next_check(date(2026, 1, 30)) == "2026-01-30"    # already the last weekday
    assert next_check(date(2026, 2, 27)) == "2026-02-27"


def test_portfolio_history_lists_month_end_changes():
    idx = pd.bdate_range("2026-01-01", "2026-06-10")
    a = pd.Series(idx >= "2026-03-31", index=idx)
    b = pd.Series(idx < "2026-04-30", index=idx)
    changes = portfolio_history({"A": a, "B": b})
    assert changes[0] == {"date": "2026-04-30", "bought": [], "sold": ["B"], "holding": 1}
    assert changes[1] == {"date": "2026-03-31", "bought": ["A"], "sold": [], "holding": 2}


def test_trend_kinds_go_to_phone_with_default_scope():
    pusher = Pusher(lambda: {"push_url": "https://ntfy.sh/t", "push_scope": "insider"}, opener=lambda *a, **k: None)
    assert pusher.wants({"kind": "trend_portfolio"}) and pusher.wants({"kind": "market_trend"})
    assert not pusher.wants({"kind": "signal"})


def test_trend_api(client):
    data = client.get("/api/trend").json()
    assert data["alerts"]["using_default"] and data["alerts"]["symbols"] == data["alerts"]["default_symbols"]
    assert [a["symbol"] for a in data["portfolio"]["assets"]] == FABER
    assert data["portfolio"]["invested"] + data["portfolio"]["cash"] == pytest.approx(data["portfolio"]["budget"])
    res = client.put("/api/settings", json={"trend_alert_symbols": ["GLD", "slv"]})
    assert res.status_code == 200
    data = client.get("/api/trend").json()
    assert data["alerts"]["symbols"] == ["GLD", "SLV"] and not data["alerts"]["using_default"]
    assert data["alerts"]["signals"]["GLD"]["decided_on"]
    assert client.put("/api/settings", json={"trend_alert_symbols": ["bad ticker"]}).status_code == 400
