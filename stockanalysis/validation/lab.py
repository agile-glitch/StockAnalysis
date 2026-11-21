"""Indicator Lab: tune indicator settings like model weights, then check
whether the tuning survives on data it never saw.

    python -m stockanalysis.validation.lab

Protocol (machine-learning style, fixed before running):

* Train:      TRAIN stocks, 2003-2014. Every setting in the grid is scored here.
* Select:     for each tactic, the settings with the best training Sharpe ratio.
* Validate:   the selected settings on three sets never used for tuning
              (held-out stocks 2003-2014, training stocks 2015-2026,
              held-out stocks 2015-2026). The overfitting check compares
              training and validation rankings across the whole grid.
* Test:       one run on 84 brand-new stocks (INDICATOR_TEST), both periods.
* Market:     the same settings applied to the S&P 500 itself (SPY), since
              timing the whole market is what held up in earlier rounds.

Two ways of trading each tactic are measured:
* pooled (the headline): one pot of money split equally across the stocks
  the tactic currently holds, at most 10% each, the rest in T-bills;
* per stock: each stock gets its own slice, in or out of that stock only.
Signals at the close, trades at the next open, 10 basis points per trade.
Sharpe ratios use returns above T-bills. "Beats holding" compares against
holding the same stocks the whole time (equal weight).
"""

from __future__ import annotations

import itertools
import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .. import tactics as T
from . import data, universe
from .portfolio import _daily_cash_rate, curve_metrics

log = logging.getLogger("stockanalysis.validation")

REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_lab.json"

INDICATOR_TEST = [
    "ADM", "AEP", "AES", "AJG", "ALB", "AME", "AOS", "APA", "ATO", "AVY", "BALL", "BIO", "BRO", "BWA", "CAG",
    "CHD", "CMS", "CNP", "COO", "CPB", "CTSH", "DGX", "DHI", "DLTR", "DTE", "EIX", "EL", "EMN", "ES", "ETR",
    "FE", "FFIV", "HBAN", "HRL", "HST", "IDXX", "INTU", "IRM", "IT", "JCI", "JKHY", "KLAC", "KMX", "LNT",
    "LRCX", "MCHP", "MHK", "MLM", "MNST", "MTD", "NEE", "NI", "NTAP", "O", "ODFL", "PEG", "PNW", "POOL",
    "PPL", "PWR", "REGN", "RMD", "RSG", "SBAC", "SCHW", "SPG", "STE", "STZ", "SWKS", "TAP", "TER", "TFX",
    "TMO", "TSCO", "UDR", "UHS", "URI", "VRSN", "VTR", "WAB", "WEC", "WST", "XEL", "ZION",
]

PERIODS = {"2003_2014": ("2003-01-01", "2014-12-31"), "2015_now": ("2015-01-01", None)}
TRAIN_CELL = ("train", "2003_2014")
VALIDATION_CELLS = [("holdout", "2003_2014"), ("train", "2015_now"), ("holdout", "2015_now")]
TEST_CELLS = [("test", "2003_2014"), ("test", "2015_now")]


def grid() -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    g["price_ma"] = [{"n": n} for n in (10, 20, 50, 100, 150, 200, 250, 300)]
    g["ma_cross"] = [{"fast": f, "slow": s, "ema": e}
                     for f, s, e in itertools.product((5, 10, 20, 50, 100), (50, 100, 150, 200, 300), (0, 1)) if f < s]
    g["rsi_reversion"] = [{"period": p, "buy_below": b, "sell_above": s, "trend_filter": t}
                          for p, b, s, t in itertools.product((2, 3, 5, 14), (5, 10, 20, 30), (50, 70), (0, 1))]
    g["bollinger_reversion"] = [{"n": n, "k": k} for n, k in itertools.product((10, 20, 50), (1.5, 2.0, 2.5))]
    g["bollinger_breakout"] = [{"n": n, "k": k} for n, k in itertools.product((10, 20, 50, 100), (1.0, 1.5, 2.0, 2.5))]
    g["macd"] = [{"fast": f, "slow": s, "signal": sg, "zero_line": z}
                 for (f, s, sg), z in itertools.product(((5, 35, 5), (8, 17, 9), (12, 26, 9), (19, 39, 9), (50, 150, 20)), (0, 1))]
    g["donchian"] = [{"entry": e, "exit": x} for e, x in itertools.product((20, 55, 100, 200), (10, 20, 50, 100)) if x < e]
    g["momentum"] = [{"lookback": lb, "skip": sk} for lb, sk in itertools.product((63, 126, 189, 252, 378), (0, 21))]
    return g


class Group:
    """Prices for one set of stocks, aligned on the S&P 500's trading days."""

    def __init__(self, frames: dict[str, pd.DataFrame], dates: pd.DatetimeIndex, cash_rate: pd.Series):
        self.close = pd.DataFrame({s: f["close"] for s, f in frames.items()}).reindex(dates)
        self.open = pd.DataFrame({s: f["open"] for s, f in frames.items()}).reindex(dates)
        self.cash_rate = cash_rate
        self._hold = T.backtest(self.open, self.close, self.close.notna(), self.cash_rate)
        self._bench: dict = {}

    def _benchmarks(self, start, end, cols):
        key = (start, end)
        if key not in self._bench:
            window = slice(start, end)
            hold = self._hold.loc[window, cols]
            self._bench[key] = {
                "slices": curve_metrics(T.basket_curve(hold), self.cash_rate),
                "pooled": curve_metrics((1 + T.pooled_returns(hold, self.close.loc[window, cols].notna(),
                                                              self.cash_rate, max_weight=1.0)).cumprod(), self.cash_rate),
            }
        return self._bench[key]

    def evaluate(self, key: str, params: dict, start: str, end: str | None) -> dict:
        return self.evaluate_held(T.positions(key, params, self.close), start, end)

    def evaluate_held(self, held: pd.DataFrame, start: str, end: str | None, keep_returns: bool = False) -> dict:
        """Score any hold/cash signal (one column per stock)."""
        rets = T.backtest(self.open, self.close, held, self.cash_rate)
        window = slice(start, end)
        alive = self.close.loc[start:].iloc[:5].notna().all()       # stocks trading at the start
        cols = alive[alive].index
        r, h = rets.loc[window, cols], held.loc[window, cols]
        bench = self._benchmarks(start, end, cols)
        slices = curve_metrics(T.basket_curve(r), self.cash_rate)
        pooled = curve_metrics((1 + T.pooled_returns(r, h, self.cash_rate)).cumprod(), self.cash_rate)
        stats = T.trade_stats(h)
        out = {**pooled, **stats, "hold": bench["pooled"], "stocks": len(cols),
               "per_stock": {**slices, "hold": bench["slices"]}}
        if keep_returns:   # daily pooled returns minus holding, for the deflated Sharpe ratio
            hold_r = T.pooled_returns(self._hold.loc[window, cols], self.close.loc[window, cols].notna(),
                                      self.cash_rate, max_weight=1.0)
            out["_active"] = T.pooled_returns(r, h, self.cash_rate) - hold_r
        return out


def _edge(m: dict) -> float:
    return (m.get("sharpe") or 0) - (m["hold"].get("sharpe") or 0)


def _rank_corr(a: list[float], b: list[float]) -> float:
    if len(a) < 3:
        return float("nan")
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def run() -> dict:
    groups_syms = {"train": universe.TRAIN, "holdout": universe.HOLDOUT, "test": INDICATOR_TEST}
    all_syms = [s for g in groups_syms.values() for s in g]
    prices = data.load_prices(all_syms + [universe.BENCHMARK])
    tbill = data.load_tbill()
    spy = prices[universe.BENCHMARK]
    dates = spy.index
    cash = pd.Series(_daily_cash_rate(dates, tbill), index=dates)
    groups = {g: Group({s: prices[s] for s in syms if s in prices}, dates, cash) for g, syms in groups_syms.items()}
    market = Group({"SPY": spy}, dates, cash)

    families = []
    for key, settings in grid().items():
        log.info("%s: %d settings", key, len(settings))
        rows = []
        for params in settings:
            train = groups[TRAIN_CELL[0]].evaluate(key, params, *PERIODS[TRAIN_CELL[1]])
            val = [groups[g].evaluate(key, params, *PERIODS[p]) for g, p in VALIDATION_CELLS]
            rows.append({"params": params, "train": train, "validation": val,
                         "train_edge": _edge(train), "val_edge": float(np.mean([_edge(v) for v in val]))})
        eligible = [r for r in rows if r["train"].get("trades_per_stock_year", 0) > 0.05] or rows
        best = max(eligible, key=lambda r: (r["train"].get("sharpe") or -9))
        oracle = max(rows, key=lambda r: r["val_edge"])        # best in hindsight, for the overfitting check
        test = {f"{g}_{p}": groups[g].evaluate(key, best["params"], *PERIODS[p]) for g, p in TEST_CELLS}
        spy_res = {p: market.evaluate(key, best["params"], *PERIODS[p])["per_stock"] for p in PERIODS}
        default = T.clean_params(key, {})
        default_val = [groups[g].evaluate(key, default, *PERIODS[p]) for g, p in VALIDATION_CELLS]
        tr_rank = pd.Series([r["train_edge"] for r in rows]).rank(pct=True)
        families.append({
            "key": key,
            "name": T.TACTICS[key].name,
            "style": T.TACTICS[key].style,
            "settings_tried": len(rows),
            "best_params": best["params"],
            "best_label": T.describe(key, best["params"]),
            "default_params": default,
            "default_label": T.describe(key, default),
            "train": best["train"],
            "validation": {f"{g}_{p}": v for (g, p), v in zip(VALIDATION_CELLS, best["validation"])},
            "default_validation": {f"{g}_{p}": v for (g, p), v in zip(VALIDATION_CELLS, default_val)},
            "test": test,
            "spy": spy_res,
            "train_edge": round(best["train_edge"], 3),
            "validation_edge": round(best["val_edge"], 3),
            "test_edge": round(float(np.mean([_edge(v) for v in test.values()])), 3),
            "oracle_label": T.describe(key, oracle["params"]),
            "oracle_validation_edge": round(oracle["val_edge"], 3),
            "rank_corr_train_vs_validation": round(_rank_corr([r["train_edge"] for r in rows], [r["val_edge"] for r in rows]), 2),
            "grid": [{"label": T.describe(key, r["params"]), "params": r["params"],
                      "train_sharpe": r["train"].get("sharpe"), "train_cagr": r["train"].get("cagr_pct"),
                      "train_edge": round(r["train_edge"], 3), "val_edge": round(r["val_edge"], 3),
                      "train_pct_rank": round(float(tr_rank[i]), 2),
                      "time_in_market_pct": r["train"].get("time_in_market_pct")} for i, r in enumerate(rows)],
        })

    all_rows = [g for f in families for g in f["grid"]]
    hold_spy = {p: market.evaluate("price_ma", {"n": 5}, *PERIODS[p])["per_stock"]["hold"] for p in PERIODS}
    report = {
        "design": __doc__,
        "groups": {g: len(v.close.columns) for g, v in groups.items()},
        "validation_cells": [f"{g}_{p}" for g, p in VALIDATION_CELLS],
        "test_cells": [f"{g}_{p}" for g, p in TEST_CELLS],
        "families": families,
        "spy_hold": hold_spy,
        "overall_rank_corr": round(_rank_corr([r["train_edge"] for r in all_rows], [r["val_edge"] for r in all_rows]), 2),
        "settings_total": len(all_rows),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "lab.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(report))
    return report


DOC = Path(__file__).resolve().parents[2] / "docs" / "INDICATOR_LAB.md"


def write_markdown(r: dict) -> str:
    def p(x):
        return "n/a" if x is None else f"{x:+.1f}%"

    fams = r["families"]
    held = [f for f in fams if f["validation_edge"] > 0 and f["test_edge"] > 0]
    out = [
        "# Indicator Lab: can tuning indicator settings beat holding?",
        "",
        "Generated by `python -m stockanalysis.validation.lab`. The same results, plus a playground to try any "
        "settings on any stock, are on the app's **Indicator lab** page.",
        "",
        "## Bottom line",
        "",
        (f"**{len(held)} of {len(fams)} indicators** kept an edge over holding on both unseen data and new stocks."
         if held else
         f"**None of the {r['settings_total']} settings across {len(fams)} indicators beat simply holding the same "
         "stocks on data they were not tuned on.** Several looked better in training and lost it on new stocks and "
         "later years: indicator settings overfit just like model weights."),
        "",
        "For " + ", ".join(f"{f['name'].lower()} ({f['rank_corr_train_vs_validation']:+.2f})"
                           for f in fams if f["rank_corr_train_vs_validation"] < 0.5)
        + ", the ranking of settings in training barely predicted their ranking on unseen data, so picking the "
        "'best' settings mostly picked luck. For the other indicators the rankings were stable, but even their best "
        "settings trailed holding.",
        "",
        "## Method",
        "",
        "Tactic settings were treated like model weights and fitted the machine-learning way:",
        "",
        f"- **Train:** {r['groups']['train']} stocks, 2003–2014. Every setting in the grid scored; the best training Sharpe chosen per indicator.",
        f"- **Validate:** {r['groups']['holdout']} other stocks (2003–2014 and 2015–2026) and the training stocks in 2015–2026.",
        f"- **Test:** {r['groups']['test']} stocks used for nothing else, both periods, run once.",
        "- **Trading:** one shared pot of money split across the stocks the tactic holds (max 10% each), the rest in T-bills. "
        "Signals at the close, trades at the next open, 0.1% per trade. Sharpe ratios use returns above T-bills.",
        "- **Edge:** the tactic's Sharpe ratio minus that of holding the same stocks equally.",
        "",
        "## Results",
        "",
        "| Indicator | Settings tried | Best in training | Training edge | Unseen-data edge | New-stocks edge | Training/unseen rank agreement |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for f in fams:
        out.append(f"| {f['name']} | {f['settings_tried']} | {f['best_label']} | {f['train_edge']:+.2f} | "
                   f"{f['validation_edge']:+.2f} | {f['test_edge']:+.2f} | {f['rank_corr_train_vs_validation']:.2f} |")
    out += ["", "### Yearly return and worst drop on the new stocks (tested-best settings vs holding)", "",
            "| Indicator | 2003–2014 | 2015–2026 |", "| --- | --- | --- |"]
    for f in fams:
        cells = []
        for k in ("test_2003_2014", "test_2015_now"):
            v = f["test"][k]
            cells.append(f"{p(v['cagr_pct'])} / {p(v['max_drawdown_pct'])} vs {p(v['hold']['cagr_pct'])} / {p(v['hold']['max_drawdown_pct'])}")
        out.append(f"| {f['name']} | " + " | ".join(cells) + " |")
    out += ["", "### Timing the S&P 500 itself (Sharpe, tactic vs holding SPY)", "",
            "| Indicator | 2003–2014 | 2015–2026 |", "| --- | --- | --- |"]
    for f in fams:
        out.append(f"| {f['name']} | " + " | ".join(
            f"{f['spy'][k]['sharpe']:.2f} vs {f['spy'][k]['hold']['sharpe']:.2f}" for k in ("2003_2014", "2015_now")) + " |")
    out += ["", "Trend indicators on the index helped in 2003–2014, thanks to 2008, and lagged since 2015, the same "
            "pattern as the app's market risk rule.", "",
            "## Caveats", "",
            "- Large, still-listed US stocks only (survivorship bias flatters long-only results, including holding).",
            "- A grid of common settings, not every possible combination; more search means more overfitting, not less.",
            "- Taxes not modelled; short selling not tested.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()
