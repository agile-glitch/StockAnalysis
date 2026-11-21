"""Maximum profit: which approach made the most money, and at what risk?

    python -m stockanalysis.validation.profit

Earlier tests found that timing individual stocks earned less than holding.
This test looks at the approaches with the best published record for
*more* return than holding an index:

* Holding the S&P 500 or the Nasdaq-100 (the baseline to beat).
* Leveraged index funds (2x, 3x daily, like SSO/UPRO/QLD/TQQQ). Held all
  the time they can be wiped out in crashes (-95% or worse).
* Leverage with a trend switch (Gayed & Bilello 2016, "Leverage for the long
  run"): hold the leveraged fund while the index is in an uptrend, T-bills
  otherwise. Three standard switches, none tuned here:
    - 200-day: index above its 200-day average (checked daily);
    - app switch: above its 200-day average OR 12-month return beating T-bills;
    - 10-month: Faber's monthly rule with the app's 2% band.
* Dual momentum (Antonacci 2014): each month hold the stronger of US and
  foreign stocks if US stocks beat T-bills over 12 months, else bonds.

Leveraged funds before they existed are simulated from the index: L x the
daily return, minus (L-1) x (T-bill + 0.4%) financing and 0.95% a year in fees.
The simulation is checked against the real funds where both exist.

The long tests use index prices without dividends (S&P 500 from 1961, Nasdaq-
100 from 1986) for both the strategies and holding, so the comparison is fair
but every return is about 2 points a year too low. The fund-era tests use
total returns.

Signals at the close, trades at the next close (a day later than the other
tests: leveraged funds have no simulated opening prices), 0.1% per switch.

The choice is made by a rule fixed before the results: the highest yearly
return over the long S&P 500 history whose worst drop is no deeper than simply
holding the index. It is then checked in each half of history, in the fund
era, and on the Nasdaq-100.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .markets import faber_positions
from .portfolio import _daily_cash_rate, curve_metrics

log = logging.getLogger("stockanalysis.validation")
REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_profit.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "PROFIT.md"

COST = 0.001
EXPENSE = 0.0095
SPREAD = 0.004
REAL_FUNDS = {("SPY", 2): "SSO", ("SPY", 3): "UPRO", ("QQQ", 2): "QLD", ("QQQ", 3): "TQQQ"}
SIGNALS = {"200d": "200-day average", "switch": "App market switch", "10m": "10-month rule, 2% band"}


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def leveraged(r: pd.Series, lev: float, cash: pd.Series) -> pd.Series:
    """Daily return of an L-times daily leveraged fund, with financing and fees."""
    if lev == 1:
        return r
    c = cash.reindex(r.index).fillna(0.0)
    return lev * r - (lev - 1) * (c + SPREAD / 252) - EXPENSE / 252


def signal(close: pd.Series, kind: str, tbill: pd.Series) -> pd.Series:
    """True = in the market after that day's close."""
    sma = close.rolling(200, min_periods=200).mean()
    if kind == "200d":
        return (close > sma) & sma.notna()
    if kind == "switch":
        tb12 = tbill.reindex(close.index, method="ffill").rolling(252, min_periods=20).mean() / 100.0
        mom = close / close.shift(252) - 1
        return ((close > sma) | (mom > tb12)) & sma.notna() & mom.notna()
    if kind == "10m":
        return faber_positions(close.to_frame("c"), 0.02)["c"]
    raise KeyError(kind)


def timed(r_in: pd.Series, held: pd.Series, cash: pd.Series) -> pd.Series:
    """In the fund while `held` (decided at a close, traded at the next close), else T-bills."""
    pos = held.reindex(r_in.index).fillna(False).astype(float).shift(2).fillna(0.0)   # traded a day later
    c = cash.reindex(r_in.index).fillna(0.0)
    switch = pos.diff().abs().fillna(0.0)
    return pos * r_in + (1 - pos) * c - COST * switch


def dual_momentum(prices: dict, cash: pd.Series, tbill: pd.Series) -> pd.Series:
    """Antonacci's global equity momentum, monthly, with IEF then AGG as the bond leg."""
    us, intl = prices["SPY"]["close"], prices["EFA"]["close"]
    bond = prices["AGG"]["close"].reindex(us.index)
    ief = prices["IEF"]["close"].reindex(us.index)
    bond_r = bond.pct_change().where(bond.notna() & bond.shift(1).notna(), ief.pct_change())
    idx = us.index[us.index >= intl.index[0] + pd.Timedelta(days=370)]
    idx = idx[idx >= ief.dropna().index[0] + pd.Timedelta(days=10)]
    us, intl = us.reindex(idx), intl.reindex(idx).ffill()
    rets = pd.DataFrame({"us": us.pct_change(), "intl": intl.pct_change(), "bond": bond_r.reindex(idx)}).fillna(0.0)
    m12 = pd.DataFrame({"us": us / us.shift(252) - 1, "intl": intl / intl.shift(252) - 1})
    tb12 = tbill.reindex(idx, method="ffill").rolling(252, min_periods=20).mean() / 100.0
    month = pd.Series(idx.to_period("M"), index=idx)
    ends = month.ne(month.shift(-1))
    ends.iloc[-1] = False
    choice = pd.Series(np.where(m12["us"] > tb12, np.where(m12["us"] >= m12["intl"], "us", "intl"), "bond"), index=idx)
    choice = choice.where(ends & m12["us"].notna()).ffill().fillna("bond")
    held = choice.shift(2).fillna("bond")              # traded at the next close
    r = pd.Series(np.choose(held.map({"us": 0, "intl": 1, "bond": 2}).to_numpy(),
                            [rets["us"].to_numpy(), rets["intl"].to_numpy(), rets["bond"].to_numpy()]), index=idx)
    switches = held.ne(held.shift(1)).astype(float)
    switches.iloc[0] = 0.0
    return (r - 2 * COST * switches).iloc[260:]       # a switch sells one fund and buys another


def describe(r: pd.Series, cash: pd.Series, held: pd.Series | None = None) -> dict:
    curve = (1 + r).cumprod()
    m = curve_metrics(curve, cash)
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    under = curve / curve.cummax() < 1
    runs = under.groupby((~under).cumsum()).sum()
    m.update({
        "worst_year_pct": round(float(yearly.min()) * 100, 1),
        "worst_year": int(yearly.idxmin()),
        "best_year_pct": round(float(yearly.max()) * 100, 1),
        "longest_underwater_years": round(float(runs.max()) / 252, 1),
        "growth_of_10k": round(float(curve.iloc[-1]) * 10_000, 0),
    })
    if held is not None:
        h = held.reindex(r.index).fillna(False).astype(bool)
        m["time_in_market_pct"] = round(float(h.mean()) * 100, 1)
        m["switches_per_year"] = round(float(h.ne(h.shift(1)).sum()) / max(len(h) / 252, 1e-9), 1)
    roll = np.log1p(r).rolling(2520).sum().dropna()
    if len(roll):
        m["worst_10y_cagr_pct"] = round(float(np.expm1(roll.min() / 10)) * 100, 1)
        m["median_10y_cagr_pct"] = round(float(np.expm1(roll.median() / 10)) * 100, 1)
    return m


def strategy_set(close: pd.Series, r_index: pd.Series, cash: pd.Series, tbill: pd.Series) -> dict[str, tuple[pd.Series, pd.Series | None]]:
    out = {}
    for lev in (1, 2, 3):
        r_lev = leveraged(r_index, lev, cash)
        out[f"hold_{lev}x"] = (r_lev, None)
        for kind in SIGNALS:
            held = signal(close, kind, tbill)
            out[f"{kind}_{lev}x"] = (timed(r_lev, held, cash), held)
    return out


def label(key: str) -> str:
    kind, lev = key.rsplit("_", 1)
    lev_txt = {"1x": "", "2x": "2x ", "3x": "3x "}[lev]
    if kind == "hold":
        return f"Hold {lev_txt}index" if lev_txt else "Hold the index"
    return f"{lev_txt or '1x '}index, {SIGNALS[kind]}"


def evaluate(name: str, close: pd.Series, r_index: pd.Series, cash: pd.Series, tbill: pd.Series,
             start: str, end: str | None = None) -> dict:
    strategies = strategy_set(close, r_index, cash, tbill)
    rows = {}
    for key, (r, held) in strategies.items():
        r = r.loc[start:end]
        rows[key] = {"label": label(key), **describe(r, cash, held.loc[start:end] if held is not None else None)}
    return {"name": name, "start": start, "end": end or close.index[-1].date().isoformat(), "rows": rows}


def calibration(prices: dict, cash: pd.Series) -> list[dict]:
    out = []
    for (base, lev), fund in REAL_FUNDS.items():
        real = prices[fund]["close"].pct_change().dropna()
        idx = real.index[1:]
        synth = leveraged(prices[base]["close"].pct_change().reindex(idx), lev, cash)
        a = curve_metrics((1 + real.reindex(idx)).cumprod(), cash)
        b = curve_metrics((1 + synth).cumprod(), cash)
        out.append({"fund": fund, "base": base, "leverage": lev, "start": idx[0].date().isoformat(),
                    "real_cagr_pct": a["cagr_pct"], "simulated_cagr_pct": b["cagr_pct"],
                    "real_max_drawdown_pct": a["max_drawdown_pct"], "simulated_max_drawdown_pct": b["max_drawdown_pct"],
                    "daily_correlation": round(float(real.reindex(idx).corr(synth)), 4)})
    return out


def pick(test: dict) -> str:
    """Highest yearly return whose worst drop is no deeper than holding the index."""
    rows = test["rows"]
    floor = rows["hold_1x"]["max_drawdown_pct"]
    ok = [k for k, v in rows.items() if v["max_drawdown_pct"] >= floor]
    return max(ok, key=lambda k: rows[k]["cagr_pct"])


def run() -> dict:
    prices = data.load_prices(["SPY", "QQQ", "^GSPC", "^NDX", "EFA", "IEF", "AGG", "SSO", "UPRO", "QLD", "TQQQ"])
    tbill = data.load_tbill()
    tests = {}
    for key, sym, start, name in (("sp_long", "^GSPC", "1961-06-01", "S&P 500 index, 1961–today (no dividends)"),
                                  ("ndx_long", "^NDX", "1987-01-01", "Nasdaq-100 index, 1987–today (no dividends)"),
                                  ("spy", "SPY", "1994-03-01", "S&P 500 fund (SPY), 1994–today (with dividends)"),
                                  ("qqq", "QQQ", "2000-03-15", "Nasdaq-100 fund (QQQ), 2000–today (with dividends)")):
        close = prices[sym]["close"].dropna()
        cash = pd.Series(_daily_cash_rate(close.index, tbill), index=close.index)
        r = close.pct_change().fillna(0.0)
        log.info("profit: %s", name)
        tests[key] = evaluate(name, close, r, cash, tbill, start)
        if key == "sp_long":
            mid = "1993-12-31"
            tests["sp_first"] = evaluate("S&P 500 index, 1961–1993", close, r, cash, tbill, start, mid)
            tests["sp_second"] = evaluate("S&P 500 index, 1994–today", close, r, cash, tbill, "1994-01-01")
    spy_cash = pd.Series(_daily_cash_rate(prices["SPY"].index, tbill), index=prices["SPY"].index)
    dm = dual_momentum(prices, spy_cash, tbill)
    tests["dual_momentum"] = {"name": f"Dual momentum (US / foreign stocks / bonds), {dm.index[0].year}–today",
                              "rows": {"dual_momentum": {"label": "Dual momentum", **describe(dm, spy_cash)},
                                       "hold_1x": {"label": "Hold the S&P 500 (same years)",
                                                   **describe(prices["SPY"]["close"].pct_change().loc[dm.index[0]:], spy_cash)}}}
    chosen = pick(tests["sp_long"])
    checks = {k: {"chosen": tests[k]["rows"][chosen], "hold": tests[k]["rows"]["hold_1x"],
                  "beats_hold": tests[k]["rows"][chosen]["cagr_pct"] > tests[k]["rows"]["hold_1x"]["cagr_pct"],
                  "drop_no_deeper": tests[k]["rows"][chosen]["max_drawdown_pct"] >= tests[k]["rows"]["hold_1x"]["max_drawdown_pct"]}
              for k in ("sp_first", "sp_second", "spy", "ndx_long", "qqq")}
    report = {"design": __doc__, "tests": tests, "calibration": calibration(prices, spy_cash),
              "chosen": chosen, "chosen_label": label(chosen), "checks": checks,
              "generated": pd.Timestamp.now().isoformat(timespec="seconds")}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "profit.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(json.loads(text)))
    return report


def write_markdown(r: dict) -> str:
    def p(x, d=1):
        return "—" if x is None else f"{x:+.{d}f}%"

    out = ["# Maximum profit", "", "Generated by `python -m stockanalysis.validation.profit`. See the module "
           "docstring for the method.", ""]
    for key, t in r["tests"].items():
        out += [f"## {t['name']}", "",
                "| Strategy | Yearly return | Worst drop | Worst year | Worst 10 years (per year) | $10k becomes | Sharpe | In market |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for k, v in sorted(t["rows"].items(), key=lambda kv: -kv[1]["cagr_pct"]):
            mark = " **(chosen)**" if k == r["chosen"] else ""
            out.append(f"| {v['label']}{mark} | {p(v['cagr_pct'])} | {v['max_drawdown_pct']:.0f}% | "
                       f"{p(v['worst_year_pct'], 0)} ({v['worst_year']}) | {p(v.get('worst_10y_cagr_pct'))} | "
                       f"${v['growth_of_10k']:,.0f} | {v['sharpe']:.2f} | {v.get('time_in_market_pct', 100)}% |")
        out.append("")
    out += ["## Simulated vs real leveraged funds", "",
            "| Fund | Since | Real yearly / worst drop | Simulated yearly / worst drop | Daily correlation |", "| --- | --- | --- | --- | --- |"]
    for c in r["calibration"]:
        out.append(f"| {c['fund']} ({c['leverage']}x {c['base']}) | {c['start'][:4]} | {p(c['real_cagr_pct'])} / "
                   f"{c['real_max_drawdown_pct']:.0f}% | {p(c['simulated_cagr_pct'])} / {c['simulated_max_drawdown_pct']:.0f}% | "
                   f"{c['daily_correlation']} |")
    out += ["", f"## The pick: {r['chosen_label']}", "",
            "Chosen on the S&P 500 1961–today as the highest yearly return with a worst drop no deeper than holding. Checks:", "",
            "| Test | Chosen: yearly / worst drop | Holding: yearly / worst drop | More return | Drop no deeper |", "| --- | --- | --- | --- | --- |"]
    for k, c in r["checks"].items():
        out.append(f"| {r['tests'][k]['name']} | {p(c['chosen']['cagr_pct'])} / {c['chosen']['max_drawdown_pct']:.0f}% | "
                   f"{p(c['hold']['cagr_pct'])} / {c['hold']['max_drawdown_pct']:.0f}% | {'✓' if c['beats_hold'] else '✗'} | "
                   f"{'✓' if c['drop_no_deeper'] else '✗'} |")
    out += ["", "## Caveats", "",
            "- Leveraged funds reset daily; in choppy markets they lose value even when the index ends flat.",
            "- A one-day crash like October 1987 (−20%) is a −40% or −60% day for 2x / 3x funds, before any switch can act.",
            "- Simulated fees and financing are estimates; the check against real funds is shown above.",
            "- Taxes: every switch to cash realizes gains. In a taxable account, returns are lower.",
            "- Past results do not guarantee future ones.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()
