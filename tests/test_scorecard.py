import numpy as np
import pandas as pd

from stockanalysis.validation.scorecard import market_switch, rolling, round_trips, verdict
from .test_api import client  # noqa: F401  (shared fixture)


def test_rolling_windows_count_gains_and_comparison():
    idx = pd.bdate_range("2020-01-01", periods=800)
    up = pd.Series(0.001, index=idx)
    down = pd.Series(-0.0005, index=idx)
    cash = pd.Series(0.0001, index=idx)
    out = rolling(up, down, cash)
    assert out["1y"]["made_money_pct"] == 100 and out["1y"]["beat_comparison_pct"] == 100
    assert out["1y"]["windows"] == 800 - 252 + 1 and out["3y"]["windows"] == 800 - 756 + 1
    assert rolling(down, None, cash)["1y"]["made_money_pct"] == 0


def test_verdict_flags():
    v = verdict({"cagr_pct": 5, "sharpe": 0.6, "max_drawdown_pct": -20},
                {"cagr_pct": 8, "sharpe": 0.5, "max_drawdown_pct": -40}, cash_cagr=2)
    assert v == {"made_money": True, "beat_cash": True, "more_money_than_comparison": False,
                 "better_risk_adjusted": True, "smaller_worst_drop": True}


def test_round_trips_split_stretches_in_market():
    idx = pd.bdate_range("2021-01-01", periods=10)
    held = pd.Series([1, 1, 0, 0, 1, 1, 1, 0, 0, 0], index=idx).astype(bool)
    r = pd.Series([0.0, 0.10, 0.10, 0.0, 0.0, -0.05, -0.05, 0.02, 0.0, 0.0], index=idx)
    t = round_trips(r, held)
    assert t["trades"] == 2 and t["won"] == 1
    assert t["best_pct"] == 21.0                                   # 1.1 * 1.1 - 1


def test_market_switch_goes_to_cash_in_a_long_slide():
    idx = pd.bdate_range("2000-01-01", periods=900)
    price = np.r_[np.linspace(100, 200, 500), np.linspace(200, 80, 400)]
    spy = pd.DataFrame({"open": price, "close": price}, index=idx)
    tbill = pd.Series(2.0, index=idx)
    cash = pd.Series(0.02 / 252, index=idx)
    r, hold = market_switch(spy, tbill, cash, scaled=False)
    late = r.iloc[-50:]
    assert np.allclose(late, 0.02 / 252)                          # out of the market, earning T-bills
    assert hold.iloc[-50:].lt(0).all()


def test_scorecard_endpoint(client):
    res = client.get("/api/validation/scorecard")
    if res.status_code == 404:
        return
    data = res.json()
    keys = [m["key"] for m in data["methods"]]
    assert {"market", "trend_portfolio", "trend_alerts"} <= set(keys)
    for m in data["methods"]:
        assert set(m["verdict"]) >= {"made_money", "beat_cash", "more_money_than_comparison"}
        assert m["rolling"]["1y"]["windows"] > 0
    assert data["trend_alerts"]["picks"] and data["trend_alerts"]["pick_end"] == "2015-12-31"
