"""Technical indicators, computed as pandas Series so they can be reused by
the live signal engine (last row) and the backtester (every row)."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # No losses in the window means maximum strength, not "unknown".
    out = out.where(avg_loss != 0.0, 100.0)
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def realized_vol(close: pd.Series, n: int = 30) -> pd.Series:
    """Annualised close-to-close volatility over n trading days."""
    returns = np.log(close / close.shift(1))
    return returns.rolling(n, min_periods=n).std() * np.sqrt(TRADING_DAYS)


def build_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Attach every indicator the strategies use to an OHLCV frame.

    Expects columns open/high/low/close/volume on a date index, oldest first.
    """
    f = df[["open", "high", "low", "close", "volume"]].copy()
    close = f["close"]

    f["sma5"] = sma(close, 5)
    f["sma20"] = sma(close, 20)
    f["sma50"] = sma(close, 50)
    f["sma200"] = sma(close, 200)
    # Slope of the 200-day average over the last month.
    f["sma200_slope"] = f["sma200"] / f["sma200"].shift(21) - 1.0

    f["rsi2"] = rsi(close, 2)
    f["rsi14"] = rsi(close, 14)
    f["macd"], f["macd_signal"], f["macd_hist"] = macd(close)

    f["atr14"] = atr(f, 14)
    f["atr22"] = atr(f, 22)
    f["hv30"] = realized_vol(close, 30)

    # 52-week closing high (needs roughly half a year before it means anything).
    f["high252"] = close.rolling(TRADING_DAYS, min_periods=126).max()
    f["low252"] = close.rolling(TRADING_DAYS, min_periods=126).min()
    # 12-1 momentum: the return from 12 months ago to 1 month ago, skipping the
    # most recent month (which tends to mean-revert).
    f["mom_12_1"] = close.shift(21) / close.shift(TRADING_DAYS) - 1.0

    f["vol_avg50"] = f["volume"].rolling(50, min_periods=20).mean()
    # Chandelier exit: a trailing stop 3 ATRs under the highest high of 22 days.
    f["chandelier"] = f["high"].rolling(22, min_periods=22).max() - 3.0 * f["atr22"]
    f["day_change"] = close.pct_change()
    return f
