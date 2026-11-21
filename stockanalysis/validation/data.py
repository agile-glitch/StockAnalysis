"""Download and cache long price and earnings histories from Yahoo Finance."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger("stockanalysis.validation")

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "history"
MAX_AGE_DAYS = 3


def _fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < MAX_AGE_DAYS * 86400


def _yf():
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return yf


def load_prices(symbols: list[str], refresh: bool = False) -> dict[str, pd.DataFrame]:
    """{symbol: OHLCV frame}, split- and dividend-adjusted, oldest first."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    missing = []
    for sym in symbols:
        path = CACHE_DIR / f"{sym}.prices.csv.gz"
        if not refresh and _fresh(path):
            out[sym] = pd.read_csv(path, index_col=0, parse_dates=True)
        elif not refresh and _fresh(CACHE_DIR / f"{sym}.missing"):
            continue  # Yahoo had no history for it recently
        else:
            missing.append(sym)
    yf = _yf()
    for i in range(0, len(missing), 20):
        batch = missing[i:i + 20]
        for attempt in range(3):
            try:
                raw = yf.download(batch, period="max", auto_adjust=True, progress=False,
                                  threads=True, group_by="ticker")
                break
            except Exception as exc:  # network hiccup or rate limit
                log.warning("Download failed (%s), retrying", exc)
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for sym in batch:
            try:
                df = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
            except KeyError:
                df = pd.DataFrame()
            if len(df) < 300:
                log.warning("Skipping %s: no usable history (delisted or renamed)", sym)
                (CACHE_DIR / f"{sym}.missing").touch()
                continue
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            df.to_csv(CACHE_DIR / f"{sym}.prices.csv.gz")
            out[sym] = df
        time.sleep(1)
    return out


def load_earnings(symbols: list[str], refresh: bool = False) -> dict[str, pd.DataFrame]:
    """{symbol: frame of reported earnings with 'date' and 'surprise_pct'}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    yf = _yf()
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        path = CACHE_DIR / f"{sym}.earnings.csv"
        if not refresh and _fresh(path):
            out[sym] = pd.read_csv(path, parse_dates=["date"])
            continue
        df = None
        for attempt in range(3):
            try:
                df = yf.Ticker(sym).get_earnings_dates(limit=100)
                break
            except Exception as exc:
                log.warning("Earnings for %s failed (%s), retrying", sym, exc)
                time.sleep(5 * (attempt + 1))
        rows = []
        if df is not None and not df.empty:
            for when, row in df.iterrows():
                surprise = row.get("Surprise(%)")
                if pd.notna(surprise):
                    rows.append({"date": pd.Timestamp(when).tz_localize(None), "surprise_pct": float(surprise)})
        frame = pd.DataFrame(rows, columns=["date", "surprise_pct"]).sort_values("date")
        frame.to_csv(path, index=False)
        out[sym] = frame
        time.sleep(0.4)
    return out


def load_tbill(refresh: bool = False) -> pd.Series:
    """Daily 13-week Treasury bill yield in percent (interest earned on idle cash)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "TBILL.csv"
    if not refresh and _fresh(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)["yield"]
    yf = _yf()
    h = yf.Ticker("^IRX").history(period="max", auto_adjust=False)
    series = h["Close"].rename("yield")
    series.index = pd.DatetimeIndex(series.index).tz_localize(None).normalize()
    series.to_frame().to_csv(path)
    return series
