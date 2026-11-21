"""Run the full historical validation and write the report.

    python -m stockanalysis.validation

Design, fixed before looking at any results:

* Training data: the TRAIN stocks from 2003 to 2014. This is the only data
  used to compare rule variants. It covers the 2008 crash.
* Test data, looked at once, after a variant is chosen:
    - the TRAIN stocks from 2015 to today (later years), and
    - the HOLDOUT stocks over both periods (stocks never used for tuning).
* Selection rule: highest Sharpe ratio on the training data among variants
  with at least 150 trades. Ties broken by return / max drawdown.
* "Holds up" means, on the test data, after costs:
    1. Buy signals beat the S&P 500 over the next 60 days more often than not,
       with a positive average excess return,
    2. the rules make money, and
    3. they beat buy-and-hold of the same stocks on risk-adjusted return
       (Sharpe) or cut the worst drawdown by at least a third while keeping
       at least 60% of its annual return.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import data, universe
from .portfolio import (MonthlyRules, Panel, Rules, benchmarks, curve_metrics, run_rules, trade_metrics, variant,
                        yearly_returns)
from .scores import score_history
from .study import signal_events, state_returns, summarize_events, summarize_states

log = logging.getLogger("stockanalysis.validation")

TRAIN_START, TRAIN_END = "2003-01-01", "2014-12-31"
TEST_START = "2015-01-01"
MIN_TRADES = 150
REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "validation"
BUNDLED_REPORT = Path(__file__).resolve().parent / "latest_report.json"   # shipped with the app
DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "VALIDATION.md"

BASELINE = Rules()

# Each variant changes one or two things, each a well-known idea:
VARIANTS = [
    BASELINE,
    variant(BASELINE, name="Market filter", market_filter=True,
            notes="No new buys while the S&P 500 is below its 200-day average (Faber's rule, applied to the market)."),
    variant(BASELINE, name="Stricter buys (score 40+)", buy_score=40),
    variant(BASELINE, name="Strongest buys only (score 50+)", buy_score=50),
    variant(BASELINE, name="Rank by momentum", rank_by="momentum",
            notes="When there are more buys than free slots, take the strongest 12-month momentum first."),
    variant(BASELINE, name="5 positions", max_positions=5, max_position=0.25),
    variant(BASELINE, name="20 positions", max_positions=20, max_position=0.10),
    variant(BASELINE, name="Wider stops (3.5 ATR)", stop_atr=3.5),
    variant(BASELINE, name="No trailing stop", trailing=False),
    variant(BASELINE, name="Keep through 200-day breaks", exit_on_trend_break=False,
            notes="Exit only on the stop, trailing stop or a Sell score."),
    variant(BASELINE, name="Exit only on strong sell", sell_score=-50),
    variant(BASELINE, name="Buy pullbacks only", entry="pullback",
            notes="Enter only when the 2-day RSI is under 10 inside the uptrend."),
    variant(BASELINE, name="Market filter + momentum rank", market_filter=True, rank_by="momentum"),
    variant(BASELINE, name="Market filter + strongest buys", market_filter=True, buy_score=50),
    variant(BASELINE, name="Market filter + wider stops", market_filter=True, stop_atr=3.5),
    variant(BASELINE, name="Market filter + keep through 200-day breaks", market_filter=True,
            exit_on_trend_break=False),
    variant(BASELINE, name="Trend-following core", market_filter=True, rank_by="momentum",
            exit_on_trend_break=False, sell_score=-50, stop_atr=3.0,
            notes="Market filter, momentum ranking, let winners run (exit on trailing stop or strong sell)."),
    variant(BASELINE, name="Trend-following core, 20 positions", market_filter=True, rank_by="momentum",
            exit_on_trend_break=False, sell_score=-50, stop_atr=3.0, max_positions=20, max_position=0.10),
]


# Round 2: ideas chosen after round 1 showed the app's score does not pick
# winning stocks among large caps, while trend filters at the market level cut
# drawdowns. Being invested is where the return comes from; the rules are
# better used to decide *when* to hold stocks than *which* to trade.
ROUND2 = [
    BASELINE,
    variant(BASELINE, name="Market filter", market_filter=True,
            notes="Original rules, but no new buys while the S&P 500 is below its 200-day average."),
    MonthlyRules(name="Hold all, market filter", select="all", market_filter=True, max_weight=1.0,
                 notes="Hold every stock equally; move to T-bills while the S&P 500 is below its 200-day average."),
    MonthlyRules(name="Hold Buy-rated stocks", select="buy", max_weight=0.10,
                 notes="Each month, hold every stock the app rates Buy (up to 10% each)."),
    MonthlyRules(name="Hold Buy-rated stocks, market filter", select="buy", max_weight=0.10, market_filter=True,
                 notes="As above, but in T-bills while the S&P 500 is below its 200-day average."),
    MonthlyRules(name="Hold all except Sell-rated, market filter", select="not_sell", max_weight=1.0,
                 market_filter=True, notes="Drop stocks the app rates Sell; T-bills in market downtrends."),
    MonthlyRules(name="Hold stocks above their 200-day average", select="above_200", max_weight=1.0,
                 notes="Faber's trend rule applied to each stock, checked monthly."),
    MonthlyRules(name="Top 15 momentum, market filter", select="top_momentum", top_n=15, max_weight=1 / 15,
                 market_filter=True, notes="The 15 strongest 12-month performers in uptrends; T-bills in market downtrends."),
    MonthlyRules(name="Top 15 by app score, market filter", select="top_score", top_n=15, max_weight=1 / 15,
                 market_filter=True, notes="The 15 highest app scores among Buy-rated stocks; T-bills in market downtrends."),
    MonthlyRules(name="Top 25 momentum, market filter", select="top_momentum", top_n=25, max_weight=1 / 25,
                 market_filter=True),
]


def score_universe(symbols, prices, earnings, use_earnings=True):
    frames = {}
    for sym in symbols:
        if sym in prices:
            frames[sym] = score_history(prices[sym], earnings.get(sym), use_earnings=use_earnings)
    return frames


def signal_study(frames, spy, start, end=None) -> dict:
    events, states = [], []
    for sym, f in frames.items():
        window = f.loc[start:end] if end else f.loc[start:]
        events.append(signal_events(sym, window, spy))
        states.append(state_returns(sym, window, spy))
    ev = pd.concat(events, ignore_index=True)
    stt = pd.concat(states, ignore_index=True)
    buys = ev[(ev["kind"] == "buy")].dropna(subset=["exc_60"])
    by_year = (buys.groupby(buys["date"].dt.year)
                   .apply(lambda g: pd.Series({"signals": len(g), "win_rate": round((g["exc_60"] > 0).mean() * 100, 1),
                                               "avg_excess": round(g["exc_60"].mean() * 100, 2)}),
                          include_groups=False))
    return {
        "events": summarize_events(ev),
        "states": summarize_states(stt),
        "buy_60d_by_year": {str(y): row.to_dict() for y, row in by_year.iterrows()},
    }


def portfolio_cell(panel: Panel, rules: Rules, start: str, end: str | None = None, keep_curve=True) -> dict:
    result = run_rules(panel, rules, start, end)
    curve = result["curve"]
    bench = benchmarks(panel, start, end)
    out = {
        "strategy": {**curve_metrics(curve), **trade_metrics(result)},
        "spy": curve_metrics(bench["spy"]),
        "equal_weight": curve_metrics(bench["equal_weight"]),
        "yearly": {"strategy": yearly_returns(curve), "spy": yearly_returns(bench["spy"]),
                   "equal_weight": yearly_returns(bench["equal_weight"])},
    }
    if keep_curve:
        weekly = pd.DataFrame({"strategy": curve / curve.iloc[0], "spy": bench["spy"],
                               "equal_weight": bench["equal_weight"]}).resample("W-FRI").last().dropna()
        out["curve"] = {"dates": [d.date().isoformat() for d in weekly.index],
                        **{k: [round(v * 100, 2) for v in weekly[k]] for k in weekly.columns}}
        out["recent_trades"] = result["trades"][-15:][::-1]
    return out


def verdict(study: dict, cell: dict) -> dict:
    buy60 = next((e for e in study["events"] if e["kind"] == "buy" and e["horizon"] == 60), None)
    s, ew = cell["strategy"], cell["equal_weight"]
    checks = {
        "buy_signals_beat_market": bool(buy60 and buy60["win_rate"] > 50 and buy60["avg_excess"] > 0),
        "profitable": bool(s.get("total_return_pct", -1) > 0),
        "beats_buy_and_hold": bool(
            (s.get("sharpe") or 0) > (ew.get("sharpe") or 0)
            or (s.get("max_drawdown_pct", -100) >= ew.get("max_drawdown_pct", -100) * (2 / 3)
                and s.get("cagr_pct", 0) >= 0.6 * ew.get("cagr_pct", 0))),
    }
    checks["holds_up"] = all(checks.values())
    return checks


def round2(cells: dict, studies: dict) -> dict:
    """Compare round-2 ideas on every period already seen; pick the most robust."""
    rows = []
    for rules in ROUND2:
        per_cell = {}
        for k, (_, panel, start, end) in cells.items():
            out = portfolio_cell(panel, rules, start, end, keep_curve=False)
            per_cell[k] = {"strategy": out["strategy"], "equal_weight": out["equal_weight"], "spy": out["spy"]}
        edges = [(c["strategy"].get("sharpe") or -9) - (c["equal_weight"].get("sharpe") or 0) for c in per_cell.values()]
        always_profitable = all(c["strategy"].get("total_return_pct", -1) > 0 for c in per_cell.values())
        rows.append({"rules": rules, "cells": per_cell, "median_sharpe_edge": round(float(pd.Series(edges).median()), 3),
                     "worst_sharpe_edge": round(min(edges), 3), "always_profitable": always_profitable})
    eligible = [r for r in rows if r["always_profitable"]] or rows
    best = max(eligible, key=lambda r: (r["median_sharpe_edge"], r["worst_sharpe_edge"]))
    return {"rows": rows, "chosen": best["rules"]}


def final_exam(prices, earnings, spy, tbill, rules) -> dict:
    syms = [s for s in universe.FINAL_EXAM if s in prices]
    frames = score_universe(syms, prices, earnings)
    panel = Panel.build(frames, spy, tbill)
    out = {"symbols": syms, "cells": {}}
    for label, start, end in (("exam_2003_2014", TRAIN_START, TRAIN_END), ("exam_2015_now", TEST_START, None)):
        study = signal_study(frames, spy, start, end)
        cell = portfolio_cell(panel, rules, start, end)
        baseline = portfolio_cell(panel, BASELINE, start, end, keep_curve=False)
        out["cells"][label] = {"study": study, "portfolio": cell, "baseline": baseline["strategy"],
                               "verdict": verdict(study, cell), "baseline_verdict": verdict(study, baseline)}
    return out


def main(refresh: bool = False) -> dict:
    t0 = time.time()
    all_syms = universe.TRAIN + universe.HOLDOUT + universe.FINAL_EXAM
    prices = data.load_prices(all_syms + [universe.BENCHMARK], refresh=refresh)
    earnings = data.load_earnings([s for s in all_syms if s in prices], refresh=refresh)
    spy = prices[universe.BENCHMARK]
    tbill = data.load_tbill(refresh=refresh)
    train_syms = [s for s in universe.TRAIN if s in prices]
    hold_syms = [s for s in universe.HOLDOUT if s in prices]
    log.info("Scoring %d + %d stocks", len(train_syms), len(hold_syms))
    train = score_universe(train_syms, prices, earnings)
    hold = score_universe(hold_syms, prices, earnings)
    p_train, p_hold = Panel.build(train, spy, tbill), Panel.build(hold, spy, tbill)

    cells = {
        "train_2003_2014": (train, p_train, TRAIN_START, TRAIN_END),
        "train_2015_now": (train, p_train, TEST_START, None),
        "holdout_2003_2014": (hold, p_hold, TRAIN_START, TRAIN_END),
        "holdout_2015_now": (hold, p_hold, TEST_START, None),
    }

    log.info("Signal study")
    studies = {k: signal_study(frames, spy, s, e) for k, (frames, _, s, e) in cells.items()}

    log.info("Comparing %d rule variants on training data only", len(VARIANTS))
    search = []
    for rules in VARIANTS:
        cell = portfolio_cell(p_train, rules, TRAIN_START, TRAIN_END, keep_curve=False)
        search.append({"rules": rules, "metrics": cell["strategy"]})
    eligible = [r for r in search if r["metrics"].get("trades", 0) >= MIN_TRADES] or search
    best = max(eligible, key=lambda r: ((r["metrics"].get("sharpe") or -9), (r["metrics"].get("return_to_drawdown") or -9)))
    chosen = best["rules"]
    log.info("Chosen: %s", chosen.name)

    portfolios = {}
    for label, rules in (("baseline", BASELINE), ("chosen", chosen)):
        portfolios[label] = {k: portfolio_cell(panel, rules, s, e) for k, (_, panel, s, e) in cells.items()}

    test_cells = ["train_2015_now", "holdout_2003_2014", "holdout_2015_now"]
    verdicts = {label: {k: verdict(studies[k], portfolios[label][k]) for k in cells} for label in portfolios}

    log.info("Round 2: %d ideas across all four periods already seen", len(ROUND2))
    r2 = round2(cells, studies)
    log.info("Round 2 chose: %s. Running the final exam once.", r2["chosen"].name)
    exam = final_exam(prices, earnings, spy, tbill, r2["chosen"])
    dev = {k: portfolio_cell(panel, r2["chosen"], s, e) for k, (_, panel, s, e) in cells.items()}

    log.info("Round 3: walk-forward test of market-timing rules")
    from .walkforward import walk_forward
    spy_frames = {"SPY": score_history(spy, None, use_earnings=False)}
    exam_frames = score_universe([s for s in universe.FINAL_EXAM if s in prices], prices, earnings)
    wf = walk_forward(
        dev_panels={"seen_stocks_train": p_train, "seen_stocks_holdout": p_hold,
                    "sp500": Panel.build(spy_frames, spy, tbill)},
        test_panels={"exam_stocks": Panel.build(exam_frames, spy, tbill), "seen_stocks_train": p_train,
                     "sp500": Panel.build(spy_frames, spy, tbill)},
    )

    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "round2": {
            "selection": "made money in all four periods, then highest median Sharpe advantage over holding the same stocks",
            "chosen_rules": r2["chosen"].describe(),
            "rows": [{"name": r["rules"].name, "notes": r["rules"].notes, "median_sharpe_edge": r["median_sharpe_edge"],
                      "worst_sharpe_edge": r["worst_sharpe_edge"], "always_profitable": r["always_profitable"],
                      "cells": r["cells"]} for r in r2["rows"]],
            "portfolio": dev,
        },
        "final_exam": exam,
        "walk_forward": wf,
        "runtime_s": round(time.time() - t0, 1),
        "design": {
            "train": f"{len(train_syms)} stocks, {TRAIN_START[:4]}-{TRAIN_END[:4]}",
            "test": f"same stocks {TEST_START[:4]}-today, plus {len(hold_syms)} held-out stocks over both periods",
            "selection": f"highest training Sharpe with at least {MIN_TRADES} trades",
            "cost_bps_per_side": BASELINE.cost_bps,
            "signals_replayed": "price rules (trend, momentum, 52-week high, pullback, MACD) and earnings surprise",
            "not_replayed": "insider trades and news tone (no free history)",
            "train_symbols": train_syms, "holdout_symbols": hold_syms,
            "test_cells": test_cells,
        },
        "search": [{"name": r["rules"].name, "notes": r["rules"].notes, **r["metrics"]} for r in search],
        "baseline_rules": BASELINE.describe(),
        "chosen_rules": chosen.describe(),
        "signal_study": studies,
        "portfolio": portfolios,
        "verdict": verdicts,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, separators=(",", ":"), default=str)
    (REPORT_DIR / "report.json").write_text(text)
    BUNDLED_REPORT.write_text(text)
    from .writeup import write_markdown
    DOC_PATH.write_text(write_markdown(report))
    log.info("Done in %.0fs. Report: %s", time.time() - t0, REPORT_DIR / "report.json")
    return report
