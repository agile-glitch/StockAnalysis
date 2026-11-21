import numpy as np
import pandas as pd

from stockanalysis import markets_view
from .test_api import client  # noqa: F401  (shared fixture)
from stockanalysis.validation.markets import MARKETS, RULES, faber_positions


def test_ten_month_rule_acts_only_at_completed_month_ends():
    idx = pd.bdate_range("2020-01-01", "2021-06-15")
    close = pd.DataFrame({"x": np.linspace(100, 200, len(idx))}, index=idx)
    close.iloc[-5:] = 50.0                                  # crash in the unfinished month
    held = faber_positions(close)["x"]
    assert held.iloc[-1]                                     # still holding: June is not over
    assert not held.iloc[:150].any()                         # needs 10 months of history first
    may_end = idx[idx.to_period("M") == pd.Period("2021-05")][-1]
    assert held.loc[may_end]
    # Decisions change only at a month's last close (the backtest trades them at the next open).
    month = pd.Series(idx.to_period("M"), index=idx)
    last_day = month.ne(month.shift(-1))
    flips = held.ne(held.shift(1)) & held.index.isin(held.index[1:])
    assert flips.any() and last_day[flips].all()


def test_market_list_and_rules():
    symbols = [m[0] for m in MARKETS]
    assert {"GLD", "SLV", "USO", "TLT", "BTC-USD", "GC=F"} <= set(symbols)
    assert len(symbols) == len(set(symbols))
    assert set(RULES) == {"app", "ma200", "faber", "cross", "breakout", "rsi"}


def test_markets_endpoint_and_non_stock_symbols(client):
    markets_view._cache["data"] = None
    data = client.get("/api/markets").json()
    assert len(data["markets"]) == len(MARKETS)
    gold = next(m for m in data["markets"] if m["symbol"] == "GLD")
    assert gold["live"]["price"] > 0 and isinstance(gold["live"]["trend_hold"], bool)
    if data["tested_available"]:
        assert 0 <= gold["tested"]["trend_wins"] <= 4 and gold["tested"]["verdict"]
        assert data["faber"]["assets"] and data["persistence"]["stocks"] > 100
    for sym in ("GC=F", "BTC-USD", "^GSPC", "GLD"):
        res = client.post("/api/watchlist", json={"symbol": sym})
        assert res.status_code == 200, (sym, res.text)
        assert client.get("/api/stock/" + sym.replace("^", "%5E")).json()["symbol"] == sym
    assert client.post("/api/watchlist", json={"symbol": "NOT A TICKER"}).status_code == 400
    assert client.delete("/api/watchlist/%5EGSPC").status_code == 200
