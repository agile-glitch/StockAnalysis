"""Round 3: walk-forward test of market-timing rules.

Rounds 1 and 2 showed that the app's per-stock signals do not pick winners,
and that the gain comes from deciding when to own stocks at all. The plain
200-day filter protected well in slow bear markets (2008) but was whipsawed
by fast V-shaped recoveries (2018-19, 2020, 2023).

This round tests research-backed fixes for that, without reusing the final
exam for tuning:

* Every candidate is run over the whole history once.
* For each year Y, the candidate with the best Sharpe ratio over all years
  before Y is picked, using only the stocks already seen in rounds 1-2 and
  the S&P 500 itself back to 1995.
* That pick is then applied to year Y on the final-exam stocks. Stitching
  those years together gives the result of following the process in real
  time: every year's choice was made without seeing that year.

Caveat, stated plainly: the candidate list was written after seeing the
round 2 final exam, so the menu itself is informed by it. The year-by-year
choices are not.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .portfolio import MonthlyRules, Panel, curve_metrics, simulate_monthly, yearly_returns

START = "1996-01-01"
FIRST_TEST_YEAR = 2006   # at least ~10 years of history behind the first choice

CANDIDATES = [
    MonthlyRules(name="Buy and hold", select="all", max_weight=1.0, market_filter=False,
                 notes="Always fully invested in the basket (the benchmark)."),
    MonthlyRules(name="200-day filter", select="all", max_weight=1.0, market_filter=True, regime="sma200",
                 notes="T-bills while the S&P 500 is below its 200-day average (round 2's rule)."),
    MonthlyRules(name="12-month momentum filter", select="all", max_weight=1.0, market_filter=True, regime="abs_mom",
                 notes="T-bills while the S&P 500's 12-month return is below T-bills (Antonacci)."),
    MonthlyRules(name="Both filters must agree", select="all", max_weight=1.0, market_filter=True, regime="dual",
                 notes="T-bills only when the S&P 500 is below its 200-day average AND its 12-month return lags T-bills."),
    MonthlyRules(name="200-day filter with 3% band", select="all", max_weight=1.0, market_filter=True, regime="band",
                 notes="Leave only below 97% of the 200-day average; return above it."),
    MonthlyRules(name="Half out on 200-day break", select="all", max_weight=1.0, market_filter=True, regime="sma200",
                 risk_off_exposure=0.5, notes="Cut to 50% stocks instead of 0% when below the 200-day average."),
    MonthlyRules(name="Half out when both agree", select="all", max_weight=1.0, market_filter=True, regime="dual",
                 risk_off_exposure=0.5),
    MonthlyRules(name="Volatility target 15%", select="all", max_weight=1.0, vol_target=0.15,
                 notes="Hold less when the market is turbulent: exposure = 15% / recent S&P 500 volatility (max 100%)."),
    MonthlyRules(name="Volatility target 15% + both filters", select="all", max_weight=1.0, vol_target=0.15,
                 market_filter=True, regime="dual"),
    MonthlyRules(name="Volatility target 15% + 200-day filter", select="all", max_weight=1.0, vol_target=0.15,
                 market_filter=True, regime="sma200"),
]


def _daily_returns(p: Panel, rules: MonthlyRules) -> pd.Series:
    curve = simulate_monthly(p, rules, START)["curve"]
    return curve.pct_change().fillna(0.0)


def _sharpe(r: pd.Series, cash: pd.Series | None = None) -> float:
    r = r.dropna()
    if cash is not None:
        r = r - cash.reindex(r.index).fillna(0.0)
    return float(r.mean() / r.std() * math.sqrt(252)) if len(r) > 20 and r.std() > 0 else -9.0


def walk_forward(dev_panels: dict[str, Panel], test_panels: dict[str, Panel]) -> dict:
    cash = next(iter(dev_panels.values())).cash_series()
    dev = {name: {c.name: _daily_returns(p, c) for c in CANDIDATES} for name, p in dev_panels.items()}
    test = {name: {c.name: _daily_returns(p, c) for c in CANDIDATES} for name, p in test_panels.items()}
    last_year = max(s.index.max().year for d in test.values() for s in d.values())

    picks = {}
    for year in range(FIRST_TEST_YEAR, last_year + 1):
        cutoff = pd.Timestamp(f"{year}-01-01")
        scores = {}
        for c in CANDIDATES:
            values = [_sharpe(d[c.name][d[c.name].index < cutoff], cash) for d in dev.values()]
            scores[c.name] = float(np.mean(values))
        picks[str(year)] = max(scores, key=scores.get)

    out = {"picks": picks, "panels": {}}
    for name, series in test.items():
        stitched = []
        for year, pick in picks.items():
            r = series[pick]
            stitched.append(r[r.index.year == int(year)])
        wf = pd.concat(stitched)
        hold = series["Buy and hold"]
        hold = hold[hold.index >= wf.index.min()]
        wf_curve, hold_curve = (1 + wf).cumprod(), (1 + hold).cumprod()
        weekly = pd.DataFrame({"walk_forward": wf_curve, "buy_and_hold": hold_curve}).resample("W-FRI").last().dropna()
        out["panels"][name] = {
            "walk_forward": curve_metrics(wf_curve, cash),
            "buy_and_hold": curve_metrics(hold_curve, cash),
            "yearly": {"walk_forward": yearly_returns(wf_curve), "buy_and_hold": yearly_returns(hold_curve)},
            "curve": {"dates": [d.date().isoformat() for d in weekly.index],
                      "walk_forward": [round(v * 100, 2) for v in weekly["walk_forward"]],
                      "buy_and_hold": [round(v * 100, 2) for v in weekly["buy_and_hold"]]},
        }
    # Full-period statistics per candidate (in-sample for the dev panels; shown for context).
    out["candidates"] = []
    for c in CANDIDATES:
        row = {"name": c.name, "notes": c.notes, "rules": c.describe(), "panels": {}}
        for name, d in {**dev, **test}.items():
            r = d[c.name]
            r = r[r.index >= pd.Timestamp(f"{FIRST_TEST_YEAR}-01-01")]
            row["panels"][name] = curve_metrics((1 + r).cumprod(), cash)
        out["candidates"].append(row)
    return out
