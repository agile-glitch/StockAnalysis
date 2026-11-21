"""Which stocks do the rules suit, and do they work better on other markets?

    python -m stockanalysis.validation.markets

Part A - persistence across ~360 stocks. For each stock and each rule, the
rule's Sharpe ratio minus holding's is measured in 2003-2014 and again in
2015-2026. If "the stocks we are best at" is a real thing, stocks that did well
in the first period should do well in the second. Traits measured in the first
period (volatility, trendiness, beta) are also checked for whether they predict
where the rules work in the second.

Part B - other markets (gold, silver, oil, gas, copper, commodities, farm
goods, Treasury and corporate bonds, inflation-linked bonds, the dollar, euro,
yen, real estate, foreign and emerging stocks, small caps, Nasdaq, Bitcoin,
Ether), using the funds you can actually buy. Futures prices for gold, silver,
copper and platinum give longer history; they ignore roll costs, which is
small for metals. Results are shown for the full history and for each half.

Part C - a diversified trend portfolio decided before looking at results:
Faber's (2007) rule, unchanged. Eight asset classes in equal shares (US,
foreign and emerging stocks, real estate, Treasury bonds, inflation-linked
bonds, commodities, gold); each month, hold an asset only while it closes above
its 10-month average, otherwise T-bills. Compared with holding the same eight,
the S&P 500, and a 60/40 stock/bond mix.

Signals at the close, trades at the next open, 0.1% per trade, cash earns
T-bills, Sharpe ratios above T-bills. No rule is tuned here.
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
from .portfolio import _daily_cash_rate, curve_metrics
from .scores import score_history

log = logging.getLogger("stockanalysis.validation")
REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_markets.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "MARKETS.md"

PERIOD_A = ("2003-01-01", "2014-12-31")
PERIOD_B = ("2015-01-01", None)
COST = 0.001

MARKETS = [
    # symbol, name, asset class
    ("GLD", "Gold", "Precious metals"), ("SLV", "Silver", "Precious metals"),
    ("GC=F", "Gold futures (price only)", "Precious metals"), ("SI=F", "Silver futures (price only)", "Precious metals"),
    ("PL=F", "Platinum futures (price only)", "Precious metals"),
    ("USO", "Crude oil", "Energy"), ("UNG", "Natural gas", "Energy"),
    ("HG=F", "Copper futures (price only)", "Industrial metals"), ("CPER", "Copper", "Industrial metals"),
    ("DBC", "Broad commodities", "Commodities"), ("DBA", "Agriculture", "Commodities"),
    ("TLT", "Long-term Treasury bonds", "Bonds"), ("IEF", "7-10 year Treasury bonds", "Bonds"),
    ("TIP", "Inflation-linked Treasury bonds", "Bonds"), ("LQD", "Corporate bonds", "Bonds"),
    ("HYG", "High-yield bonds", "Bonds"),
    ("UUP", "US dollar", "Currencies"), ("FXE", "Euro", "Currencies"), ("FXY", "Japanese yen", "Currencies"),
    ("VNQ", "US real estate", "Real estate"),
    ("SPY", "S&P 500", "Stocks"), ("QQQ", "Nasdaq 100", "Stocks"), ("IWM", "US small caps", "Stocks"),
    ("EFA", "Developed foreign stocks", "Stocks"), ("EEM", "Emerging-market stocks", "Stocks"),
    ("BTC-USD", "Bitcoin", "Crypto"), ("ETH-USD", "Ether", "Crypto"),
]
FABER = ["SPY", "EFA", "EEM", "VNQ", "IEF", "TIP", "DBC", "GLD"]

RULES = {
    "app": "App's Buy/Sell rules",
    "ma200": "Above 200-day average",
    "faber": "Above 10-month average (checked monthly)",
    "cross": "50/200-day crossover",
    "breakout": "55-day breakout, 20-day exit",
    "rsi": "RSI(14) bounce, 30/70",
}


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------

def app_positions(frames: dict[str, pd.DataFrame], index: pd.DatetimeIndex) -> pd.DataFrame:
    """The app's own price rules, as in backtest.py: buy on a Buy score above the
    200-day average and the trailing stop; sell on the trailing stop, a close
    under the 200-day average, or a Sell score."""
    out = {}
    for sym, f in frames.items():
        s = score_history(f, None, use_earnings=False)
        enter = (s["action"] >= 1) & (s["close"] > s["sma200"]) & (s["close"] >= s["chandelier"])
        leave = (s["close"] < s["chandelier"]) | (s["close"] < s["sma200"]) | (s["score"] <= -25)
        out[sym] = T._enter_exit(enter.to_frame(), leave.to_frame()).iloc[:, 0]
    return pd.DataFrame(out).reindex(index).fillna(False).astype(bool)


def faber_positions(close: pd.DataFrame, band: float = 0.0) -> pd.DataFrame:
    """Hold while the month-end close is above the 10-month (210-day) average.

    With `band` (e.g. 0.02), buy only on a month-end close more than 2% above
    the average and sell only on one more than 2% below; in between, keep the
    current position. That skips many whipsaws (docs/ENTRIES.md).
    """
    ma = close.rolling(210, min_periods=210).mean()
    month_end = pd.Series(close.index.to_period("M"), index=close.index)
    is_end = month_end.ne(month_end.shift(-1))
    is_end.iloc[-1] = False   # the latest day is not a month end until the month is over
    if band:
        ends = pd.DataFrame({c: is_end for c in close.columns}, index=close.index)
        enter = ((close > ma * (1 + band)) & ma.notna()).where(ends)
        leave = ((close < ma * (1 - band)) & ma.notna()).where(ends)
        return T._enter_exit(enter, leave)
    signal = (close > ma).where(ma.notna(), False)
    held = signal.where(is_end).ffill().fillna(False).astype(bool)
    return held


def rule_positions(rule: str, close: pd.DataFrame, frames: dict | None = None) -> pd.DataFrame:
    if rule == "app":
        return app_positions(frames, close.index)
    if rule == "ma200":
        return T.positions("price_ma", {"n": 200}, close)
    if rule == "faber":
        return faber_positions(close)
    if rule == "cross":
        return T.positions("ma_cross", {"fast": 50, "slow": 200}, close)
    if rule == "breakout":
        return T.positions("donchian", {"entry": 55, "exit": 20}, close)
    if rule == "rsi":
        return T.positions("rsi_reversion", {}, close)
    raise KeyError(rule)


def per_column_stats(returns: pd.DataFrame, cash: pd.Series, start: str, end: str | None) -> pd.DataFrame:
    r = returns.loc[start:end]
    rf = cash.reindex(r.index).fillna(0.0)
    ex = r.sub(rf, axis=0)
    years = (r.index[-1] - r.index[0]).days / 365.25
    growth = (1 + r).prod()
    curve = (1 + r).cumprod()
    return pd.DataFrame({
        "sharpe": ex.mean() / ex.std() * math.sqrt(252),
        "cagr": (growth ** (1 / years) - 1) * 100,
        "max_dd": (curve / curve.cummax() - 1).min() * 100,
    })


# --------------------------------------------------------------------------
# Part A: persistence across stocks
# --------------------------------------------------------------------------

def persistence(prices: dict, spy: pd.DataFrame, cash: pd.Series) -> dict:
    syms = [s for s in dict.fromkeys(universe.TRAIN + universe.HOLDOUT + universe.FINAL_EXAM + INDICATOR_TEST + FRESH_TEST)
            if s in prices and prices[s].index[0] <= pd.Timestamp("2002-01-31")]
    index = spy.index
    close = pd.DataFrame({s: prices[s]["close"] for s in syms}).reindex(index)
    open_ = pd.DataFrame({s: prices[s]["open"] for s in syms}).reindex(index)
    frames = {s: prices[s] for s in syms}
    hold_r = T.backtest(open_, close, close.notna(), cash, COST)
    hold = {p: per_column_stats(hold_r, cash, *p) for p in (PERIOD_A, PERIOD_B)}

    # Traits measured in period A only.
    daily = close.pct_change(fill_method=None).loc[PERIOD_A[0]:PERIOD_A[1]]
    spy_d = spy["close"].pct_change().reindex(daily.index)
    monthly = close.loc[PERIOD_A[0]:PERIOD_A[1]].resample("ME").last().pct_change()
    change = close.diff().abs().loc[PERIOD_A[0]:PERIOD_A[1]].rolling(252).sum()
    net = (close - close.shift(252)).abs().loc[PERIOD_A[0]:PERIOD_A[1]]
    traits = pd.DataFrame({
        "volatility": daily.std() * math.sqrt(252) * 100,
        "beta": daily.apply(lambda c: c.cov(spy_d) / spy_d.var()),
        "trendiness": (net / change).mean(),            # Kaufman efficiency ratio: 1 = straight line
        "monthly_autocorr": monthly.apply(lambda c: c.autocorr()),
    })
    trait_labels = {"volatility": "Volatility", "beta": "Market beta", "trendiness": "Trendiness (efficiency ratio)",
                    "monthly_autocorr": "Month-to-month return persistence"}

    out = {"stocks": len(syms), "rules": {}}
    for rule, label in RULES.items():
        log.info("persistence: %s", label)
        held = rule_positions(rule, close, frames)
        r = T.backtest(open_, close, held, cash, COST)
        a, b = per_column_stats(r, cash, *PERIOD_A), per_column_stats(r, cash, *PERIOD_B)
        edge_a = (a["sharpe"] - hold[PERIOD_A]["sharpe"]).dropna()
        edge_b = (b["sharpe"] - hold[PERIOD_B]["sharpe"]).dropna()
        common = edge_a.index.intersection(edge_b.index)
        ea, eb = edge_a[common], edge_b[common]
        q = pd.qcut(ea.rank(method="first"), 5, labels=False)
        top, bottom = common[q == 4], common[q == 0]
        trait_rows = {}
        for t in traits.columns:
            tv = traits.loc[common, t]
            trait_rows[t] = {"label": trait_labels[t],
                             "corr_with_edge_same_period": round(float(tv.rank().corr(ea.rank())), 2),
                             "corr_with_edge_next_period": round(float(tv.rank().corr(eb.rank())), 2)}
        vol_q = pd.qcut(traits.loc[common, "volatility"].rank(method="first"), 5, labels=False)
        by_vol = [{"quintile": int(k) + 1,
                   "volatility_A": round(float(traits.loc[common[vol_q == k], "volatility"].median()), 1),
                   "edge_B": round(float(eb[common[vol_q == k]].mean()), 3),
                   "beating_hold_B_pct": round(float((eb[common[vol_q == k]] > 0).mean()) * 100, 1)} for k in range(5)]
        best_a = ea.sort_values(ascending=False).head(15)
        best_b = eb.sort_values(ascending=False).head(15)
        out["rules"][rule] = {
            "label": label,
            "rank_corr_A_vs_B": round(float(ea.rank().corr(eb.rank())), 2),
            "share_beating_hold_A": round(float((ea > 0).mean()) * 100, 1),
            "share_beating_hold_B": round(float((eb > 0).mean()) * 100, 1),
            "top_quintile_edge_A": round(float(ea[top].mean()), 3),
            "top_quintile_edge_B": round(float(eb[top].mean()), 3),
            "bottom_quintile_edge_B": round(float(eb[bottom].mean()), 3),
            "top_quintile_still_beating_hold_B": round(float((eb[top] > 0).mean()) * 100, 1),
            "traits": trait_rows,
            "edge_B_by_volatility_A": by_vol,
            "best_in_A": [{"symbol": s, "edge_A": round(float(ea[s]), 2), "edge_B": round(float(eb[s]), 2)} for s in best_a.index],
            "best_in_B": [{"symbol": s, "edge_A": round(float(ea[s]), 2), "edge_B": round(float(eb[s]), 2),
                           "cagr_B": round(float(b.loc[s, "cagr"]), 1), "hold_cagr_B": round(float(hold[PERIOD_B].loc[s, "cagr"]), 1)}
                          for s in best_b.index],
        }
    return out


# --------------------------------------------------------------------------
# Part B: other markets
# --------------------------------------------------------------------------

def _metrics(r: pd.Series, cash: pd.Series, held: pd.Series | None = None) -> dict:
    curve = (1 + r).cumprod()
    m = curve_metrics(curve, cash)
    if held is not None and len(held):
        h = held.astype(bool)
        years = max((h.index[-1] - h.index[0]).days / 365.25, 1e-9)
        m["time_in_market_pct"] = round(float(h.mean()) * 100, 1)
        m["trades_per_year"] = round(float((h & ~h.shift(1, fill_value=False)).sum()) / years, 2)
    return m


def markets(prices: dict, tbill: pd.Series) -> list[dict]:
    rows = []
    for sym, name, cls in MARKETS:
        if sym not in prices:
            continue
        df = prices[sym]
        close, open_ = df[["close"]], df[["open"]]
        cash = pd.Series(_daily_cash_rate(df.index, tbill), index=df.index)
        start = df.index[min(len(df) - 1, 260)]
        end = df.index[-1]
        mid = start + (end - start) / 2
        windows = {"full": (start, end), "first_half": (start, mid), "second_half": (mid, end)}
        hold_r = T.backtest(open_, close, close.notna(), cash, COST)["close"]
        row = {"symbol": sym, "name": name, "class": cls, "start": start.date().isoformat(),
               "years": round((end - start).days / 365.25, 1), "hold": {}, "rules": {}}
        for w, (a, b) in windows.items():
            row["hold"][w] = _metrics(hold_r.loc[a:b], cash)
        for rule, label in RULES.items():
            held = rule_positions(rule, close, {sym: df})
            r = T.backtest(open_, close, held, cash, COST)["close"]
            row["rules"][rule] = {}
            for w, (a, b) in windows.items():
                m = _metrics(r.loc[a:b], cash, held["close"].loc[a:b] if rule != "app" else held[sym].loc[a:b])
                m["edge"] = round((m.get("sharpe") or 0) - (row["hold"][w].get("sharpe") or 0), 3)
                row["rules"][rule][w] = m
        # Live state of the pre-registered rule (10-month average) as of the last close.
        row["faber_now"] = bool(faber_positions(close)["close"].iloc[-1])
        rows.append(row)
        log.info("markets: %s done", sym)
    return rows


# --------------------------------------------------------------------------
# Part C: diversified trend portfolio (Faber 2007, unchanged)
# --------------------------------------------------------------------------

def faber_portfolio(prices: dict, tbill: pd.Series) -> dict:
    syms = [s for s in FABER if s in prices]
    start = max(prices[s].index[0] for s in syms) + pd.Timedelta(days=320)
    idx = prices["SPY"].loc[start:].index
    close = pd.DataFrame({s: prices[s]["close"] for s in syms}).reindex(prices["SPY"].index).ffill()
    open_ = pd.DataFrame({s: prices[s]["open"] for s in syms}).reindex(prices["SPY"].index).ffill()
    cash = pd.Series(_daily_cash_rate(close.index, tbill), index=close.index)
    held = faber_positions(close)
    timed = T.backtest(open_, close, held, cash, COST).loc[idx]
    hold = T.backtest(open_, close, close.notna(), cash, COST).loc[idx]
    # Equal shares, rebalanced monthly (each sleeve's daily return averaged).
    strat_r, hold_r = timed.mean(axis=1), hold.mean(axis=1)
    spy_r = hold["SPY"]
    sixty_forty = 0.6 * hold["SPY"] + 0.4 * hold["IEF"]
    series = {"trend": strat_r, "hold_same": hold_r, "spy": spy_r, "sixty_forty": sixty_forty}
    metrics = {k: _metrics(v, cash) for k, v in series.items()}
    curves = pd.DataFrame({k: (1 + v).cumprod() for k, v in series.items()})
    yearly = {k: {str(y): round(float((1 + v[v.index.year == y]).prod() - 1) * 100, 1) for y in sorted(set(v.index.year))}
              for k, v in series.items()}
    weekly = curves.resample("W-FRI").last().dropna()
    return {"assets": syms, "start": idx[0].date().isoformat(), "metrics": metrics, "yearly": yearly,
            "invested_pct": round(float(held.loc[idx].mean().mean()) * 100, 1),
            "holding_now": {s: bool(held[s].iloc[-1]) for s in syms},
            "curve": {"dates": [d.date().isoformat() for d in weekly.index],
                      **{k: [round(float(x) * 100, 2) for x in weekly[k]] for k in weekly.columns}}}


def run() -> dict:
    stock_syms = list(dict.fromkeys(universe.TRAIN + universe.HOLDOUT + universe.FINAL_EXAM + INDICATOR_TEST + FRESH_TEST))
    market_syms = [m[0] for m in MARKETS]
    prices = data.load_prices(stock_syms + market_syms + [universe.BENCHMARK])
    tbill = data.load_tbill()
    spy = prices[universe.BENCHMARK]
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)
    report = {"design": __doc__, "rules": RULES,
              "persistence": persistence(prices, spy, cash),
              "markets": markets(prices, tbill),
              "faber": faber_portfolio(prices, tbill)}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "markets.json").write_text(text)
    BUNDLED.write_text(text)
    DOC.write_text(write_markdown(json.loads(text)))
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    run()


def write_markdown(r: dict) -> str:
    p, f = r["persistence"], r["faber"]

    def e(x):
        return f"{x:+.2f}"

    out = ["# Which stocks suit the rules, and other markets", "",
           "Generated by `python -m stockanalysis.validation.markets`. Live trend status for every market is on "
           "the app's **Markets** page.", "",
           "## Which stocks are we best at?", "",
           f"Six rules were run on {p['stocks']} stocks. Each stock's result (Sharpe ratio above T-bills minus "
           "holding's) in 2003–2014 was compared with its result in 2015–2026.", "",
           "| Rule | Ranking carried over (rank correlation) | Top fifth in 2003–14 | Same stocks in 2015–26 | Bottom fifth in 2015–26 | Beat holding in 2015–26 |",
           "| --- | --- | --- | --- | --- | --- |"]
    for x in p["rules"].values():
        out.append(f"| {x['label']} | {x['rank_corr_A_vs_B']:+.2f} | {e(x['top_quintile_edge_A'])} | "
                   f"{e(x['top_quintile_edge_B'])} | {e(x['bottom_quintile_edge_B'])} | {x['share_beating_hold_B']}% |")
    fx = p["rules"]["faber"]
    out += ["", "**The best stocks for a rule did not stay best.** Rankings barely carried over (rank correlations "
            "near zero), and the previous top fifth did about as badly as everyone else. A list of 'stocks we are best "
            "at' drawn from the past is mostly a list of lucky stocks. For example, for the 10-month rule: "
            + ", ".join(f"{b['symbol']} ({b['edge_A']:+.2f} then {b['edge_B']:+.2f})" for b in fx["best_in_A"][:5]) + ".", "",
            "One trait carried over a little: trend rules lost less on more volatile, higher-beta stocks, but most "
            "stocks were still better held in every volatility group (10-month rule, share beating holding in "
            "2015–26 by 2003–14 volatility: "
            + ", ".join(f"{q['volatility_A']:.0f}% vol: {q['beating_hold_B_pct']}%" for q in fx["edge_B_by_volatility_A"])
            + "). How smoothly a stock had trended predicted nothing.", "",
            "## Other markets", "",
            "Edge = Sharpe ratio above T-bills minus holding's, over each market's whole history (✓ = better in "
            "both halves). Futures prices ignore the cost of rolling contracts.", "",
            "| Market | Years | Holding: yearly / worst drop | " + " | ".join(r["rules"][k] for k in r["rules"]) + " |",
            "| --- " * (3 + len(r["rules"])) + "|"]
    for m in r["markets"]:
        h = m["hold"]["full"]
        cells = []
        for k in r["rules"]:
            x = m["rules"][k]
            ok = x["full"]["edge"] > 0 and x["first_half"]["edge"] > 0 and x["second_half"]["edge"] > 0
            cells.append(e(x["full"]["edge"]) + (" ✓" if ok else ""))
        out.append(f"| {m['name']} ({m['symbol']}) | {m['years']} | {h['cagr_pct']:+.1f}% / {h['max_drawdown_pct']:.0f}% | " + " | ".join(cells) + " |")
    out += ["", "**Where trend rules helped:** commodity funds (oil, natural gas, broad commodities, farm goods), "
            "where simply holding lost money over time because of the cost of rolling futures, and Ether. "
            "**Where holding was as good or better:** gold, platinum, copper, bonds, the dollar, real estate, "
            "small caps, foreign and emerging stocks. With six rules per market, one rule will often beat holding "
            "in both halves by chance, so agreement among the trend rules is the better guide than any single winner.", "",
            "## Diversified trend portfolio (Faber 2007, unchanged)", "",
            f"Eight asset classes ({', '.join(f['assets'])}) in equal shares since {f['start']}; each held only while "
            "above its 10-month average at month end, otherwise T-bills.", "",
            "| Portfolio | Yearly return | Worst drop | Volatility | Sharpe | 2008 | 2022 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    names = {"trend": "Trend portfolio", "hold_same": "Hold the same 8", "sixty_forty": "60/40 stocks/bonds", "spy": "S&P 500"}
    for k, label in names.items():
        mm = f["metrics"][k]
        out.append(f"| {label} | {mm['cagr_pct']:+.1f}% | {mm['max_drawdown_pct']:.1f}% | {mm['volatility_pct']:.1f}% | "
                   f"{mm['sharpe']:.2f} | {f['yearly'][k].get('2008', 0):+.1f}% | {f['yearly'][k].get('2022', 0):+.1f}% |")
    out += ["", "The trend portfolio had the smallest crashes by far, but the lowest return, and a plain 60/40 "
            "stock/bond mix had the best return per unit of risk over this period.", "",
            "## Caveats", "",
            "- Stocks: only companies still listed today (survivorship bias).",
            "- Markets: one history each; 2007–2026 includes only a few big trends in some markets.",
            "- No rule was tuned here; the Faber portfolio is the published rule, unchanged.", ""]
    return "\n".join(out)
