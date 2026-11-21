"""Indicator tactics with adjustable settings.

Each tactic turns prices into a simple rule: hold the stock (True) or stay
in cash (False). Every setting is a number you can change, like the weights
of a model, and the same code is used by the live app, the Indicator Lab
playground and the historical tests, so what was tested is what you run.

All functions work on a DataFrame of prices with one column per stock, so a
whole basket is computed at once. Signals use the day's close; trades
happen at the next open (see `backtest`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: float
    lo: float
    hi: float
    step: float = 1
    kind: str = "int"   # int | float | bool | choice
    choices: tuple = ()
    help: str = ""


@dataclass(frozen=True)
class Tactic:
    key: str
    name: str
    style: str          # "trend" or "reversion"
    summary: str
    params: tuple


TACTICS: dict[str, Tactic] = {t.key: t for t in [
    Tactic("price_ma", "Price above moving average", "trend",
           "Hold while the close is above its N-day average; cash when it falls below.",
           (Param("n", "Average length (days)", 200, 5, 400, 5, help="Longer = fewer trades, slower to react."),)),
    Tactic("ma_cross", "Moving-average crossover", "trend",
           "Hold while the fast average is above the slow one (golden cross); cash after a death cross.",
           (Param("fast", "Fast average (days)", 50, 2, 200, 1),
            Param("slow", "Slow average (days)", 200, 10, 400, 5),
            Param("ema", "Use exponential averages", 0, 0, 1, 1, "bool",
                  help="Exponential averages react faster to recent prices."))),
    Tactic("rsi_reversion", "RSI oversold bounce", "reversion",
           "Buy when the RSI drops below the oversold level; sell when it rises above the exit level.",
           (Param("period", "RSI length (days)", 14, 2, 30, 1),
            Param("buy_below", "Buy when RSI is below", 30, 1, 50, 1),
            Param("sell_above", "Sell when RSI is above", 70, 40, 99, 1),
            Param("trend_filter", "Only buy above the 200-day average", 1, 0, 1, 1, "bool",
                  help="Skip dips in stocks that are in a long downtrend."))),
    Tactic("bollinger_reversion", "Bollinger band bounce", "reversion",
           "Buy when the close falls below the lower band; sell when it gets back to the middle.",
           (Param("n", "Band length (days)", 20, 5, 100, 1),
            Param("k", "Band width (standard deviations)", 2.0, 0.5, 4.0, 0.1, "float"))),
    Tactic("bollinger_breakout", "Bollinger band breakout", "trend",
           "Buy when the close breaks above the upper band; sell when it falls below the middle.",
           (Param("n", "Band length (days)", 20, 5, 100, 1),
            Param("k", "Band width (standard deviations)", 2.0, 0.5, 4.0, 0.1, "float"))),
    Tactic("macd", "MACD", "trend",
           "Hold while the MACD line is above its signal line (or above zero).",
           (Param("fast", "Fast EMA (days)", 12, 2, 50, 1),
            Param("slow", "Slow EMA (days)", 26, 5, 200, 1),
            Param("signal", "Signal line (days)", 9, 2, 50, 1),
            Param("zero_line", "Use the zero line instead of the signal line", 0, 0, 1, 1, "bool"))),
    Tactic("donchian", "Breakout (Donchian / Turtle)", "trend",
           "Buy on a close above the highest close of the last N days; sell on a close below the lowest of the last M.",
           (Param("entry", "Breakout length (days)", 55, 5, 300, 5),
            Param("exit", "Exit length (days)", 20, 5, 200, 5))),
    Tactic("momentum", "Time-series momentum", "trend",
           "Hold while the return over the lookback (skipping the most recent days) is positive.",
           (Param("lookback", "Lookback (trading days)", 252, 20, 504, 1),
            Param("skip", "Skip the most recent (days)", 21, 0, 63, 1))),
]}


def clean_params(key: str, raw: dict | None) -> dict:
    """Fill defaults, clamp to range, and coerce types. Raises KeyError for unknown tactics."""
    tactic = TACTICS[key]
    raw = raw or {}
    out = {}
    for p in tactic.params:
        value = raw.get(p.key, p.default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = p.default
        if math.isnan(value):
            value = p.default
        value = min(max(value, p.lo), p.hi)
        out[p.key] = int(round(value)) if p.kind in ("int", "bool") else round(value, 3)
    if key == "ma_cross" and out["fast"] >= out["slow"]:
        out["fast"] = max(2, out["slow"] // 4)
    if key == "macd" and out["fast"] >= out["slow"]:
        out["fast"] = max(2, out["slow"] // 2)
    if key == "rsi_reversion" and out["sell_above"] <= out["buy_below"]:
        out["sell_above"] = min(99, out["buy_below"] + 20)
    return out


def describe(key: str, params: dict) -> str:
    p = clean_params(key, params)
    if key == "price_ma":
        return f"Above {p['n']}-day average"
    if key == "ma_cross":
        kind = "EMA" if p["ema"] else "SMA"
        return f"{p['fast']}/{p['slow']}-day {kind} crossover"
    if key == "rsi_reversion":
        f = ", above 200-day" if p["trend_filter"] else ""
        return f"RSI({p['period']}) buy < {p['buy_below']}, sell > {p['sell_above']}{f}"
    if key in ("bollinger_reversion", "bollinger_breakout"):
        what = "bounce" if key == "bollinger_reversion" else "breakout"
        return f"Bollinger {what} ({p['n']} days, {p['k']:g} SD)"
    if key == "macd":
        line = "zero line" if p["zero_line"] else "signal line"
        return f"MACD {p['fast']}/{p['slow']}/{p['signal']} vs {line}"
    if key == "donchian":
        return f"{p['entry']}-day breakout, {p['exit']}-day exit"
    if key == "momentum":
        return f"{p['lookback']}-day momentum, skip {p['skip']}"
    return key


# --------------------------------------------------------------------------
# Positions
# --------------------------------------------------------------------------

def _rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def _enter_exit(enter: pd.DataFrame, leave: pd.DataFrame) -> pd.DataFrame:
    """Hold from an entry signal until an exit signal (exit wins on the same day)."""
    state = pd.DataFrame(np.nan, index=enter.index, columns=enter.columns)
    state = state.mask(enter.fillna(False).astype(bool), 1.0)
    state = state.mask(leave.fillna(False).astype(bool), 0.0)
    return state.ffill().fillna(0.0).astype(bool)


def positions(key: str, params: dict, close: pd.DataFrame) -> pd.DataFrame:
    """True where the tactic says to hold the stock after that day's close."""
    p = clean_params(key, params)
    if key == "price_ma":
        ma = close.rolling(p["n"], min_periods=p["n"]).mean()
        return (close > ma) & ma.notna()
    if key == "ma_cross":
        if p["ema"]:
            fast = close.ewm(span=p["fast"], adjust=False, min_periods=p["fast"]).mean()
            slow = close.ewm(span=p["slow"], adjust=False, min_periods=p["slow"]).mean()
        else:
            fast = close.rolling(p["fast"], min_periods=p["fast"]).mean()
            slow = close.rolling(p["slow"], min_periods=p["slow"]).mean()
        return (fast > slow) & slow.notna()
    if key == "rsi_reversion":
        rsi = _rsi(close, p["period"])
        enter = rsi < p["buy_below"]
        if p["trend_filter"]:
            sma200 = close.rolling(200, min_periods=200).mean()
            enter &= close > sma200
        return _enter_exit(enter, rsi > p["sell_above"])
    if key in ("bollinger_reversion", "bollinger_breakout"):
        mid = close.rolling(p["n"], min_periods=p["n"]).mean()
        sd = close.rolling(p["n"], min_periods=p["n"]).std()
        if key == "bollinger_reversion":
            return _enter_exit(close < mid - p["k"] * sd, close > mid)
        return _enter_exit(close > mid + p["k"] * sd, close < mid)
    if key == "macd":
        fast = close.ewm(span=p["fast"], adjust=False, min_periods=p["fast"]).mean()
        slow = close.ewm(span=p["slow"], adjust=False, min_periods=p["slow"]).mean()
        line = fast - slow
        if p["zero_line"]:
            return (line > 0) & slow.notna()
        sig = line.ewm(span=p["signal"], adjust=False, min_periods=p["signal"]).mean()
        return (line > sig) & sig.notna()
    if key == "donchian":
        hi = close.rolling(p["entry"], min_periods=p["entry"]).max().shift(1)
        lo = close.rolling(p["exit"], min_periods=p["exit"]).min().shift(1)
        return _enter_exit(close > hi, close < lo)
    if key == "momentum":
        ret = close.shift(p["skip"]) / close.shift(p["lookback"]) - 1
        return ret > 0
    raise KeyError(key)


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def backtest(open_: pd.DataFrame, close: pd.DataFrame, held: pd.DataFrame, cash_rate: pd.Series | None = None,
             cost: float = 0.001) -> pd.DataFrame:
    """Daily returns of each stock's slice of money following `held`.

    `held` is decided at each close and traded at the next open: buying earns
    the open-to-close return that day, selling earns the close-to-open gap.
    Cash earns `cash_rate` (daily decimal). `cost` is charged per trade.
    """
    held = held.reindex(close.index).fillna(False).astype(bool)
    pos = held.shift(1).fillna(False).astype(bool).to_numpy()        # held during day t
    prev = held.shift(2).fillna(False).astype(bool).to_numpy()       # held during day t-1
    o, c = open_.to_numpy(float), close.to_numpy(float)
    c_prev = np.vstack([np.full((1, c.shape[1]), np.nan), c[:-1]])
    o = np.where(np.isnan(o), c_prev, o)
    hold_ret = c / c_prev - 1
    buy_ret = c / o - 1 - cost
    sell_ret = o / c_prev - 1 - cost
    rate = np.zeros(len(close)) if cash_rate is None else cash_rate.reindex(close.index).fillna(0).to_numpy()
    cash_ret = np.repeat(rate[:, None], c.shape[1], axis=1)
    r = np.where(pos & prev, hold_ret, np.where(pos & ~prev, buy_ret, np.where(~pos & prev, sell_ret, cash_ret)))
    r = np.where(np.isnan(r), 0.0, r)
    return pd.DataFrame(r, index=close.index, columns=close.columns)


def pooled_returns(returns: pd.DataFrame, held: pd.DataFrame, cash_rate: pd.Series | None = None,
                   max_weight: float = 0.10) -> pd.Series:
    """One shared pot of money: each day it is split equally across the stocks
    the tactic holds (at most `max_weight` each); the rest earns T-bills.

    `returns` comes from `backtest` (it already includes entry/exit timing and
    costs). Rebalancing between active positions is not charged; entries and
    exits are.
    """
    held = held.reindex(returns.index).fillna(False).astype(bool)
    active = (held.shift(1, fill_value=False) | held.shift(2, fill_value=False)).to_numpy()
    n = active.sum(axis=1)
    weight = np.where(n > 0, np.minimum(max_weight, 1.0 / np.maximum(n, 1)), 0.0)
    invested = weight * n
    rate = np.zeros(len(returns)) if cash_rate is None else cash_rate.reindex(returns.index).fillna(0).to_numpy()
    stock_part = (returns.to_numpy() * active).sum(axis=1) * weight
    return pd.Series(stock_part + (1 - invested) * rate, index=returns.index)


def basket_curve(returns: pd.DataFrame) -> pd.Series:
    """Equal starting money in every stock, no rebalancing."""
    equity = (1 + returns).cumprod()
    return equity.mean(axis=1)


def trade_stats(held: pd.DataFrame) -> dict:
    h = held.astype(bool)
    entries = (h & ~h.shift(1, fill_value=False)).sum().sum()
    years = max((h.index[-1] - h.index[0]).days / 365.25, 1e-9)
    return {
        "time_in_market_pct": round(float(h.to_numpy().mean()) * 100, 1),
        "trades_per_stock_year": round(float(entries) / h.shape[1] / years, 2),
    }
