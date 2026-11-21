"""Recent market test: how has each method done lately?

    python -m stockanalysis.validation.recent

Part A - every method the app recommends, over the last 12 months, since the
start of 2024, and 2026 so far, against simply holding the S&P 500. The
leveraged Profit plans use the real funds (SSO, UPRO), not simulations.

Part B - copying insider purchases over the last two years, using Yahoo's
insider-trade lists (about two years per company, no SEC contact needed) for
the app's 364-stock test list. Yahoo gives the trade date, not the filing
date; insiders must file within two business days, so the copy buys at the
open three trading days after the trade (a little later than a live alert
would). Returns are measured against the S&P 500 over the same days.

Short periods say little about the long run: one good or bad year can come
from luck. This is a check that nothing has broken lately, not a new test of
the rules.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .. import tactics as T
from . import data, universe
from .entries import prepare, stock_trades
from .experiments import FRESH_TEST
from .lab import INDICATOR_TEST
from .markets import COST, faber_positions
from .portfolio import _daily_cash_rate, curve_metrics

log = logging.getLogger("stockanalysis.validation")
ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_recent.json"
DOC = ROOT / "docs" / "RECENT.md"
INSIDER_CACHE = ROOT / "data" / "insider_recent.csv"
TREND_LIST = ["USO", "UNG", "DBC", "DBA", "FXE", "QQQ", "ETH-USD"]
OFFICER = re.compile(r"\b(?:CEO|CFO|COO|CHIEF|PRESIDENT)\b", re.I)


def windows(end: pd.Timestamp) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    return {"12m": (end - pd.DateOffset(years=1), end),
            "since_2024": (pd.Timestamp("2024-01-01"), end),
            "ytd": (pd.Timestamp(f"{end.year}-01-01"), end)}


def window_stats(r: pd.Series, cash: pd.Series, a, b) -> dict:
    x = r.loc[a:b].dropna()
    if len(x) < 5:
        return {}
    curve = (1 + x).cumprod()
    m = curve_metrics(curve, cash)
    return {"return_pct": round(float(curve.iloc[-1] - 1) * 100, 1), "max_drawdown_pct": m.get("max_drawdown_pct"),
            "sharpe": m.get("sharpe")}


# --------------------------------------------------------------------------
# Part A
# --------------------------------------------------------------------------

def method_returns(prices: dict, tbill: pd.Series) -> dict[str, tuple[str, pd.Series]]:
    from .profit import signal, timed
    spy = prices["SPY"]
    idx = spy.index
    cash = pd.Series(_daily_cash_rate(idx, tbill), index=idx)
    spy_r = spy["close"].pct_change()
    out = {"hold_spy": ("Hold the S&P 500 (SPY)", spy_r)}
    for key, label, fund, kind in (("steady", "Profit plan: Steady (SPY + market switch)", "SPY", "switch"),
                                   ("growth", "Profit plan: Growth (SSO + 200-day switch)", "SSO", "200d"),
                                   ("aggressive", "Profit plan: Aggressive (UPRO + market switch)", "UPRO", "switch")):
        r = prices[fund]["close"].pct_change().reindex(idx)
        out[key] = (label, timed(r, signal(spy["close"], kind, tbill), cash))
    for fund in ("SSO", "UPRO"):
        out[f"hold_{fund.lower()}"] = (f"Hold {fund} all the time (no switch)", prices[fund]["close"].pct_change().reindex(idx))

    def banded_basket(syms):
        rs = {}
        for s in syms:
            if s not in prices:
                continue
            df = prices[s]
            c = pd.Series(_daily_cash_rate(df.index, tbill), index=df.index)
            rs[s] = T.backtest(df[["open"]], df[["close"]], faber_positions(df[["close"]], 0.02), c, COST)["close"]
        return pd.DataFrame(rs).reindex(idx).mean(axis=1, skipna=True)

    out["trend_portfolio"] = ("Trend portfolio (8 assets, 2% band)",
                              banded_basket(["SPY", "EFA", "EEM", "VNQ", "IEF", "TIP", "DBC", "GLD"]))
    out["trend_alerts"] = ("Market trend alerts (default list, 2% band)", banded_basket(TREND_LIST))
    return out


def part_a(prices: dict, tbill: pd.Series, stock_prices: dict) -> dict:
    spy = prices["SPY"]
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)
    end = spy.index[-1]
    wins = windows(end)
    rows = {}
    for key, (label, r) in method_returns(prices, tbill).items():
        rows[key] = {"label": label, **{w: window_stats(r, cash, a, b) for w, (a, b) in wins.items()}}
    # Stock Buy/Sell signals: the app's Buy rule on the stocks never used for tuning, one pot.
    test = [s for s in dict.fromkeys(universe.HOLDOUT + universe.FINAL_EXAM + INDICATOR_TEST + FRESH_TEST)
            if s in stock_prices and s not in universe.TRAIN]
    close = spy["close"]
    tb12 = tbill.reindex(close.index, method="ffill").rolling(252, min_periods=20).mean() / 100.0
    spy_on = (close > close.rolling(200).mean()) | (close / close.shift(252) - 1 > tb12)
    prep = prepare(test, {**stock_prices, "SPY": spy}, {}, spy_on)
    row = {"label": f"Stock Buy signals ({len(test)} stocks never used for tuning)"}
    for w, (a, b) in wins.items():
        st = stock_trades(prep, stock_prices, cash, a, b)
        row[w] = {"return_pct": None, "trades": st.get("trades"), "losing_pct": st.get("losing_pct"),
                  "cagr_pct": st.get("basket_cagr_pct"), "max_drawdown_pct": st.get("basket_max_drawdown_pct"),
                  "sharpe": st.get("basket_sharpe")}
        years = (b - a).days / 365.25
        if st.get("basket_cagr_pct") is not None:
            row[w]["return_pct"] = round(((1 + st["basket_cagr_pct"] / 100) ** years - 1) * 100, 1)
    rows["stock_signals"] = row
    # Holding the same stocks equally, for the stock signals' fair comparison.
    hold = pd.DataFrame({s: stock_prices[s]["close"].pct_change() for s in test}).reindex(spy.index).mean(axis=1)
    rows["hold_stocks"] = {"label": "Hold those stocks equally", **{w: window_stats(hold, cash, a, b) for w, (a, b) in wins.items()}}
    return {"as_of": end.date().isoformat(), "windows": {w: [a.date().isoformat(), b.date().isoformat()] for w, (a, b) in wins.items()},
            "rows": rows}


# --------------------------------------------------------------------------
# Part B
# --------------------------------------------------------------------------

def fetch_insider_purchases(symbols: list[str], refresh: bool = False) -> pd.DataFrame:
    if INSIDER_CACHE.exists() and not refresh and time.time() - INSIDER_CACHE.stat().st_mtime < 3 * 86400:
        return pd.read_csv(INSIDER_CACHE, parse_dates=["date"])
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    rows = []
    for i, sym in enumerate(symbols):
        try:
            df = yf.Ticker(sym).insider_transactions
        except Exception:
            df = None
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            text = str(r.get("Text") or "")
            if not text.lower().startswith("purchase"):
                continue
            rows.append({"symbol": sym, "date": pd.to_datetime(r.get("Start Date")), "insider": str(r.get("Insider") or ""),
                         "position": str(r.get("Position") or ""), "shares": r.get("Shares"), "value": r.get("Value"),
                         "text": text})
        if i % 50 == 0:
            log.info("insider lists: %d/%d", i, len(symbols))
        time.sleep(0.15)
    out = pd.DataFrame(rows, columns=["symbol", "date", "insider", "position", "shares", "value", "text"])
    INSIDER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(INSIDER_CACHE, index=False)
    return out


def part_b(stock_prices: dict, spy: pd.DataFrame, cash: pd.Series) -> dict:
    symbols = sorted(stock_prices)
    buys = fetch_insider_purchases(symbols)
    if buys.empty:
        return {"purchases": 0}
    buys["value"] = pd.to_numeric(buys["value"], errors="coerce").fillna(0.0)
    buys["officer"] = buys["position"].fillna("").str.contains(OFFICER)
    ev = buys.groupby(["symbol", "date"]).agg(value=("value", "sum"), insiders=("insider", "nunique"),
                                             officer=("officer", "any")).reset_index().sort_values(["symbol", "date"])
    # Cluster: 2+ different insiders buying within 30 days.
    cl = []
    for sym, g in buys.groupby("symbol"):
        for d in ev.loc[ev["symbol"] == sym, "date"]:
            w = g[(g["date"] <= d) & (g["date"] > d - pd.Timedelta(days=30))]
            cl.append(((sym, d), w["insider"].nunique() >= 2))
    ev["cluster"] = ev.set_index(["symbol", "date"]).index.map(dict(cl)).astype(bool)
    rows = []
    sidx = spy.index
    for _, e in ev.iterrows():
        df = stock_prices.get(e["symbol"])
        if df is None:
            continue
        i = df.index.searchsorted(e["date"], side="right") + 2        # filed within 2 business days; buy the next open
        if i >= len(df):
            continue
        entry = float(df["open"].iloc[i])
        si = sidx.searchsorted(df.index[i])
        row = {**e.to_dict(), "entry": df.index[i]}
        for h in (21, 63, 126):
            j, sj = i + h - 1, si + h - 1
            if j < len(df) and sj < len(sidx):
                row[f"ret_{h}"] = df["close"].iloc[j] / entry - 1
                row[f"excess_{h}"] = row[f"ret_{h}"] - (spy["close"].iloc[sj] / spy["open"].iloc[si] - 1)
        rows.append(row)
    evp = pd.DataFrame(rows)
    variants = {"all": ("Every insider purchase", evp.index == evp.index),
                "big": ("$100,000 or more", evp["value"] >= 100_000),
                "officers": ("Bought by a CEO, CFO, president or other chief", evp["officer"]),
                "cluster": ("2+ insiders within 30 days", evp["cluster"])}
    out = {"purchases": int(len(buys)), "events": int(len(evp)), "stocks": int(evp["symbol"].nunique()),
           "first": str(buys["date"].min().date()), "last": str(buys["date"].max().date()), "variants": {}}
    for k, (label, mask) in variants.items():
        sub = evp[mask]
        row = {"label": label, "events": int(len(sub))}
        for h in (21, 63, 126):
            x = sub.get(f"excess_{h}", pd.Series(dtype=float)).dropna()
            if len(x) < 5:
                continue
            t = x.mean() / (x.std() / math.sqrt(len(x))) if x.std() > 0 else None
            row[f"h{h}"] = {"n": int(len(x)), "avg_return_pct": round(float(sub.loc[x.index, f"ret_{h}"].mean()) * 100, 2),
                            "avg_excess_pct": round(float(x.mean()) * 100, 2),
                            "beat_market_pct": round(float((x > 0).mean()) * 100, 1),
                            "t_stat": round(float(t), 2) if t is not None else None}
        out["variants"][k] = row
    out["examples"] = [{"symbol": r["symbol"], "date": str(pd.Timestamp(r["date"]).date()), "value": round(float(r["value"])),
                        "excess_63_pct": round(float(r["excess_63"]) * 100, 1)}
                       for _, r in evp.dropna(subset=["excess_63"]).sort_values("value", ascending=False).head(15).iterrows()]
    return out


def run() -> dict:
    stock_syms = list(dict.fromkeys(universe.TRAIN + universe.HOLDOUT + universe.FINAL_EXAM + INDICATOR_TEST + FRESH_TEST))
    market = ["SPY", "SSO", "UPRO", "EFA", "EEM", "VNQ", "IEF", "TIP", "DBC", "GLD"] + TREND_LIST
    prices = data.load_prices(list(dict.fromkeys(market)))
    stock_prices = {s: df for s, df in data.load_prices(stock_syms).items()}
    tbill = data.load_tbill()
    spy = prices["SPY"]
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)
    report = {"design": __doc__, "methods": part_a(prices, tbill, stock_prices),
              "insiders": part_b(stock_prices, spy, cash), "generated": pd.Timestamp.now().isoformat(timespec="seconds")}
    text = json.dumps(report, separators=(",", ":"), default=str)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "recent.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(json.loads(text)))
    return report


def write_markdown(r: dict) -> str:
    m, ins = r["methods"], r["insiders"]
    w = m["windows"]

    def cell(x):
        if not x or x.get("return_pct") is None:
            return "—"
        return f"{x['return_pct']:+.1f}% (worst {x['max_drawdown_pct']:.0f}%)"

    out = ["# Recent market test", "", f"Generated by `python -m stockanalysis.validation.recent`, data to {m['as_of']}.", "",
           f"| Method | Last 12 months ({w['12m'][0]} to {w['12m'][1]}) | Since 2024 (total) | {m['as_of'][:4]} so far |",
           "| --- | --- | --- | --- |"]
    for row in m["rows"].values():
        out.append(f"| {row['label']} | {cell(row.get('12m'))} | {cell(row.get('since_2024'))} | {cell(row.get('ytd'))} |")
    out += ["", "## Copying insider purchases, last two years", ""]
    if ins.get("events"):
        out += [f"{ins['purchases']} purchases ({ins['events']} events in {ins['stocks']} stocks) from {ins['first']} to "
                f"{ins['last']}, from Yahoo's insider lists for the app's 364-stock test list. Bought at the open three "
                "trading days after each trade.", "",
                "| Copy rule | Events | 1 month: avg vs S&P 500 (beat %) | 3 months | 6 months |", "| --- | --- | --- | --- | --- |"]
        for v in ins["variants"].values():
            def c(h):
                x = v.get(h)
                return "—" if not x else f"{x['avg_excess_pct']:+.1f}% ({x['beat_market_pct']:.0f}%, n {x['n']}, t {x['t_stat']})"
            out.append(f"| {v['label']} | {v['events']} | {c('h21')} | {c('h63')} | {c('h126')} |")
    else:
        out.append("No insider purchases found.")
    out += ["", "Short periods are mostly luck; see the long tests for whether a method works.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()
