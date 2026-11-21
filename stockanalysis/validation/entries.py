"""Can we cut losing entries without cutting profits?

    python -m stockanalysis.validation.entries

Most losing trades come from entries that reverse soon after: a market pokes
above its average and falls back (a whipsaw), a stock is bought after a big
run and pulls back, or an earnings report lands days after buying. Each filter
below delays or skips entries; exits are unchanged, so any difference comes
from the entries alone.

Every filter is checked on its own, and the choice is made before looking at
the test data:

* Part A, trend-rule entries (the 10-month rule behind market alerts and the
  trend portfolio), on the market funds. Filters are judged on 2003-2015 and
  the best kept one is then tested on 2016-today.
* Part B, stock Buy entries (the app's Buy rule with its usual exits). Filters
  are judged on the 73 training stocks in 2003-2014 and the pick is then
  tested on 150+ other stocks in 2015-today.

A filter is kept only if, in the selection data, it lowers the share of
losing trades AND does not lower the return per unit of risk (Sharpe ratio
above T-bills) by more than 0.02. For stocks, kept filters are combined. Fewer losing
trades is not the goal by itself: a filter that skips losers but also skips
the big winners makes less money, and trend rules live on a few big winners.

Signals at the close, trades at the next open, 0.1% per trade, idle cash earns
T-bills.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .. import tactics as T
from . import data, universe
from .experiments import FRESH_TEST
from .lab import INDICATOR_TEST
from .markets import COST, MARKETS
from .portfolio import _daily_cash_rate, curve_metrics
from .scores import score_history

log = logging.getLogger("stockanalysis.validation")
REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_entries.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "ENTRIES.md"

SHARPE_SLACK = 0.02

# --------------------------------------------------------------------------
# Trade statistics
# --------------------------------------------------------------------------


def trade_list(r: pd.Series, held: pd.Series) -> pd.DataFrame:
    """One row per trade: entry day (first day in the market) and its return."""
    h = held.reindex(r.index).fillna(False).astype(bool)
    in_mkt = h.shift(1, fill_value=False)
    starts = in_mkt & ~in_mkt.shift(1, fill_value=False)
    tid = starts.cumsum().where(in_mkt)
    if not in_mkt.any():
        return pd.DataFrame(columns=["entry", "ret", "days"])
    g = (1 + r[in_mkt]).groupby(tid[in_mkt])
    entry = pd.Series(r.index[in_mkt]).groupby(tid[in_mkt].to_numpy()).first()
    out = pd.DataFrame({"entry": entry.to_numpy(), "ret": (g.prod() - 1).to_numpy(), "days": g.size().to_numpy()})
    # A trade still open at the end of the data is not finished; leave it out.
    if bool(in_mkt.iloc[-1]):
        out = out.iloc[:-1]
    return out


def trade_stats(trades: pd.DataFrame) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0}
    ret = trades["ret"]
    wins, losses = ret[ret > 0], ret[ret <= 0]
    return {
        "trades": int(n),
        "losing_pct": round(float((ret <= 0).mean()) * 100, 1),
        "avg_win_pct": round(float(wins.mean()) * 100, 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()) * 100, 2) if len(losses) else None,
        "avg_trade_pct": round(float(ret.mean()) * 100, 2),
        "big_losses_pct": round(float((ret < -0.10).mean()) * 100, 1),     # trades losing more than 10%
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
    }


def basket_metrics(r: pd.DataFrame, cash: pd.Series, start, end) -> dict:
    b = r.loc[start:end].mean(axis=1, skipna=True).dropna()
    return curve_metrics((1 + b).cumprod(), cash)


# --------------------------------------------------------------------------
# Part A: trend-rule entries
# --------------------------------------------------------------------------

def month_end_flags(index: pd.DatetimeIndex) -> pd.Series:
    month = pd.Series(index.to_period("M"), index=index)
    ends = month.ne(month.shift(-1))
    ends.iloc[-1] = False
    return ends


def trend_variants(close: pd.Series, tbill: pd.Series) -> dict[str, tuple[str, pd.Series]]:
    """Each variant's held series. Exits are the base rule's (a month end below the average)
    except the band variant, whose point is a wider exit as well."""
    ma = close.rolling(210, min_periods=210).mean()
    ends = month_end_flags(close.index)
    above = (close > ma) & ma.notna()
    below = (close < ma) & ma.notna()
    mom12 = close / close.shift(252) - 1
    tb12 = tbill.reindex(close.index, method="ffill").rolling(252, min_periods=20).mean() / 100.0
    ma_rising = ma > ma.shift(21)
    vol = np.log(close).diff().rolling(21).std()
    calm = vol <= 1.5 * vol.rolling(252, min_periods=126).median()
    hi = close.rolling(252, min_periods=126).max()

    def build(enter, leave):
        e = (enter & ends).to_frame("c").where(ends.to_frame("c"))
        x = (leave & ends).to_frame("c").where(ends.to_frame("c"))
        return T._enter_exit(e, x)["c"]

    # Previous completed month end's state, evaluated at each month end.
    end_idx = close.index[ends.values]
    prev_end_above = above.loc[end_idx].shift(1).reindex(close.index).fillna(False).astype(bool)
    return {
        "base": ("10-month rule as is", build(above, below)),
        "band2": ("2% band: buy 2% above the average, sell 2% below", build(close > ma * 1.02, close < ma * 0.98)),
        "confirm2": ("Two month ends in a row above the average", build(above & prev_end_above, below)),
        "slope": ("Average rising over the last month", build(above & ma_rising, below)),
        "momentum": ("12-month return also beats T-bills", build(above & (mom12 > tb12), below)),
        "calm": ("Not in a volatility spike (1-month volatility under 1.5x normal)", build(above & calm, below)),
        "near_high": ("Within 10% of the 1-year high", build(above & (close >= 0.9 * hi), below)),
    }


def part_a(prices: dict, tbill: pd.Series) -> dict:
    syms = [m[0] for m in MARKETS if not m[0].endswith("=F") and m[0] in prices]
    base_index = prices["SPY"].index
    cash = pd.Series(_daily_cash_rate(base_index, tbill), index=base_index)
    returns: dict[str, dict[str, pd.Series]] = {}
    trades: dict[str, list[pd.DataFrame]] = {}
    labels: dict[str, str] = {}
    for sym in syms:
        df = prices[sym]
        c = pd.Series(_daily_cash_rate(df.index, tbill), index=df.index)
        for key, (label, held) in trend_variants(df["close"], tbill).items():
            labels[key] = label
            r = T.backtest(df[["open"]], df[["close"]], held.to_frame("close"), c, COST)["close"]
            returns.setdefault(key, {})[sym] = r
            t = trade_list(r, held)
            t["symbol"] = sym
            trades.setdefault(key, []).append(t)
    periods = {"selection": ("2003-01-01", "2015-12-31"), "test": ("2016-01-01", None)}
    rows = {}
    for key in labels:
        frame = pd.DataFrame(returns[key]).reindex(base_index)
        allt = pd.concat(trades[key], ignore_index=True)
        rows[key] = {"label": labels[key]}
        for p, (a, b) in periods.items():
            tt = allt[(allt["entry"] >= a) & ((allt["entry"] <= b) if b else True)]
            rows[key][p] = {**trade_stats(tt), **{f"basket_{k}": v for k, v in basket_metrics(frame, cash, a, b).items()
                                                   if k in ("cagr_pct", "sharpe", "max_drawdown_pct")}}
    return {"markets": syms, "periods": periods, "variants": rows, **choose(rows)}


# --------------------------------------------------------------------------
# Part B: stock Buy entries
# --------------------------------------------------------------------------

def days_to_next_earnings(index: pd.DatetimeIndex, earnings: pd.DataFrame | None) -> pd.Series:
    """Trading days until the next report (companies publish the date weeks ahead)."""
    if earnings is None or earnings.empty:
        return pd.Series(np.inf, index=index)
    days = pd.DatetimeIndex(pd.to_datetime(earnings["date"]).dt.normalize().unique()).sort_values()
    pos = np.arange(len(index))
    nxt = np.searchsorted(index.values, days.values, side="left")     # index position of each report day
    out = np.full(len(index), np.inf)
    j = np.searchsorted(nxt, pos, side="left")
    ok = j < len(nxt)
    out[ok] = nxt[j[ok]] - pos[ok]
    return pd.Series(out, index=index)


STOCK_FILTERS = {
    "market": "Market risk switch is on (S&P 500 above its 200-day average or beating T-bills)",
    "not_extended": "Not stretched: less than 10% above the 50-day average",
    "rsi": "RSI(14) under 70 (not overbought)",
    "volume": "Volume above its 50-day average on the signal day",
    "momentum": "12-month momentum positive",
    "calm": "Volatility not above its 1-year median",
    "earnings": "No earnings report in the next 10 trading days",
}


def stock_filters(f: pd.DataFrame, spy_on: pd.Series, earn_days: pd.Series) -> dict[str, pd.Series]:
    c = f["close"]
    hv_med = f["hv30"].rolling(252, min_periods=126).median()
    return {
        "market": spy_on.reindex(f.index).fillna(False).astype(bool),
        "not_extended": (c / f["sma50"] - 1) < 0.10,
        "rsi": f["rsi14"] < 70,
        "volume": f["volume"] > f["vol_avg50"],
        "momentum": f["mom_12_1"] > 0,
        "calm": f["hv30"] <= hv_med,
        "earnings": earn_days > 10,
    }


def prepare(symbols, prices, earnings, spy_on) -> dict:
    """Score each stock once: base entry and exit signals plus every filter."""
    out = {}
    for sym in symbols:
        f = score_history(prices[sym], None, use_earnings=False)
        enter = (f["action"] >= 1) & (f["close"] > f["sma200"]) & (f["close"] >= f["chandelier"])
        leave = (f["close"] < f["chandelier"]) | (f["close"] < f["sma200"]) | (f["score"] <= -25)
        flt = stock_filters(f, spy_on, days_to_next_earnings(f.index, earnings.get(sym)))
        out[sym] = (enter, leave, {k: v.fillna(False).astype(bool) for k, v in flt.items()})
    return out


def stock_trades(prepared, prices, cash, start, end, filters=()):
    """Trade stats and pooled-portfolio metrics for the app's Buy rule with the given entry filters."""
    rets, helds, trades = {}, {}, []
    for sym, (enter, leave, flt) in prepared.items():
        for k in filters:
            enter = enter & flt[k]
        held = T._enter_exit(enter.to_frame("c"), leave.to_frame("c"))["c"]
        r = T.backtest(prices[sym][["open"]], prices[sym][["close"]], held.to_frame("close"),
                       cash.reindex(held.index).fillna(0.0), COST)["close"]
        rets[sym], helds[sym] = r, held
        t = trade_list(r, held)
        t["symbol"] = sym
        trades.append(t)
    allt = pd.concat(trades, ignore_index=True)
    allt = allt[(allt["entry"] >= start) & ((allt["entry"] <= end) if end else True)]
    ret_df, held_df = pd.DataFrame(rets), pd.DataFrame(helds)
    pooled = T.pooled_returns(ret_df, held_df, cash.reindex(ret_df.index), max_weight=0.10).loc[start:end]
    m = curve_metrics((1 + pooled).cumprod(), cash)
    return {**trade_stats(allt), **{f"basket_{k}": v for k, v in m.items() if k in ("cagr_pct", "sharpe", "max_drawdown_pct")}}


def part_b(prices: dict, earnings: dict, tbill: pd.Series) -> dict:
    spy = prices["SPY"]
    close = spy["close"]
    tb12 = tbill.reindex(close.index, method="ffill").rolling(252, min_periods=20).mean() / 100.0
    spy_on = (close > close.rolling(200).mean()) | (close / close.shift(252) - 1 > tb12)
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)
    train = [s for s in universe.TRAIN if s in prices]
    test = [s for s in dict.fromkeys(universe.HOLDOUT + universe.FINAL_EXAM + INDICATOR_TEST + FRESH_TEST)
            if s in prices and s not in universe.TRAIN]
    sel, tst = ("2003-01-01", "2014-12-31"), ("2015-01-01", None)
    log.info("entries B: scoring %d + %d stocks", len(train), len(test))
    prep_train = prepare(train, prices, earnings, spy_on)
    prep_test = prepare(test, prices, earnings, spy_on)
    rows = {"base": {"label": "App's Buy rule as is", "selection": stock_trades(prep_train, prices, cash, *sel)}}
    for k, label in STOCK_FILTERS.items():
        log.info("entries B: %s", k)
        rows[k] = {"label": label, "selection": stock_trades(prep_train, prices, cash, *sel, filters=(k,))}
    combo = tuple(choose(rows, only_selection=True)["kept"])
    if len(combo) > 1:
        rows["combined"] = {"label": "All kept filters together",
                            "filters": list(combo),
                            "selection": stock_trades(prep_train, prices, cash, *sel, filters=combo)}
    # Test every filter (not only the kept ones) so nothing is hidden; the verdict uses the pick.
    for k in rows:
        log.info("entries B test: %s", k)
        flt = () if k == "base" else combo if k == "combined" else (k,)
        rows[k]["test"] = stock_trades(prep_test, prices, cash, *tst, filters=flt)
    return {"train_stocks": len(train), "test_stocks": len(test), "periods": {"selection": sel, "test": tst},
            "variants": rows, **choose(rows)}


# --------------------------------------------------------------------------

def choose(rows: dict, only_selection: bool = False) -> dict:
    """Keep filters that cut losing trades without hurting Sharpe in the selection data."""
    base = rows["base"]["selection"]
    kept = [k for k, v in rows.items() if k not in ("base", "combined") and v["selection"].get("trades")
            and v["selection"]["losing_pct"] < base["losing_pct"]
            and (v["selection"].get("basket_sharpe") or 0) >= (base.get("basket_sharpe") or 0) - SHARPE_SLACK]
    out = {"kept": kept}
    if only_selection:
        return out
    pick = "combined" if "combined" in rows else (kept[0] if len(kept) == 1 else None)
    if pick is None and kept:   # several kept but no combined row (Part A): the best Sharpe among them
        pick = max(kept, key=lambda k: rows[k]["selection"].get("basket_sharpe") or 0)
    out["pick"] = pick
    if pick:
        b, p = rows["base"]["test"], rows[pick]["test"]
        out["test_verdict"] = {
            "fewer_losing_trades": p["losing_pct"] < b["losing_pct"],
            "losing_pct": [b["losing_pct"], p["losing_pct"]],
            "sharpe": [b.get("basket_sharpe"), p.get("basket_sharpe")],
            "cagr_pct": [b.get("basket_cagr_pct"), p.get("basket_cagr_pct")],
            "max_drawdown_pct": [b.get("basket_max_drawdown_pct"), p.get("basket_max_drawdown_pct")],
            "no_worse_risk_adjusted": (p.get("basket_sharpe") or 0) >= (b.get("basket_sharpe") or 0) - SHARPE_SLACK,
        }
        v = out["test_verdict"]
        # Held up = fewer losers while keeping the return (within 0.25 points a year) and risk-adjusted return.
        v["held_up"] = bool(v["fewer_losing_trades"] and v["no_worse_risk_adjusted"]
                            and (p.get("basket_cagr_pct") or 0) >= (b.get("basket_cagr_pct") or 0) - 0.25)
    return out


def run() -> dict:
    stock_syms = list(dict.fromkeys(universe.TRAIN + universe.HOLDOUT + universe.FINAL_EXAM + INDICATOR_TEST + FRESH_TEST))
    market_syms = [m[0] for m in MARKETS]
    prices = data.load_prices(stock_syms + market_syms + ["SPY"])
    cached = [s for s in stock_syms if (data.CACHE_DIR / f"{s}.earnings.csv").exists()]
    earnings = data.load_earnings(cached)
    tbill = data.load_tbill()
    log.info("entries A: trend rules")
    a = part_a(prices, tbill)
    b = part_b(prices, earnings, tbill)
    report = {"design": __doc__, "trend": a, "stocks": b, "generated": pd.Timestamp.now().isoformat(timespec="seconds")}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "entries.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(json.loads(text)))
    return report


def write_markdown(r: dict) -> str:
    def f(x, d=1, pct=True):
        return "—" if x is None else (f"{x:+.{d}f}%" if pct else f"{x:.{d}f}")

    def table(part, title, sel_label, test_label):
        out = [f"## {title}", "",
               f"| Filter | Kept? | {sel_label}: trades / losing / avg trade / Sharpe | "
               f"{test_label}: trades / losing / avg trade / Sharpe / yearly / worst drop |", "| --- | --- | --- | --- |"]
        for k, v in part["variants"].items():
            s, t = v["selection"], v.get("test", {})
            kept = "base" if k == "base" else ("pick" if k == part.get("pick") else "✓" if k in part["kept"] else "✗")
            out.append(f"| {v['label']} | {kept} | {s.get('trades', 0)} / {s.get('losing_pct', '—')}% / "
                       f"{f(s.get('avg_trade_pct'), 2)} / {f(s.get('basket_sharpe'), 2, False)} | "
                       f"{t.get('trades', 0)} / {t.get('losing_pct', '—')}% / {f(t.get('avg_trade_pct'), 2)} / "
                       f"{f(t.get('basket_sharpe'), 2, False)} / {f(t.get('basket_cagr_pct'))} / "
                       f"{f(t.get('basket_max_drawdown_pct'), 0)} |")
        v = part.get("test_verdict")
        out.append("")
        if v:
            out.append(f"**Picked before testing: {part['variants'][part['pick']]['label']}.** On the test data, losing "
                       f"trades went from {v['losing_pct'][0]}% to {v['losing_pct'][1]}%, Sharpe from "
                       f"{v['sharpe'][0]} to {v['sharpe'][1]}, yearly return from {f(v['cagr_pct'][0])} to "
                       f"{f(v['cagr_pct'][1])}, worst drop from {f(v['max_drawdown_pct'][0], 0)} to "
                       f"{f(v['max_drawdown_pct'][1], 0)}. "
                       + ("It held up." if v["held_up"] else "Fewer losing trades, but it did not keep the profits, "
                          "so it is not used as a rule."))
        else:
            out.append("**No filter passed the selection test**, so the rule stays as it is.")
        return out

    a, b = r["trend"], r["stocks"]
    out = ["# Cutting losing entries", "",
           "Generated by `python -m stockanalysis.validation.entries`. Exits are unchanged; each filter only "
           "delays or skips entries. A filter is kept only if, on the selection data, it lowers the share of "
           "losing trades without lowering the Sharpe ratio by more than 0.02. Then the pick is tested once on "
           "data it never saw.", ""]
    out += table(a, f"Trend-rule entries ({len(a['markets'])} funds)", "2003–2015", "2016–today")
    out += [""]
    out += table(b, f"Stock Buy entries ({b['train_stocks']} training stocks, {b['test_stocks']} test stocks)",
                 "Training stocks 2003–2014", "Other stocks 2015–today")
    out += ["", "## Caveats", "",
            "- Fewer losing trades is not the same as more money: a filter can skip losers and the big winners too.",
            "- Earnings dates are the actual report dates; companies announce them weeks ahead, so the filter is usable live.",
            "- Stocks: only companies still listed today (survivorship bias).", ""]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()
