import numpy as np
import pandas as pd
import pytest

from stockanalysis.db import SettingsError
from stockanalysis.trend_watch import signal
from stockanalysis.validation.entries import days_to_next_earnings, trade_list, trade_stats
from stockanalysis.validation.markets import faber_positions
from .test_api import client  # noqa: F401  (shared fixture)


def wobbly(n=900, seed=0):
    """A flat market that crosses its average back and forth."""
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(seed)
    close = 100 * (1 + 0.03 * np.sin(np.arange(n) / 9.0) + rng.normal(0, 0.002, n))
    return pd.DataFrame({"x": close}, index=idx)


def test_band_trades_less_and_never_contradicts_its_levels():
    close = wobbly()
    base = faber_positions(close)["x"]
    band = faber_positions(close, 0.02)["x"]
    flips = lambda h: int(h.ne(h.shift(1)).sum())  # noqa: E731
    assert flips(band) < flips(base)
    # With a 2% band, a month-end buy only happens more than 2% above the average.
    ma = close["x"].rolling(210).mean()
    bought = band & ~band.shift(1, fill_value=False)
    assert ((close["x"][bought] / ma[bought]) > 1.02).all()
    sold = ~band & band.shift(1, fill_value=False)
    assert ((close["x"][sold] / ma[sold]) < 0.98).all()
    assert faber_positions(close, 0.0)["x"].equals(base)            # band 0 = the original rule


def test_signal_reports_band_levels():
    df = wobbly().rename(columns={"x": "close"})
    sig, _ = signal(df, 0.02)
    assert sig["band_pct"] == 2.0
    assert sig["buy_level"] == pytest.approx(sig["average"] * 1.02, rel=1e-6)
    assert sig["sell_level"] == pytest.approx(sig["average"] * 0.98, rel=1e-6)
    expected = sig["price"] < sig["sell_level"] if sig["holding"] else sig["price"] > sig["buy_level"]
    assert sig["flip_pending"] == expected


def test_trade_list_and_stats():
    idx = pd.bdate_range("2021-01-01", periods=12)
    held = pd.Series([1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1], index=idx).astype(bool)
    r = pd.Series([0, .1, .1, 0, 0, -.05, -.05, .02, 0, 0, .3, .3], index=idx, dtype=float)
    t = trade_list(r, held)
    assert len(t) == 2                                            # the last trade is still open: left out
    st = trade_stats(t)
    assert st["trades"] == 2 and st["losing_pct"] == 50.0 and st["avg_win_pct"] == 21.0


def test_days_to_next_earnings():
    idx = pd.bdate_range("2024-01-01", periods=30)
    e = pd.DataFrame({"date": [idx[10], idx[25]], "surprise_pct": [1.0, 2.0]})
    d = days_to_next_earnings(idx, e)
    assert d.iloc[0] == 10 and d.iloc[10] == 0 and d.iloc[11] == 14 and np.isinf(d.iloc[-1])


def test_band_setting(db):
    assert db.get_settings()["trend_band_pct"] == 2.0
    assert db.update_settings({"trend_band_pct": 0})["trend_band_pct"] == 0
    with pytest.raises(SettingsError):
        db.update_settings({"trend_band_pct": 9})


def test_band_changes_trend_api(client):
    assert client.get("/api/trend").json()["band_pct"] == 2.0
    assert client.put("/api/settings", json={"trend_band_pct": 0}).status_code == 200
    data = client.get("/api/trend").json()
    assert data["band_pct"] == 0
    sig = data["portfolio"]["assets"][0]["signal"]
    assert sig["buy_level"] == sig["sell_level"] == sig["average"]


def test_entries_endpoint(client):
    res = client.get("/api/validation/entries")
    if res.status_code == 404:
        return
    data = res.json()
    assert data["trend"]["pick"] == "band2" and data["trend"]["test_verdict"]["held_up"]
    assert not data["stocks"]["test_verdict"]["held_up"]
    assert "base" in data["stocks"]["variants"] and data["stocks"]["test_stocks"] > 100
