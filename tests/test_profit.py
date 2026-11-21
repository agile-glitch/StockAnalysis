import numpy as np
import pandas as pd
import pytest

from stockanalysis.db import SettingsError
from stockanalysis.profit_plan import PLANS, ProfitPlan, state
from stockanalysis.validation.profit import EXPENSE, SPREAD, leveraged, pick, signal, timed

from .conftest import make_history
from .test_api import client  # noqa: F401  (shared fixture)


def test_leveraged_return_formula():
    idx = pd.bdate_range("2020-01-01", periods=3)
    r = pd.Series([0.01, -0.02, 0.0], index=idx)
    cash = pd.Series(0.0001, index=idx)
    out = leveraged(r, 3, cash)
    expected = 3 * r - 2 * (0.0001 + SPREAD / 252) - EXPENSE / 252
    assert np.allclose(out, expected)
    assert leveraged(r, 1, cash).equals(r)


def test_timed_trades_a_day_after_the_signal_and_charges_switches():
    idx = pd.bdate_range("2020-01-01", periods=6)
    r = pd.Series(0.01, index=idx)
    cash = pd.Series(0.0, index=idx)
    held = pd.Series([True, True, True, False, False, False], index=idx)
    out = timed(r, held, cash)
    # Decided at close 0, bought at close 1, so the first return earned is day 2's.
    assert out.iloc[0] == 0 and out.iloc[1] == 0
    assert out.iloc[2] == pytest.approx(0.01 - 0.001)          # entry cost
    assert out.iloc[4] == pytest.approx(0.01)                  # sold at close 4 (signal at close 3)
    assert out.iloc[5] == pytest.approx(-0.001)                # exit cost, in cash


def test_signals():
    df = make_history(n=600)
    tb = pd.Series(1.0, index=df.index)
    for kind in ("200d", "switch", "10m"):
        s = signal(df["close"], kind, tb)
        assert s.dtype == bool and not s.iloc[:150].any() and s.iloc[-1]   # rising market: in


def test_pick_respects_the_drawdown_limit():
    rows = {"hold_1x": {"cagr_pct": 7, "max_drawdown_pct": -50},
            "a": {"cagr_pct": 20, "max_drawdown_pct": -80},
            "b": {"cagr_pct": 10, "max_drawdown_pct": -45}}
    assert pick({"rows": rows}) == "b"


def test_plan_state_and_alerts(db):
    up = make_history(n=600)
    down = up.copy()
    down.iloc[-60:, :4] *= np.linspace(1, 0.6, 60)[:, None]     # a 40% slide below the 200-day average
    st = state(up, None, "growth")
    assert st["invested"] and st["fund"] == "SSO" and st["leverage"] == 2
    assert not state(down, None, "growth")["invested"]

    class Provider:
        frame = up

        def history(self, symbol, period="2y"):
            if symbol == "^IRX":
                raise KeyError(symbol)
            return self.frame

    prov = Provider()
    plan = ProfitPlan(db, prov)
    plan.update(notify=True)                                     # first run only records
    assert not [n for n in db.notifications() if n["kind"] == "profit_plan"]
    prov.frame = down
    plan.update(notify=True)
    plan.update(notify=True)
    notes = [n for n in db.notifications() if n["kind"] == "profit_plan"]
    assert len(notes) == 1 and "sell SSO" in notes[0]["title"] and notes[0]["tone"] == "bearish"
    # Switching plans records the new plan's state without an alert.
    db.update_settings({"profit_plan": "aggressive"})
    plan.update(notify=True)
    assert len([n for n in db.notifications() if n["kind"] == "profit_plan"]) == 1


def test_profit_settings(db):
    assert db.get_settings()["profit_plan"] == "growth"
    with pytest.raises(SettingsError):
        db.update_settings({"profit_plan": "yolo"})
    assert set(PLANS) == {"steady", "growth", "aggressive"}


def test_profit_api(client):
    data = client.get("/api/profit").json()
    assert data["plan"] == "growth" and data["state"]["fund"] == "SSO"
    assert set(data["options"]) == {"steady", "growth", "aggressive"}
    assert client.put("/api/settings", json={"profit_plan": "off"}).status_code == 200
    assert client.get("/api/profit").json()["state"] is None
    res = client.get("/api/validation/profit")
    if res.status_code == 200:
        rep = res.json()
        assert rep["chosen"] == "200d_2x" and all(c["daily_correlation"] > 0.99 for c in rep["calibration"])
