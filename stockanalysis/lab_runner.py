"""Run one indicator tactic on one stock's history (the Indicator Lab playground)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from . import tactics as T
from .validation.portfolio import curve_metrics

LAB_REPORT_PATHS = [
    Path(__file__).resolve().parent.parent / "data" / "validation" / "lab.json",
    Path(__file__).resolve().parent / "validation" / "latest_lab.json",
]


def load_lab_report() -> dict | None:
    for path in LAB_REPORT_PATHS:
        if path.exists():
            return json.loads(path.read_text())
    return None


def tactic_catalog() -> list[dict]:
    """Every tactic with its adjustable settings and what the historical test found."""
    report = load_lab_report() or {}
    found = {f["key"]: f for f in report.get("families", [])}
    out = []
    for key, t in T.TACTICS.items():
        f = found.get(key)
        out.append({
            "key": key, "name": t.name, "style": t.style, "summary": t.summary,
            "params": [{"key": p.key, "label": p.label, "default": p.default, "min": p.lo, "max": p.hi,
                        "step": p.step, "kind": p.kind, "help": p.help} for p in t.params],
            "tested": None if not f else {
                "best_params": f["best_params"], "best_label": f["best_label"],
                "settings_tried": f["settings_tried"], "train_edge": f["train_edge"],
                "validation_edge": f["validation_edge"], "test_edge": f["test_edge"],
                "rank_corr": f["rank_corr_train_vs_validation"],
            },
        })
    return out


def run(df: pd.DataFrame, tactic: str, params: dict | None, tbill: pd.Series | None = None,
        cost: float = 0.001) -> dict:
    params = T.clean_params(tactic, params)
    close, open_ = df[["close"]], df[["open"]]
    held = T.positions(tactic, params, close)
    cash = None
    if tbill is not None and len(tbill.dropna()):
        cash = (tbill.reindex(df.index).ffill().fillna(0) / 100 / 252).clip(lower=0)
    rets = T.backtest(open_, close, held, cash, cost)["close"]
    hold = T.backtest(open_, close, close.notna(), cash, cost)["close"]
    # Start the comparison once every indicator has enough history (up to about 400 days).
    warmup = int(max([v for k, v in params.items() if k not in ("k", "buy_below", "sell_above")] + [252]))
    start = close.index[min(len(close) - 1, min(warmup, len(close) // 2))]
    strat_curve = (1 + rets.loc[start:]).cumprod()
    hold_curve = (1 + hold.loc[start:]).cumprod()
    h = held["close"]

    trades, entry = [], None
    dates, opens = df.index, df["open"].to_numpy()
    # Entries/exits happen at the open after the signal day.
    flips = h.ne(h.shift(1, fill_value=False))
    for i in [k for k in range(len(h)) if flips.iloc[k] and dates[k] >= start]:
        nxt = i + 1
        if nxt >= len(h):
            break
        px = opens[nxt] if not math.isnan(opens[nxt]) else df["close"].iloc[i]
        if h.iloc[i]:
            entry = (dates[nxt], px)
        elif entry is not None:
            trades.append({"entry_date": entry[0].date().isoformat(), "entry": round(float(entry[1]), 2),
                           "exit_date": dates[nxt].date().isoformat(), "exit": round(float(px), 2),
                           "days": int((dates[nxt] - entry[0]).days),
                           "return_pct": round(float(px / entry[1] - 1) * 100 - 2 * cost * 100, 2)})
            entry = None
    open_trade = None
    if entry is not None:
        last = float(df["close"].iloc[-1])
        open_trade = {"entry_date": entry[0].date().isoformat(), "entry": round(float(entry[1]), 2),
                      "return_pct": round(float(last / entry[1] - 1) * 100, 2)}

    wins = [t for t in trades if t["return_pct"] > 0]
    step = max(1, len(strat_curve) // 400)
    idx = list(range(0, len(strat_curve), step))
    if idx[-1] != len(strat_curve) - 1:
        idx.append(len(strat_curve) - 1)
    window = df.loc[start:]
    held_w = h.loc[start:]
    return {
        "tactic": tactic,
        "params": params,
        "label": T.describe(tactic, params),
        "start": start.date().isoformat(),
        "end": df.index[-1].date().isoformat(),
        "holding_now": bool(h.iloc[-1]),
        "strategy": curve_metrics(strat_curve, cash),
        "hold": curve_metrics(hold_curve, cash),
        "stats": {**T.trade_stats(held.loc[start:]), "trades": len(trades),
                  "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else None,
                  "avg_trade_pct": round(sum(t["return_pct"] for t in trades) / len(trades), 2) if trades else None},
        "trades": trades[-25:][::-1],
        "open_trade": open_trade,
        "chart": {
            "dates": [d.date().isoformat() for d in window.index[idx]],
            "price": [round(float(v), 2) for v in window["close"].iloc[idx]],
            "holding_price": [round(float(v), 2) if bool(hh) else None
                              for v, hh in zip(window["close"].iloc[idx], held_w.iloc[idx])],
            "strategy": [round(float(v) * 100, 2) for v in strat_curve.iloc[idx]],
            "hold": [round(float(v) * 100, 2) for v in hold_curve.iloc[idx]],
        },
    }
