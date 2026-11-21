"""Scorecard: is each method the app recommends profitable on past prices?

    python -m stockanalysis.validation.scorecard

One row per method the app tells you to act on, each judged on data it was
not tuned or chosen on wherever possible:

1. Stock Buy/Sell signals: the walk-forward test on 58 stocks never used for
   tuning, 2006-today (rules re-picked each year from past data only). Taken
   from the main validation report.
2. Market risk switch (dashboard): the S&P 500 held only while it is above its
   200-day average or beating T-bills over 12 months, scaled down when
   turbulent (15% volatility target), else T-bills. 1994-today.
3. Trend portfolio (Markets page): Faber's 10-month rule on 8 asset classes,
   with the app's default 2% band (chosen on 2003-2015 data, docs/ENTRIES.md).
4. Market trend alerts (Markets page): which markets get alerts was picked
   from results on the full history, which flatters them. Here the same
   picking rule (3 or more of 4 trend rules beat holding) is applied using
   only data up to the end of 2015, and the picked markets are then traded with
   the 10-month rule over 2016-today, which the pick never saw.

For each: yearly return, worst drop and Sharpe ratio above T-bills; whether
it made money, beat T-bills and beat its fair comparison; and how often it was
profitable over every rolling 1-year and 3-year window.

Signals at the close, trades at the next open, 0.1% per trade, idle cash earns
T-bills. Nothing is tuned here.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .. import tactics as T
from . import data
from .markets import COST, FABER, MARKETS, _metrics, faber_positions, rule_positions
from .portfolio import _daily_cash_rate, curve_metrics

log = logging.getLogger("stockanalysis.validation")
REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_scorecard.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "SCORECARD.md"

PICK_END = "2015-12-31"
TEST_START = "2016-01-01"
TREND_RULES = ("faber", "ma200", "cross", "breakout")
MIN_PICK_YEARS = 7
BAND = 0.02          # the app's default whipsaw band for the 10-month rule (docs/ENTRIES.md)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def rolling(r: pd.Series, comp: pd.Series | None, cash: pd.Series, per_year: int = 252) -> dict:
    """Share of rolling 1- and 3-year windows that made money / beat cash / beat the comparison."""
    out = {}
    g = np.log1p(r.fillna(0.0))
    gc = np.log1p(cash.reindex(r.index).fillna(0.0))
    gx = np.log1p(comp.reindex(r.index).fillna(0.0)) if comp is not None else None
    for years in (1, 3):
        n = per_year * years
        if len(r) <= n:
            continue
        s = g.rolling(n).sum().dropna()
        row = {"windows": int(len(s)),
               "made_money_pct": round(float((s > 0).mean()) * 100, 1),
               "beat_cash_pct": round(float((s > gc.rolling(n).sum().reindex(s.index)).mean()) * 100, 1),
               "worst_pct": round(float(np.expm1(s.min())) * 100, 1),
               "median_pct": round(float(np.expm1(s.median())) * 100, 1)}
        if gx is not None:
            row["beat_comparison_pct"] = round(float((s > gx.rolling(n).sum().reindex(s.index)).mean()) * 100, 1)
        out[f"{years}y"] = row
    return out


def verdict(m: dict, comp: dict, cash_cagr: float) -> dict:
    made = m["cagr_pct"] > 0
    beat_cash = m["cagr_pct"] > cash_cagr
    better_risk = (m.get("sharpe") or 0) > (comp.get("sharpe") or 0)
    more_money = m["cagr_pct"] > comp["cagr_pct"]
    smaller_drop = m["max_drawdown_pct"] > comp["max_drawdown_pct"] * 0.8   # at least 20% smaller
    return {"made_money": made, "beat_cash": beat_cash, "more_money_than_comparison": more_money,
            "better_risk_adjusted": better_risk, "smaller_worst_drop": smaller_drop}


def _cash_cagr(cash: pd.Series, index: pd.DatetimeIndex) -> float:
    c = cash.reindex(index).fillna(0.0)
    years = (index[-1] - index[0]).days / 365.25
    return round(float((1 + c).prod() ** (1 / years) - 1) * 100, 2)


def _row(key, name, what, period, unseen, r, comp_name, comp_r, cash, note="", extra=None):
    m = _metrics(r, cash)
    cm = _metrics(comp_r, cash)
    cash_cagr = _cash_cagr(cash, r.index)
    return {"key": key, "name": name, "what": what, "period": period, "unseen": unseen,
            "strategy": m, "comparison": {"name": comp_name, **cm}, "cash_cagr_pct": cash_cagr,
            "verdict": verdict(m, cm, cash_cagr), "rolling": rolling(r, comp_r, cash),
            "rolling_comparison": rolling(comp_r, None, cash), "note": note, **(extra or {})}


def _weekly_curve(r: pd.Series) -> dict:
    c = (1 + r).cumprod().resample("W-FRI").last().dropna()
    return {"dates": [d.date().isoformat() for d in c.index], "values": [round(float(x) * 100, 2) for x in c]}


# --------------------------------------------------------------------------
# 1. Stock signals (from the main report)
# --------------------------------------------------------------------------

def stock_signals(report: dict, cash: pd.Series) -> dict | None:
    panel = (report.get("walk_forward") or {}).get("panels", {}).get("exam_stocks")
    if not panel:
        return None
    curve = panel["curve"]
    idx = pd.DatetimeIndex(curve["dates"])
    strat = pd.Series(curve["walk_forward"], index=idx).pct_change().dropna()
    hold = pd.Series(curve["buy_and_hold"], index=idx).pct_change().dropna()
    weekly_cash = (1 + cash).cumprod().reindex(idx, method="ffill").pct_change().dropna()
    m, cm = panel["walk_forward"], panel["buy_and_hold"]
    cash_cagr = _cash_cagr(cash, cash.loc[idx[0]:idx[-1]].index)
    return {"key": "stocks", "name": "Stock Buy/Sell signals",
            "what": "The app's Buy/Sell rules and market filter, re-picked each year from past data only, "
                    "on 58 stocks never used for tuning.",
            "period": f"{idx[0].year}–{idx[-1].year}", "unseen": "Stocks and years never used for tuning",
            "strategy": m, "comparison": {"name": "Holding the same 58 stocks", **cm}, "cash_cagr_pct": cash_cagr,
            "verdict": verdict(m, cm, cash_cagr),
            "rolling": rolling(strat, hold, weekly_cash, per_year=52),
            "rolling_comparison": rolling(hold, None, weekly_cash, per_year=52),
            "note": "Weekly figures from the walk-forward test (docs/VALIDATION.md). Only companies still listed "
                    "today, which flatters both the rules and holding."}


# --------------------------------------------------------------------------
# 2. Market risk switch
# --------------------------------------------------------------------------

def market_switch(spy: pd.DataFrame, tbill: pd.Series, cash: pd.Series, scaled: bool = True) -> tuple[pd.Series, pd.Series]:
    close, open_ = spy["close"], spy["open"]
    sma200 = close.rolling(200).mean()
    mom12 = close / close.shift(252) - 1
    tb12 = tbill.reindex(close.index, method="ffill").rolling(252, min_periods=20).mean() / 100.0
    risk_on = (close > sma200) | (mom12 > tb12)
    vol20 = np.log(close).diff().rolling(20).std() * math.sqrt(252)
    scale = (0.15 / vol20).clip(upper=1.0) if scaled else pd.Series(1.0, index=close.index)
    expo = (risk_on.astype(float) * scale).where(sma200.notna() & mom12.notna()).fillna(0.0)
    # Decided at the close, traded at the next open.
    gap = open_ / close.shift(1) - 1           # overnight: still the old exposure
    day = close / open_ - 1                    # next session: the new exposure
    prev = expo.shift(1).fillna(0.0)
    prev2 = expo.shift(2).fillna(0.0)
    c = cash.reindex(close.index).fillna(0.0)
    r = (prev2 * gap + prev * day) + (1 - prev) * c - COST * (prev - prev2).abs()
    hold = close.pct_change()
    return r, hold


# --------------------------------------------------------------------------
# 3. Trend portfolio
# --------------------------------------------------------------------------

def trend_portfolio(prices: dict, tbill: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    syms = [s for s in FABER if s in prices]
    start = max(prices[s].index[0] for s in syms) + pd.Timedelta(days=320)
    base = prices["SPY"].index
    close = pd.DataFrame({s: prices[s]["close"] for s in syms}).reindex(base).ffill()
    open_ = pd.DataFrame({s: prices[s]["open"] for s in syms}).reindex(base).ffill()
    cash = pd.Series(_daily_cash_rate(close.index, tbill), index=close.index)
    held = faber_positions(close, BAND)
    timed = T.backtest(open_, close, held, cash, COST).loc[start:]
    hold = T.backtest(open_, close, close.notna(), cash, COST).loc[start:]
    sixty = 0.6 * hold["SPY"] + 0.4 * hold["IEF"]
    return timed.mean(axis=1), hold.mean(axis=1), sixty, cash


# --------------------------------------------------------------------------
# 4. Market trend alerts, picked without looking ahead
# --------------------------------------------------------------------------

def trend_alert_test(prices: dict, tbill: pd.Series, today_list: list[str]) -> dict:
    eligible, picks, table = [], [], []
    rule_r, hold_r = {}, {}
    for sym, name, cls in MARKETS:
        if sym.endswith("=F") or sym not in prices:
            continue                 # futures prices ignore roll costs; the funds are what you can buy
        df = prices[sym]
        close, open_ = df[["close"]], df[["open"]]
        cash = pd.Series(_daily_cash_rate(df.index, tbill), index=df.index)
        start = df.index[min(len(df) - 1, 260)]
        if (pd.Timestamp(PICK_END) - start).days / 365.25 < MIN_PICK_YEARS:
            continue
        eligible.append(sym)
        h = T.backtest(open_, close, close.notna(), cash, COST)["close"]
        hold_pick = _metrics(h.loc[start:PICK_END], cash)
        wins = 0
        for rule in TREND_RULES:
            held = rule_positions(rule, close)
            r = T.backtest(open_, close, held, cash, COST)["close"]
            edge = (_metrics(r.loc[start:PICK_END], cash).get("sharpe") or 0) - (hold_pick.get("sharpe") or 0)
            wins += edge > 0.02
        # Picking uses the four standard rules, as on the Markets page; trading uses the app's banded rule.
        banded = faber_positions(close, BAND)
        rule_r[sym] = T.backtest(open_, close, banded, cash, COST)["close"]
        hold_r[sym] = h
        picked = wins >= 3
        if picked:
            picks.append(sym)
        test_rule = _metrics(rule_r[sym].loc[TEST_START:], cash)
        test_hold = _metrics(hold_r[sym].loc[TEST_START:], cash)
        held = banded["close"].loc[TEST_START:]
        trades = round_trips(rule_r[sym].loc[TEST_START:], held)
        table.append({"symbol": sym, "name": name, "class": cls, "trend_wins_before_2016": int(wins),
                      "picked": picked, "on_today_list": sym in today_list,
                      "test": {"rule": test_rule, "hold": test_hold, "trades": trades}})

    def basket(syms, source):
        frame = pd.DataFrame({s: source[s] for s in syms}).loc[TEST_START:]
        return frame.mean(axis=1, skipna=True).dropna()

    spy_index = prices["SPY"].loc[TEST_START:].index
    cash = pd.Series(_daily_cash_rate(prices["SPY"].index, tbill), index=prices["SPY"].index)
    out = {"pick_end": PICK_END, "test_start": TEST_START, "eligible": eligible, "picks": picks,
           "today_list": today_list, "markets": table}
    groups = {"picked": picks, "all": eligible, "today_list": [s for s in today_list if s in rule_r]}
    out["baskets"] = {}
    for g, syms in groups.items():
        if not syms:
            continue
        r = basket(syms, rule_r).reindex(spy_index).fillna(0.0)
        h = basket(syms, hold_r).reindex(spy_index).fillna(0.0)
        trades = [t for row in table if row["symbol"] in syms for t in [row["test"]["trades"]]]
        n = sum(t["trades"] for t in trades)
        won = sum(t["won"] for t in trades)
        out["baskets"][g] = {"symbols": syms, "rule": _metrics(r, cash), "hold": _metrics(h, cash),
                             "trades": n, "win_rate_pct": round(won / n * 100, 1) if n else None,
                             "series": (r, h)}
    return out


def round_trips(r: pd.Series, held: pd.Series) -> dict:
    """Each stretch in the market = one trade (buy alert to sell alert)."""
    h = held.reindex(r.index).fillna(False).astype(bool)
    # Positions are entered at the open after the signal, so the trade's days lag the signal by one.
    in_mkt = h.shift(1, fill_value=False)
    trade_id = (in_mkt & ~in_mkt.shift(1, fill_value=False)).cumsum().where(in_mkt)
    results = (1 + r[in_mkt]).groupby(trade_id[in_mkt]).prod() - 1
    return {"trades": int(len(results)), "won": int((results > 0).sum()),
            "avg_pct": round(float(results.mean()) * 100, 1) if len(results) else None,
            "best_pct": round(float(results.max()) * 100, 1) if len(results) else None,
            "worst_pct": round(float(results.min()) * 100, 1) if len(results) else None}


# --------------------------------------------------------------------------

def run() -> dict:
    from ..trend_watch import FALLBACK_TREND_FRIENDLY, trend_friendly
    syms = list(dict.fromkeys([m[0] for m in MARKETS] + FABER + ["SPY"]))
    prices = data.load_prices(syms)
    tbill = data.load_tbill()
    spy = prices["SPY"]
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)

    rows = []
    report_path = REPORT_DIR / "report.json"
    if not report_path.exists():
        report_path = Path(__file__).resolve().parent / "latest_report.json"
    if report_path.exists():
        row = stock_signals(json.loads(report_path.read_text()), cash)
        if row:
            rows.append(row)

    r, hold = market_switch(spy, tbill, cash)
    start = r.index[260]
    r, hold = r.loc[start:], hold.loc[start:]
    rows.append(_row("market", "Market risk switch", "Hold the S&P 500 while it is above its 200-day average or "
                     "beating T-bills over 12 months, scaled down when turbulent; otherwise T-bills.",
                     f"{start.year}–{r.index[-1].year}", "Mostly: the rule was picked on 2003–2014 stock data; 1994–2002 and "
                     "2015 onward it never saw", r, "Holding the S&P 500", hold, cash,
                     note="Rebalanced daily to the volatility target, with costs; a monthly check would trade less.",
                     extra={"curve": {"strategy": _weekly_curve(r), "comparison": _weekly_curve(hold)}}))

    tp, same, sixty, pcash = trend_portfolio(prices, tbill)
    rows.append(_row("trend_portfolio", "Trend portfolio", "Faber's 10-month rule on 8 asset classes, equal shares, with the app's 2% band: "
                     "bought after a month-end close 2% above its 10-month average, sold after one 2% below.",
                     f"{tp.index[0].year}–{tp.index[-1].year}", "Yes: the published 2007 rule; the band was chosen on 2003–2015 data", tp,
                     "60% stocks / 40% bonds", sixty, pcash,
                     note="Also compared with holding the same 8 assets.",
                     extra={"also": {"name": "Holding the same 8", **_metrics(same, pcash)},
                            "curve": {"strategy": _weekly_curve(tp), "comparison": _weekly_curve(sixty)}}))

    try:
        today_list = trend_friendly()
    except Exception:
        today_list = list(FALLBACK_TREND_FRIENDLY)
    alerts = trend_alert_test(prices, tbill, today_list)
    picked = alerts["baskets"].get("picked")
    if picked:
        pr, ph = picked.pop("series")
        rows.append(_row("trend_alerts", "Market trend alerts",
                         f"Markets picked using only data up to {PICK_END[:4]} (3+ of 4 trend rules beat holding), then "
                         "bought and sold on each 10-month-rule alert (2% band), equal shares.",
                         f"{TEST_START[:4]}–{pr.index[-1].year}", f"Yes: picked on data up to {PICK_END[:4]}, tested after",
                         pr, "Holding the same markets", ph, cash,
                         note="Picked: " + ", ".join(picked["symbols"]) + ".",
                         extra={"trades": picked["trades"], "win_rate_pct": picked["win_rate_pct"],
                                "curve": {"strategy": _weekly_curve(pr), "comparison": _weekly_curve(ph)}}))
    for b in alerts["baskets"].values():
        b.pop("series", None)

    report = {"design": __doc__, "methods": rows, "trend_alerts": alerts,
              "generated": pd.Timestamp.now().isoformat(timespec="seconds")}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "scorecard.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(json.loads(text)))
    return report


def write_markdown(r: dict) -> str:
    def yes(x):
        return "✓" if x else "✗"

    out = ["# Scorecard: is each method profitable on past prices?", "",
           "Generated by `python -m stockanalysis.validation.scorecard`. Signals at the close, trades at the next "
           "open, 0.1% per trade, idle cash earns T-bills. Also shown on the app's **Track record** page.", "",
           "| Method | Period | Yearly return | Worst drop | Sharpe | Compared with | Their yearly / worst drop / Sharpe | "
           "Made money | Beat T-bills | Beat comparison (return) | Better return per risk | Smaller worst drop |",
           "| --- " * 12 + "|"]
    for m in r["methods"]:
        s, c, v = m["strategy"], m["comparison"], m["verdict"]
        out.append(f"| {m['name']} | {m['period']} | {s['cagr_pct']:+.1f}% | {s['max_drawdown_pct']:.0f}% | "
                   f"{s['sharpe']:.2f} | {c['name']} | {c['cagr_pct']:+.1f}% / {c['max_drawdown_pct']:.0f}% / "
                   f"{c['sharpe']:.2f} | {yes(v['made_money'])} | {yes(v['beat_cash'])} | "
                   f"{yes(v['more_money_than_comparison'])} | {yes(v['better_risk_adjusted'])} | "
                   f"{yes(v['smaller_worst_drop'])} |")
    out += ["", "## How often it made money", "",
            "Share of every rolling window (starting on any day) that ended with a gain.", "",
            "| Method | 1 year: made money | 1 year: beat comparison | 1 year: worst | 3 years: made money | "
            "3 years: beat comparison | 3 years: worst | Comparison, 3 years: made money |",
            "| --- " * 8 + "|"]
    for m in r["methods"]:
        a, b = m["rolling"].get("1y", {}), m["rolling"].get("3y", {})
        cb = m["rolling_comparison"].get("3y", {})
        out.append(f"| {m['name']} | {a.get('made_money_pct', '—')}% | {a.get('beat_comparison_pct', '—')}% | "
                   f"{a.get('worst_pct', '—')}% | {b.get('made_money_pct', '—')}% | {b.get('beat_comparison_pct', '—')}% | "
                   f"{b.get('worst_pct', '—')}% | {cb.get('made_money_pct', '—')}% |")
    t = r["trend_alerts"]
    out += ["", "## Market trend alerts, picked without hindsight", "",
            f"Markets with at least {MIN_PICK_YEARS} years of history before {t['pick_end'][:4]} (funds only, no "
            f"futures): {len(t['eligible'])}. Picked using only data up to {t['pick_end']}: "
            f"{', '.join(t['picks']) or 'none'}. Today's alert list (picked with the full history): "
            f"{', '.join(t['today_list'])}.", "",
            f"| Basket, {t['test_start'][:4]}–today | Markets | 10-month rule: yearly / worst drop / Sharpe | "
            "Holding: yearly / worst drop / Sharpe | Trades | Trades that won |", "| --- " * 6 + "|"]
    labels = {"picked": "Picked before 2016", "all": "All eligible markets", "today_list": "Today's list (hindsight)"}
    for k, b in t["baskets"].items():
        ru, ho = b["rule"], b["hold"]
        out.append(f"| {labels[k]} | {len(b['symbols'])} | {ru['cagr_pct']:+.1f}% / {ru['max_drawdown_pct']:.0f}% / "
                   f"{ru['sharpe']:.2f} | {ho['cagr_pct']:+.1f}% / {ho['max_drawdown_pct']:.0f}% / {ho['sharpe']:.2f} | "
                   f"{b['trades']} | {b['win_rate_pct']}% |")
    out += ["", "| Market | Trend rules that beat holding before 2016 | Picked | 2016–today: rule yearly / worst | "
            "Holding yearly / worst | Trades (won) | Average trade |", "| --- " * 7 + "|"]
    for m in t["markets"]:
        ru, ho, tr = m["test"]["rule"], m["test"]["hold"], m["test"]["trades"]
        out.append(f"| {m['name']} ({m['symbol']}) | {m['trend_wins_before_2016']} of 4 | {yes(m['picked'])} | "
                   f"{ru['cagr_pct']:+.1f}% / {ru['max_drawdown_pct']:.0f}% | {ho['cagr_pct']:+.1f}% / "
                   f"{ho['max_drawdown_pct']:.0f}% | {tr['trades']} ({tr['won']}) | "
                   f"{'' if tr['avg_pct'] is None else format(tr['avg_pct'], '+.1f') + '%'} |")
    out += ["", "## Caveats", "",
            "- Past results do not guarantee future ones; each market has one history.",
            "- Stock results include only companies still listed today (survivorship bias).",
            "- Insider trades and news tone have no free history and are not in these tests.",
            "- Taxes are ignored; selling winners in a taxable account lowers every timing method's return.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()
