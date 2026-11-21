"""Live insider-trade alerts from SEC Form 4 filings.

Two jobs run every couple of minutes:

1. Watchlist sync: for each watched company, list its recent Form 4 filings
   (data.sec.gov submissions API), download any new ones and alert on
   open-market purchases (and, if enabled, large sales).
2. Market-wide scan: read EDGAR's live feed of new Form 4s across every US
   company and alert on large open-market purchases by officers and directors,
   plus cluster buying (3+ insiders at one company within 30 days).

Purchases are also checked against the insider's own history: a "routine"
insider (same calendar month in each of the past three years) carries little
information, per Cohen, Malloy & Pomorski (2012); anything else is flagged as
opportunistic, which is the kind of trade that predicted returns.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

from .db import Database
from .sec import SecClient, SecError, is_routine

log = logging.getLogger("stockanalysis.insiders")

BACKFILL_DAYS = 120       # first sync of a watched stock covers the signal window
RESYNC_DAYS = 10          # later syncs only look at recent filings
BUY_ALERT_DAYS = 14       # alert on purchases filed within this many days
SELL_ALERT_DAYS = 3
CLUSTER_DAYS = 30
CLUSTER_MIN_BUYERS = 3
MARKET_PAGES = 5          # up to 500 feed entries per poll
MARKET_MAX_FETCH = 250    # cap downloads per poll so a backlog cannot stall the app
ROUTINE_LOOKBACK_FILINGS = 12

_ENTITY_WORDS = re.compile(
    r"\b(INC|LLC|L\.?P|LP|LTD|CORP|CORPORATION|CO|TRUST|FUND|FUNDS|CAPITAL|PARTNERS|HOLDINGS?|GROUP|"
    r"MANAGEMENT|ADVISORS?|INVESTMENTS?|FOUNDATION|BANK|PLC|SA|AG|NV|LIMITED|VENTURES?|ASSOCIATES)\b",
    re.IGNORECASE)


def display_name(raw: str | None) -> str:
    """'COOK TIMOTHY D' -> 'Timothy D Cook'; entity names keep their order."""
    raw = (raw or "").strip()
    if not raw:
        return "Unknown insider"
    if " & " in raw:
        return " & ".join(display_name(part) for part in raw.split(" & "))
    titled = " ".join(w.capitalize() if not re.fullmatch(r"[IVX]+|[A-Z]\.?", w) else w for w in raw.split())
    if _ENTITY_WORDS.search(raw) or len(raw.split()) < 2:
        return titled
    parts = titled.split()
    suffix = parts.pop() if parts[-1].rstrip(".").upper() in ("JR", "SR", "II", "III", "IV") else None
    name = " ".join(parts[1:] + parts[:1])
    return f"{name} {suffix}" if suffix else name


def short_role(role: str | None) -> str:
    role = role or "Insider"
    lowered = role.lower()
    for needle, short in (("chief executive", "CEO"), ("chief financial", "CFO"), ("chief operating", "COO"),
                          ("president", "President"), ("chair", "Chair"), ("general counsel", "General Counsel")):
        if needle in lowered:
            return short
    if "director" in lowered:
        return "Director"
    if "10%" in lowered:
        return "10% owner"
    return role.split(",")[0][:40]


def _money(x: float | None) -> str:
    if x is None:
        return "an undisclosed amount"
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"${x / size:.1f}{suffix}"
    return f"${x:,.0f}"


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        return date.fromisoformat(iso[:10]).strftime("%b %-d")
    except ValueError:
        return iso


def summarize_filing(rows: list[dict], code: str) -> dict | None:
    """Aggregate one filing's non-derivative trades of one code (P or S)."""
    picked = sorted((r for r in rows if r["code"] == code and not r["derivative"]), key=lambda r: r.get("seq", 0))
    if not picked:
        return None
    shares = sum(r["shares"] or 0 for r in picked)
    value = sum(r["value"] or 0 for r in picked) or None
    after = next((r["shares_after"] for r in reversed(picked) if r["shares_after"] is not None), None)
    first = picked[0]
    before = None
    if after is not None:
        before = after - shares if code == "P" else after + shares
    return {
        "symbol": first["symbol"],
        "issuer_cik": first["issuer_cik"],
        "issuer_name": first["issuer_name"],
        "owner_cik": first["owner_cik"],
        "owner_name": first["owner_name"],
        "role": first["role"],
        "is_officer": bool(first["is_officer"]),
        "is_director": bool(first["is_director"]),
        "is_ten_pct": bool(first["is_ten_pct"]),
        "shares": shares,
        "value": value,
        "avg_price": (value / shares) if value and shares else None,
        "shares_after": after,
        "stake_change_pct": (shares / before * 100.0) if before and before > 0 else None,
        "plan_10b5_1": any(r["plan_10b5_1"] for r in picked),
        "trade_date": min(r["trade_date"] for r in picked if r["trade_date"]) if any(r["trade_date"] for r in picked) else None,
        "filed": first["filed"],
        "accepted": first["accepted"],
        "accession": first["accession"],
        "url": first["url"],
    }


class InsiderService:
    def __init__(self, db: Database, client: SecClient, today_fn=None, on_update=None):
        self.db = db
        self.client = client
        self.on_update = on_update  # called with a symbol after its insider data changes
        self._today_fn = today_fn or date.today
        self._lock = threading.Lock()
        self.status: dict = {"configured": False, "last_poll": None, "last_error": None,
                             "polling": False, "filings_seen": 0}

    def today(self) -> date:
        return self._today_fn()

    @property
    def configured(self) -> bool:
        return self.client.configured

    # ------------------------------------------------------------------
    def poll(self) -> dict:
        """One full cycle: watchlist sync, then the market-wide scan."""
        if not self._lock.acquire(blocking=False):
            return self.status
        try:
            self.status["configured"] = self.configured
            if not self.status["configured"]:
                self.status["last_error"] = None
                return self.status
            self.status.update({"polling": True, "last_error": None})
            errors = []
            try:
                errors += self.sync_watchlist()
                if self.db.get_settings()["insider_market_alerts"]:
                    self.scan_market()
            except SecError as exc:
                errors.append(str(exc))
            except Exception as exc:  # never let one bad filing kill the poller
                log.exception("Insider poll failed")
                errors.append(f"Insider poll failed: {exc}")
            self.status["last_error"] = errors[0] if errors else None
            self.status["last_poll"] = time.time()
            return self.status
        finally:
            self.status["polling"] = False
            self._lock.release()

    # ------------------------------------------------------------------
    def _watch_ciks(self) -> dict[str, str]:
        """{cik: symbol} for the watchlist (stocks without SEC filings are skipped)."""
        out = {}
        for symbol in self.db.watchlist():
            cik = self.client.cik_for(symbol)
            if cik:
                out[cik] = symbol
        return out

    def _store(self, cik_for_path: str, accession: str, filed: str | None, accepted: str | None,
               symbol_override: str | None = None) -> list[dict]:
        try:
            parsed = self.client.fetch_form4(cik_for_path, accession)
        except SecError as exc:
            if "Not found" in str(exc) or "No Form 4 XML" in str(exc) or "Could not read" in str(exc):
                self.db.save_filing({"accession": accession, "filed": filed, "issuer": {}, "owners": [],
                                     "transactions": []}, error=str(exc))
                return []
            raise
        parsed["filed"] = filed or (parsed.get("accepted") or "")[:10] or None
        parsed["accepted"] = accepted or parsed.get("accepted")
        if symbol_override:
            parsed["issuer"]["symbol"] = symbol_override
        self.status["filings_seen"] += 1
        return self.db.save_filing(parsed)

    def sync_watchlist(self) -> list[str]:
        errors = []
        today = self.today()
        for cik, symbol in self._watch_ciks().items():
            try:
                first = self.db.get_state(f"sec_synced:{symbol}") is None
                since = today - timedelta(days=BACKFILL_DAYS if first else RESYNC_DAYS)
                filings = self.client.recent_form4s(cik, since)
                known = self.db.known_filings([f["accession"] for f in filings])
                fresh = sorted((f for f in filings if f["accession"] not in known),
                               key=lambda f: f["accepted"] or f["filed"])
                for f in fresh:
                    rows = self._store(cik, f["accession"], f["filed"], f["accepted"], symbol_override=symbol)
                    self._alert(rows, watched=True)
                self.db.set_state(f"sec_synced:{symbol}", today.isoformat())
                if (first or fresh) and self.on_update:
                    try:
                        self.on_update(symbol)  # re-score the stock with the new filings
                    except Exception:
                        log.exception("Refreshing %s after new filings failed", symbol)
            except SecError as exc:
                errors.append(f"{symbol}: {exc}")
                if "refused" in str(exc) or "undeclared" in str(exc).lower():
                    break  # the same problem will hit every symbol
        return errors

    def scan_market(self):
        recent = set(self.db.get_state("sec_feed_recent", []))
        items = self.client.current_form4s(pages=MARKET_PAGES, stop_at=recent or None)
        known = self.db.known_filings([i["accession"] for i in items])
        fresh = [i for i in items if i["accession"] not in known][:MARKET_MAX_FETCH]
        watch = self._watch_ciks()
        for item in reversed(fresh):  # oldest first, so alerts arrive in order
            path_cik = item["issuer_cik"] or item.get("owner_cik")
            if not path_cik:
                continue
            updated = item.get("updated") or ""
            rows = self._store(path_cik, item["accession"], updated[:10] or None, None,
                               symbol_override=watch.get(item["issuer_cik"] or ""))
            self._alert(rows, watched=bool(rows) and rows[0]["issuer_cik"] in watch)
        self.db.set_state("sec_feed_recent", [i["accession"] for i in items[:300]] or list(recent))

    # ------------------------------------------------------------------
    def classify(self, buy: dict) -> str | None:
        """'routine' or 'opportunistic' for a purchase, from the insider's own filings."""
        if not buy.get("owner_cik") or not buy.get("trade_date"):
            return None
        trade_day = date.fromisoformat(buy["trade_date"])
        key = f"routine:{buy['owner_cik']}:{buy['issuer_cik']}:{trade_day:%Y-%m}"
        cached = self.db.get_state(key)
        if cached:
            return cached
        try:
            history = self.client.recent_form4s(buy["owner_cik"], date(trade_day.year - 3, 1, 1), ttl=3600)
        except SecError:
            return None
        same_month = [f for f in history if f["report_date"] and f["accession"] != buy["accession"]
                      and int(f["report_date"][5:7]) == trade_day.month
                      and trade_day.year - 3 <= int(f["report_date"][:4]) < trade_day.year]
        months: set[tuple[int, int]] = set()
        for f in same_month[:ROUTINE_LOOKBACK_FILINGS]:
            rows = self.db.sec_trades_for_accession(f["accession"])
            if not rows and not self.db.has_filing(f["accession"]):
                try:
                    rows = self._store(buy["owner_cik"], f["accession"], f["filed"], f["accepted"])
                except SecError:
                    continue
            for r in rows:
                if (r["code"] in ("P", "S") and not r["derivative"] and r["issuer_cik"] == buy["issuer_cik"]
                        and r["trade_date"]):
                    d = date.fromisoformat(r["trade_date"])
                    months.add((d.year, d.month))
        label = "routine" if is_routine(months, trade_day) else "opportunistic"
        self.db.set_state(key, label)
        return label

    def _alert(self, rows: list[dict], watched: bool):
        if not rows:
            return
        settings = self.db.get_settings()
        today = self.today()
        buy = summarize_filing(rows, "P")
        if buy:
            age = (today - date.fromisoformat(buy["filed"])).days if buy["filed"] else 0
            insider_role = buy["is_officer"] or buy["is_director"]
            big = (buy["value"] or 0) >= float(settings["insider_market_min_value"])
            if age <= BUY_ALERT_DAYS and (watched or (insider_role and big and not buy["plan_10b5_1"])):
                buy["routine"] = self.classify(buy)
                if buy["routine"]:
                    self.db.set_routine(buy["accession"], buy["owner_cik"], buy["routine"])
                self._push_buy(buy, watched)
            if buy["issuer_cik"]:
                self._check_cluster(buy, watched)
        sell = summarize_filing(rows, "S")
        if sell and watched and settings["insider_alert_sells"]:
            age = (today - date.fromisoformat(sell["filed"])).days if sell["filed"] else 0
            if age <= SELL_ALERT_DAYS and (sell["value"] or 0) >= float(settings["insider_sell_min_value"]):
                self._push_sell(sell)

    def _describe(self, t: dict, verb: str) -> str:
        who = display_name(t["owner_name"])
        price = f" at ${t['avg_price']:,.2f}" if t["avg_price"] else ""
        lag = ""
        if t["trade_date"] and t["filed"]:
            days = (date.fromisoformat(t["filed"]) - date.fromisoformat(t["trade_date"])).days
            lag = (" (filed the same day)" if days <= 0 else
                   f" (filed {_fmt_date(t['filed'])}, {days} day{'s' if days != 1 else ''} later)")
        parts = [f"{who} ({t['role'] or 'insider'}) {verb} {t['shares']:,.0f} shares{price}, "
                 f"{_money(t['value'])}, on {_fmt_date(t['trade_date'])}{lag}."]
        if t["stake_change_pct"] is not None:
            direction = "Raises" if verb == "bought" else "Cuts"
            parts.append(f"{direction} their holding by {t['stake_change_pct']:.0f}% to {t['shares_after']:,.0f} shares.")
        parts.append("Pre-planned under a Rule 10b5-1 plan, so it says less about their view."
                     if t["plan_10b5_1"] else "Not a pre-planned (10b5-1) trade.")
        return " ".join(parts)

    def _push_buy(self, buy: dict, watched: bool):
        symbol = buy["symbol"] or buy["issuer_name"] or "?"
        body = self._describe(buy, "bought")
        if buy.get("routine") == "routine":
            body += " Routine: they traded in this same month in each of the last 3 years, which research finds carries little signal."
        elif buy.get("routine") == "opportunistic":
            body += " Not a routine pattern for this insider, the type of purchase research finds most informative."
        if not watched:
            body += f" {buy['issuer_name'] or symbol} is not on your watchlist."
        self.db.add_notification(
            symbol=buy["symbol"], kind="insider_buy" if watched else "insider_buy_market", tone="bullish",
            title=f"{symbol}: {short_role(buy['role'])} bought {_money(buy['value'])}",
            body=body, link=buy["url"],
            dedup_key=f"{buy['symbol']}:insider_buy:{(buy['owner_name'] or '').upper()}:{buy['trade_date']}",
        )

    def _push_sell(self, sell: dict):
        self.db.add_notification(
            symbol=sell["symbol"], kind="insider_sell", tone="bearish",
            title=f"{sell['symbol']}: {short_role(sell['role'])} sold {_money(sell['value'])}",
            body=self._describe(sell, "sold") + " Insider sales are often for taxes or diversification; on their own they predict little.",
            link=sell["url"],
            dedup_key=f"{sell['symbol']}:insider_sell:{(sell['owner_name'] or '').upper()}:{sell['trade_date']}",
        )

    def _check_cluster(self, buy: dict, watched: bool):
        since = (self.today() - timedelta(days=CLUSTER_DAYS)).isoformat()
        rows = [r for r in self.db.sec_trades(since=since, codes=("P",), limit=2000)
                if r["issuer_cik"] == buy["issuer_cik"] and not r["derivative"] and not r["plan_10b5_1"]]
        buyers = sorted({r["owner_name"] for r in rows})
        if len(buyers) < CLUSTER_MIN_BUYERS:
            return
        total = sum(r["value"] or 0 for r in rows)
        if not watched and total < float(self.db.get_settings()["insider_market_min_value"]):
            return  # off the watchlist, small clusters at tiny companies are noise
        symbol = buy["symbol"] or buy["issuer_name"]
        names = ", ".join(display_name(b) for b in buyers[:5]) + ("…" if len(buyers) > 5 else "")
        self.db.add_notification(
            symbol=buy["symbol"], kind="insider_cluster", tone="bullish",
            title=f"{symbol}: cluster buying, {len(buyers)} insiders",
            body=(f"{len(buyers)} different insiders bought {_money(total)} of {buy['issuer_name'] or symbol} "
                  f"in the last {CLUSTER_DAYS} days: {names}. Several insiders buying at once is the "
                  "strongest form of the insider signal." + ("" if watched else " Not on your watchlist.")),
            link=buy["url"],
            dedup_key=f"{buy['symbol']}:insider_cluster:{buy['issuer_cik']}:{len(buyers)}",
        )

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def trades_for_symbol(self, symbol: str, days: int = 365) -> list[dict] | None:
        """Trades in the provider shape the strategies use, or None if this
        symbol has not been synced from the SEC yet."""
        if not self.configured or self.db.get_state(f"sec_synced:{symbol}") is None:
            return None
        since = (self.today() - timedelta(days=days)).isoformat()
        out = []
        for r in self.db.sec_trades(symbol=symbol, since=since, limit=1000):
            if r["derivative"]:
                continue
            kind = {"P": "buy", "S": "sell"}.get(r["code"], "other")
            out.append({
                "date": r["trade_date"] or r["filed"],
                "insider": r["owner_name"],
                "insider_display": display_name(r["owner_name"]),
                "position": r["role"],
                "kind": kind,
                "code": r["code"],
                "shares": r["shares"],
                "value": r["value"],
                "price": r["price"],
                "text": f"{r['code']}: {_code_label(r['code'])}",
                "plan_10b5_1": bool(r["plan_10b5_1"]),
                "routine": r["routine"],
                "filed": r["filed"],
                "url": r["url"],
                "source": "sec",
            })
        return out

    def market_buys(self, days: int = 14, min_value: float = 0) -> list[dict]:
        since = (self.today() - timedelta(days=days)).isoformat()
        by_filing: dict[str, list[dict]] = {}
        for r in self.db.sec_trades(since=since, codes=("P",), limit=3000):
            by_filing.setdefault(r["accession"], []).append(r)
        out = []
        for rows in by_filing.values():
            t = summarize_filing(rows, "P")
            if t and (t["value"] or 0) >= min_value:
                t["owner_display"] = display_name(t["owner_name"])
                t["routine"] = rows[0]["routine"]
                out.append(t)
        return sorted(out, key=lambda t: (t["accepted"] or t["filed"] or ""), reverse=True)


def _code_label(code: str) -> str:
    from .sec import CODE_LABELS
    return CODE_LABELS.get(code, "Other")


class InsiderWatcher(threading.Thread):
    """Polls EDGAR every `insider_poll_minutes` (2 by default)."""

    def __init__(self, service: InsiderService):
        super().__init__(daemon=True, name="stockanalysis-insiders")
        self.service = service
        self._wake = threading.Event()
        self._halt = threading.Event()

    def trigger(self):
        self._wake.set()

    def stop(self):
        self._halt.set()
        self._wake.set()

    def run(self):
        while not self._halt.is_set():
            self._wake.clear()
            self.service.poll()
            minutes = self.service.db.get_settings()["insider_poll_minutes"]
            self._wake.wait(timeout=max(60, minutes * 60))
