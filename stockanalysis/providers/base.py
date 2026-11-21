"""Data provider interface.

Every provider returns the same plain shapes so the engine never touches a
vendor's format:

  history(symbol, period)  DataFrame, date index (oldest first), columns
                           open/high/low/close/volume
  quote(symbol)            {name, price, prev_close, change_pct, currency, market_cap,
                            sector, quote_type, analyst_target, analyst_rating}
  news(symbol)             [{id, title, summary, publisher, url, published (epoch s)}]
  earnings(symbol)         [{date (ISO), eps_estimate, eps_actual, surprise_pct}]
                           including the next scheduled report (eps_actual None)
  insiders(symbol)         [{date, insider, position, kind (buy|sell|other),
                            shares, value, text}] or None when unavailable
  expirations(symbol)      ["YYYY-MM-DD", ...]
  option_chain(symbol, e)  [{contract, type (call|put), strike, expiry, bid, ask,
                            last, volume, open_interest, iv}]
  search(query)            [{symbol, name, type}]
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

import pandas as pd


class ProviderError(Exception):
    """The data source could not answer (network, rate limit, unknown symbol)."""


class Provider(ABC):
    name = "base"
    is_demo = False

    @abstractmethod
    def history(self, symbol: str, period: str = "2y") -> pd.DataFrame: ...

    @abstractmethod
    def quote(self, symbol: str) -> dict: ...

    @abstractmethod
    def news(self, symbol: str, count: int = 12) -> list[dict]: ...

    @abstractmethod
    def earnings(self, symbol: str) -> list[dict]: ...

    @abstractmethod
    def insiders(self, symbol: str) -> list[dict] | None: ...

    @abstractmethod
    def expirations(self, symbol: str) -> list[str]: ...

    @abstractmethod
    def option_chain(self, symbol: str, expiry: str) -> list[dict]: ...

    @abstractmethod
    def search(self, query: str) -> list[dict]: ...


# Seconds each kind of data stays fresh. Slow-moving data is cached for hours
# so a scan every few minutes does not hammer the source.
DEFAULT_TTL = {
    "history": 5 * 60,
    "quote": 5 * 60,
    "news": 10 * 60,
    "earnings": 6 * 3600,
    "insiders": 6 * 3600,
    "expirations": 6 * 3600,
    "option_chain": 10 * 60,
    "search": 24 * 3600,
}


class CachedProvider(Provider):
    """Wraps a provider with an in-memory TTL cache, safe to use from threads."""

    def __init__(self, inner: Provider, ttl: dict | None = None):
        self.inner = inner
        self.name = inner.name
        self.is_demo = inner.is_demo
        self.ttl = {**DEFAULT_TTL, **(ttl or {})}
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def _get(self, kind: str, *args):
        key = (kind, *args)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl[kind]:
                return hit[1]
        value = getattr(self.inner, kind)(*args)
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def invalidate(self, symbol: str | None = None):
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                for key in [k for k in self._cache if len(k) > 1 and k[1] == symbol]:
                    del self._cache[key]

    def history(self, symbol, period="2y"):
        return self._get("history", symbol, period)

    def quote(self, symbol):
        return self._get("quote", symbol)

    def news(self, symbol, count=12):
        return self._get("news", symbol, count)

    def earnings(self, symbol):
        return self._get("earnings", symbol)

    def insiders(self, symbol):
        return self._get("insiders", symbol)

    def expirations(self, symbol):
        return self._get("expirations", symbol)

    def option_chain(self, symbol, expiry):
        return self._get("option_chain", symbol, expiry)

    def search(self, query):
        return self._get("search", query)
