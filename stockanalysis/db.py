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
}

SETTING_LIMITS = {
    "budget": (1.0, 1e9),
    "risk_per_trade_pct": (0.1, 10.0),
    "max_position_pct": (1.0, 100.0),
    "option_risk_pct": (0.1, 25.0),
    "refresh_minutes": (1, 240),
}

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
        with self._lock:
            self._conn.executescript(SCHEMA)
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
            if key == "options_enabled":
                clean[key] = bool(value)
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} must be a number") from None
            lo, hi = SETTING_LIMITS[key]
            if not (lo <= number <= hi):
                raise SettingsError(f"{key} must be between {lo:g} and {hi:g}")
            clean[key] = int(number) if key == "refresh_minutes" else number
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
    def add_notification(self, *, symbol: str | None, kind: str, tone: str, title: str, body: str,
                         dedup_key: str | None = None) -> int | None:
        """Insert unless one with the same dedup key exists. Returns the new id or None."""
        cur = self._run(
            "INSERT OR IGNORE INTO notifications (created_at, symbol, kind, tone, title, body, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), symbol, kind, tone, title, body, dedup_key),
        )
        return cur.lastrowid if cur.rowcount else None

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

    def close(self):
        with self._lock:
            self._conn.close()
