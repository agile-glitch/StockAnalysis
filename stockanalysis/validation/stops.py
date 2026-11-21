"""Stop-loss test: does putting a stop under each stock improve results?

Set-up (the classic design from the stop-loss literature, e.g. Lei & Li 2009,
Kaminski & Lo 2014): every stock gets an equal slice of money and starts
fully invested. Each slice then follows one exit rule. After a stop-out the
slice sits in T-bills until its re-entry rule says buy again. The benchmark is
the same slices with no stop at all (buy and hold).

Fills:
* Intraday stops (fixed %, trailing %, ATR at entry) act like a resting stop
  order: if the day's low reaches the stop, the sale fills at the stop price,
  or at the open if the stock gaps below it (so gap losses are counted).
* Close-based stops (moving averages, chandelier, time stop) are decided at
  the close and sold at the next open.
Every buy and sell pays 10 basis points. Nothing looks ahead.

Run:  python -m stockanalysis.validation.stops
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import data, universe
from .portfolio import _daily_cash_rate, curve_metrics
from .run import REPORT_DIR, TEST_START, TRAIN_END, TRAIN_START, score_universe

log = logging.getLogger("stockanalysis.validation")
COST = 0.001
BUNDLED_STOPS = __import__("pathlib").Path(__file__).resolve().parent / "latest_stops.json"


@dataclass(frozen=True)
class StopRule:
    name: str
    kind: str                 # none | fixed | trail | atr_entry | chandelier | ma | time
    param: float = 0.0        # % for fixed/trail, ATR multiple, MA length, days for time
    reentry: str = "none"     # none | next_month | breakout | above_ma
    family: str = ""


def rules() -> list[StopRule]:
    out = [StopRule("No stop (buy and hold)", "none", family="Benchmark")]
    for reentry, label in (("next_month", "re-buy next month"), ("breakout", "re-buy on new 20-day high")):
        for pct in (8, 15, 25):
            out.append(StopRule(f"Fixed {pct}% stop, {label}", "fixed", pct, reentry, "Fixed % below entry"))
        for pct in (10, 20, 30):
            out.append(StopRule(f"Trailing {pct}% stop, {label}", "trail", pct, reentry, "Trailing % below highest close"))
        out.append(StopRule(f"2.5 ATR stop at entry, {label}", "atr_entry", 2.5, reentry, "Volatility (ATR)"))
        out.append(StopRule(f"Chandelier (22-day high minus 3 ATR), {label}", "chandelier", 3.0, reentry, "Volatility (ATR)"))
        out.append(StopRule(f"Time stop (losing after 60 days), {label}", "time", 60, reentry, "Time"))
    for length in (50, 200):
        out.append(StopRule(f"Close below {length}-day average, re-buy above it", "ma", length, "above_ma", "Moving average"))
    return out


@dataclass
class StockPanel:
    dates: pd.DatetimeIndex
    symbols: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr14: np.ndarray
    chandelier: np.ndarray
    sma50: np.ndarray
    sma200: np.ndarray
    high20: np.ndarray     # highest close of the previous 20 days
    cash_rate: np.ndarray

    @classmethod
    def build(cls, frames: dict, spy: pd.DataFrame, tbill: pd.Series) -> "StockPanel":
        dates = spy.index
        syms = sorted(frames)

        def mat(fn):
            return np.column_stack([fn(frames[s]).reindex(dates).to_numpy(dtype=float) for s in syms])
        return cls(dates, syms, mat(lambda f: f["open"]), mat(lambda f: f["high"]), mat(lambda f: f["low"]),
                   mat(lambda f: f["close"]), mat(lambda f: f["atr14"]), mat(lambda f: f["chandelier"]),
                   mat(lambda f: f["sma50"]), mat(lambda f: f["sma200"]),
                   mat(lambda f: f["close"].rolling(20).max().shift(1)), _daily_cash_rate(dates, tbill))


def simulate_stops(p: StockPanel, rule: StopRule, start: str, end: str | None = None) -> dict:
    lo = int(p.dates.searchsorted(pd.Timestamp(start)))
    hi = int(p.dates.searchsorted(pd.Timestamp(end), side="right")) if end else len(p.dates)
    live = np.flatnonzero(~np.isnan(p.open[lo]) & ~np.isnan(p.close[lo]) & ~np.isnan(p.sma200[lo]))
    n = len(live)
    o, h, lw, c = p.open[:, live], p.high[:, live], p.low[:, live], p.close[:, live]
    months = p.dates.to_period("M")

    cash = np.full(n, 1.0)
    shares = np.zeros(n)
    inside = np.zeros(n, dtype=bool)
    entry_px = np.full(n, np.nan)
    stop_lvl = np.full(n, np.nan)
    peak = np.full(n, np.nan)
    entry_day = np.zeros(n, dtype=int)
    exit_day = np.full(n, -10)
    pend_in = np.ones(n, dtype=bool)          # everyone buys on the first day
    pend_out = np.zeros(n, dtype=bool)
    last = c[lo].copy()
    curve, invested = [], []
    stops = []   # (stock, day, exit price)

    def sell(j, px, i):
        cash[j] += shares[j] * px * (1 - COST)
        shares[j] = 0.0
        inside[j] = False
        exit_day[j] = i
        stops.append((j, i, px))

    for i in range(lo, hi):
        cash *= 1 + p.cash_rate[i]
        # Next-open orders.
        for j in np.flatnonzero(pend_out):
            if not math.isnan(o[i, j]):
                sell(j, o[i, j], i)
                pend_out[j] = False
        for j in np.flatnonzero(pend_in & ~inside):
            px = o[i, j]
            if math.isnan(px) or px <= 0:
                continue
            shares[j] = cash[j] * (1 - COST) / px
            cash[j] = 0.0
            inside[j] = True
            entry_px[j], peak[j], entry_day[j] = px, px, i
            atr = p.atr14[i - 1, live[j]]
            stop_lvl[j] = px - rule.param * atr if rule.kind == "atr_entry" and not math.isnan(atr) else np.nan
            pend_in[j] = False
        # Intraday stops.
        if rule.kind in ("fixed", "trail", "atr_entry"):
            if rule.kind == "fixed":
                level = entry_px * (1 - rule.param / 100)
            elif rule.kind == "trail":
                level = peak * (1 - rule.param / 100)
            else:
                level = stop_lvl
            hit = inside & ~np.isnan(level) & ~np.isnan(lw[i]) & (lw[i] <= level)
            for j in np.flatnonzero(hit):
                fill = min(o[i, j], level[j]) if not math.isnan(o[i, j]) else level[j]
                sell(j, fill, i)
        ok = ~np.isnan(c[i])
        last[ok] = c[i, ok]
        peak = np.where(inside & ok, np.fmax(peak, c[i]), peak)
        # Close-based exits (sold at the next open).
        if rule.kind == "chandelier":
            pend_out |= inside & ok & (c[i] < p.chandelier[i, live])
        elif rule.kind == "ma":
            ma = p.sma50[i, live] if rule.param == 50 else p.sma200[i, live]
            pend_out |= inside & ok & (c[i] < ma)
        elif rule.kind == "time":
            held = i - entry_day
            pend_out |= inside & ok & (held > 0) & (held % int(rule.param) == 0) & (c[i] < entry_px)
        # Re-entry decisions (never on the day of an exit).
        out_now = ~inside & ~pend_in & (exit_day < i) & ok
        if rule.reentry == "next_month" and i + 1 < len(p.dates) and months[i + 1] != months[i]:
            pend_in |= out_now
        elif rule.reentry == "breakout":
            pend_in |= out_now & (c[i] >= p.high20[i, live])
        elif rule.reentry == "above_ma":
            ma = p.sma50[i, live] if rule.param == 50 else p.sma200[i, live]
            pend_in |= out_now & (c[i] > ma)
        equity = cash + shares * last
        curve.append(equity.sum())
        invested.append(float((shares * last).sum() / equity.sum()))

    dates = p.dates[lo:hi]
    curve = pd.Series(curve, index=dates) / n
    years = (dates[-1] - dates[0]).days / 365.25
    # How did stopped-out stocks do afterwards?
    after = []
    for j, i, px in stops:
        k = min(i + 60, hi - 1)
        if k - i >= 40 and not math.isnan(c[k, j]):
            after.append(c[k, j] / px - 1)
    after = np.array(after)
    return {
        "rule": asdict(rule),
        "curve": curve,
        "stocks": n,
        "invested_pct": round(float(np.mean(invested)) * 100, 1),
        "stop_outs": len(stops),
        "stop_outs_per_stock_year": round(len(stops) / n / years, 2) if years > 0 else None,
        "rose_after_stop_pct": round(float((after > 0).mean()) * 100, 1) if len(after) else None,
        "avg_move_60d_after_stop_pct": round(float(after.mean()) * 100, 2) if len(after) else None,
    }


CELLS = {
    "train_2003_2014": ("train", TRAIN_START, TRAIN_END),
    "train_2015_now": ("train", TEST_START, None),
    "holdout_2003_2014": ("holdout", TRAIN_START, TRAIN_END),
    "holdout_2015_now": ("holdout", TEST_START, None),
    "exam_2003_2014": ("exam", TRAIN_START, TRAIN_END),
    "exam_2015_now": ("exam", TEST_START, None),
}


def run() -> dict:
    groups = {"train": universe.TRAIN, "holdout": universe.HOLDOUT, "exam": universe.FINAL_EXAM}
    all_syms = [s for g in groups.values() for s in g]
    prices = data.load_prices(all_syms + [universe.BENCHMARK])
    tbill = data.load_tbill()
    spy = prices[universe.BENCHMARK]
    panels = {}
    for g, syms in groups.items():
        frames = score_universe([s for s in syms if s in prices], prices, {}, use_earnings=False)
        panels[g] = StockPanel.build(frames, spy, tbill)

    results = []
    for rule in rules():
        row = {"name": rule.name, "family": rule.family, "kind": rule.kind, "reentry": rule.reentry, "cells": {}}
        for cell, (g, start, end) in CELLS.items():
            res = simulate_stops(panels[g], rule, start, end)
            row["cells"][cell] = {**curve_metrics(res["curve"]), **{k: v for k, v in res.items() if k not in ("curve", "rule")}}
        results.append(row)
        log.info("%s done", rule.name)

    base = results[0]["cells"]
    for row in results:
        cells = row["cells"]
        row["avg_cagr_vs_hold"] = round(float(np.mean([cells[k]["cagr_pct"] - base[k]["cagr_pct"] for k in CELLS])), 2)
        row["avg_drawdown_vs_hold"] = round(float(np.mean([cells[k]["max_drawdown_pct"] - base[k]["max_drawdown_pct"] for k in CELLS])), 1)
        row["avg_sharpe_vs_hold"] = round(float(np.mean([(cells[k]["sharpe"] or 0) - (base[k]["sharpe"] or 0) for k in CELLS])), 3)
        row["cells_beating_hold_on_return"] = sum(cells[k]["cagr_pct"] > base[k]["cagr_pct"] for k in CELLS)
        row["cells_beating_hold_on_sharpe"] = sum((cells[k]["sharpe"] or 0) > (base[k]["sharpe"] or 0) for k in CELLS)
    report = {"design": __doc__, "cells": list(CELLS), "results": results}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "stops.json").write_text(text)
    BUNDLED_STOPS.write_text(text)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()
