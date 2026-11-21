"""The trading rules.

Each strategy turns data into a Signal with a score in [-1, 1] (bearish to
bullish) and a fixed weight. The weighted sum is the composite score in
[-100, 100] that drives Buy / Hold / Sell.

The rules were chosen because they have published evidence behind them rather
than because they are popular (see docs/STRATEGIES.md for sources):

  trend       Price vs its 200-day average. Faber (2007): staying out below
              the ~10-month average kept equity-like returns with far smaller
              drawdowns. Also used as a hard gate: no new buys below it.
  momentum    12-month return skipping the last month. Jegadeesh & Titman (1993).
  high52      Nearness to the 52-week high. George & Hwang (2004).
  pullback    RSI(2) dips inside an uptrend as an entry timer (Connors).
  macd        MACD as a small confirmation of short-term direction.
  earnings    Post-earnings-announcement drift after a surprise. Bernard &
              Thomas (1989); weaker in large caps since ~2006, so modest weight.
  insiders    Open-market insider buying, especially several insiders at once.
              Cohen, Malloy & Pomorski (2012). Sales say much less.
  news        Headline tone. Tetlock (2007): real but lasts a day or two.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime

WEIGHTS = {
    "trend": 25,
    "momentum": 15,
    "high52": 10,
    "pullback": 10,
    "macd": 5,
    "earnings": 10,
    "insiders": 15,
    "news": 10,
}
TECHNICAL_KEYS = ("trend", "momentum", "high52", "pullback", "macd")
TECHNICAL_WEIGHT = sum(WEIGHTS[k] for k in TECHNICAL_KEYS)

BUY_THRESHOLD = 25
STRONG_THRESHOLD = 50

ACTION_LABELS = {
    "strong_buy": "Strong buy",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "strong_sell": "Strong sell",
}

# How long after a report an earnings surprise still counts (calendar days,
# roughly the 60 trading days the drift literature measures).
EARNINGS_DRIFT_DAYS = 85
INSIDER_WINDOW_DAYS = 90


@dataclass
class Signal:
    key: str
    name: str
    category: str
    score: float  # -1 bearish .. +1 bullish
    weight: int
    headline: str
    detail: str
    available: bool = True

    @property
    def points(self) -> float:
        return self.score * self.weight if self.available else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(self.score, 3)
        d["points"] = round(self.points, 1)
        return d


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _unavailable(key: str, name: str, category: str, why: str) -> Signal:
    return Signal(key, name, category, 0.0, WEIGHTS[key], why, "", available=False)


def _pct(x: float, signed: bool = True) -> str:
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


# --------------------------------------------------------------------------
# Technical strategies: computed from one row of the indicator frame.
# --------------------------------------------------------------------------

def trend_signal(r) -> Signal:
    name, cat = "Long-term trend", "trend"
    if _nan(r["sma200"]):
        return _unavailable("trend", name, cat, "Not enough price history for a 200-day average")
    above = r["close"] > r["sma200"]
    score = 0.6 if above else -0.6
    if not _nan(r["sma50"]):
        score += 0.2 if r["sma50"] > r["sma200"] else -0.2
    if not _nan(r["sma200_slope"]):
        score += 0.2 if r["sma200_slope"] > 0 else -0.2
    gap = r["close"] / r["sma200"] - 1.0
    headline = (
        f"Uptrend: {_pct(gap)} above the 200-day average" if above
        else f"Downtrend: {_pct(gap)} below the 200-day average"
    )
    detail = (
        "Stocks above their 200-day average have historically had better returns and "
        "far smaller drawdowns than stocks below it. Below the line, new buys are blocked."
    )
    return Signal("trend", name, cat, _clip(score), WEIGHTS["trend"], headline, detail)


def momentum_signal(r) -> Signal:
    name, cat = "12-month momentum", "trend"
    m = r["mom_12_1"]
    if _nan(m):
        return _unavailable("momentum", name, cat, "Needs a full year of price history")
    headline = f"{_pct(m)} over the past year (skipping the last month)"
    detail = (
        "Winners of the past 3-12 months tend to keep outperforming for several more "
        "months. The most recent month is skipped because it tends to reverse."
    )
    return Signal("momentum", name, cat, _clip(m / 0.30), WEIGHTS["momentum"], headline, detail)


def high52_signal(r) -> Signal:
    name, cat = "52-week high", "trend"
    if _nan(r["high252"]) or r["high252"] <= 0:
        return _unavailable("high52", name, cat, "Not enough price history for a 52-week high")
    d = r["close"] / r["high252"] - 1.0  # zero at the high, negative below it
    if d >= -0.05:
        score = 1.0
    elif d >= -0.15:
        score = (d + 0.15) / 0.10
    elif d >= -0.35:
        score = (d + 0.15) / 0.20
    else:
        score = -1.0
    headline = "At a 52-week high" if d >= -0.002 else f"{_pct(-d, signed=False)} below its 52-week high"
    detail = (
        "Stocks trading near their 52-week high tend to keep outperforming: investors "
        "anchor on the old high and are slow to price in good news."
    )
    return Signal("high52", name, cat, _clip(score), WEIGHTS["high52"], headline, detail)


def pullback_signal(r) -> Signal:
    name, cat = "Entry timing", "timing"
    if _nan(r["rsi2"]) or _nan(r["rsi14"]):
        return _unavailable("pullback", name, cat, "Not enough price history")
    uptrend = (not _nan(r["sma200"])) and r["close"] > r["sma200"]
    rsi2, rsi14 = r["rsi2"], r["rsi14"]
    if uptrend:
        if rsi2 < 10:
            score, headline = 1.0, f"Sharp pullback inside an uptrend (2-day RSI {rsi2:.0f})"
        elif rsi2 < 25:
            score, headline = 0.4, f"Mild pullback inside an uptrend (2-day RSI {rsi2:.0f})"
        elif rsi14 > 75:
            score, headline = -0.5, f"Overbought (14-day RSI {rsi14:.0f}): a pullback is likely"
        else:
            score, headline = 0.0, f"No timing edge today (14-day RSI {rsi14:.0f})"
    else:
        if rsi2 > 90:
            score, headline = -0.6, f"Bounce inside a downtrend (2-day RSI {rsi2:.0f})"
        elif rsi14 < 30:
            score, headline = 0.0, f"Oversold in a downtrend (14-day RSI {rsi14:.0f}): not a buy by itself"
        else:
            score, headline = 0.0, f"No timing edge today (14-day RSI {rsi14:.0f})"
    detail = (
        "Short dips in a rising stock tend to snap back within days, so they make "
        "better entries than chasing strength. Dips in a falling stock do not."
    )
    return Signal("pullback", name, cat, score, WEIGHTS["pullback"], headline, detail)


def macd_signal(r) -> Signal:
    name, cat = "MACD", "timing"
    if _nan(r["macd"]) or _nan(r["macd_hist"]):
        return _unavailable("macd", name, cat, "Not enough price history")
    rising, positive = r["macd_hist"] > 0, r["macd"] > 0
    if rising and positive:
        score, headline = 1.0, "Short-term momentum is positive and strengthening"
    elif rising:
        score, headline = 0.5, "Short-term momentum is turning up"
    elif positive:
        score, headline = -0.5, "Short-term momentum is fading"
    else:
        score, headline = -1.0, "Short-term momentum is negative and weakening"
    detail = "A minor confirmation signal: whether the last few weeks agree with the bigger trend."
    return Signal("macd", name, cat, score, WEIGHTS["macd"], headline, detail)


def technical_signals(r) -> list[Signal]:
    return [trend_signal(r), momentum_signal(r), high52_signal(r), pullback_signal(r), macd_signal(r)]


def technical_score(r) -> float:
    """Technical-only score rescaled to [-100, 100]; used by the backtester."""
    return sum(s.points for s in technical_signals(r)) / TECHNICAL_WEIGHT * 100.0


def technical_events(frame) -> list[dict]:
    """Things that happened on the latest bar and deserve an alert."""
    if len(frame) < 2:
        return []
    r, p = frame.iloc[-1], frame.iloc[-2]
    day = frame.index[-1]
    day = day.date().isoformat() if hasattr(day, "date") else str(day)
    events: list[dict] = []

    def add(kind: str, direction: str, title: str, body: str):
        events.append({"kind": kind, "direction": direction, "date": day, "title": title, "body": body})

    def crossed_up(a_now, b_now, a_prev, b_prev) -> bool:
        return not any(_nan(v) for v in (a_now, b_now, a_prev, b_prev)) and a_now > b_now and a_prev <= b_prev

    if crossed_up(r["sma50"], r["sma200"], p["sma50"], p["sma200"]):
        add("golden_cross", "bullish", "Golden cross",
            "The 50-day average crossed above the 200-day average, confirming a new uptrend.")
    if crossed_up(r["sma200"], r["sma50"], p["sma200"], p["sma50"]):
        add("death_cross", "bearish", "Death cross",
            "The 50-day average crossed below the 200-day average, confirming a downtrend.")
    if crossed_up(r["close"], r["sma200"], p["close"], p["sma200"]):
        add("trend_reclaim", "bullish", "Back above the 200-day average",
            f"Closed at {r['close']:.2f}, back above the 200-day average ({r['sma200']:.2f}).")
    if crossed_up(r["sma200"], r["close"], p["sma200"], p["close"]):
        add("trend_break", "bearish", "Fell below the 200-day average",
            f"Closed at {r['close']:.2f}, below the 200-day average ({r['sma200']:.2f}). "
            "The trend filter now blocks new buys.")
    uptrend = not _nan(r["sma200"]) and r["close"] > r["sma200"]
    if uptrend and not _nan(r["rsi2"]) and r["rsi2"] < 10:
        add("pullback_entry", "bullish", "Pullback entry",
            f"A sharp dip inside an uptrend (2-day RSI {r['rsi2']:.0f}). "
            "Historically a better entry point than buying strength.")
    if (not _nan(r["high252"]) and not _nan(p["high252"]) and r["close"] >= r["high252"]
            and p["close"] < p["high252"] and not _nan(r["vol_avg50"])
            and r["volume"] >= 1.5 * r["vol_avg50"]):
        add("breakout", "bullish", "Breakout to a 52-week high",
            f"New 52-week closing high on {r['volume'] / r['vol_avg50']:.1f}x normal volume.")
    if crossed_up(r["chandelier"], r["close"], p["chandelier"], p["close"]):
        add("chandelier_exit", "bearish", "Trailing stop broken",
            f"Closed at {r['close']:.2f}, below the trailing stop ({r['chandelier']:.2f}, "
            "3 ATRs under the 22-day high).")
    if not _nan(r["day_change"]) and abs(r["day_change"]) >= 0.05:
        direction = "bullish" if r["day_change"] > 0 else "bearish"
        add("big_move", direction, f"Moved {_pct(r['day_change'])} today",
            f"Closed at {r['close']:.2f}. Check the news for the cause before acting.")
    return events


# --------------------------------------------------------------------------
# Event and sentiment strategies.
# --------------------------------------------------------------------------

def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def earnings_signal(history: list[dict], today: date) -> Signal:
    name, cat = "Earnings surprise", "event"
    reported = [e for e in history if e.get("surprise_pct") is not None and _as_date(e.get("date"))]
    reported = [e for e in reported if _as_date(e["date"]) <= today]
    if not reported:
        return _unavailable("earnings", name, cat, "No recent earnings results available")
    last = max(reported, key=lambda e: _as_date(e["date"]))
    age = (today - _as_date(last["date"])).days
    surprise = float(last["surprise_pct"])
    verb = "Beat" if surprise >= 0 else "Missed"
    if age > EARNINGS_DRIFT_DAYS:
        return Signal("earnings", name, cat, 0.0, WEIGHTS["earnings"],
                      f"Last report was {age} days ago: too old to matter",
                      "Earnings surprises only move prices for about a quarter.")
    decay = 1.0 - age / EARNINGS_DRIFT_DAYS
    score = _clip(surprise / 10.0) * decay
    headline = f"{verb} EPS estimates by {abs(surprise):.1f}% {age} days ago"
    detail = (
        "After a surprise, prices tend to keep drifting the same way for weeks. The "
        "effect has faded in large, heavily covered stocks, so it gets a modest weight."
    )
    return Signal("earnings", name, cat, score, WEIGHTS["earnings"], headline, detail)


def summarize_insiders(trades: list[dict], today: date, window: int = INSIDER_WINDOW_DAYS) -> dict:
    """Open-market buys and sells in the window. Gifts, grants and option
    exercises are not opinions about the stock and are left out."""
    recent = []
    for t in trades:
        d = _as_date(t.get("date"))
        if d and 0 <= (today - d).days <= window:
            recent.append(t)
    buys = [t for t in recent if t.get("kind") == "buy"]
    sells = [t for t in recent if t.get("kind") == "sell"]
    return {
        "window_days": window,
        "buyers": sorted({t.get("insider") or "?" for t in buys}),
        "sellers": sorted({t.get("insider") or "?" for t in sells}),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_value": float(sum(t.get("value") or 0 for t in buys)),
        "sell_value": float(sum(t.get("value") or 0 for t in sells)),
        "last_buy_date": max((str(t["date"])[:10] for t in buys), default=None),
    }


def _money(x: float) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"${x / size:.1f}{suffix}"
    return f"${x:.0f}"


def insider_signal(trades: list[dict] | None, today: date) -> Signal:
    name, cat = "Insider trades", "event"
    if trades is None:
        return _unavailable("insiders", name, cat, "Insider filings unavailable")
    s = summarize_insiders(trades, today)
    n_buy, n_sell = len(s["buyers"]), len(s["sellers"])
    if n_buy >= 3:
        score = 1.0
        headline = f"Cluster buying: {n_buy} insiders bought {_money(s['buy_value'])} in {s['window_days']} days"
    elif n_buy == 2:
        score = 0.7
        headline = f"2 insiders bought {_money(s['buy_value'])} in {s['window_days']} days"
    elif n_buy == 1:
        score = 0.4
        headline = f"{s['buyers'][0].title()} bought {_money(s['buy_value'])} of stock"
    elif n_sell >= 3:
        score = -0.3
        headline = f"{n_sell} insiders sold {_money(s['sell_value'])} in {s['window_days']} days, none bought"
    elif n_sell >= 1:
        score = -0.1
        headline = f"Insider selling only ({_money(s['sell_value'])}), usually routine"
    else:
        score = 0.0
        headline = f"No open-market insider trades in {s['window_days']} days"
    if n_buy and n_sell:
        # Buying is the informative side, but offsetting sales temper it.
        score -= 0.1 * min(n_sell, 3)
        headline += f"; {n_sell} sold"
    detail = (
        "Insiders sell for many reasons (taxes, diversification, scheduled plans) but "
        "buy with their own cash for one. Several insiders buying at once is the "
        "strongest version of this signal; sales are mostly noise."
    )
    return Signal("insiders", name, cat, _clip(score), WEIGHTS["insiders"], headline, detail)


def news_signal(sentiment: dict | None) -> Signal:
    name, cat = "News tone", "sentiment"
    if not sentiment or sentiment.get("count", 0) < 2:
        return _unavailable("news", name, cat, "Too few recent headlines to judge")
    score = _clip(sentiment["score"] * 1.5)
    tone = "positive" if score >= 0.25 else "negative" if score <= -0.25 else "mixed"
    headline = (
        f"Headlines are {tone}: {sentiment['positive']} positive, "
        f"{sentiment['negative']} negative of {sentiment['count']} this week"
    )
    detail = "Headline tone nudges prices for a day or two, so it is a small tie-breaker, not a reason to trade."
    return Signal("news", name, cat, score, WEIGHTS["news"], headline, detail)


# --------------------------------------------------------------------------
# Composite.
# --------------------------------------------------------------------------

def decide(signals: list[Signal]) -> dict:
    """Combine signals into a score and an action, applying the trend gate."""
    score = sum(s.points for s in signals)
    if score >= STRONG_THRESHOLD:
        action = "strong_buy"
    elif score >= BUY_THRESHOLD:
        action = "buy"
    elif score <= -STRONG_THRESHOLD:
        action = "strong_sell"
    elif score <= -BUY_THRESHOLD:
        action = "sell"
    else:
        action = "hold"

    gate_note = None
    trend = next((s for s in signals if s.key == "trend"), None)
    if action in ("buy", "strong_buy"):
        if trend is None or not trend.available:
            action = "hold"
            gate_note = "Not enough history to confirm an uptrend, so this stays a Hold."
        elif trend.score < 0:  # negative only when the close is below the 200-day average
            action = "hold"
            gate_note = "Other signals are positive, but the price is below its 200-day average. The trend filter blocks new buys."

    ranked = sorted((s for s in signals if s.available and abs(s.points) >= 1.0),
                    key=lambda s: -abs(s.points))
    agree = [s for s in ranked if (s.points > 0) == (score >= 0)]
    reasons = [s.headline for s in (agree or ranked)[:3]]
    return {
        "score": round(score, 1),
        "action": action,
        "action_label": ACTION_LABELS[action],
        "gate_note": gate_note,
        "reasons": reasons,
    }


def direction_of(action: str) -> str:
    if action in ("buy", "strong_buy"):
        return "bullish"
    if action in ("sell", "strong_sell"):
        return "bearish"
    return "neutral"
