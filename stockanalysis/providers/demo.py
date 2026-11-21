"""Simulated market data for trying the app offline and for tests.

Nothing here is real: prices are a seeded random walk, and the news, earnings,
insider trades and option chains are generated to be internally consistent
with that walk. The same symbol always produces the same data.
"""

from __future__ import annotations

import math
import time
import zlib
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ..options import bs_price
from .base import Provider, ProviderError

# (yearly drift, yearly volatility, start price) chosen to show a mix of signals.
PROFILES = {
    "AAPL": (0.28, 0.24, 180.0, "Apple Inc."),
    "MSFT": (0.20, 0.21, 330.0, "Microsoft Corporation"),
    "NVDA": (0.60, 0.42, 60.0, "NVIDIA Corporation"),
    "AMZN": (0.08, 0.30, 150.0, "Amazon.com, Inc."),
    "GOOGL": (0.32, 0.27, 130.0, "Alphabet Inc."),
    "TSLA": (-0.30, 0.55, 320.0, "Tesla, Inc."),
    "SPY": (0.14, 0.14, 480.0, "SPDR S&P 500 ETF Trust"),
}

POSITIVE_NEWS = [
    "{name} beats estimates as demand stays strong",
    "Analysts upgrade {sym} after record quarter",
    "{sym} shares rally on raised full-year guidance",
    "{name} wins major contract, boosting growth outlook",
    "{sym} jumps as buyback plan expands",
]
NEGATIVE_NEWS = [
    "{sym} shares slide after analyst downgrade",
    "{name} faces probe; stock falls",
    "{sym} drops as margins miss expectations",
    "{name} warns of weak demand next quarter",
    "Lawsuit concerns weigh on {sym}",
]
NEUTRAL_NEWS = [
    "{name} to present at industry conference next week",
    "What to watch in {sym} this quarter",
    "{name} names new head of operations",
]


def _seed(symbol: str, salt: str = "") -> int:
    return zlib.crc32(f"{symbol}:{salt}".encode())


def _last_business_day(today: date) -> date:
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class DemoProvider(Provider):
    name = "demo"
    is_demo = True

    def __init__(self, today: date | None = None):
        self._today = today

    def today(self) -> date:
        return self._today or datetime.now(timezone.utc).date()

    def _profile(self, symbol: str):
        if symbol in PROFILES:
            return PROFILES[symbol]
        if not symbol.isalpha() or len(symbol) > 5:
            raise ProviderError(f"No price data for {symbol}. Check the ticker symbol.")
        rng = np.random.default_rng(_seed(symbol, "profile"))
        return (float(rng.uniform(-0.25, 0.45)), float(rng.uniform(0.18, 0.5)),
                float(rng.uniform(15, 400)), f"{symbol} Corp. (simulated)")

    def history(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        drift, vol, start, _ = self._profile(symbol)
        years = {"1y": 1, "2y": 2, "5y": 5, "10y": 5, "max": 5}.get(period, 2)
        # Generate the longest path and slice, so every period ends on the same prices.
        n_total = 5 * 252
        rng = np.random.default_rng(_seed(symbol, "prices"))
        daily = rng.normal((drift - 0.5 * vol * vol) / 252, vol / math.sqrt(252), n_total)
        close = start * np.exp(np.cumsum(daily))
        spread = np.abs(rng.normal(0, vol / math.sqrt(252) * 0.6, n_total))
        open_ = np.concatenate([[start], close[:-1]]) * (1 + rng.normal(0, 0.003, n_total))
        high = np.maximum(open_, close) * (1 + spread)
        low = np.minimum(open_, close) * (1 - spread)
        volume = rng.integers(8_000_000, 60_000_000, n_total).astype(float)
        idx = pd.bdate_range(end=pd.Timestamp(_last_business_day(self.today())), periods=n_total)
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
        return df.iloc[-years * 252:]

    def quote(self, symbol: str) -> dict:
        _, _, _, name = self._profile(symbol)
        df = self.history(symbol, "1y")
        price, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        rng = np.random.default_rng(_seed(symbol, "quote"))
        return {
            "name": name,
            "price": price,
            "prev_close": prev,
            "change_pct": (price / prev - 1) * 100,
            "currency": "USD",
            "market_cap": price * float(rng.integers(200, 15000)) * 1e6,
            "sector": "Simulated",
            "quote_type": "ETF" if symbol == "SPY" else "EQUITY",
            "analyst_target": price * float(rng.uniform(0.9, 1.25)),
            "analyst_rating": "buy",
            "analyst_count": 30.0,
        }

    def news(self, symbol: str, count: int = 12) -> list[dict]:
        _, _, _, name = self._profile(symbol)
        df = self.history(symbol, "1y")
        recent = float(df["close"].iloc[-1] / df["close"].iloc[-6] - 1)
        rng = np.random.default_rng(_seed(symbol, f"news{self.today()}"))
        p_pos = min(0.8, max(0.15, 0.45 + recent * 4))
        now = time.time()
        items = []
        for i in range(min(count, 8)):
            roll = rng.random()
            pool = POSITIVE_NEWS if roll < p_pos else NEGATIVE_NEWS if roll < p_pos + 0.3 else NEUTRAL_NEWS
            title = pool[int(rng.integers(0, len(pool)))].format(sym=symbol, name=name.split(",")[0])
            items.append({
                "id": f"demo-{symbol}-{self.today()}-{i}",
                "title": title,
                "summary": "Simulated headline for demo mode.",
                "publisher": "Demo Wire",
                "url": None,
                "published": now - (i * 7 + float(rng.uniform(0.2, 5))) * 3600,
            })
        return items

    def earnings(self, symbol: str) -> list[dict]:
        if symbol == "SPY":
            return []
        rng = np.random.default_rng(_seed(symbol, "earnings"))
        last = self.today() - timedelta(days=int(rng.integers(5, 85)))
        base = float(rng.uniform(0.5, 4.0))
        events = [{
            "date": (last + timedelta(days=91)).isoformat(),
            "eps_estimate": round(base * 1.05, 2),
            "eps_actual": None,
            "surprise_pct": None,
        }]
        for q in range(8):
            estimate = round(base * (1 - 0.03 * q), 2)
            surprise = float(rng.normal(3, 6))
            events.append({
                "date": (last - timedelta(days=91 * q)).isoformat(),
                "eps_estimate": estimate,
                "eps_actual": round(estimate * (1 + surprise / 100), 2),
                "surprise_pct": round(surprise, 2),
            })
        return events

    def insiders(self, symbol: str) -> list[dict] | None:
        if symbol == "SPY":
            return []
        rng = np.random.default_rng(_seed(symbol, "insiders"))
        price = float(self.history(symbol, "1y")["close"].iloc[-1])
        names = ["RIVERA ANA M", "CHEN DAVID", "OKAFOR JAMES T", "LINDQVIST SARA", "PATEL ROHAN"]
        roles = ["Chief Executive Officer", "Chief Financial Officer", "Director", "Director", "Officer"]
        # Roughly a third of symbols show cluster buying, a third only selling.
        mode = int(rng.integers(0, 3))
        trades = []
        for i in range(6):
            who = int(rng.integers(0, len(names)))
            kind = "buy" if (mode == 0 and i < 4) else "sell" if (mode != 2 or i % 2) else "other"
            if mode == 0 and i < 4:
                who = i % 4  # four different insiders buying
            shares = float(rng.integers(500, 40000))
            verb = {"buy": "Purchase", "sell": "Sale", "other": "Stock Award(Grant)"}[kind]
            px = 0.0 if kind == "other" else price * float(rng.uniform(0.92, 1.02))
            trades.append({
                "date": (self.today() - timedelta(days=int(rng.integers(2, 120)))).isoformat(),
                "insider": names[who],
                "position": roles[who],
                "kind": kind,
                "shares": shares,
                "value": round(shares * px, 0),
                "text": f"{verb} at price {px:.2f} per share.",
            })
        return sorted(trades, key=lambda t: t["date"], reverse=True)

    def expirations(self, symbol: str) -> list[str]:
        self._profile(symbol)
        first = self.today() + timedelta(days=(4 - self.today().weekday()) % 7 or 7)
        return [(first + timedelta(days=7 * i)).isoformat() for i in range(12)]

    def option_chain(self, symbol: str, expiry: str) -> list[dict]:
        df = self.history(symbol, "1y")
        spot = float(df["close"].iloc[-1])
        returns = np.log(df["close"] / df["close"].shift(1)).dropna().iloc[-30:]
        hv = float(returns.std() * math.sqrt(252))
        dte = max((date.fromisoformat(expiry) - self.today()).days, 1)
        t = dte / 365.0
        step = 1.0 if spot < 50 else 2.5 if spot < 150 else 5.0 if spot < 500 else 10.0
        center = round(spot / step) * step
        rng = np.random.default_rng(_seed(symbol, f"chain{expiry}"))
        out = []
        for i in range(-14, 15):
            strike = center + i * step
            if strike <= 0:
                continue
            moneyness = strike / spot - 1
            iv = hv * 1.15 * (1 + 0.6 * max(-moneyness, 0) + 0.2 * max(moneyness, 0))
            for kind in ("call", "put"):
                fair = bs_price(spot, strike, t, iv, kind)
                if fair < 0.03:
                    continue
                half = max(0.01, fair * 0.015)
                out.append({
                    "contract": f"{symbol}{expiry.replace('-', '')[2:]}{kind[0].upper()}{int(strike * 1000):08d}",
                    "type": kind,
                    "strike": float(strike),
                    "expiry": expiry,
                    "bid": round(fair - half, 2),
                    "ask": round(fair + half, 2),
                    "last": round(fair, 2),
                    "volume": int(rng.integers(20, 4000)),
                    "open_interest": int(rng.integers(150, 20000)),
                    "iv": round(iv, 4),
                })
        return out

    def search(self, query: str) -> list[dict]:
        q = query.strip().upper()
        hits = [{"symbol": s, "name": p[3], "type": "EQUITY"}
                for s, p in PROFILES.items() if q in s or q in p[3].upper()]
        if not hits and q.isalpha() and len(q) <= 5:
            hits = [{"symbol": q, "name": f"{q} Corp. (simulated)", "type": "EQUITY"}]
        return hits
