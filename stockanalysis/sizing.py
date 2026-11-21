"""Budget-aware position sizing.

The size of a stock position is set by how much you are willing to lose if the
stop is hit, not by how confident the signal looks:

    shares = (budget x risk-per-trade %) / (entry - stop)

and then capped by the largest position you allow and by the cash you have left.
The stop sits 2.5 ATRs under the entry so normal daily noise does not trigger it.
"""

from __future__ import annotations

import math

STOP_ATR_MULTIPLE = 2.5
TARGET_R_MULTIPLE = 2.0
# Trailing stop for positions you hold: 20% below the highest close since you
# bought. In the app's 20-year stop-loss test (validation/stops.py) this was
# the best balance: it cut the worst drawdown by about 13 points for about 2.6
# points a year of return. Tight trailing stops (10%, or 3 ATR under the 22-day
# high) were stopped out by ordinary noise and cost 7-9 points a year.
TRAILING_STOP_PCT = 20.0


def available_cash(settings: dict, positions: list[dict]) -> float:
    invested = sum(float(p["shares"]) * float(p["entry_price"]) for p in positions)
    return max(0.0, float(settings["budget"]) - invested)


def plan_trade(price: float, atr: float | None, action: str, settings: dict, cash: float,
               position: dict | None = None, peak_close: float | None = None) -> dict:
    budget = float(settings["budget"])
    risk_pct = float(settings["risk_per_trade_pct"])
    max_pos_pct = float(settings["max_position_pct"])

    plan: dict = {
        "action": action,
        "entry": round(price, 2),
        "budget": budget,
        "cash_available": round(cash, 2),
        "shares": 0,
        "cost": 0.0,
        "notes": [],
    }
    if not atr or math.isnan(atr) or atr <= 0 or price <= 0:
        plan["notes"].append("Not enough price history to size a position.")
        return plan

    stop_distance = STOP_ATR_MULTIPLE * atr
    stop = max(price - stop_distance, 0.01)
    stop_distance = price - stop
    plan.update({
        "atr": round(atr, 2),
        "stop": round(stop, 2),
        "stop_pct": round(stop_distance / price * 100, 1),
        "target": round(price + TARGET_R_MULTIPLE * stop_distance, 2),
        "target_pct": round(TARGET_R_MULTIPLE * stop_distance / price * 100, 1),
    })
    if position and peak_close and not math.isnan(peak_close):
        plan["trailing_stop"] = round(peak_close * (1 - TRAILING_STOP_PCT / 100), 2)
        plan["trailing_stop_pct"] = TRAILING_STOP_PCT
        plan["peak_close"] = round(peak_close, 2)

    if position:
        shares = float(position["shares"])
        entry = float(position["entry_price"])
        plan["holding"] = {
            "shares": shares,
            "entry_price": entry,
            "value": round(shares * price, 2),
            "pnl": round(shares * (price - entry), 2),
            "pnl_pct": round((price / entry - 1) * 100, 1) if entry else None,
        }

    if action in ("buy", "strong_buy") and position:
        plan["notes"].append("You already own this stock and the signal is still positive: "
                             "hold, and keep the stop in place.")
    elif action in ("buy", "strong_buy"):
        risk_dollars = budget * risk_pct / 100.0
        position_cap = budget * max_pos_pct / 100.0
        by_risk = math.floor(risk_dollars / stop_distance)
        by_cap = math.floor(position_cap / price)
        by_cash = math.floor(cash / price)
        shares = max(0, min(by_risk, by_cap, by_cash))
        limiting = min((by_risk, "risk"), (by_cap, "position cap"), (by_cash, "cash"))[1]
        plan.update({
            "shares": shares,
            "cost": round(shares * price, 2),
            "risk_amount": round(shares * stop_distance, 2),
            "pct_of_budget": round(shares * price / budget * 100, 1) if budget else 0.0,
            "limited_by": limiting,
        })
        if shares == 0:
            if by_cash == 0 and cash < price:
                plan["notes"].append(
                    f"One share costs ${price:,.2f} but only ${cash:,.2f} of your budget is uncommitted.")
            elif by_cap == 0:
                plan["notes"].append(
                    f"One share (${price:,.2f}) is more than your {max_pos_pct:g}% position cap "
                    f"(${position_cap:,.2f}). Raise the budget or the cap, or use fractional shares.")
            else:
                plan["notes"].append(
                    f"Risking {risk_pct:g}% (${risk_dollars:,.2f}) does not cover one share's "
                    f"stop distance (${stop_distance:,.2f}). Raise the budget or risk per trade.")
        else:
            plan["notes"].append(
                f"Sized so a stop-out loses about ${shares * stop_distance:,.2f} "
                f"({shares * stop_distance / budget * 100:.1f}% of your budget).")
    elif action in ("sell", "strong_sell"):
        if position:
            plan["notes"].append("Signals have turned negative: consider closing this position.")
        else:
            plan["notes"].append("Avoid opening a new position while signals are negative.")
    else:
        if position:
            plan["notes"].append("No change: hold the position and keep the stop in place.")
        else:
            plan["notes"].append("No edge right now: wait for a clearer setup.")
    return plan
