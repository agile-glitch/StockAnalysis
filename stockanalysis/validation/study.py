"""Signal test: when the app said Buy or Sell, what happened next?

For every day a stock *turns* Buy (or Sell), the trade is entered at the next
day's open (the signal is only known after the close) and measured at the
close 5, 20, 60 and 120 trading days later, against the S&P 500 (SPY) over
the exact same window.

A Buy signal "wins" if the stock beat the market afterwards; a Sell signal
wins if the stock lagged it. Beating the market is the right bar: almost any
stock rises in a long bull market, so "it went up" proves little.

Overlapping events (many stocks turning Buy in the same rally) are not
independent, so the t-statistic averages events within each month first and
then tests the monthly averages.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

HORIZONS = (5, 20, 60, 120)


def forward_returns(f: pd.DataFrame, spy: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """Return from the next open to the close h days later, for the stock and SPY."""
    spy = spy.reindex(f.index)
    out = pd.DataFrame(index=f.index)
    entry, spy_entry = f["open"].shift(-1), spy["open"].shift(-1)
    for h in horizons:
        out[f"ret_{h}"] = f["close"].shift(-h) / entry - 1.0
        out[f"mkt_{h}"] = spy["close"].shift(-h) / spy_entry - 1.0
        out[f"exc_{h}"] = out[f"ret_{h}"] - out[f"mkt_{h}"]
    return out


def signal_events(symbol: str, f: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    """Rows for each day the action turns Buy (from Hold/Sell) or turns Sell."""
    action = f["action"]
    prev = action.shift(1)
    turned_buy = (action >= 1) & (prev < 1)
    turned_sell = (action <= -1) & (prev > -1)
    fwd = forward_returns(f, spy)
    rows = []
    for kind, mask in (("buy", turned_buy), ("sell", turned_sell)):
        sub = fwd[mask].copy()
        sub["kind"] = kind
        sub["score"] = f.loc[mask, "score"]
        sub["symbol"] = symbol
        rows.append(sub)
    events = pd.concat(rows)
    events.index.name = "date"
    return events.reset_index()


def state_returns(symbol: str, f: pd.DataFrame, spy: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """Every day's state (buy/hold/sell) with its forward excess return. Shows
    whether the score ranks stocks at all, not just at the moment it flips."""
    fwd = forward_returns(f, spy, (horizon,))
    state = np.where(f["action"] >= 1, "buy", np.where(f["action"] <= -1, "sell", "hold"))
    return pd.DataFrame({"date": f.index, "symbol": symbol, "state": state,
                         "exc": fwd[f"exc_{horizon}"].to_numpy(), "ret": fwd[f"ret_{horizon}"].to_numpy()})


def _monthly_t(df: pd.DataFrame, col: str) -> tuple[float, int]:
    """t-statistic of the mean, treating each calendar month as one observation."""
    monthly = df.groupby(df["date"].dt.to_period("M"))[col].mean().dropna()
    n = len(monthly)
    if n < 3 or monthly.std(ddof=1) == 0:
        return float("nan"), n
    return float(monthly.mean() / (monthly.std(ddof=1) / math.sqrt(n))), n


def summarize_events(events: pd.DataFrame) -> list[dict]:
    out = []
    for kind in ("buy", "sell"):
        k = events[events["kind"] == kind]
        for h in HORIZONS:
            valid = k.dropna(subset=[f"exc_{h}"])
            if valid.empty:
                continue
            exc, ret = valid[f"exc_{h}"], valid[f"ret_{h}"]
            beat = (exc > 0) if kind == "buy" else (exc < 0)
            t, months = _monthly_t(valid, f"exc_{h}")
            out.append({
                "kind": kind,
                "horizon": h,
                "signals": int(len(valid)),
                "months": months,
                "win_rate": round(float(beat.mean()) * 100, 1),          # beat (buy) / lagged (sell) the market
                "rose_rate": round(float((ret > 0).mean()) * 100, 1),     # stock simply went up
                "avg_excess": round(float(exc.mean()) * 100, 2),
                "median_excess": round(float(exc.median()) * 100, 2),
                "avg_return": round(float(ret.mean()) * 100, 2),
                "t_stat": round(t, 2) if not math.isnan(t) else None,
            })
    return out


def summarize_states(states: pd.DataFrame) -> list[dict]:
    out = []
    for state in ("buy", "hold", "sell"):
        s = states[states["state"] == state].dropna(subset=["exc"])
        if s.empty:
            continue
        t, months = _monthly_t(s, "exc")
        out.append({
            "state": state,
            "stock_days": int(len(s)),
            "avg_excess_20d": round(float(s["exc"].mean()) * 100, 2),
            "beat_market": round(float((s["exc"] > 0).mean()) * 100, 1),
            "t_stat": round(t, 2) if not math.isnan(t) else None,
        })
    return out
