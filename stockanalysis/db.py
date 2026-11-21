"""SQLite storage: settings, watchlist, positions, notifications and the last
analysis of each symbol (so the dashboard has something to show on restart)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_SETTINGS = {
    "budget": 10000.0,            # total money available for trading
    "risk_per_trade_pct": 1.0,    # % of budget lost if a stock trade hits its stop
    "max_position_pct": 20.0,     # largest single stock position, % of budget
    "options_enabled": True,
    "option_risk_pct": 3.0,       # most that one options trade may lose, % of budget
    "refresh_minutes": 15,
    # Insider alerts (SEC EDGAR Form 4 filings)
    "sec_contact": "",            # "Name email" - the SEC requires one; only sent to sec.gov
    "insider_poll_minutes": 2,
    "insider_alert_sells": False,  # sales are mostly noise, so off by default
    "insider_sell_min_value": 1_000_000.0,
    "insider_market_alerts": True,  # big buys by officers/directors at any US company
    "insider_market_min_value": 500_000.0,
    # Push notifications to a phone (ntfy, Discord or Slack webhook URL)
    "push_url": "",
    "push_scope": "insider",      # "insider" (insider trades only) or "all"
    # Your own indicator alert from the Indicator Lab: {"tactic": key, "params": {...}} or {}
    "my_tactic": {},
    # Secret in the TradingView webhook URL (generated on first use)
    "tv_webhook_token": "",
    # 10-month trend rule alerts for markets (gold, oil, crypto...). None = the
    # markets where testing found trend rules helped; [] = none.
    "trend_alert_symbols": None,
    # Month-end alerts when the 8-asset trend portfolio changes what it holds
    "trend_portfolio_alerts": True,
}

TEXT_SETTINGS = {"sec_contact": 200, "push_url": 500, "tv_webhook_token": 100}
CHOICE_SETTINGS = {"push_scope": ("insider", "all")}
BOOL_SETTINGS = {"options_enabled", "insider_alert_sells", "insider_market_alerts", "trend_portfolio_alerts"}
MAX_TREND_ALERTS = 60

SETTING_LIMITS = {
    "budget": (1.0, 1e9),
    "risk_per_trade_pct": (0.1, 10.0),
    "max_position_pct": (1.0, 100.0),
    "option_risk_pct": (0.1, 25.0),
    "refresh_minutes": (1, 240),
    "insider_poll_minutes": (1, 60),
    "insider_sell_min_value": (0, 1e12),
    "insider_market_min_value": (0, 1e12),
}
INT_SETTINGS = {"refresh_minutes", "insider_poll_minutes"}

def _symbol_list(value) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise SettingsError("trend_alert_symbols must be a list of symbols")
    from .symbols import SYMBOL_RE
    out: list[str] = []
    for raw in value:
        symbol = str(raw or "").strip().upper()
        if not SYMBOL_RE.match(symbol):
            raise SettingsError(f"Not a ticker symbol: {raw}")
        if symbol not in out:
            out.append(symbol)
    if len(out) > MAX_TREND_ALERTS:
        raise SettingsError(f"At most {MAX_TREND_ALERTS} trend alerts")
    return out


DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "TSLA"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, added_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    shares REAL NOT NULL,
    entry_price REAL NOT NULL,
    stop REAL,
    opened_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    symbol TEXT,
    kind TEXT NOT NULL,
    tone TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    dedup_key TEXT UNIQUE,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS analyses (symbol TEXT PRIMARY KEY, updated_at REAL NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sec_filings (
    accession TEXT PRIMARY KEY,
    issuer_cik TEXT,
    symbol TEXT,
    issuer_name TEXT,
    filed TEXT,
    accepted TEXT,
    url TEXT,
    seen_at REAL NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS sec_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accession TEXT NOT NULL,
    seq INTEGER NOT NULL,
    symbol TEXT,
    issuer_cik TEXT,
    issuer_name TEXT,
    owner_cik TEXT,
    owner_name TEXT,
    role TEXT,
    is_director INTEGER,
    is_officer INTEGER,
    is_ten_pct INTEGER,
    code TEXT,
    acquired INTEGER,
    derivative INTEGER,
    shares REAL,
    price REAL,
    value REAL,
    shares_after REAL,
    direct INTEGER,
    plan_10b5_1 INTEGER,
    trade_date TEXT,
    filed TEXT,
    accepted TEXT,
    url TEXT,
    footnote TEXT,
    routine TEXT,
    UNIQUE (accession, seq)
);
CREATE INDEX IF NOT EXISTS sec_trades_symbol ON sec_trades (symbol, trade_date);
CREATE INDEX IF NOT EXISTS sec_trades_code ON sec_trades (code, filed);
"""


def default_db_path() -> Path:
    override = os.environ.get("STOCKANALYSIS_DB")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data" / "stockanalysis.db"


class SettingsError(ValueError):
    pass


class Database:
    def __init__(self, path: str | Path | None = None, seed_watchlist: bool = True):
        self.path = str(path or default_db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._listeners: list = []
        with self._lock:
            self._conn.executescript(SCHEMA)
            columns = {r[1] for r in self._conn.execute("PRAGMA table_info(notifications)")}
            if "link" not in columns:  # databases created before insider alerts
                self._conn.execute("ALTER TABLE notifications ADD COLUMN link TEXT")
            first_run = self._conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
            if first_run:
                for key, value in DEFAULT_SETTINGS.items():
                    self._conn.execute("INSERT INTO settings VALUES (?, ?)", (key, json.dumps(value)))
                if seed_watchlist:
                    for i, symbol in enumerate(DEFAULT_WATCHLIST):
                        self._conn.execute("INSERT INTO watchlist VALUES (?, ?)", (symbol, time.time() + i))
            self._conn.commit()

    def _run(self, sql: str, args: tuple = ()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---- settings ----
    def get_settings(self) -> dict:
        stored = {r["key"]: json.loads(r["value"]) for r in self._all("SELECT key, value FROM settings")}
        return {**DEFAULT_SETTINGS, **stored}

    def update_settings(self, changes: dict) -> dict:
        clean = {}
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS:
                raise SettingsError(f"Unknown setting: {key}")
            if key in BOOL_SETTINGS:
                clean[key] = bool(value)
                continue
            if key == "trend_alert_symbols":
                clean[key] = _symbol_list(value)
                continue
            if key == "my_tactic":
                if not value:
                    clean[key] = {}
                    continue
                from .tactics import TACTICS, clean_params
                if not isinstance(value, dict) or value.get("tactic") not in TACTICS:
                    raise SettingsError("my_tactic needs a known tactic")
                clean[key] = {"tactic": value["tactic"], "params": clean_params(value["tactic"], value.get("params"))}
                continue
            if key in TEXT_SETTINGS:
                text = str(value or "").strip()
                if len(text) > TEXT_SETTINGS[key]:
                    raise SettingsError(f"{key} is too long")
                if key == "push_url" and text and not text.lower().startswith(("https://", "http://")):
                    raise SettingsError("push_url must start with https://")
                if key == "sec_contact" and text:
                    from .sec import valid_contact
                    if not valid_contact(text):
                        raise SettingsError("sec_contact needs a name and an email address, "
                                            "e.g. Jane Doe jane@example.com")
                clean[key] = text
                continue
            if key in CHOICE_SETTINGS:
                if value not in CHOICE_SETTINGS[key]:
                    raise SettingsError(f"{key} must be one of: {', '.join(CHOICE_SETTINGS[key])}")
                clean[key] = value
                continue
            if isinstance(value, bool):
                raise SettingsError(f"{key} must be a number")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} must be a number") from None
            lo, hi = SETTING_LIMITS[key]
            if not (lo <= number <= hi):
                raise SettingsError(f"{key} must be between {lo:g} and {hi:g}")
            clean[key] = int(number) if key in INT_SETTINGS else number
        for key, value in clean.items():
            self._run("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (key, json.dumps(value)))
        return self.get_settings()

    # ---- watchlist ----
    def watchlist(self) -> list[str]:
        return [r["symbol"] for r in self._all("SELECT symbol FROM watchlist ORDER BY added_at")]

    def add_symbol(self, symbol: str):
        self._run("INSERT OR IGNORE INTO watchlist VALUES (?, ?)", (symbol, time.time()))

    def remove_symbol(self, symbol: str):
        self._run("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        self._run("DELETE FROM analyses WHERE symbol = ?", (symbol,))

    # ---- positions ----
    def positions(self) -> list[dict]:
        return self._all("SELECT * FROM positions ORDER BY opened_at")

    def position(self, symbol: str) -> dict | None:
        rows = self._all("SELECT * FROM positions WHERE symbol = ?", (symbol,))
        return rows[0] if rows else None

    def set_position(self, symbol: str, shares: float, entry_price: float, stop: float | None = None) -> dict:
        self._run(
            "INSERT INTO positions VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET "
            "shares = excluded.shares, entry_price = excluded.entry_price, stop = excluded.stop",
            (symbol, shares, entry_price, stop, time.time()),
        )
        return self.position(symbol)

    def close_position(self, symbol: str):
        self._run("DELETE FROM positions WHERE symbol = ?", (symbol,))

    # ---- notifications ----
    def on_notification(self, callback):
        """Call `callback(notification_dict)` for every newly inserted notification."""
        self._listeners.append(callback)

    def add_notification(self, *, symbol: str | None, kind: str, tone: str, title: str, body: str,
                         dedup_key: str | None = None, link: str | None = None) -> int | None:
        """Insert unless one with the same dedup key exists. Returns the new id or None."""
        created = time.time()
        cur = self._run(
            "INSERT OR IGNORE INTO notifications (created_at, symbol, kind, tone, title, body, dedup_key, link) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (created, symbol, kind, tone, title, body, dedup_key, link),
        )
        if not cur.rowcount:
            return None
        note = {"id": cur.lastrowid, "created_at": created, "symbol": symbol, "kind": kind,
                "tone": tone, "title": title, "body": body, "link": link}
        for callback in self._listeners:
            try:
                callback(note)
            except Exception:  # a broken push target must never block alerts
                pass
        return cur.lastrowid

    def notifications(self, limit: int = 200, after_id: int = 0) -> list[dict]:
        return self._all("SELECT * FROM notifications WHERE id > ? ORDER BY id DESC LIMIT ?", (after_id, limit))

    def unread_count(self) -> int:
        return self._all("SELECT COUNT(*) AS n FROM notifications WHERE read = 0")[0]["n"]

    def mark_read(self, ids: list[int] | None = None):
        if ids is None:
            self._run("UPDATE notifications SET read = 1 WHERE read = 0")
        elif ids:
            marks = ",".join("?" * len(ids))
            self._run(f"UPDATE notifications SET read = 1 WHERE id IN ({marks})", tuple(ids))

    def clear_notifications(self):
        self._run("DELETE FROM notifications")

    # ---- cached analyses ----
    def save_analysis(self, symbol: str, payload: dict):
        self._run(
            "INSERT INTO analyses VALUES (?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET "
            "updated_at = excluded.updated_at, payload = excluded.payload",
            (symbol, time.time(), json.dumps(payload)),
        )

    def load_analyses(self) -> dict[str, dict]:
        return {r["symbol"]: json.loads(r["payload"]) for r in self._all("SELECT symbol, payload FROM analyses")}

    # ---- small key/value state ----
    def get_state(self, key: str, default=None):
        rows = self._all("SELECT value FROM state WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_state(self, key: str, value):
        self._run("INSERT INTO state VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (key, json.dumps(value)))

    # ---- SEC insider filings ----
    def has_filing(self, accession: str) -> bool:
        return bool(self._all("SELECT 1 FROM sec_filings WHERE accession = ?", (accession,)))

    def known_filings(self, accessions: list[str]) -> set[str]:
        if not accessions:
            return set()
        marks = ",".join("?" * len(accessions))
        rows = self._all(f"SELECT accession FROM sec_filings WHERE accession IN ({marks})", tuple(accessions))
        return {r["accession"] for r in rows}

    def save_filing(self, filing: dict, error: str | None = None) -> list[dict]:
        """Store a parsed Form 4 and its transactions. Returns the stored trade rows."""
        issuer = filing.get("issuer") or {}
        owners = filing.get("owners") or [{}]
        owner = owners[0]
        names = " & ".join(o.get("name", "") for o in owners if o.get("name"))
        rows = []
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sec_filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (filing["accession"], issuer.get("cik"), issuer.get("symbol"), issuer.get("name"),
                 filing.get("filed"), filing.get("accepted"), filing.get("url"), time.time(), error))
            for seq, tx in enumerate(filing.get("transactions") or []):
                row = {
                    "accession": filing["accession"], "seq": seq, "symbol": issuer.get("symbol"),
                    "issuer_cik": issuer.get("cik"), "issuer_name": issuer.get("name"),
                    "owner_cik": owner.get("cik"), "owner_name": names or owner.get("name"),
                    "role": owner.get("role"), "is_director": int(bool(owner.get("is_director"))),
                    "is_officer": int(bool(owner.get("is_officer"))),
                    "is_ten_pct": int(bool(owner.get("is_ten_pct"))), "code": tx["code"],
                    "acquired": int(tx["acquired"]), "derivative": int(tx["derivative"]),
                    "shares": tx["shares"], "price": tx["price"], "value": tx["value"],
                    "shares_after": tx["shares_after"], "direct": int(tx["direct"]),
                    "plan_10b5_1": int(tx["plan_10b5_1"]), "trade_date": tx["date"],
                    "filed": filing.get("filed"), "accepted": filing.get("accepted"),
                    "url": filing.get("url"), "footnote": tx.get("footnote"), "routine": None,
                }
                cols = ",".join(row)
                self._conn.execute(f"INSERT OR IGNORE INTO sec_trades ({cols}) VALUES ({','.join('?' * len(row))})",
                                   tuple(row.values()))
                rows.append(row)
            self._conn.commit()
        return rows

    def sec_trades_for_accession(self, accession: str) -> list[dict]:
        return self._all("SELECT * FROM sec_trades WHERE accession = ? ORDER BY seq", (accession,))

    def set_routine(self, accession: str, owner_cik: str | None, label: str):
        self._run("UPDATE sec_trades SET routine = ? WHERE accession = ? AND (owner_cik = ? OR ? IS NULL)",
                  (label, accession, owner_cik, owner_cik))

    def sec_trades(self, symbol: str | None = None, since: str | None = None, codes: tuple | None = None,
                   limit: int = 500) -> list[dict]:
        sql, args = "SELECT * FROM sec_trades WHERE 1=1", []
        if symbol:
            sql += " AND symbol = ?"
            args.append(symbol)
        if since:
            sql += " AND COALESCE(filed, trade_date) >= ?"
            args.append(since)
        if codes:
            sql += f" AND code IN ({','.join('?' * len(codes))})"
            args.extend(codes)
        sql += " ORDER BY COALESCE(accepted, filed) DESC, id DESC LIMIT ?"
        args.append(limit)
        return self._all(sql, tuple(args))

    def close(self):
        with self._lock:
            self._conn.close()
