"""A plain backtest of the price-based rules on one stock.

It answers "would following these timing rules have helped on this stock?" by
replaying the technical score day by day: buy at the next open once the score
reaches Buy while the price is above its 200-day average and its trailing
stop, sell at the next open
when the trailing stop breaks, the price falls under the 200-day average, or
the score turns to Sell.

It only tests the price rules. News, earnings and insider signals are left out
because their history is not available, and it ignores commissions and taxes.
Past results on one stock say little about the future; the main thing to look
at is whether drawdowns were smaller than simply holding.
"""

from __future__ import annotations

import math

import pandas as pd

from .indicators import build_frame
from .strategies import BUY_THRESHOLD, technical_score


def _max_drawdown(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


def run_backtest(df: pd.DataFrame) -> dict:
    frame = build_frame(df)
    rows = frame.to_dict("records")
    dates = [d.date().isoformat() for d in frame.index]
    start = next((i for i, r in enumerate(rows)
                  if not math.isnan(r["sma200"]) and not math.isnan(r["mom_12_1"])), None)
    if start is None or len(rows) - start < 60:
        return {"available": False, "reason": "Needs about two years of price history."}

    cash, shares = 1.0, 0.0
    entry_price = 0.0
    pending: str | None = None  # order decided at the previous close
    trades: list[dict] = []
    equity: list[float] = []
    days_in_market = 0

    for i in range(start, len(rows)):
        r = rows[i]
        if pending == "buy":
            shares, cash, entry_price = cash / r["open"], 0.0, r["open"]
            trades.append({"entry_date": dates[i], "entry": round(r["open"], 2)})
        elif pending == "sell":
            cash, shares = shares * r["open"], 0.0
            trades[-1].update({
                "exit_date": dates[i], "exit": round(r["open"], 2),
                "return_pct": round((r["open"] / entry_price - 1) * 100, 1),
            })
        pending = None

        equity.append(cash + shares * r["close"])
        if shares:
            days_in_market += 1

        score = technical_score(r)
        stop_broken = not math.isnan(r["chandelier"]) and r["close"] < r["chandelier"]
        if not shares:
            # Do not buy straight back in while the price is still under the trailing stop.
            if score >= BUY_THRESHOLD and r["close"] > r["sma200"] and not stop_broken:
                pending = "buy"
        else:
            if stop_broken or r["close"] < r["sma200"] or score <= -BUY_THRESHOLD:
                pending = "sell"

    closed = [t for t in trades if "exit" in t]
    wins = [t for t in closed if t["return_pct"] > 0]
    years = (len(rows) - start) / 252.0
    first_close, last_close = rows[start]["close"], rows[-1]["close"]
    hold_curve = [r["close"] / first_close for r in rows[start:]]

    step = max(1, len(equity) // 150)
    idx = list(range(0, len(equity), step))
    if idx[-1] != len(equity) - 1:
        idx.append(len(equity) - 1)

    return {
        "available": True,
        "start": dates[start],
        "end": dates[-1],
        "years": round(years, 1),
        "strategy_return_pct": round((equity[-1] - 1) * 100, 1),
        "buy_hold_return_pct": round((last_close / first_close - 1) * 100, 1),
        "strategy_max_drawdown_pct": round(_max_drawdown(equity) * 100, 1),
        "buy_hold_max_drawdown_pct": round(_max_drawdown(hold_curve) * 100, 1),
        "trades": len(trades),
        "closed_trades": len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 0) if closed else None,
        "avg_trade_pct": round(sum(t["return_pct"] for t in closed) / len(closed), 1) if closed else None,
        "time_in_market_pct": round(days_in_market / len(equity) * 100, 0),
        "open_trade": bool(shares),
        "recent_trades": trades[-8:][::-1],
        "curve": {
            "dates": [dates[start + i] for i in idx],
            "strategy": [round(equity[i] * 100, 2) for i in idx],
            "buy_hold": [round(hold_curve[i] * 100, 2) for i in idx],
        },
    }
