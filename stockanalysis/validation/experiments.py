"""Two experiments, run the machine-learning way:

    python -m stockanalysis.validation.experiments

1. Fit the score's weights. The app gives each signal fixed points (trend 25,
   momentum 15, 52-week high 10, pullback 10, MACD 5, earnings 10). Here a
   ridge regression learns them from the training stocks, predicting each
   stock's return over the S&P 500 in the next 20 trading days, sampled at
   month ends. The ridge penalty is chosen by leave-one-year-out
   cross-validation inside the training years only.

2. Combine indicators. 16 indicator signals (each Lab tactic at its tested-best
   and default settings) combined as "both agree" (AND), "either" (OR) and
   "two of three" (majority): about 800 combinations. The best training
   combination is checked with the deflated Sharpe ratio (Bailey & Lopez de
   Prado 2014), which asks how likely a "best of N" result is to be luck.

Data roles, fixed before running:
* Train:      TRAIN stocks, 2003-2014.
* Validate:   HOLDOUT stocks 2003-2014 and 2015-2026; TRAIN stocks 2015-2026.
* Test:       FRESH_TEST, 92 stocks used in no earlier test, both periods, once.

Rule for changing the app, also fixed before running: adopt the fitted weights
or a combination only if, on the fresh stocks, it beats holding in both
periods AND its ranking skill (or deflated Sharpe ratio) is statistically
significant.
"""

from __future__ import annotations

import itertools
import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .. import strategies as st
from .. import tactics as T
from . import data, universe
from .lab import INDICATOR_TEST, PERIODS, Group
from .portfolio import _daily_cash_rate, curve_metrics
from .run import score_universe
from .study import forward_returns

log = logging.getLogger("stockanalysis.validation")

REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_experiments.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "EXPERIMENTS.md"

FRESH_TEST = [
    "AFG", "ALK", "AMT", "ARE", "BXP", "CACI", "CCK", "CDNS", "CHE", "CMC", "CPRT", "CSGP", "DCI", "DECK", "DVA",
    "EXPD", "FDS", "FICO", "FLS", "FMC", "FRT", "GGG", "GL", "GPN", "HEI", "HELE", "HP", "HSIC", "HUBB", "IEX",
    "INCY", "ITT", "KIM", "KSS", "LECO", "MAA", "MAN", "MAT", "MKL", "MSA", "MSM", "NDSN", "NFG", "NWL", "NYT",
    "OKE", "ORI", "R", "RLI", "ROL", "ROP", "RPM", "SEIC", "SIGI", "SNPS", "SON", "SSD", "STLD", "SWX", "TECH",
    "THO", "TKR", "TRMB", "TTC", "TYL", "UFPI", "UNM", "VMI", "WDC", "WRB", "WSM", "WSO", "XRAY", "BMI", "CBSH",
    "CFR", "CW", "EGP", "FUL", "GATX", "MDU", "NJR", "OGE", "PRGO", "SCI", "SKY", "TDS", "TRN", "UGI", "WEN",
    "WGO", "WWD",
]

TRAIN_CELL = ("train", "2003_2014")
VALIDATION_CELLS = [("holdout", "2003_2014"), ("train", "2015_now"), ("holdout", "2015_now")]
TEST_CELLS = [("fresh", "2003_2014"), ("fresh", "2015_now")]
FEATURES = ["trend", "momentum", "high52", "pullback", "macd", "earnings"]
FEATURE_LABELS = {"trend": "Long-term trend", "momentum": "12-month momentum", "high52": "52-week high",
                  "pullback": "Entry timing (pullback)", "macd": "MACD", "earnings": "Earnings surprise"}
TOP_N = 15
COST = 0.001


# --------------------------------------------------------------------------
# Shared statistics
# --------------------------------------------------------------------------

def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's approximation, |error| < 1.2e-9)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        return -_norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def deflated_sharpe(returns: pd.Series, trial_sharpes: list[float]) -> dict:
    """Probability that the best of N trials has a true Sharpe above zero
    (Bailey & Lopez de Prado 2014). Sharpe ratios are per period (daily)."""
    r = returns.dropna()
    n = len(trial_sharpes)
    sr = float(r.mean() / r.std()) if r.std() > 0 else 0.0
    var = float(np.var(trial_sharpes, ddof=1)) if n > 1 else 0.0
    gamma = 0.5772156649
    expected_max = math.sqrt(var) * ((1 - gamma) * _norm_ppf(1 - 1 / n) + gamma * _norm_ppf(1 - 1 / (n * math.e))) if n > 1 else 0.0
    skew = float(r.skew())
    kurt = float(r.kurt()) + 3.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    z = (sr - expected_max) * math.sqrt(len(r) - 1) / denom
    plain_z = sr * math.sqrt(len(r) - 1) / denom
    return {"trials": n, "sharpe_annual": round(sr * math.sqrt(252), 2),
            "luck_threshold_annual": round(expected_max * math.sqrt(252), 2),
            "probability_real": round(_norm_cdf(z), 3), "probability_real_if_one_trial": round(_norm_cdf(plain_z), 3)}


# --------------------------------------------------------------------------
# Experiment 1: fitted weights
# --------------------------------------------------------------------------

class FeatureGroup:
    """Monthly signal values and next-20-day excess returns for one set of stocks."""

    def __init__(self, frames: dict[str, pd.DataFrame], spy: pd.DataFrame, cash: pd.Series):
        dates = spy.index
        self.dates = dates
        self.cash = cash
        self.features = {}
        for name in FEATURES:
            w = st.WEIGHTS[name]
            self.features[name] = pd.DataFrame({s: f[f"{name}_pts"] / w for s, f in frames.items()}).reindex(dates)
        valid = pd.DataFrame({s: f["trend_score"].notna() & f["mom_12_1"].notna() for s, f in frames.items()}).reindex(dates)
        self.valid = valid.fillna(False).astype(bool)
        fwd = {s: forward_returns(f, spy, (20,))["exc_20"] for s, f in frames.items()}
        self.target = pd.DataFrame(fwd).reindex(dates)
        self.close = pd.DataFrame({s: f["close"] for s, f in frames.items()}).reindex(dates)
        self.daily = self.close.pct_change(fill_method=None)

    def month_ends(self, start: str, end: str | None) -> pd.DatetimeIndex:
        window = self.dates[(self.dates >= pd.Timestamp(start)) & (self.dates <= pd.Timestamp(end or "2100-01-01"))]
        s = pd.Series(window, index=window)
        return pd.DatetimeIndex(s.groupby(window.to_period("M")).max().to_numpy())

    def table(self, start: str, end: str | None) -> pd.DataFrame:
        rows = []
        for d in self.month_ends(start, end):
            ok = self.valid.loc[d]
            stocks = ok[ok].index
            x = pd.DataFrame({k: v.loc[d, stocks] for k, v in self.features.items()})
            x["target"] = self.target.loc[d, stocks]
            x["date"] = d
            rows.append(x)
        return pd.concat(rows).dropna(subset=FEATURES)

    def scores(self, weights: np.ndarray) -> pd.DataFrame:
        total = sum(self.features[k] * w for k, w in zip(FEATURES, weights))
        return total.where(self.valid)

    def evaluate(self, weights: np.ndarray, start: str, end: str | None) -> dict:
        score = self.scores(weights)
        months = self.month_ends(start, end)
        ics = []
        for d in months:
            s, t = score.loc[d], self.target.loc[d]
            ok = s.notna() & t.notna()
            if ok.sum() >= 10:
                ics.append(s[ok].rank().corr(t[ok].rank()))
        ics = pd.Series(ics).dropna()
        # Top-N portfolio, rebalanced at each month end, one day's lag (no peeking).
        w = pd.DataFrame(0.0, index=self.dates, columns=self.close.columns)
        ew = w.copy()
        for d in months:
            s = score.loc[d].dropna()
            if len(s) < TOP_N:
                continue
            top = s.nlargest(TOP_N).index
            w.loc[d, :] = 0.0
            w.loc[d, top] = 1.0 / TOP_N
            alive = s.index
            ew.loc[d, :] = 0.0
            ew.loc[d, alive] = 1.0 / len(alive)
        mask = pd.Series(False, index=self.dates)
        mask.loc[months] = True
        out = {}
        for name, wt in (("top", w), ("all", ew)):
            wt = wt.where(mask, np.nan).ffill().fillna(0.0)
            held = wt.shift(2).fillna(0.0)                     # decided at the close, held from the day after next
            turnover = wt.diff().abs().sum(axis=1).shift(1).fillna(0.0)
            daily = (held * self.daily.fillna(0.0)).sum(axis=1) - turnover * COST
            window = slice(months[0], months[-1] + pd.Timedelta(days=31))
            curve = (1 + daily.loc[window]).cumprod()
            out[name] = curve_metrics(curve, self.cash)
        return {
            "ic_mean": round(float(ics.mean()), 4) if len(ics) else None,
            "ic_t": round(float(ics.mean() / ics.std() * math.sqrt(len(ics))), 2) if len(ics) > 2 and ics.std() > 0 else None,
            "ic_positive_pct": round(float((ics > 0).mean()) * 100, 1) if len(ics) else None,
            "months": int(len(ics)),
            "top": out["top"],
            "hold": out["all"],
            "edge": round((out["top"].get("sharpe") or 0) - (out["all"].get("sharpe") or 0), 3),
        }


def _ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    xtx = x.T @ x + alpha * np.eye(x.shape[1])
    return np.linalg.solve(xtx, x.T @ y)


def _monthly_ic(table: pd.DataFrame, pred: np.ndarray) -> float:
    t = table.assign(pred=pred)
    ics = t.groupby("date").apply(lambda g: g["pred"].rank().corr(g["target"].rank()) if len(g) >= 10 else np.nan,
                                  include_groups=False)
    return float(ics.mean())


def fit_weights(train: pd.DataFrame) -> dict:
    train = train.dropna(subset=["target"])
    x = train[FEATURES].to_numpy(float)
    y = train["target"].to_numpy(float)
    mu, sd = x.mean(axis=0), x.std(axis=0)
    sd[sd == 0] = 1.0
    z = (x - mu) / sd
    years = train["date"].dt.year.to_numpy()
    cv = {}
    for alpha in (0.1, 1, 10, 100, 1000, 10_000, 100_000):
        ics = []
        for yr in np.unique(years):
            tr, te = years != yr, years == yr
            beta = _ridge(z[tr], y[tr] - y[tr].mean(), alpha)
            ics.append(_monthly_ic(train[te], z[te] @ beta))
        cv[alpha] = float(np.nanmean(ics))
    best_alpha = max(cv, key=cv.get)
    beta = _ridge(z, y - y.mean(), best_alpha)
    raw = beta / sd                                             # weights on the original -1..1 signals
    scale = 100.0 / np.abs(raw).sum() if np.abs(raw).sum() > 0 else 1.0
    return {"alpha": best_alpha, "cv_ic": {str(k): round(v, 4) for k, v in cv.items()},
            "weights": raw * scale, "standardized_beta": beta.tolist(), "samples": int(len(train))}


def experiment_weights(groups: dict[str, FeatureGroup]) -> dict:
    train_table = groups[TRAIN_CELL[0]].table(*PERIODS[TRAIN_CELL[1]])
    fit = fit_weights(train_table)
    models = {
        "App weights (current)": np.array([st.WEIGHTS[k] for k in FEATURES], float),
        "Fitted weights (ridge regression)": fit["weights"],
        "Equal weights": np.ones(len(FEATURES)),
    }
    for i, k in enumerate(FEATURES):
        single = np.zeros(len(FEATURES))
        single[i] = 1.0
        models[f"{FEATURE_LABELS[k]} only"] = single
    results = []
    for name, w in models.items():
        row = {"name": name, "weights": {k: round(float(v), 1) for k, v in zip(FEATURES, w)}, "cells": {}}
        for g, p in [TRAIN_CELL] + VALIDATION_CELLS + TEST_CELLS:
            row["cells"][f"{g}_{p}"] = groups[g].evaluate(w, *PERIODS[p])
        results.append(row)
        log.info("weights: %s done", name)
    fresh = [r for r in results if r["name"].startswith("Fitted")][0]
    pooled = groups["fresh"].table(*PERIODS["2003_2014"]), groups["fresh"].table(*PERIODS["2015_now"])
    fresh_table = pd.concat(pooled)
    w = fit["weights"]
    pred = fresh_table[FEATURES].to_numpy(float) @ w
    ics = fresh_table.assign(pred=pred).groupby("date").apply(
        lambda g: g["pred"].rank().corr(g["target"].rank()) if len(g) >= 10 else np.nan, include_groups=False).dropna()
    fresh_ic_t = float(ics.mean() / ics.std() * math.sqrt(len(ics)))
    adopt = all(fresh["cells"][f"{g}_{p}"]["edge"] > 0 for g, p in TEST_CELLS) and fresh_ic_t >= 2
    return {"fit": {k: v for k, v in fit.items() if k != "weights"}, "models": results,
            "fresh_pooled_ic_t": round(fresh_ic_t, 2), "adopt": adopt}


# --------------------------------------------------------------------------
# Experiment 2: indicator combinations
# --------------------------------------------------------------------------

def base_signals(lab_report: dict) -> dict[str, tuple[str, dict]]:
    out = {}
    for f in lab_report["families"]:
        for which, params in (("tested-best", f["best_params"]), ("default", f["default_params"])):
            label = T.describe(f["key"], params)
            if label not in out:
                out[label] = (f["key"], params)
    return out


def experiment_combinations(groups: dict[str, Group], lab_report: dict) -> dict:
    signals = base_signals(lab_report)
    names = list(signals)
    held = {g: {n: T.positions(k, p, grp.close) for n, (k, p) in signals.items()} for g, grp in groups.items()}
    combos = [(n,) for n in names]
    combos += [("AND", a, b) for a, b in itertools.combinations(names, 2)]
    combos += [("OR", a, b) for a, b in itertools.combinations(names, 2)]
    combos += [("2 of 3", a, b, c) for a, b, c in itertools.combinations(names, 3)]

    def build(combo, g):
        h = held[g]
        if len(combo) == 1:
            return h[combo[0]]
        op, *parts = combo
        if op == "AND":
            return h[parts[0]] & h[parts[1]]
        if op == "OR":
            return h[parts[0]] | h[parts[1]]
        votes = h[parts[0]].astype(int) + h[parts[1]].astype(int) + h[parts[2]].astype(int)
        return votes >= 2

    def label(combo):
        if len(combo) == 1:
            return combo[0]
        op, *parts = combo
        return f"{op}: " + " + ".join(parts)

    log.info("combinations: %d to score on training data", len(combos))
    tg, tp = TRAIN_CELL
    rows = []
    for i, combo in enumerate(combos):
        res = groups[tg].evaluate_held(build(combo, tg), *PERIODS[tp], keep_returns=True)
        active = res.pop("_active")
        rows.append({"combo": combo, "label": label(combo), "train": res,
                     "train_edge": (res.get("sharpe") or 0) - (res["hold"].get("sharpe") or 0),
                     "daily_active_sharpe": float(active.mean() / active.std()) if active.std() > 0 else 0.0,
                     "_active": active})
        if i % 100 == 0:
            log.info("  %d/%d", i, len(combos))
    best = max(rows, key=lambda r: r["train_edge"])
    dsr = deflated_sharpe(best["_active"], [r["daily_active_sharpe"] for r in rows])

    # Validation for every combination (for the ranking check) and the test for the best.
    log.info("validating all combinations")
    for r in rows:
        vals = [groups[g].evaluate_held(build(r["combo"], g), *PERIODS[p]) for g, p in VALIDATION_CELLS]
        r["validation"] = {f"{g}_{p}": v for (g, p), v in zip(VALIDATION_CELLS, vals)}
        r["val_edge"] = float(np.mean([(v.get("sharpe") or 0) - (v["hold"].get("sharpe") or 0) for v in vals]))
    test = {f"{g}_{p}": groups[g].evaluate_held(build(best["combo"], g), *PERIODS[p]) for g, p in TEST_CELLS}
    test_edges = [(v.get("sharpe") or 0) - (v["hold"].get("sharpe") or 0) for v in test.values()]
    rank_corr = float(pd.Series([r["train_edge"] for r in rows]).rank().corr(pd.Series([r["val_edge"] for r in rows]).rank()))
    top_train = sorted(rows, key=lambda r: -r["train_edge"])[:15]
    best_val = max(rows, key=lambda r: r["val_edge"])
    by_type = {}
    for kind in ("single", "AND", "OR", "2 of 3"):
        sub = [r for r in rows if (len(r["combo"]) == 1 if kind == "single" else r["combo"][0] == kind)]
        by_type[kind] = {"count": len(sub),
                         "median_train_edge": round(float(np.median([r["train_edge"] for r in sub])), 3),
                         "median_val_edge": round(float(np.median([r["val_edge"] for r in sub])), 3),
                         "share_beating_hold_in_validation": round(float(np.mean([r["val_edge"] > 0 for r in sub])) * 100, 1)}
    adopt = all(e > 0 for e in test_edges) and dsr["probability_real"] >= 0.95

    def slim(r):
        return {"label": r["label"], "train_edge": round(r["train_edge"], 3), "val_edge": round(r["val_edge"], 3),
                "train": {k: r["train"].get(k) for k in ("cagr_pct", "max_drawdown_pct", "sharpe", "time_in_market_pct")},
                "train_hold": {k: r["train"]["hold"].get(k) for k in ("cagr_pct", "max_drawdown_pct", "sharpe")}}

    return {
        "signals": [{"label": n, "tactic": k, "params": p} for n, (k, p) in signals.items()],
        "combinations": len(rows),
        "best": {**slim(best), "validation": best["validation"], "test": test,
                 "test_edge": round(float(np.mean(test_edges)), 3), "deflated_sharpe": dsr},
        "top_training": [slim(r) for r in top_train],
        "best_in_validation_hindsight": slim(best_val),
        "share_beating_hold_in_validation": round(float(np.mean([r["val_edge"] > 0 for r in rows])) * 100, 1),
        "rank_corr_train_vs_validation": round(rank_corr, 2),
        "by_type": by_type,
        "adopt": adopt,
    }


# --------------------------------------------------------------------------

def run() -> dict:
    sets = {"train": universe.TRAIN, "holdout": universe.HOLDOUT, "fresh": FRESH_TEST}
    every = [s for g in sets.values() for s in g]
    prices = data.load_prices(every + [universe.BENCHMARK])
    earnings = data.load_earnings([s for s in every if s in prices])
    tbill = data.load_tbill()
    spy = prices[universe.BENCHMARK]
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)
    lab_report = json.loads((Path(__file__).resolve().parent / "latest_lab.json").read_text())

    log.info("Experiment 1: fitting the score's weights")
    feature_groups = {g: FeatureGroup(score_universe([s for s in syms if s in prices], prices, earnings), spy, cash)
                      for g, syms in sets.items()}
    weights = experiment_weights(feature_groups)

    log.info("Experiment 2: indicator combinations")
    lab_groups = {g: Group({s: prices[s] for s in syms if s in prices}, spy.index, cash) for g, syms in sets.items()}
    combos = experiment_combinations(lab_groups, lab_report)

    report = {"design": __doc__, "groups": {g: len(v.close.columns) for g, v in lab_groups.items()},
              "validation_cells": [f"{g}_{p}" for g, p in VALIDATION_CELLS],
              "test_cells": [f"{g}_{p}" for g, p in TEST_CELLS],
              "weights": weights, "combinations": combos}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "experiments.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(json.loads(text)))
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()


def write_markdown(r: dict) -> str:
    w, c = r["weights"], r["combinations"]
    cells = ["train_2003_2014"] + r["validation_cells"] + r["test_cells"]
    names = {"train_2003_2014": "Training", "holdout_2003_2014": "Held-out 03–14", "train_2015_now": "Training stocks 15–26",
             "holdout_2015_now": "Held-out 15–26", "fresh_2003_2014": "Fresh 03–14", "fresh_2015_now": "Fresh 15–26"}
    out = ["# Experiments: fitted score weights and indicator combinations", "",
           "Generated by `python -m stockanalysis.validation.experiments`. Rules for changing the app were fixed before "
           "running: adopt only if it beats holding on the fresh stocks in both periods and the result is "
           "statistically significant.", "",
           "## 1. Fitting the score's weights", "",
           f"A ridge regression learned the weights from {w['fit']['samples']:,} stock-months of training data "
           f"(penalty {w['fit']['alpha']:g}, chosen by leave-one-year-out cross-validation). Weights are scaled so "
           "their sizes add up to 100, like the app's.", "",
           "| Model | " + " | ".join(FEATURE_LABELS[k] for k in FEATURES) + " |", "| --- " * (len(FEATURES) + 1) + "|"]
    for m in w["models"][:3]:
        out.append(f"| {m['name']} | " + " | ".join(f"{m['weights'][k]:+.0f}" for k in FEATURES) + " |")
    out += ["", "**Ranking skill** (average monthly rank correlation between score and next-month return vs the "
            "S&P 500; t-statistic in brackets, above 2 is significant):", "",
            "| Model | " + " | ".join(names[k] for k in cells) + " |", "| --- " * (len(cells) + 1) + "|"]
    for m in w["models"]:
        out.append(f"| {m['name']} | " + " | ".join(
            f"{m['cells'][k]['ic_mean']:+.3f} ({m['cells'][k]['ic_t']:+.1f})" for k in cells) + " |")
    out += ["", f"**Top-{TOP_N} portfolio** (Sharpe ratio above T-bills minus that of holding all the same stocks, "
            "rebalanced monthly with costs):", "",
            "| Model | " + " | ".join(names[k] for k in cells) + " |", "| --- " * (len(cells) + 1) + "|"]
    for m in w["models"]:
        out.append(f"| {m['name']} | " + " | ".join(f"{m['cells'][k]['edge']:+.2f}" for k in cells) + " |")
    fitted = next(m for m in w["models"] if m["name"].startswith("Fitted"))
    out += ["", "Yearly return / worst drop on the fresh stocks, fitted weights vs holding all of them:", ""]
    for k in r["test_cells"]:
        x = fitted["cells"][k]
        out.append(f"- {names[k]}: {x['top']['cagr_pct']:+.1f}% / {x['top']['max_drawdown_pct']:.1f}% vs "
                   f"{x['hold']['cagr_pct']:+.1f}% / {x['hold']['max_drawdown_pct']:.1f}%")
    out += ["", f"Fresh-stock ranking skill, both periods pooled: t = {w['fresh_pooled_ic_t']:+.2f}. "
            f"**Adopted in the app: {'yes' if w['adopt'] else 'no'}.**", "",
            "## 2. Indicator combinations", "",
            f"{len(c['signals'])} indicator signals combined into {c['combinations']:,} rules (single, both agree, "
            "either, two of three). Each trades one shared pot of money across the stocks it holds (max 10% each), "
            "the rest in T-bills.", "",
            "| Rule type | Count | Median training edge | Median unseen-data edge | Share beating holding on unseen data |",
            "| --- | --- | --- | --- | --- |"]
    for kind, x in c["by_type"].items():
        out.append(f"| {kind} | {x['count']} | {x['median_train_edge']:+.3f} | {x['median_val_edge']:+.3f} | "
                   f"{x['share_beating_hold_in_validation']}% |")
    b = c["best"]
    d = b["deflated_sharpe"]
    out += ["", f"**Best on training data:** {b['label']}. Training edge {b['train_edge']:+.2f}, unseen data "
            f"{b['val_edge']:+.2f}, fresh stocks {b['test_edge']:+.2f}.", "",
            f"**Is the training winner real or luck?** Its training Sharpe over holding was {d['sharpe_annual']:.2f} a "
            f"year. Picking the best of {d['trials']:,} tries would produce about {d['luck_threshold_annual']:.2f} "
            f"by luck alone. Deflated Sharpe ratio: {d['probability_real']:.0%} probability the edge is real "
            f"(it would look {d['probability_real_if_one_trial']:.0%} certain if it had been the only rule tried).", "",
            f"Across all combinations, training rank vs unseen-data rank correlation: {c['rank_corr_train_vs_validation']:+.2f}. "
            f"{c['share_beating_hold_in_validation']}% of combinations beat holding on unseen data.", "",
            f"**Adopted in the app: {'yes' if c['adopt'] else 'no'}.**", "",
            "## Caveats", "",
            "- Large, still-listed US stocks only. Insider and news signals have no history and are not included.",
            "- The combinations' trials are correlated, so the luck correction treats them as more independent "
            "tries than they really are, which makes it stricter.", ""]
    return "\n".join(out)
