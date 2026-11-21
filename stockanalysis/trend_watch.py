"""Trend alerts for other markets and the 8-asset trend portfolio.

Both use Faber's 10-month rule: hold while the last month-end close is above
the 10-month (210-day) average, otherwise sit in cash. Decisions are made only
at completed month ends, so an alert arrives on the first scan after a month's
last close, once per change.

Testing (docs/MARKETS.md) found the rule most useful in commodity funds and
Ether; the trend portfolio had the smallest crashes of anything tested but
earned less than a plain 60/40 mix.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd

from .validation.markets import FABER, MARKETS, faber_positions

log = logging.getLogger("stockanalysis.trend")

PERIOD = "5y"
NAMES = {sym: name for sym, name, _ in MARKETS}
# Used when no test report is available: the markets where most trend rules beat holding.
FALLBACK_TREND_FRIENDLY = ["USO", "UNG", "DBC", "DBA", "FXE", "QQQ", "ETH-USD"]
HISTORY_MONTHS = 24


def name_of(symbol: str) -> str:
    return NAMES.get(symbol, symbol)


def trend_friendly() -> list[str]:
    """Markets where at least 3 of the 4 trend rules beat holding (from the test report)."""
    from .markets_view import _tested, load_report
    report = load_report() or {}
    rows = report.get("markets") or []
    picks = [r["symbol"] for r in rows if (_tested(r) or {}).get("trend_wins", 0) >= 3
             and not r["symbol"].endswith("=F")]   # futures prices ignore roll costs: use the funds
    return picks or list(FALLBACK_TREND_FRIENDLY)


def alert_symbols(settings: dict) -> list[str]:
    chosen = settings.get("trend_alert_symbols")
    return trend_friendly() if chosen is None else list(chosen)


def _month_ends(index: pd.DatetimeIndex) -> pd.Series:
    month = pd.Series(index.to_period("M"), index=index)
    ends = month.ne(month.shift(-1))
    ends.iloc[-1] = False    # the latest day is not a month end until the month is over
    return ends


def band_of(settings: dict) -> float:
    return float(settings.get("trend_band_pct") or 0.0) / 100.0


def signal(df: pd.DataFrame, band: float = 0.0) -> tuple[dict, pd.Series] | None:
    """Current 10-month-rule state of one market, plus its daily held series.

    `band` (e.g. 0.02): buy only on a month-end close that far above the
    average, sell only on one that far below.
    """
    close = df["close"].dropna()
    if len(close) < 212:
        return None
    held = faber_positions(close.to_frame("c"), band)["c"]
    ma = close.rolling(210).mean()
    ends = _month_ends(close.index)
    end_days = close.index[ends.values & ma.notna().values]
    if not len(end_days):
        return None
    decided = end_days[-1]
    flips = held.ne(held.shift(1))
    flips.iloc[0] = False
    since = held.index[flips.values][-1].date().isoformat() if flips.any() else None
    price, avg = float(close.iloc[-1]), float(ma.iloc[-1])
    holding = bool(held.iloc[-1])
    buy_level, sell_level = avg * (1 + band), avg * (1 - band)
    return {
        "holding": holding,
        "decided_on": decided.date().isoformat(),
        "decided_close": round(float(close.loc[decided]), 4),
        "decided_average": round(float(ma.loc[decided]), 4),
        "since": since,
        "price": round(price, 4),
        "average": round(avg, 4),
        "gap_pct": round((price / avg - 1) * 100, 2),
        "band_pct": round(band * 100, 2),
        "buy_level": round(buy_level, 4),
        "sell_level": round(sell_level, 4),
        # If the month ended today, would the rule change its mind?
        "flip_pending": (price < sell_level) if holding else (price > buy_level),
        "as_of": close.index[-1].date().isoformat(),
    }, held


def next_check(today: date) -> str:
    """The last trading day of this month (weekends skipped; holidays not)."""
    return pd.offsets.BMonthEnd().rollforward(pd.Timestamp(today)).date().isoformat()


def portfolio_history(helds: dict[str, pd.Series], months: int = HISTORY_MONTHS) -> list[dict]:
    """Month ends where the trend portfolio changed what it held, newest first."""
    frame = pd.DataFrame(helds).dropna(how="all")
    if frame.empty:
        return []
    frame = frame.fillna(False).astype(bool)
    ends = frame.index[_month_ends(frame.index).values]
    monthly = frame.loc[ends]
    changes = []
    for i in range(1, len(monthly)):
        before, after = monthly.iloc[i - 1], monthly.iloc[i]
        bought = [s for s in monthly.columns if after[s] and not before[s]]
        sold = [s for s in monthly.columns if before[s] and not after[s]]
        if bought or sold:
            changes.append({"date": monthly.index[i].date().isoformat(), "bought": bought, "sold": sold,
                            "holding": int(after.sum())})
    return changes[::-1][:months]


class TrendWatch:
    """Keeps track of the 10-month rule for chosen markets and the trend portfolio."""

    def __init__(self, db, provider, today_fn=None):
        self.db = db
        self.provider = provider
        self._today_fn = today_fn or date.today

    # ------------------------------------------------------------------
    def _signals(self, symbols: list[str], band: float = 0.0) -> tuple[dict, dict]:
        def load(sym):
            try:
                return signal(self.provider.history(sym, PERIOD), band)
            except Exception as exc:
                log.warning("Trend data unavailable for %s: %s", sym, exc)
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = dict(zip(symbols, pool.map(load, symbols)))
        signals = {s: r[0] for s, r in results.items() if r}
        helds = {s: r[1] for s, r in results.items() if r}
        return signals, helds

    def snapshot(self) -> dict:
        settings = self.db.get_settings()
        watched = alert_symbols(settings)
        symbols = list(dict.fromkeys([*watched, *FABER]))
        band = band_of(settings)
        signals, helds = self._signals(symbols, band)
        budget = float(settings["budget"])
        slot = budget / len(FABER)
        assets = []
        for sym in FABER:
            sig = signals.get(sym)
            assets.append({"symbol": sym, "name": name_of(sym), "signal": sig,
                           "amount": round(slot, 2) if sig and sig["holding"] else 0.0})
        invested = sum(a["amount"] for a in assets)
        complete = all(a["signal"] for a in assets)
        return {
            "alerts": {
                "symbols": watched,
                "using_default": settings.get("trend_alert_symbols") is None,
                "default_symbols": trend_friendly(),
                "signals": {s: signals.get(s) for s in watched},
                "names": {s: name_of(s) for s in watched},
            },
            "band_pct": round(band * 100, 2),
            "portfolio": {
                "alerts_on": bool(settings["trend_portfolio_alerts"]),
                "complete": complete,
                "budget": budget,
                "slot": round(slot, 2),
                "assets": assets,
                "invested": round(invested, 2),
                "cash": round(budget - invested, 2),
                "holding": [a["symbol"] for a in assets if a["amount"]],
                "next_check": next_check(self._today_fn()),
                "changes": portfolio_history({s: helds[s] for s in FABER if s in helds}),
            },
        }

    # ------------------------------------------------------------------
    def update(self, notify: bool = True) -> dict:
        """Recompute and alert on any change since the last scan."""
        snap = self.snapshot()
        settings = self.db.get_settings()
        for sym, sig in snap["alerts"]["signals"].items():
            if not sig:
                continue
            key = f"trend_hold:{sym}"
            previous = self.db.get_state(key)
            if previous is not None and previous != sig["holding"] and notify:
                self._market_alert(sym, sig)
            self.db.set_state(key, sig["holding"])

        port = snap["portfolio"]
        if port["complete"]:
            now = sorted(port["holding"])
            previous = self.db.get_state("trend_portfolio")
            if previous is not None and previous != now and notify and settings["trend_portfolio_alerts"]:
                self._portfolio_alert(previous, port)
            self.db.set_state("trend_portfolio", now)
        return snap

    def _market_alert(self, sym: str, sig: dict):
        from .markets_view import _tested, load_report
        name = name_of(sym)
        month = pd.Timestamp(sig["decided_on"]).strftime("%B")
        close, avg = sig["decided_close"], sig["decided_average"]
        band = sig.get("band_pct") or 0
        margin = f" by more than {band:g}%" if band else ""
        if sig["holding"]:
            title, tone = f"{name} turned up: 10-month rule says hold", "bullish"
            what = (f"{name} ({sym}) closed {month} at {close:,.2f}, above its 10-month average of {avg:,.2f}{margin}. "
                    "The 10-month rule moves back in.")
        else:
            title, tone = f"{name} turned down: 10-month rule says cash", "bearish"
            what = (f"{name} ({sym}) closed {month} at {close:,.2f}, below its 10-month average of {avg:,.2f}{margin}. "
                    "The 10-month rule steps aside until a month ends back above it"
                    + (f" by more than {band:g}%." if band else "."))
        row = next((r for r in (load_report() or {}).get("markets", []) if r["symbol"] == sym), None)
        tested = _tested(row)
        note = (f" In testing, {tested['trend_wins']} of 4 trend rules beat simply holding {name.lower()}."
                if tested else "")
        self.db.add_notification(symbol=sym, kind="market_trend", tone=tone, title=f"{sym}: {title}",
                                 body=what + note, dedup_key=f"trend:{sym}:{sig['decided_on']}:{sig['holding']}")

    def _portfolio_alert(self, previous: list[str], port: dict):
        now = set(port["holding"])
        bought = [s for s in FABER if s in now and s not in previous]
        sold = [s for s in FABER if s not in now and s in previous]
        slot = port["slot"]
        parts = []
        if bought:
            parts.append("Buy " + ", ".join(f"{name_of(s)} ({s})" for s in bought)
                         + f": about ${slot:,.0f} each with your budget.")
        if sold:
            parts.append("Sell " + ", ".join(f"{name_of(s)} ({s})" for s in sold)
                         + " and hold that share in T-bills or cash.")
        parts.append(f"Now holding {len(now)} of {len(FABER)}: about ${port['invested']:,.0f} invested, "
                     f"${port['cash']:,.0f} in cash.")
        verbs = [w for w, xs in (("buy", bought), ("sell", sold)) if xs]
        title = "Trend portfolio: " + " and ".join(
            f"{v} {', '.join(xs)}" for v, xs in zip(verbs, [x for x in (bought, sold) if x]))
        day = next((a["signal"]["decided_on"] for a in port["assets"] if a["signal"]), "")
        self.db.add_notification(symbol=None, kind="trend_portfolio", tone="info", title=title,
                                 body=" ".join(parts), dedup_key=f"trend_portfolio:{day}:{','.join(sorted(now))}")
