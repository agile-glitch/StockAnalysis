"""Live view of other markets (gold, silver, oil, bonds, currencies, crypto...)
combined with what the historical test found for each one."""

from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from .validation.markets import FABER, MARKETS, RULES, faber_positions

REPORT_PATHS = [
    Path(__file__).resolve().parent.parent / "data" / "validation" / "markets.json",
    Path(__file__).resolve().parent / "validation" / "latest_markets.json",
]
CACHE_SECONDS = 300
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def load_report() -> dict | None:
    for path in REPORT_PATHS:
        if path.exists():
            return json.loads(path.read_text())
    return None


def _live(provider, symbol: str) -> dict:
    try:
        df = provider.history(symbol, "2y")
    except Exception as exc:
        return {"error": str(exc)}
    close = df["close"].dropna()
    if len(close) < 2:
        return {"error": "Not enough data"}
    sma200 = close.rolling(200).mean().iloc[-1]
    held = faber_positions(close.to_frame())["close"]
    step = max(1, len(close.iloc[-250:]) // 60)
    return {
        "price": round(float(close.iloc[-1]), 4),
        "change_pct": round(float(close.iloc[-1] / close.iloc[-2] - 1) * 100, 2),
        "return_1y_pct": round(float(close.iloc[-1] / close.iloc[-253] - 1) * 100, 1) if len(close) > 253 else None,
        "above_200": None if math.isnan(sma200) else bool(close.iloc[-1] > sma200),
        "trend_hold": bool(held.iloc[-1]),
        "as_of": close.index[-1].date().isoformat(),
        "spark": [round(float(v), 4) for v in close.iloc[-250::step]],
    }


def _tested(row: dict | None) -> dict | None:
    if not row:
        return None
    rules = {}
    for key, label in RULES.items():
        r = row["rules"][key]
        rules[key] = {"label": label, "edge": r["full"]["edge"], "first_half": r["first_half"]["edge"],
                      "second_half": r["second_half"]["edge"], "cagr_pct": r["full"].get("cagr_pct"),
                      "max_drawdown_pct": r["full"].get("max_drawdown_pct"),
                      "consistent": r["full"]["edge"] > 0 and r["first_half"]["edge"] > 0 and r["second_half"]["edge"] > 0}
    consistent = [k for k, v in rules.items() if v["consistent"]]
    best = max(consistent, key=lambda k: rules[k]["edge"]) if consistent else None
    hold = row["hold"]["full"]
    # Agreement among the four trend rules is sturdier evidence than any one rule
    # that happened to win: with six rules per market, one "winner" is likely by chance.
    trend_keys = ("faber", "ma200", "cross", "breakout")
    trend_wins = sum(rules[k]["edge"] > 0.02 for k in trend_keys)
    if trend_wins >= 3:
        verdict, tone = "Trend-friendly: most trend rules beat holding", "bullish"
    elif trend_wins <= 1:
        verdict, tone = "Holding was as good or better", "neutral"
    else:
        verdict, tone = "Mixed: some trend rules helped", "warning"
    return {"years": row["years"], "start": row["start"], "hold": {k: hold.get(k) for k in ("cagr_pct", "max_drawdown_pct", "sharpe")},
            "rules": rules, "consistent": consistent, "best_consistent": best, "trend_wins": trend_wins,
            "verdict": verdict, "tone": tone}


def overview(provider, engine=None) -> dict:
    with _lock:
        if _cache["data"] and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
    report = load_report() or {}
    rows = {r["symbol"]: r for r in report.get("markets", [])}
    with ThreadPoolExecutor(max_workers=6) as pool:
        live = dict(zip([m[0] for m in MARKETS], pool.map(lambda m: _live(provider, m[0]), MARKETS)))
    markets = [{"symbol": sym, "name": name, "class": cls, "live": live[sym], "tested": _tested(rows.get(sym))}
               for sym, name, cls in MARKETS]
    faber = report.get("faber")
    if faber:
        faber = {**faber, "holding_now_live": {s: live.get(s, {}).get("trend_hold") for s in FABER}}
    persistence = report.get("persistence")
    if persistence:
        persistence = {"stocks": persistence["stocks"],
                       "rules": {k: {kk: v[kk] for kk in ("label", "rank_corr_A_vs_B", "share_beating_hold_A",
                                                         "share_beating_hold_B", "top_quintile_edge_A",
                                                         "top_quintile_edge_B", "bottom_quintile_edge_B",
                                                         "edge_B_by_volatility_A", "best_in_A", "traits")}
                                 for k, v in persistence["rules"].items()}}
    data = {"markets": markets, "faber": faber, "persistence": persistence, "rules": RULES,
            "tested_available": bool(rows)}
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data
