"""Headline sentiment from a small finance word list.

General-purpose sentiment dictionaries misfire on financial text ("liability",
"tax" and "cost" are not bad news for a company), so this uses a hand-picked
list in the spirit of the Loughran-McDonald finance lexicon. It is deliberately
simple: it runs offline, is easy to audit, and research finds headline tone only
moves prices for a day or two anyway, so it carries a small weight.
"""

from __future__ import annotations

import math
import re
import time

POSITIVE = {
    "beat", "beats", "beating", "tops", "topped", "exceeds", "exceeded", "surpasses",
    "surge", "surges", "surged", "soar", "soars", "soared", "jump", "jumps", "jumped",
    "rally", "rallies", "rallied", "climb", "climbs", "climbed", "gain", "gains", "gained",
    "rise", "rises", "rose", "rebound", "rebounds", "rebounded", "recover", "recovers",
    "upgrade", "upgrades", "upgraded", "outperform", "outperforms", "overweight", "bullish",
    "raise", "raises", "raised", "boost", "boosts", "boosted", "hike", "hikes",
    "record", "strong", "stronger", "strength", "robust", "growth", "grows", "grew",
    "profit", "profits", "profitable", "win", "wins", "won", "approval", "approved",
    "approves", "breakthrough", "buyback", "dividend", "expands", "expansion", "momentum",
    "optimistic", "optimism", "upbeat", "accelerates", "accelerating", "milestone",
    "partnership", "awarded", "outpaces", "blowout", "upside", "breakout",
}

NEGATIVE = {
    "miss", "misses", "missed", "plunge", "plunges", "plunged", "tumble", "tumbles",
    "tumbled", "sink", "sinks", "sank", "slump", "slumps", "slumped", "slide", "slides",
    "slid", "fall", "falls", "fell", "drop", "drops", "dropped", "decline", "declines",
    "declined", "crash", "crashes", "crashed", "selloff", "plummet", "plummets", "plummeted",
    "downgrade", "downgrades", "downgraded", "underperform", "underweight", "bearish",
    "cut", "cuts", "slash", "slashes", "slashed", "lowers", "lowered",
    "weak", "weaker", "weakness", "loss", "losses", "lawsuit", "sued", "sues", "probe",
    "investigation", "investigates", "subpoena", "fraud", "recall", "recalls", "layoffs",
    "layoff", "bankruptcy", "bankrupt", "default", "warning", "warns", "warned", "fears",
    "concern", "concerns", "worries", "worried", "risk", "risks", "delay", "delays",
    "delayed", "halt", "halts", "halted", "ban", "banned", "fine", "fined", "penalty",
    "shortfall", "disappoints", "disappointing", "disappointed", "struggles", "struggling",
    "trouble", "scandal", "breach", "hack", "hacked", "resigns", "ousted", "downside",
    "tariff", "tariffs", "bubble", "overvalued",
}

NEGATORS = {"not", "no", "never", "without", "fails", "failed", "despite", "less", "avoid", "avoids"}

_WORD = re.compile(r"[a-z']+")


def score_text(text: str) -> float | None:
    """Tone of one headline in [-1, 1]; None when it carries no signal words."""
    words = _WORD.findall((text or "").lower())
    pos = neg = 0
    for i, word in enumerate(words):
        negated = any(w in NEGATORS for w in words[max(0, i - 2):i])
        if word in POSITIVE:
            if negated:
                neg += 1
            else:
                pos += 1
        elif word in NEGATIVE:
            if negated:
                pos += 1
            else:
                neg += 1
    if pos + neg == 0:
        return None
    return (pos - neg) / (pos + neg)


_GENERIC_NAME_WORDS = {"the", "inc", "corp", "corporation", "company", "co", "ltd", "plc", "group",
                       "holdings", "trust", "fund", "etf", "class", "common", "stock", "shares"}


def is_about(text: str, symbol: str, name: str | None) -> bool:
    """Does a headline mention this company? Ticker feeds mix in general market
    stories, and their tone says nothing about the stock."""
    if re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", text or ""):
        return True
    lowered = (text or "").lower()
    for word in re.findall(r"[a-z]+", (name or "").lower()):
        if word not in _GENERIC_NAME_WORDS and len(word) >= 3:
            return bool(re.search(rf"\b{re.escape(word)}", lowered))  # first distinctive word of the name
    return False


def label(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score >= 0.25:
        return "positive"
    if score <= -0.25:
        return "negative"
    return "neutral"


def aggregate(items: list[dict], now: float | None = None, half_life_days: float = 2.0,
              max_age_days: float = 7.0) -> dict:
    """Recency-weighted average tone of recent headlines.

    Each item needs "title", optional "summary", and "published" (epoch seconds).
    """
    now = now or time.time()
    total = weight_sum = 0.0
    counted = pos = neg = 0
    for item in items:
        age_days = (now - (item.get("published") or 0)) / 86400.0
        if age_days > max_age_days or age_days < -1:
            continue
        score = item.get("sentiment")
        if score is None:
            continue
        weight = math.pow(0.5, max(age_days, 0.0) / half_life_days)
        total += score * weight
        weight_sum += weight
        counted += 1
        if score >= 0.25:
            pos += 1
        elif score <= -0.25:
            neg += 1
    avg = total / weight_sum if weight_sum else 0.0
    return {"score": round(avg, 3), "count": counted, "positive": pos, "negative": neg}
