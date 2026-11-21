"""Turn the validation report into docs/VALIDATION.md (numbers come straight
from the report, so the write-up cannot drift from the data)."""

from __future__ import annotations


def _p(x, digits=1):
    return "n/a" if x is None else f"{x:+.{digits}f}%"


def _row(*cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


CELL_NAMES = {
    "train_2003_2014": "Training stocks, 2003–2014 (used for tuning)",
    "train_2015_now": "Training stocks, 2015–today",
    "holdout_2003_2014": "Held-out stocks, 2003–2014",
    "holdout_2015_now": "Held-out stocks, 2015–today",
}


def write_markdown(r: dict) -> str:
    d = r["design"]
    out = [
        "# Track record: does the program hold up on past data?",
        "",
        f"Generated {r['generated']} by `python -m stockanalysis.validation` (runs in under a minute once "
        "prices are cached). The same results are on the app's **Track record** page.",
        "",
        "## Bottom line",
        "",
    ]
    wf = r.get("walk_forward")
    if wf:
        ex, sp = wf["panels"]["exam_stocks"], wf["panels"]["sp500"]
        buy60 = next(e for e in r["signal_study"]["train_2015_now"]["events"] if e["kind"] == "buy" and e["horizon"] == 60)
        out += [
            "1. **Every version of the rules made money** in every period tested.",
            f"2. **The per-stock Buy and Sell ratings did not beat the market.** For example, on 2015–today data, "
            f"{buy60['signals']:,} new Buy signals beat the S&P 500 over the next 3 months {buy60['win_rate']}% of the "
            f"time, with an average excess return of {_p(buy60['avg_excess'], 2)}. Stocks rated Sell did no worse than "
            "average, and in some periods better.",
            f"3. **Market-level risk control held up.** Following a market-timing rule chosen year by year with only "
            f"past data, on {len(r['final_exam']['symbols'])} stocks never used for tuning ({ex['walk_forward']['years']} years): "
            f"worst loss {ex['walk_forward']['max_drawdown_pct']}% instead of {ex['buy_and_hold']['max_drawdown_pct']}%, "
            f"Sharpe {ex['walk_forward']['sharpe']} vs {ex['buy_and_hold']['sharpe']}.",
            f"4. **It did not make more money than staying invested:** {ex['walk_forward']['cagr_pct']}% a year vs "
            f"{ex['buy_and_hold']['cagr_pct']}%. On the S&P 500 itself: {sp['walk_forward']['cagr_pct']}% vs "
            f"{sp['buy_and_hold']['cagr_pct']}% a year, worst loss {sp['walk_forward']['max_drawdown_pct']}% vs "
            f"{sp['buy_and_hold']['max_drawdown_pct']}%. The cost comes from missing fast rebounds (2019, 2020, 2023).",
            "",
            "So the app now shows a **Market risk** indicator on the dashboard (suggested share of the budget in "
            "stocks) based on the rule that held up, and the per-stock ratings are presented as information, not "
            "as a proven trading system.",
            "",
        ]
    out += [
        "## How the test works",
        "",
        "- **What is replayed:** " + d["signals_replayed"] + ". Not replayed: " + d["not_replayed"] + ". "
        "The replayed scorer is checked against the live app's code to give identical scores.",
        "- **No peeking:** signals use only data up to each day's close; trades happen at the next open. "
        "Earnings surprises count from the day after the report.",
        f"- **Costs:** {d['cost_bps_per_side']} basis points per buy and per sell. Idle cash earns the 3-month T-bill rate.",
        f"- **Training data:** {d['train']}. **Test data:** {d['test']}.",
        f"- **Final exam:** {len(r['final_exam']['symbols'])} further stocks, untouched until round 2 had picked its rules, run once.",
        "- **Survivorship bias:** only companies that still trade could be downloaded, which flatters every "
        "long-only result. Comparisons are against buying and holding the *same* stocks, which shares the bias.",
        "- **Win** for a Buy signal means the stock beat the S&P 500 afterwards (not merely went up).",
        "",
        "## Round 1: the app's original rules",
        "",
        _row("Period", "Buy signals beat market (3 mo)", "Avg excess (3 mo)", "Rules: yearly", "Rules: worst drop",
             "Hold same: yearly", "Hold same: worst drop", "Holds up?"),
        _row(*["---"] * 8),
    ]
    for cell, name in CELL_NAMES.items():
        e = next(x for x in r["signal_study"][cell]["events"] if x["kind"] == "buy" and x["horizon"] == 60)
        p = r["portfolio"]["baseline"][cell]
        v = r["verdict"]["baseline"][cell]
        out.append(_row(name, f"{e['win_rate']}% of {e['signals']:,}", _p(e["avg_excess"], 2), _p(p["strategy"]["cagr_pct"]),
                        _p(p["strategy"]["max_drawdown_pct"]), _p(p["equal_weight"]["cagr_pct"]),
                        _p(p["equal_weight"]["max_drawdown_pct"]), "Yes" if v["holds_up"] else "No"))
    out += ["", f"Round 1 also compared {len(r['search'])} variants on the training data. The best there "
            f"(\"{r['chosen_rules']['name']}\") did not hold up on the test data either.", ""]

    r2 = r.get("round2")
    if r2:
        out += ["## Round 2: hold a basket, decide when to be in the market", "",
                "Selection: " + r2["selection"] + ".", "",
                _row("Idea", "Median Sharpe advantage", "Worst period", "Always profitable"), _row(*["---"] * 4)]
        for x in sorted(r2["rows"], key=lambda x: -x["median_sharpe_edge"]):
            out.append(_row(x["name"] + (" **(chosen)**" if x["name"] == r2["chosen_rules"]["name"] else ""),
                            f"{x['median_sharpe_edge']:+.2f}", f"{x['worst_sharpe_edge']:+.2f}",
                            "Yes" if x["always_profitable"] else "No"))
        fe = r["final_exam"]
        out += ["", f"### Final exam ({len(fe['symbols'])} untouched stocks)", "",
                _row("Period", "Rule: yearly", "Rule: worst drop", "Hold same: yearly", "Hold same: worst drop",
                     "S&P 500: yearly", "Original rules: yearly", "Holds up?"), _row(*["---"] * 8)]
        for k, c in fe["cells"].items():
            s, ew, spy = c["portfolio"]["strategy"], c["portfolio"]["equal_weight"], c["portfolio"]["spy"]
            out.append(_row("2003–2014" if "2003" in k else "2015–today", _p(s["cagr_pct"]), _p(s["max_drawdown_pct"]),
                            _p(ew["cagr_pct"]), _p(ew["max_drawdown_pct"]), _p(spy["cagr_pct"]),
                            _p(c["baseline"]["cagr_pct"]), "Yes" if c["verdict"]["holds_up"] else "No"))
        out.append("")

    if wf:
        out += ["## Round 3: walk-forward test of market-timing rules", "",
                "Each year, the rule with the best Sharpe ratio over all *earlier* years (on stocks already seen and "
                "the S&P 500 back to 1996) is applied to the next year on the final-exam stocks. The candidate list "
                "was written after seeing the round 2 final exam; the year-by-year choices were not.", "",
                _row("Basket", "Rule: yearly", "Rule: worst drop", "Rule: Sharpe", "Always invested: yearly",
                     "Always invested: worst drop", "Always invested: Sharpe"), _row(*["---"] * 7)]
        names = {"exam_stocks": "Final-exam stocks (unseen)", "seen_stocks_train": "Training stocks", "sp500": "S&P 500 (SPY)"}
        for k, x in wf["panels"].items():
            a, b = x["walk_forward"], x["buy_and_hold"]
            out.append(_row(names.get(k, k), _p(a["cagr_pct"]), _p(a["max_drawdown_pct"]), a["sharpe"],
                            _p(b["cagr_pct"]), _p(b["max_drawdown_pct"]), b["sharpe"]))
        out += ["", "Rule used each year: " + ", ".join(f"{y}: {n}" for y, n in wf["picks"].items()) + ".", ""]

    out += [
        "## What this cannot tell you",
        "",
        "- Insider trades and news tone (25 of the score's 100 points) have no free history, so they were not tested. "
        "Insider history exists in the SEC's bulk Form 4 datasets, which need a declared contact to download.",
        "- Options ideas were not tested: free historical option prices do not exist.",
        "- Survivorship bias (above), and the usual: past results do not guarantee future ones.",
        "",
    ]
    return "\n".join(out)
