"""Call and put recommendations.

Design choices, and the evidence behind them (see docs/STRATEGIES.md):

* Options are only suggested when the stock signal is already Buy or Sell.
  An option is a leveraged bet on a view; with no view there is no trade.
* Long options use ~45 days to expiry and a delta near 0.60. Studies of retail
  option trading (Bryzgalova, Pavlova & Sikorskaya 2023) find the losses
  concentrate in cheap, short-dated, far out-of-the-money contracts with wide
  spreads. Slightly in-the-money contracts with a month or more left behave
  more like the stock and lose less to time decay.
* Buying options just before earnings is avoided: implied volatility is bid up
  beforehand and collapses afterwards, and retail buyers lose on average
  (de Silva, Smith & So 2023). A spread is suggested instead, because the
  option sold offsets most of that volatility drop.
* When implied volatility is rich relative to how much the stock really moves,
  selling a cash-secured put is preferred to buying a call (the put-write
  index has matched the S&P 500 with less volatility).
* Every idea is sized from the budget: the most that can be lost on one options
  trade is the "options risk per trade" setting.
"""

from __future__ import annotations

import math
from datetime import date

RISK_FREE = 0.04
TARGET_DTE = 45
MIN_DTE, MAX_DTE = 25, 70
LONG_DELTA = 0.60
SHORT_LEG_DELTA = 0.30
INCOME_DELTA = 0.28
IV_RICH, IV_CHEAP = 1.35, 0.95
MIN_OPEN_INTEREST = 50
MAX_SPREAD_PCT = 15.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_d1(spot: float, strike: float, t: float, sigma: float, r: float = RISK_FREE) -> float:
    return (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def bs_delta(spot: float, strike: float, t: float, sigma: float, kind: str, r: float = RISK_FREE) -> float:
    if t <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    d1 = bs_d1(spot, strike, t, sigma, r)
    return _norm_cdf(d1) if kind == "call" else _norm_cdf(d1) - 1.0


def bs_price(spot: float, strike: float, t: float, sigma: float, kind: str, r: float = RISK_FREE) -> float:
    if t <= 0 or sigma <= 0:
        return max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)
    d1 = bs_d1(spot, strike, t, sigma, r)
    d2 = d1 - sigma * math.sqrt(t)
    if kind == "call":
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def is_monthly(expiry: date) -> bool:
    """Standard monthly expiry: the third Friday. These are the most liquid."""
    return expiry.weekday() == 4 and 15 <= expiry.day <= 21


def pick_expiry(expirations: list[str], today: date) -> tuple[str, int] | None:
    """Closest expiry to 45 days out within the 25-70 day window, preferring
    the standard monthly expiry over weeklies and quarter-ends."""
    dated = []
    for exp in expirations:
        try:
            when = date.fromisoformat(exp)
        except ValueError:
            continue
        dte = (when - today).days
        if dte > 0:
            dated.append((exp, dte, is_monthly(when)))
    if not dated:
        return None
    window = [x for x in dated if MIN_DTE <= x[1] <= MAX_DTE]
    pool = ([x for x in window if x[2]] or window
            or [x for x in dated if x[1] >= 14] or dated)
    best = min(pool, key=lambda x: abs(x[1] - TARGET_DTE))
    return best[0], best[1]


def enrich(contracts: list[dict], spot: float, dte: int, fallback_vol: float) -> list[dict]:
    """Add mid price, spread, a usable IV and a Black-Scholes delta to each contract."""
    t = max(dte, 1) / 365.0
    out = []
    for c in contracts:
        bid, ask, last = c.get("bid") or 0.0, c.get("ask") or 0.0, c.get("last") or 0.0
        if bid > 0 and ask > 0 and ask >= bid:
            mid = (bid + ask) / 2.0
            spread_pct = (ask - bid) / mid * 100.0 if mid else None
            quoted = True
        else:
            # After hours Yahoo often has no live quote; fall back to the last trade.
            mid, spread_pct, quoted = last, None, False
        if mid <= 0:
            continue
        iv = c.get("iv") or 0.0
        if iv < 0.05 or iv > 5:  # junk values when there is no live quote
            iv = fallback_vol
        delta = bs_delta(spot, c["strike"], t, iv, c["type"])
        out.append({
            **c,
            "mid": round(mid, 2),
            "spread_pct": round(spread_pct, 1) if spread_pct is not None else None,
            "quoted": quoted,
            "iv": round(iv, 4),
            "delta": round(delta, 3),
            "liquid": (c.get("open_interest") or 0) >= MIN_OPEN_INTEREST
                      and (spread_pct is None or spread_pct <= MAX_SPREAD_PCT),
        })
    return out


def _nearest_delta(contracts: list[dict], kind: str, target: float, exclude_strike: float | None = None):
    pool = [c for c in contracts if c["type"] == kind and c["strike"] != exclude_strike]
    if not pool:
        return None
    liquid = [c for c in pool if c["liquid"]]
    # Prefer liquid contracts unless that pushes the delta far from the target.
    best_any = min(pool, key=lambda c: abs(abs(c["delta"]) - target))
    if liquid:
        best_liquid = min(liquid, key=lambda c: abs(abs(c["delta"]) - target))
        if abs(abs(best_liquid["delta"]) - target) <= 0.12:
            return best_liquid
    return best_any


def atm_iv(contracts: list[dict], spot: float) -> float | None:
    near = sorted(contracts, key=lambda c: abs(c["strike"] - spot))[:4]
    ivs = [c["iv"] for c in near if c.get("iv")]
    return sum(ivs) / len(ivs) if ivs else None


def _leg(action: str, c: dict) -> dict:
    return {
        "action": action,
        "type": c["type"],
        "strike": c["strike"],
        "expiry": c["expiry"],
        "contract": c.get("contract"),
        "price": c["mid"],
        "bid": c.get("bid"),
        "ask": c.get("ask"),
        "delta": c["delta"],
        "iv": c["iv"],
        "open_interest": c.get("open_interest"),
        "volume": c.get("volume"),
        "spread_pct": c["spread_pct"],
    }


def _liquidity_warnings(legs: list[dict]) -> list[str]:
    warnings = []
    for c in legs:
        tag = f"${c['strike']:g} {c['type']}"
        if not c["quoted"]:
            warnings.append(f"No live bid/ask for the {tag}; the price shown is the last trade. Re-check when the market is open.")
        elif c["spread_pct"] is not None and c["spread_pct"] > MAX_SPREAD_PCT:
            warnings.append(f"Wide bid/ask spread on the {tag} ({c['spread_pct']:.0f}%): use a limit order near the mid price.")
        if (c.get("open_interest") or 0) < MIN_OPEN_INTEREST:
            warnings.append(f"Thin open interest on the {tag}: it may be hard to exit.")
    return warnings


def _size(max_loss_per_contract: float, risk_budget: float) -> int:
    if max_loss_per_contract <= 0:
        return 0
    return int(risk_budget // max_loss_per_contract)


def _long_option(kind: str, c: dict, dte: int, risk_budget: float) -> dict:
    cost = c["mid"] * 100.0
    contracts = _size(cost, risk_budget)
    bullish = kind == "call"
    breakeven = c["strike"] + c["mid"] if bullish else c["strike"] - c["mid"]
    return {
        "strategy": "Buy a call" if bullish else "Buy a put",
        "kind": "long_call" if bullish else "long_put",
        "direction": "bullish" if bullish else "bearish",
        "legs": [_leg("buy", c)],
        "expiry": c["expiry"],
        "dte": dte,
        "net_cost": round(cost, 2),
        "cost_label": "Cost per contract",
        "contracts": contracts,
        "total_cost": round(cost * contracts, 2),
        "max_loss": round(cost, 2),
        "max_profit": None,
        "breakeven": round(breakeven, 2),
        "affordable": contracts >= 1,
        "rationale": [
            f"Delta {abs(c['delta']):.2f} with {dte} days left: moves about ${abs(c['delta']) * 100:.0f} per "
            f"$1 move in the stock, with enough time for the trade to work.",
            f"The most you can lose is the ${cost:,.0f} paid per contract.",
        ],
        "warnings": _liquidity_warnings([c]) + (
            ["The closest contract on offer is further from the 0.60 delta target than usual, "
             "so it behaves less like the stock."] if abs(abs(c["delta"]) - LONG_DELTA) > 0.15 else []),
        "exit_plan": "Take profit at about +50% or when the stock signal flips. Cut the trade at -50%, "
                     "and close or roll with 14 days left, when time decay speeds up.",
    }


def _debit_spread(kind: str, long_c: dict, short_c: dict, dte: int, risk_budget: float) -> dict | None:
    debit = long_c["mid"] - short_c["mid"]
    width = abs(short_c["strike"] - long_c["strike"])
    if debit <= 0 or width <= 0 or debit >= width:
        return None
    bullish = kind == "call"
    cost = debit * 100.0
    contracts = _size(cost, risk_budget)
    breakeven = long_c["strike"] + debit if bullish else long_c["strike"] - debit
    return {
        "strategy": "Bull call spread" if bullish else "Bear put spread",
        "kind": "bull_call_spread" if bullish else "bear_put_spread",
        "direction": "bullish" if bullish else "bearish",
        "legs": [_leg("buy", long_c), _leg("sell", short_c)],
        "expiry": long_c["expiry"],
        "dte": dte,
        "net_cost": round(cost, 2),
        "cost_label": "Cost per spread",
        "contracts": contracts,
        "total_cost": round(cost * contracts, 2),
        "max_loss": round(cost, 2),
        "max_profit": round((width - debit) * 100.0, 2),
        "breakeven": round(breakeven, 2),
        "affordable": contracts >= 1,
        "rationale": [
            f"Selling the ${short_c['strike']:g} {kind} pays for part of the ${long_c['strike']:g} {kind}, "
            f"cutting the cost to ${cost:,.0f} per spread.",
            f"Profit is capped at ${(width - debit) * 100:,.0f} per spread if the stock is "
            f"{'above' if bullish else 'below'} ${short_c['strike']:g} at expiry.",
            "The option sold also offsets most of the damage if implied volatility falls.",
        ],
        "warnings": _liquidity_warnings([long_c, short_c]),
        "exit_plan": "Take profit at about half of the maximum gain; close if the stock signal flips.",
    }


def _fit_spread(contracts: list[dict], kind: str, dte: int, risk_budget: float) -> dict | None:
    """The best debit spread the options risk budget covers.

    Tries the usual 0.60-delta long leg first, then cheaper at-the-money and
    slightly out-of-the-money legs, taking the widest spread that fits. A
    spread costing more than half its width risks more than it can make, so
    those are only accepted as a last resort.
    """
    bullish = kind == "call"
    for max_debit_share in (0.5, 0.67):
        for target in (LONG_DELTA, 0.50, 0.40):
            long_c = _nearest_delta(contracts, kind, target)
            if not long_c:
                continue
            shorts = [c for c in contracts if c["type"] == kind
                      and (c["strike"] > long_c["strike"] if bullish else c["strike"] < long_c["strike"])]
            shorts.sort(key=lambda c: abs(c["strike"] - long_c["strike"]), reverse=True)
            for short_c in shorts:
                width = abs(short_c["strike"] - long_c["strike"])
                debit = long_c["mid"] - short_c["mid"]
                if 0 < debit * 100.0 <= risk_budget and debit <= max_debit_share * width:
                    idea = _debit_spread(kind, long_c, short_c, dte, risk_budget)
                    if idea:
                        idea["rationale"].insert(0, "Chosen so one spread fits your options risk budget.")
                        return idea
    return None


def _cash_secured_put(c: dict, dte: int, spot: float) -> dict:
    credit = c["mid"] * 100.0
    collateral = c["strike"] * 100.0
    return {
        "strategy": "Sell a cash-secured put",
        "kind": "cash_secured_put",
        "direction": "bullish",
        "legs": [_leg("sell", c)],
        "expiry": c["expiry"],
        "dte": dte,
        "net_cost": round(-credit, 2),
        "cost_label": "Credit received per contract",
        "collateral": round(collateral, 2),
        "contracts": 1,
        "total_cost": round(collateral, 2),
        "max_loss": round(collateral - credit, 2),
        "max_profit": round(credit, 2),
        "breakeven": round(c["strike"] - c["mid"], 2),
        "affordable": True,
        "rationale": [
            f"You are paid ${credit:,.0f} now. If the stock stays above ${c['strike']:g} you keep it "
            f"({credit / collateral * 100:.1f}% on the ${collateral:,.0f} set aside in {dte} days).",
            f"If it falls below, you buy 100 shares at ${c['strike']:g}, "
            f"{(1 - c['strike'] / spot) * 100:.1f}% under today's price, less the premium.",
            "Option prices are high relative to how much the stock has actually been moving, "
            "which favours selling rather than buying.",
        ],
        "warnings": _liquidity_warnings([c]) + [
            "Needs cash for 100 shares held as collateral, and broker approval to sell puts."],
        "exit_plan": "Buy the put back once you have kept half the premium, or take the shares if assigned.",
    }


def _covered_call(c: dict, dte: int, spot: float, shares: float) -> dict:
    credit = c["mid"] * 100.0
    contracts = int(shares // 100)
    return {
        "strategy": "Sell a covered call",
        "kind": "covered_call",
        "direction": "neutral",
        "legs": [_leg("sell", c)],
        "expiry": c["expiry"],
        "dte": dte,
        "net_cost": round(-credit, 2),
        "cost_label": "Credit received per contract",
        "contracts": contracts,
        "total_cost": 0.0,
        "max_loss": None,
        "max_profit": round((c["strike"] - spot) * 100.0 + credit, 2),
        "breakeven": round(spot - c["mid"], 2),
        "affordable": True,
        "rationale": [
            f"You already hold {shares:g} shares. Selling {contracts} call(s) at ${c['strike']:g} "
            f"pays ${credit * contracts:,.0f} while the signal is neutral.",
            f"The trade-off: your shares are sold at ${c['strike']:g} if the stock rallies past it.",
        ],
        "warnings": _liquidity_warnings([c]),
        "exit_plan": "Let it expire, or buy it back after keeping half the premium.",
    }


def recommend(*, spot: float, action: str, expirations: list[str], chain_for, hv30: float | None,
              settings: dict, cash: float, today: date, next_earnings: date | None = None,
              position: dict | None = None) -> dict:
    """Build options ideas for one stock.

    chain_for(expiry) returns the contracts for that expiry as dicts with
    type/strike/expiry/bid/ask/last/volume/open_interest/iv.
    """
    result: dict = {"ideas": [], "notes": [], "enabled": bool(settings.get("options_enabled", True))}
    if not result["enabled"]:
        result["notes"].append("Options recommendations are turned off in Settings.")
        return result

    budget = float(settings["budget"])
    risk_budget = budget * float(settings["option_risk_pct"]) / 100.0
    result["risk_budget"] = round(risk_budget, 2)

    held_shares = float(position["shares"]) if position else 0.0
    bullish = action in ("buy", "strong_buy")
    bearish = action in ("sell", "strong_sell")
    if not bullish and not bearish and held_shares < 100:
        result["notes"].append(
            "The stock signal is neutral, so there is no options trade. Options add leverage "
            "to a view; without one, time decay and spreads work against you.")
        return result

    picked = pick_expiry(expirations, today)
    if not picked:
        result["notes"].append("No listed options found for this symbol.")
        return result
    expiry, dte = picked
    fallback_vol = hv30 if hv30 and not math.isnan(hv30) and hv30 > 0 else 0.30
    contracts = enrich(chain_for(expiry), spot, dte, fallback_vol)
    if not contracts:
        result["notes"].append("The option chain has no usable quotes right now.")
        return result

    iv = atm_iv(contracts, spot)
    ratio = iv / fallback_vol if iv and fallback_vol else None
    regime = "normal"
    if ratio is not None:
        regime = "rich" if ratio >= IV_RICH else "cheap" if ratio <= IV_CHEAP else "normal"
    result.update({
        "expiry": expiry,
        "dte": dte,
        "atm_iv": round(iv, 4) if iv else None,
        "hv30": round(fallback_vol, 4),
        "iv_hv_ratio": round(ratio, 2) if ratio else None,
        "iv_regime": regime,
    })

    days_to_earnings = (next_earnings - today).days if next_earnings else None
    earnings_before_expiry = days_to_earnings is not None and 0 <= days_to_earnings <= dte
    earnings_imminent = days_to_earnings is not None and 0 <= days_to_earnings <= 7
    if earnings_before_expiry:
        result["notes"].append(
            f"Earnings on {next_earnings.isoformat()} fall before this expiry. Option prices "
            "usually drop right after the report, even when the stock moves your way.")

    ideas: list[dict] = []
    if bullish or bearish:
        kind = "call" if bullish else "put"
        long_c = _nearest_delta(contracts, kind, LONG_DELTA)
        short_c = _nearest_delta(contracts, kind, SHORT_LEG_DELTA,
                                 exclude_strike=long_c["strike"] if long_c else None)
        long_idea = _long_option(kind, long_c, dte, risk_budget) if long_c else None
        spread = None
        if long_c and short_c and (
            (bullish and short_c["strike"] > long_c["strike"]) or (bearish and short_c["strike"] < long_c["strike"])
        ):
            spread = _debit_spread(kind, long_c, short_c, dte, risk_budget)
        if long_c and (spread is None or not spread["affordable"]):
            spread = _fit_spread(contracts, kind, dte, risk_budget) or spread

        csp = None
        if bullish and regime == "rich":
            put = _nearest_delta(contracts, "put", INCOME_DELTA)
            position_cap = budget * float(settings["max_position_pct"]) / 100.0
            if put and put["strike"] * 100.0 <= min(cash, position_cap):
                csp = _cash_secured_put(put, dte, spot)

        if csp:
            ideas.append(csp)
        # Lead with the spread when buying outright is a poor deal or out of budget.
        prefer_spread = spread is not None and (
            earnings_imminent or regime == "rich" or (long_idea is not None and not long_idea["affordable"]))
        ordered = [spread, long_idea] if prefer_spread else [long_idea, spread]
        ideas.extend(i for i in ordered if i)

        if earnings_imminent:
            for idea in ideas:
                if idea["kind"] in ("long_call", "long_put"):
                    idea["warnings"].insert(
                        0, f"Earnings in {days_to_earnings} day(s): buying options now means paying "
                           "inflated prices that deflate after the report. Wait, or use the spread.")
        if regime == "rich":
            for idea in ideas:
                if idea["kind"] in ("long_call", "long_put"):
                    idea["warnings"].insert(
                        0, "Options are expensive right now relative to how much the stock moves.")
        for idea in ideas:
            if not idea["affordable"]:
                idea["warnings"].insert(
                    0, f"One contract costs ${idea['max_loss']:,.0f}, above your "
                       f"${risk_budget:,.0f} options risk per trade. Raise the budget or the "
                       "options risk setting to take it.")
        if bearish and held_shares > 0:
            result["notes"].append(
                "You hold this stock. Selling the shares is the simplest response to a sell "
                "signal; a put is the alternative if you want to stay invested but hedged.")

    if not bullish and not bearish and held_shares >= 100:
        call = _nearest_delta(contracts, "call", INCOME_DELTA)
        if call and call["strike"] > spot:
            ideas.append(_covered_call(call, dte, spot, held_shares))

    for i, idea in enumerate(ideas):
        idea["primary"] = i == 0
    result["ideas"] = ideas
    if not ideas:
        result["notes"].append("No contract fits the rules right now.")
    return result
