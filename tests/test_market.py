import numpy as np
import pandas as pd

from stockanalysis.market import market_regime

from .conftest import make_history


def test_calm_uptrend_is_fully_invested():
    m = market_regime(make_history(n=400, daily=0.001, wiggle=0.004), pd.Series([2.0] * 300))
    assert m["state"] == "Risk-on" and m["risk_on"] and m["exposure_pct"] == 100
    assert m["above_200"] and m["momentum_ok"] and m["tbill_pct"] == 2.0


def test_downtrend_is_risk_off():
    m = market_regime(make_history(n=400, daily=-0.0015, wiggle=0.004), None)
    assert m["state"] == "Risk-off" and not m["risk_on"] and m["exposure_pct"] == 0
    assert m["tbill_pct"] == 4.0   # default when the rate is unavailable


def test_one_filter_is_enough_to_stay_in():
    # A sharp recent dip under the 200-day average, but the year is still well up.
    df = make_history(n=400, daily=0.0015, wiggle=0.002)
    df.iloc[-15:, :4] *= np.linspace(0.97, 0.80, 15)[:, None]
    m = market_regime(df, pd.Series([4.0] * 300))
    assert not m["above_200"] and m["momentum_ok"] and m["risk_on"]


def test_turbulence_scales_exposure_down():
    m = market_regime(make_history(n=400, daily=0.002, wiggle=0.03), pd.Series([1.0] * 300))
    assert m["risk_on"] and m["state"] == "Turbulent" and 0 < m["exposure_pct"] < 90


def test_too_little_history():
    assert market_regime(make_history(n=100), None) is None


def test_engine_alerts_when_the_market_flips(engine, db):
    engine.update_market()
    assert engine.market is not None
    db.set_state("market_risk_on", not engine.market["risk_on"])
    engine.update_market()
    notes = [n for n in db.notifications() if n["kind"] == "market_regime"]
    assert len(notes) == 1 and notes[0]["title"].startswith("Market turned")
    assert engine.overview()["market"]["state"] in ("Risk-on", "Turbulent", "Risk-off")
