"""The app's scoring rules, vectorised over a whole price history.

`strategies.py` scores one day at a time for the live app. Replaying 20+
years across 130 stocks that way is slow, so this computes the same points
for every day at once. `tests/test_validation.py` checks both give the same
numbers.

Only signals with real history are replayed: the five price rules and the
earnings surprise. Insider trades and news tone have no free history, so
they score zero here, exactly as the live app does when that data is missing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import strategies as st
from ..indicators import build_frame

POINT_COLUMNS = ("trend", "momentum", "high52", "pullback", "macd", "earnings")
ACTION_CODES = {"strong_buy": 2, "buy": 1, "hold": 0, "sell": -1, "strong_sell": -2}


def technical_points(f: pd.DataFrame) -> pd.DataFrame:
    """Points per price rule, matching strategies.technical_signals()."""
    W = st.WEIGHTS
    close, sma200, sma50 = f["close"], f["sma200"], f["sma50"]
    out = pd.DataFrame(index=f.index)

    above = close > sma200
    trend = np.where(above, 0.6, -0.6)
    trend = trend + np.where(sma50.isna(), 0.0, np.where(sma50 > sma200, 0.2, -0.2))
    trend = trend + np.where(f["sma200_slope"].isna(), 0.0, np.where(f["sma200_slope"] > 0, 0.2, -0.2))
    trend = np.clip(trend, -1, 1)
    out["trend_score"] = np.where(sma200.isna(), np.nan, trend)
    out["trend_pts"] = np.nan_to_num(out["trend_score"]) * W["trend"]

    out["momentum_pts"] = np.clip(f["mom_12_1"] / 0.30, -1, 1).fillna(0.0) * W["momentum"]

    d = close / f["high252"] - 1.0
    high52 = np.select([d >= -0.05, d >= -0.15, d >= -0.35], [1.0, (d + 0.15) / 0.10, (d + 0.15) / 0.20], -1.0)
    out["high52_pts"] = np.where(f["high252"].isna() | (f["high252"] <= 0), 0.0, np.clip(high52, -1, 1)) * W["high52"]

    rsi2, rsi14 = f["rsi2"], f["rsi14"]
    uptrend = sma200.notna() & above
    pull = np.select(
        [uptrend & (rsi2 < 10), uptrend & (rsi2 < 25), uptrend & (rsi14 > 75), ~uptrend & (rsi2 > 90)],
        [1.0, 0.4, -0.5, -0.6], 0.0)
    out["pullback_pts"] = np.where(rsi2.isna() | rsi14.isna(), 0.0, pull) * W["pullback"]

    rising, positive = f["macd_hist"] > 0, f["macd"] > 0
    macd = np.select([rising & positive, rising, positive], [1.0, 0.5, -0.5], -1.0)
    out["macd_pts"] = np.where(f["macd"].isna() | f["macd_hist"].isna(), 0.0, macd) * W["macd"]
    return out


def earnings_points(index: pd.DatetimeIndex, earnings: pd.DataFrame | None) -> pd.Series:
    """Points from the most recent earnings surprise, as of each day.

    A report only counts from the day after its date, because many are
    released after the close; using it the same day would peek ahead.
    """
    pts = pd.Series(0.0, index=index)
    if earnings is None or earnings.empty:
        return pts
    e = earnings.dropna(subset=["surprise_pct"]).copy()
    e["day"] = pd.to_datetime(e["date"]).dt.normalize().astype("datetime64[ns]")
    e["available"] = e["day"] + pd.Timedelta(days=1)
    e = e.sort_values("available")
    left = pd.DataFrame({"t": pd.DatetimeIndex(index).astype("datetime64[ns]")})
    merged = pd.merge_asof(left, e[["available", "day", "surprise_pct"]], left_on="t", right_on="available",
                           direction="backward")
    age = (merged["t"] - merged["day"]).dt.days
    decay = (1.0 - age / st.EARNINGS_DRIFT_DAYS).where(age <= st.EARNINGS_DRIFT_DAYS, 0.0)
    value = np.clip(merged["surprise_pct"] / 10.0, -1, 1) * decay * st.WEIGHTS["earnings"]
    pts[:] = value.fillna(0.0).to_numpy()
    return pts


def score_history(prices: pd.DataFrame, earnings: pd.DataFrame | None = None,
                  use_earnings: bool = True) -> pd.DataFrame:
    """Indicator frame plus each rule's points, the total score and the action."""
    f = build_frame(prices)
    pts = technical_points(f)
    f = f.join(pts)
    f["earnings_pts"] = earnings_points(f.index, earnings) if use_earnings else 0.0
    f["score"] = f[[c + "_pts" for c in POINT_COLUMNS]].sum(axis=1)
    score = f["score"]
    action = np.select([score >= st.STRONG_THRESHOLD, score >= st.BUY_THRESHOLD,
                        score <= -st.STRONG_THRESHOLD, score <= -st.BUY_THRESHOLD], [2, 1, -2, -1], 0)
    # The trend gate: no Buy without a confirmed uptrend.
    gated = (action > 0) & (f["trend_score"].isna() | (f["trend_score"] < 0))
    f["action"] = np.where(gated, 0, action)
    return f
