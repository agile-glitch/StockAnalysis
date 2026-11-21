"""Profit plan: the approach that made the most money in testing, as a live plan.

From docs/PROFIT.md (python -m stockanalysis.validation.profit):

* Steady - the S&P 500 (SPY) while the app's market switch is on, else T-bills.
* Growth - a 2x S&P 500 fund (SSO) while the S&P 500 is above its 200-day
  average, else T-bills. Chosen before testing as the highest return whose
  worst drop was no deeper than holding the index; it then beat holding in both
  halves of 1961-today, in the fund era and on the Nasdaq-100.
* Aggressive - a 3x S&P 500 fund (UPRO) while the market switch is on, else
  T-bills. The highest long-run return tested, with worst drops of -66% to -78%.

Signals use the S&P 500's latest close and are traded at the next close.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from .validation.profit import signal as profit_signal

log = logging.getLogger("stockanalysis.profit")

REPORT_PATHS = [
    Path(__file__).resolve().parent.parent / "data" / "validation" / "profit.json",
    Path(__file__).resolve().parent / "validation" / "latest_profit.json",
]
CASH_FUND = "SGOV"   # 0-3 month T-bill ETF; BIL or a money-market fund work the same way

PLANS = {
    "steady": {"label": "Steady", "fund": "SPY", "fund_name": "S&P 500 fund", "leverage": 1, "signal": "switch",
               "test_key": "switch_1x",
               "rule": "Hold the S&P 500 while it is above its 200-day average or beating T-bills over 12 months; "
                       "otherwise T-bills."},
    "growth": {"label": "Growth", "fund": "SSO", "fund_name": "2x S&P 500 fund", "leverage": 2, "signal": "200d",
               "test_key": "200d_2x",
               "rule": "Hold a 2x S&P 500 fund while the S&P 500 is above its 200-day average; otherwise T-bills."},
    "aggressive": {"label": "Aggressive", "fund": "UPRO", "fund_name": "3x S&P 500 fund", "leverage": 3,
                   "signal": "switch", "test_key": "switch_3x",
                   "rule": "Hold a 3x S&P 500 fund while the S&P 500 is above its 200-day average or beating "
                           "T-bills over 12 months; otherwise T-bills."},
}
DEFAULT_PLAN = "growth"


def load_report() -> dict | None:
    for path in REPORT_PATHS:
        if path.exists():
            return json.loads(path.read_text())
    return None


def tested(plan_key: str, report: dict | None = None) -> dict | None:
    report = report or load_report()
    if not report:
        return None
    key = PLANS[plan_key]["test_key"]
    out = {}
    for t in ("sp_long", "spy", "qqq"):
        test = report["tests"].get(t)
        if not test or key not in test["rows"]:
            continue
        pick = lambda row: {k: row.get(k) for k in ("cagr_pct", "max_drawdown_pct", "worst_year_pct", "worst_year",  # noqa: E731
                                                    "worst_10y_cagr_pct", "growth_of_10k", "time_in_market_pct")}
        out[t] = {"name": test["name"], "plan": pick(test["rows"][key]), "hold": pick(test["rows"]["hold_1x"])}
    return out


def state(spy: pd.DataFrame, tbill: pd.Series | None, plan_key: str) -> dict | None:
    """Where the plan stands after the S&P 500's latest close."""
    plan = PLANS[plan_key]
    close = spy["close"].dropna()
    if len(close) < 260:
        return None
    tb = tbill if tbill is not None and len(tbill.dropna()) else pd.Series(4.0, index=close.index)
    held = profit_signal(close, plan["signal"], tb)
    flips = held.ne(held.shift(1))
    flips.iloc[0] = False
    sma200 = float(close.rolling(200).mean().iloc[-1])
    price = float(close.iloc[-1])
    mom12 = float(close.iloc[-1] / close.iloc[-253] - 1)
    tb12 = float(tb.reindex(close.index, method="ffill").iloc[-252:].mean()) / 100.0
    since = held.index[flips.values][-1].date().isoformat() if flips.any() else None
    return {
        "plan": plan_key, "label": plan["label"], "rule": plan["rule"], "fund": plan["fund"],
        "fund_name": plan["fund_name"], "leverage": plan["leverage"], "cash_fund": CASH_FUND,
        "invested": bool(held.iloc[-1]), "since": since, "as_of": close.index[-1].date().isoformat(),
        "spy_price": round(price, 2), "sma200": round(sma200, 2), "gap_pct": round((price / sma200 - 1) * 100, 2),
        "momentum_12m_pct": round(mom12 * 100, 1), "tbill_12m_pct": round(tb12 * 100, 2),
        "uses_momentum": plan["signal"] == "switch",
    }


def describe_action(st: dict, budget: float) -> str:
    if st["invested"]:
        return (f"Hold {st['fund']} ({st['fund_name']}) with the money for this plan, about ${budget:,.0f} of your "
                f"budget.")
    return f"Hold T-bills ({st['cash_fund']} or a money-market fund) until the S&P 500 turns back up."


class ProfitPlan:
    def __init__(self, db, provider):
        self.db = db
        self.provider = provider
        self.latest: dict | None = None

    def snapshot(self) -> dict:
        settings = self.db.get_settings()
        key = settings.get("profit_plan") or "off"
        report = load_report()
        options = {k: {"label": p["label"], "rule": p["rule"], "fund": p["fund"], "fund_name": p["fund_name"],
                       "leverage": p["leverage"], "tested": tested(k, report)} for k, p in PLANS.items()}
        out = {"plan": key, "options": options, "budget": settings["budget"],
               "chosen_by_test": (report or {}).get("chosen"), "state": None}
        if key in PLANS:
            try:
                spy = self.provider.history("SPY", "2y")
            except Exception as exc:
                out["error"] = str(exc)
                return out
            tbill = None
            try:
                tbill = self.provider.history("^IRX", "2y")["close"]
            except Exception:
                pass
            st = state(spy, tbill, key)
            if st:
                st["action"] = describe_action(st, settings["budget"])
            out["state"] = st
        self.latest = out
        return out

    def update(self, notify: bool = True) -> dict:
        snap = self.snapshot()
        st = snap.get("state")
        if not st:
            return snap
        current = {"plan": st["plan"], "invested": st["invested"]}
        previous = self.db.get_state("profit_plan_state")
        if previous and previous.get("plan") == current["plan"] and previous["invested"] != current["invested"] and notify:
            if st["invested"]:
                title = f"Profit plan ({st['label']}): buy {st['fund']}"
                body = (f"The S&P 500 turned up (close {st['spy_price']:,.2f}, 200-day average {st['sma200']:,.2f}). "
                        f"Move the plan's money from T-bills into {st['fund']} ({st['fund_name']}) at the next close: "
                        f"about ${snap['budget']:,.0f} with your budget.")
                tone = "bullish"
            else:
                title = f"Profit plan ({st['label']}): sell {st['fund']}, move to T-bills"
                body = (f"The S&P 500 turned down (close {st['spy_price']:,.2f}, 200-day average {st['sma200']:,.2f}). "
                        f"Sell {st['fund']} at the next close and hold T-bills ({st['cash_fund']}) until it turns up. "
                        "In testing, stepping out here is what kept leveraged losses from becoming crashes.")
                tone = "bearish"
            self.db.add_notification(symbol=None, kind="profit_plan", tone=tone, title=title, body=body,
                                     dedup_key=f"profit_plan:{st['plan']}:{st['as_of']}:{st['invested']}")
        self.db.set_state("profit_plan_state", current)
        return snap
