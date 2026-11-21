"""The analysis engine: pulls data for each watched stock, runs the strategies,
sizes the trade from the budget, and turns changes into notifications."""

from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import options as options_mod
from . import sentiment as sentiment_mod
from . import strategies
from .backtest import run_backtest
from .db import Database
from .indicators import build_frame
from .providers import CachedProvider, ProviderError
from .sizing import available_cash, plan_trade

log = logging.getLogger("stockanalysis")

SCAN_WORKERS = 3
EARNINGS_WARNING_DAYS = 7
INSIDER_ALERT_DAYS = 14


def _clean(obj):
    """Make a structure JSON-safe: numpy scalars to Python, NaN/inf to None."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def _round_list(series, digits: int = 2) -> list:
    return [None if (v is None or math.isnan(v)) else round(float(v), digits) for v in series]


class Engine:
    def __init__(self, db: Database, provider: CachedProvider, today_fn=None):
        self.db = db
        self.provider = provider
        self._today_fn = today_fn or date.today
        self.analyses: dict[str, dict] = db.load_analyses()
        self._scan_lock = threading.Lock()
        self._backtests: dict[tuple, dict] = {}
        self.status = {"scanning": False, "last_scan": None, "last_error": None}

    def today(self) -> date:
        return self._today_fn()

    # ------------------------------------------------------------------
    # Analysis of one symbol
    # ------------------------------------------------------------------
    def analyze(self, symbol: str) -> dict:
        today = self.today()
        problems: list[str] = []

        history = self.provider.history(symbol, "2y")  # without prices there is nothing to analyse
        frame = build_frame(history)
        last = frame.iloc[-1]

        def attempt(label: str, fn, default):
            try:
                return fn()
            except ProviderError as exc:
                problems.append(str(exc))
            except Exception as exc:  # a vendor quirk must not sink the whole analysis
                log.warning("%s: %s failed: %s", symbol, label, exc)
                problems.append(f"{label} unavailable")
            return default

        quote = attempt("Quote", lambda: self.provider.quote(symbol), {}) or {}
        price = quote.get("price") or float(last["close"])
        prev_close = quote.get("prev_close") or (float(frame["close"].iloc[-2]) if len(frame) > 1 else price)
        change_pct = quote.get("change_pct")
        if change_pct is None and prev_close:
            change_pct = (price / prev_close - 1.0) * 100.0

        news = attempt("News", lambda: self.provider.news(symbol), [])
        is_fund = (quote.get("quote_type") or "").upper() == "ETF"
        news = [dict(item) for item in news]  # never mutate the provider's cached copies
        for item in news:
            text = f"{item.get('title', '')}. {item.get('summary', '')}"
            # General market stories in a ticker's feed are shown but not scored.
            item["relevant"] = is_fund or sentiment_mod.is_about(text, symbol, quote.get("name"))
            item["sentiment"] = sentiment_mod.score_text(text) if item["relevant"] else None
            item["tone"] = sentiment_mod.label(item["sentiment"])
        news_summary = sentiment_mod.aggregate(news)

        earnings = attempt("Earnings", lambda: self.provider.earnings(symbol), [])
        upcoming = sorted(e["date"] for e in earnings if e["date"] >= today.isoformat())
        next_earnings = date.fromisoformat(upcoming[0]) if upcoming else None

        insiders = attempt("Insider trades", lambda: self.provider.insiders(symbol), None)

        signals = strategies.technical_signals(last) + [
            strategies.earnings_signal(earnings, today),
            strategies.insider_signal(insiders, today),
            strategies.news_signal(news_summary),
        ]
        decision = strategies.decide(signals)
        events = strategies.technical_events(frame)

        settings = self.db.get_settings()
        positions = self.db.positions()
        position = next((p for p in positions if p["symbol"] == symbol), None)
        cash = available_cash(settings, positions)
        plan = plan_trade(price, float(last["atr14"]), decision["action"], settings, cash,
                          position=position, chandelier=float(last["chandelier"]))

        if (decision["action"] in ("buy", "strong_buy") and not position
                and not math.isnan(last["chandelier"]) and last["close"] < last["chandelier"]):
            plan["notes"].append(
                f"The price is under its trailing stop (${last['chandelier']:,.2f}). "
                "Waiting for it to recover before buying avoids catching a dip that keeps going.")

        def build_options():
            return options_mod.recommend(
                spot=price,
                action=decision["action"],
                expirations=self.provider.expirations(symbol),
                chain_for=lambda expiry: self.provider.option_chain(symbol, expiry),
                hv30=float(last["hv30"]),
                settings=settings,
                cash=cash,
                today=today,
                next_earnings=next_earnings,
                position=position,
            )

        option_ideas = attempt("Options", build_options,
                               {"ideas": [], "notes": ["Options data is unavailable right now."], "enabled": True})

        tail = frame.iloc[-260:]
        analysis = {
            "symbol": symbol,
            "name": quote.get("name") or symbol,
            "as_of": time.time(),
            "bar_date": frame.index[-1].date().isoformat(),
            "price": round(price, 2),
            "prev_close": round(prev_close, 2) if prev_close else None,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "quote": quote,
            **decision,
            "direction": strategies.direction_of(decision["action"]),
            "signals": [s.to_dict() for s in signals],
            "events": events,
            "plan": plan,
            "options": option_ideas,
            "news": news,
            "sentiment": news_summary,
            "earnings": {
                "next_date": next_earnings.isoformat() if next_earnings else None,
                "days_until": (next_earnings - today).days if next_earnings else None,
                "history": earnings,
            },
            "insiders": {
                "available": insiders is not None,
                "trades": insiders or [],
                "summary": strategies.summarize_insiders(insiders or [], today),
            },
            "stats": {
                "high_52w": last["high252"],
                "low_52w": last["low252"],
                "sma50": last["sma50"],
                "sma200": last["sma200"],
                "rsi14": last["rsi14"],
                "atr14": last["atr14"],
                "hv30": last["hv30"],
            },
            "chart": {
                "dates": [d.date().isoformat() for d in tail.index],
                "close": _round_list(tail["close"]),
                "sma50": _round_list(tail["sma50"]),
                "sma200": _round_list(tail["sma200"]),
            },
            "spark": _round_list(frame["close"].iloc[-60:]),
            "position": position,
            "problems": problems,
            "demo": self.provider.is_demo,
        }
        return _clean(analysis)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _plan_line(self, a: dict) -> str:
        plan = a["plan"]
        if a["direction"] == "bullish" and a.get("position"):
            return "You already hold this stock: keep holding."
        if a["direction"] == "bullish" and plan.get("shares"):
            return (f"Plan: buy {plan['shares']} shares near ${plan['entry']:,.2f} "
                    f"(${plan['cost']:,.0f}), stop ${plan['stop']:,.2f}, target ${plan['target']:,.2f}.")
        if a["direction"] == "bullish":
            return " ".join(plan.get("notes", []))
        if a["direction"] == "bearish":
            return ("You hold this stock: consider selling." if a.get("position")
                    else "Avoid new buys.")
        return ""

    def _notify(self, prev: dict | None, cur: dict) -> list[int]:
        sym, day = cur["symbol"], cur["bar_date"]
        today = self.today()
        created: list[int] = []

        def push(kind, tone, title, body, key):
            nid = self.db.add_notification(symbol=sym, kind=kind, tone=tone, title=f"{sym}: {title}",
                                           body=body, dedup_key=f"{sym}:{key}")
            if nid:
                created.append(nid)

        # 1. The Buy / Hold / Sell call changed (or a new stock starts out actionable).
        prev_action = prev.get("action") if prev else None
        if cur["action"] != prev_action and (prev_action or cur["action"] != "hold"):
            was = f" (was {strategies.ACTION_LABELS[prev_action]})" if prev_action else ""
            body = " ".join(filter(None, [
                f"Score {cur['score']:+.0f}.",
                ("Why: " + "; ".join(cur["reasons"]) + ".") if cur["reasons"] else "",
                cur.get("gate_note") or "",
                self._plan_line(cur),
            ]))
            push("signal", cur["direction"], f"{cur['action_label']}{was}", body, f"action:{cur['action']}:{day}")

        # 2. Chart events on the latest bar.
        for event in cur["events"]:
            body = event["body"]
            if event["kind"] in ("chandelier_exit", "trend_break") and cur.get("position"):
                body += " You hold this stock: this is a sell signal for the position."
            push(event["kind"], event["direction"], event["title"], body, f"{event['kind']}:{event['date']}")

        # 3. A held position closed below its stop.
        position = cur.get("position")
        if position and position.get("stop") and cur["price"] <= position["stop"]:
            push("stop_hit", "bearish", "Stop hit: sell",
                 f"Price ${cur['price']:,.2f} is at or below your stop of ${position['stop']:,.2f}. "
                 "The plan was to exit here and take the small loss.", f"stop_hit:{day}")

        # 4. Earnings coming up, and results when they land.
        earnings = cur["earnings"]
        if earnings["next_date"] and earnings["days_until"] is not None:
            days = earnings["days_until"]
            if 0 <= days <= EARNINGS_WARNING_DAYS:
                when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
                push("earnings_soon", "warning", f"Earnings {when}",
                     f"Reports on {earnings['next_date']}. Expect a large move either way; option "
                     "prices are inflated before the report and drop after it.",
                     f"earnings_soon:{earnings['next_date']}")
        reported = [e for e in earnings["history"] if e.get("surprise_pct") is not None]
        if reported:
            latest = max(reported, key=lambda e: e["date"])
            age = (today - date.fromisoformat(latest["date"])).days
            if 0 <= age <= 5:
                beat = latest["surprise_pct"] >= 0
                push("earnings_result", "bullish" if beat else "bearish",
                     f"{'Beat' if beat else 'Missed'} earnings by {abs(latest['surprise_pct']):.1f}%",
                     f"Reported EPS {latest['eps_actual']} vs {latest['eps_estimate']} expected on "
                     f"{latest['date']}. Prices often keep drifting in the direction of the surprise.",
                     f"earnings_result:{latest['date']}")

        # 5. Insider buying.
        cutoff = (today - timedelta(days=INSIDER_ALERT_DAYS)).isoformat()
        for trade in cur["insiders"]["trades"]:
            if trade["kind"] == "buy" and trade["date"] >= cutoff:
                value = f"${trade['value']:,.0f}" if trade.get("value") else "an undisclosed amount"
                push("insider_buy", "bullish", "Insider bought shares",
                     f"{trade['insider'].title()} ({trade['position'] or 'insider'}) bought {value} "
                     f"of stock on {trade['date']}.", f"insider_buy:{trade['insider']}:{trade['date']}")
        summary = cur["insiders"]["summary"]
        if len(summary["buyers"]) >= 3:
            push("insider_cluster", "bullish", "Cluster insider buying",
                 f"{len(summary['buyers'])} different insiders bought a combined "
                 f"${summary['buy_value']:,.0f} in the last {summary['window_days']} days. "
                 "This is the strongest form of the insider signal.",
                 f"insider_cluster:{summary['last_buy_date']}")

        # 6. News flow turned sharply one way.
        tone = cur["sentiment"]
        prev_tone = (prev or {}).get("sentiment", {}).get("score", 0.0)
        if tone["count"] >= 3 and abs(tone["score"]) >= 0.5 and abs(prev_tone) < 0.5:
            negative = tone["score"] < 0
            push("news_tone", "bearish" if negative else "bullish",
                 f"News flow turned {'negative' if negative else 'positive'}",
                 f"{tone['negative'] if negative else tone['positive']} of {tone['count']} recent "
                 f"headlines are {'negative' if negative else 'positive'}. Read them before acting.",
                 f"news_tone:{'neg' if negative else 'pos'}:{day}")

        # 7. A new options idea, when the direction or the suggested structure changes.
        ideas = cur["options"].get("ideas") or []
        if ideas and cur["direction"] != "neutral":
            idea = ideas[0]
            prev_ideas = ((prev or {}).get("options") or {}).get("ideas") or []
            prev_kind = prev_ideas[0]["kind"] if prev_ideas else None
            if prev is None or prev.get("direction") != cur["direction"] or prev_kind != idea["kind"]:
                legs = " / ".join(f"{leg['action']} ${leg['strike']:g} {leg['type']}" for leg in idea["legs"])
                size = (f"{idea['contracts']} contract(s) fit your options risk budget."
                        if idea["affordable"] else "This is above your current options risk budget.")
                loss = f" Max loss ${idea['max_loss']:,.0f} per contract." if idea.get("max_loss") else ""
                push("option_idea", cur["direction"], f"Options idea: {idea['strategy'].lower()}",
                     f"{legs}, expiring {idea['expiry']} ({idea['dte']} days).{loss} {size}",
                     f"option:{idea['kind']}:{day}")
        return created

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def refresh_symbol(self, symbol: str, notify: bool = True) -> dict:
        prev = self.analyses.get(symbol)
        if prev and prev.get("error"):
            prev = None
        try:
            cur = self.analyze(symbol)
        except ProviderError as exc:
            if prev:
                stale = {**prev, "stale": True, "problems": [str(exc)]}
                self.analyses[symbol] = stale
                return stale
            failed = {"symbol": symbol, "error": str(exc), "as_of": time.time()}
            self.analyses[symbol] = failed
            return failed
        self.analyses[symbol] = cur
        self.db.save_analysis(symbol, cur)
        if notify:
            self._notify(prev, cur)
        return cur

    def scan(self, force: bool = False, wait: bool = False, notify: bool = True) -> dict:
        """Refresh every watched symbol. Returns the status afterwards.

        If a scan is already running this returns straight away, unless `wait`
        is set, in which case it runs once the current one finishes (used after
        a settings change, which must not be skipped). `notify=False` recomputes
        quietly: resizing trades for a new budget is not news.
        """
        if not self._scan_lock.acquire(blocking=wait):
            return self.status
        try:
            self.status.update({"scanning": True, "last_error": None})
            if force:
                self.provider.invalidate()
            symbols = self.db.watchlist()
            for stale in [s for s in self.analyses if s not in symbols]:
                del self.analyses[stale]
            with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
                refresh = lambda symbol: self._safe_refresh(symbol, notify)  # noqa: E731
                for symbol, result in zip(symbols, pool.map(refresh, symbols)):
                    if result.get("error"):
                        self.status["last_error"] = f"{symbol}: {result['error']}"
            self.status["last_scan"] = time.time()
        finally:
            self.status["scanning"] = False
            self._scan_lock.release()
        return self.status

    def _safe_refresh(self, symbol: str, notify: bool = True) -> dict:
        try:
            return self.refresh_symbol(symbol, notify=notify)
        except Exception as exc:
            log.exception("Scan failed for %s", symbol)
            return {"symbol": symbol, "error": str(exc)}

    # ------------------------------------------------------------------
    # Views used by the API
    # ------------------------------------------------------------------
    def summary(self, symbol: str) -> dict:
        a = self.analyses.get(symbol)
        if not a:
            return {"symbol": symbol, "pending": True}
        if a.get("error"):
            return {"symbol": symbol, "error": a["error"]}
        ideas = a["options"].get("ideas") or []
        return {
            "symbol": symbol,
            "name": a["name"],
            "price": a["price"],
            "change_pct": a["change_pct"],
            "score": a["score"],
            "action": a["action"],
            "action_label": a["action_label"],
            "direction": a["direction"],
            "reason": a["reasons"][0] if a["reasons"] else (a.get("gate_note") or ""),
            "gate_note": a.get("gate_note"),
            "next_earnings": a["earnings"]["next_date"],
            "earnings_days": a["earnings"]["days_until"],
            "shares": a["plan"].get("shares", 0),
            "option": ideas[0]["strategy"] if ideas else None,
            "spark": a["spark"],
            "held": bool(a.get("position")),
            "stale": bool(a.get("stale")),
            "as_of": a["as_of"],
        }

    def overview(self) -> dict:
        settings = self.db.get_settings()
        positions = self.db.positions()
        invested = sum(p["shares"] * p["entry_price"] for p in positions)
        return {
            "settings": settings,
            "watchlist": [self.summary(s) for s in self.db.watchlist()],
            "budget": {
                "total": settings["budget"],
                "invested": round(invested, 2),
                "available": round(available_cash(settings, positions), 2),
            },
            "unread": self.db.unread_count(),
            "status": self.status,
            "demo": self.provider.is_demo,
        }

    def backtest(self, symbol: str) -> dict:
        key = (symbol, self.today().isoformat())
        if key not in self._backtests:
            self._backtests[key] = _clean(run_backtest(self.provider.history(symbol, "5y")))
        return self._backtests[key]

    def news_feed(self) -> list[dict]:
        seen, feed = set(), []
        for symbol in self.db.watchlist():
            for item in (self.analyses.get(symbol) or {}).get("news", []):
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                feed.append({**item, "symbol": symbol})
        return sorted(feed, key=lambda n: n.get("published") or 0, reverse=True)

    def earnings_calendar(self) -> list[dict]:
        rows = []
        for symbol in self.db.watchlist():
            a = self.analyses.get(symbol) or {}
            if a.get("error") or not a:
                continue
            reported = [e for e in a["earnings"]["history"] if e.get("eps_actual") is not None]
            last = max(reported, key=lambda e: e["date"]) if reported else None
            nxt = next((e for e in a["earnings"]["history"] if e["date"] == a["earnings"]["next_date"]), None)
            rows.append({
                "symbol": symbol,
                "name": a["name"],
                "next_date": a["earnings"]["next_date"],
                "days_until": a["earnings"]["days_until"],
                "eps_estimate": nxt.get("eps_estimate") if nxt else None,
                "last": last,
                "action_label": a["action_label"],
                "direction": a["direction"],
            })
        return sorted(rows, key=lambda r: (r["next_date"] is None, r["next_date"] or ""))

    def insider_feed(self) -> list[dict]:
        rows = []
        for symbol in self.db.watchlist():
            a = self.analyses.get(symbol) or {}
            for trade in (a.get("insiders") or {}).get("trades", []):
                rows.append({**trade, "symbol": symbol})
        return sorted(rows, key=lambda t: t["date"], reverse=True)


class Scheduler(threading.Thread):
    """Rescans the watchlist in the background every `refresh_minutes`."""

    def __init__(self, engine: Engine):
        super().__init__(daemon=True, name="stockanalysis-scheduler")
        self.engine = engine
        self._wake = threading.Event()
        self._halt = threading.Event()
        self._force = False

    def trigger(self, force: bool = False):
        self._force = self._force or force
        self._wake.set()

    def stop(self):
        self._halt.set()
        self._wake.set()

    def run(self):
        while not self._halt.is_set():
            force, self._force = self._force, False
            self._wake.clear()
            try:
                self.engine.scan(force=force)
            except Exception:
                log.exception("Background scan failed")
            minutes = self.engine.db.get_settings()["refresh_minutes"]
            self._wake.wait(timeout=max(60, minutes * 60))
