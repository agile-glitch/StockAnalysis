"""Live data from Yahoo Finance through the yfinance library (no API key)."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

import pandas as pd

from .base import Provider, ProviderError

_TAGS = re.compile(r"<[^>]+>")


def _num(x):
    """Float, or None for missing / NaN values."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _epoch(value) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def classify_insider_trade(text: str, transaction: str = "") -> str:
    """Open-market purchase, sale, or something that is not a view on the stock."""
    label = f"{transaction} {text}".strip().lower()
    if label.startswith("purchase") or " purchase" in label[:20]:
        return "buy"
    if label.startswith("sale") or label.startswith("sell"):
        return "sell"
    return "other"  # gifts, grants, option exercises, tax withholding


class YahooProvider(Provider):
    name = "yahoo"

    def __init__(self):
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("yfinance is not installed. Run: pip install -r requirements.txt") from exc
        self.yf = yf

    def _ticker(self, symbol: str):
        return self.yf.Ticker(symbol)

    def history(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        try:
            df = self._ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
        except Exception as exc:
            raise ProviderError(f"Could not load prices for {symbol}: {exc}") from exc
        if df is None or df.empty:
            raise ProviderError(f"No price data for {symbol}. Check the ticker symbol.")
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df = df.dropna(subset=["close"])
        df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        return df

    def quote(self, symbol: str) -> dict:
        t = self._ticker(symbol)
        info: dict = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        fast: dict = {}
        if not info.get("regularMarketPrice"):
            try:
                fast = dict(t.fast_info)
            except Exception:
                fast = {}
        price = _num(info.get("regularMarketPrice")) or _num(info.get("currentPrice")) or _num(fast.get("lastPrice"))
        prev = _num(info.get("regularMarketPreviousClose")) or _num(fast.get("regularMarketPreviousClose"))
        change = _num(info.get("regularMarketChangePercent"))
        if change is None and price and prev:
            change = (price / prev - 1.0) * 100.0
        return {
            "name": info.get("shortName") or info.get("longName") or symbol,
            "price": price,
            "prev_close": prev,
            "change_pct": change,
            "currency": info.get("currency") or fast.get("currency") or "USD",
            "market_cap": _num(info.get("marketCap")) or _num(fast.get("marketCap")),
            "sector": info.get("sector"),
            "quote_type": info.get("quoteType") or fast.get("quoteType"),
            "analyst_target": _num(info.get("targetMeanPrice")),
            "analyst_rating": info.get("recommendationKey"),
            "analyst_count": _num(info.get("numberOfAnalystOpinions")),
        }

    def news(self, symbol: str, count: int = 12) -> list[dict]:
        try:
            raw = self._ticker(symbol).get_news(count=count) or []
        except Exception as exc:
            raise ProviderError(f"Could not load news for {symbol}: {exc}") from exc
        items = []
        for entry in raw:
            c = entry.get("content") or entry
            title = c.get("title")
            if not title:
                continue
            url = ((c.get("canonicalUrl") or {}).get("url")
                   or (c.get("clickThroughUrl") or {}).get("url") or c.get("link"))
            summary = c.get("summary") or _TAGS.sub("", c.get("description") or "")
            items.append({
                "id": str(c.get("id") or entry.get("id") or url or title),
                "title": title.strip(),
                "summary": (summary or "").strip()[:400],
                "publisher": (c.get("provider") or {}).get("displayName") or "",
                "url": url,
                "published": _epoch(c.get("pubDate") or c.get("displayTime")),
            })
        return items

    def earnings(self, symbol: str) -> list[dict]:
        t = self._ticker(symbol)
        events: list[dict] = []
        try:
            df = t.get_earnings_dates(limit=12)
        except Exception:
            df = None
        if df is not None and not df.empty:
            if "Event Type" in df.columns:
                df = df[df["Event Type"].fillna("Earnings").str.contains("Earnings", case=False)]
            for when, row in df.iterrows():
                events.append({
                    "date": pd.Timestamp(when).date().isoformat(),
                    "eps_estimate": _num(row.get("EPS Estimate")),
                    "eps_actual": _num(row.get("Reported EPS")),
                    "surprise_pct": _num(row.get("Surprise(%)")),
                })
        today = datetime.now(timezone.utc).date().isoformat()
        if not any(e["date"] >= today for e in events):
            # Fall back to the calendar for the next scheduled report.
            try:
                cal = t.calendar or {}
                dates = cal.get("Earnings Date") or []
                for d in dates[:1]:
                    events.append({
                        "date": d.isoformat(),
                        "eps_estimate": _num(cal.get("Earnings Average")),
                        "eps_actual": None,
                        "surprise_pct": None,
                    })
            except Exception:
                pass
        return sorted(events, key=lambda e: e["date"], reverse=True)

    def insiders(self, symbol: str) -> list[dict] | None:
        try:
            df = self._ticker(symbol).insider_transactions
        except Exception:
            return None
        if df is None:
            return None
        if df.empty:
            return []
        trades = []
        for _, row in df.iterrows():
            when = row.get("Start Date")
            if when is None or pd.isna(when):
                continue
            text = str(row.get("Text") or "")
            trades.append({
                "date": pd.Timestamp(when).date().isoformat(),
                "insider": str(row.get("Insider") or "").strip(),
                "position": str(row.get("Position") or "").strip(),
                "kind": classify_insider_trade(text, str(row.get("Transaction") or "")),
                "shares": _num(row.get("Shares")),
                "value": _num(row.get("Value")),
                "text": text,
            })
        return trades

    def expirations(self, symbol: str) -> list[str]:
        try:
            return list(self._ticker(symbol).options or [])
        except Exception:
            return []

    def option_chain(self, symbol: str, expiry: str) -> list[dict]:
        try:
            chain = self._ticker(symbol).option_chain(expiry)
        except Exception as exc:
            raise ProviderError(f"Could not load options for {symbol} {expiry}: {exc}") from exc
        out = []
        for kind, df in (("call", chain.calls), ("put", chain.puts)):
            for _, row in df.iterrows():
                strike = _num(row.get("strike"))
                if strike is None:
                    continue
                out.append({
                    "contract": row.get("contractSymbol"),
                    "type": kind,
                    "strike": strike,
                    "expiry": expiry,
                    "bid": _num(row.get("bid")) or 0.0,
                    "ask": _num(row.get("ask")) or 0.0,
                    "last": _num(row.get("lastPrice")) or 0.0,
                    "volume": int(_num(row.get("volume")) or 0),
                    "open_interest": int(_num(row.get("openInterest")) or 0),
                    "iv": _num(row.get("impliedVolatility")) or 0.0,
                })
        return out

    def search(self, query: str) -> list[dict]:
        try:
            quotes = self.yf.Search(query, max_results=8).quotes or []
        except Exception:
            return []
        return [
            {"symbol": q.get("symbol"), "name": q.get("shortname") or q.get("longname") or "",
             "type": q.get("quoteType")}
            for q in quotes
            if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "FUTURE", "CRYPTOCURRENCY", "INDEX", "CURRENCY")
        ]
