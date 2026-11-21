"""Market risk indicator: how much of the budget to keep in stocks.

This is the part of the app's approach that held up in the historical tests
(see docs/VALIDATION.md). The rule, picked most often by the walk-forward
test in recent years:

* Risk-off (hold cash / T-bills) only when the S&P 500 is below its 200-day
  average AND its 12-month return is below what T-bills paid. Requiring both
  avoids many false alarms from short dips.
* Otherwise stay invested, but scale down when the market is turbulent:
  exposure = 15% / recent S&P 500 volatility, capped at 100%.

Over 2006-2026 this kind of rule cut the worst loss by roughly half, with a
similar return per unit of risk, but about 2-3 percentage points a year less
total return than always staying invested, because it misses some of the
fastest rebounds.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

VOL_TARGET = 0.15
DEFAULT_TBILL = 4.0  # percent, used when the T-bill rate is unavailable


def market_regime(spy: pd.DataFrame, tbill: pd.Series | None = None) -> dict | None:
    close = spy["close"].dropna()
    if len(close) < 260:
        return None
    sma200 = float(close.rolling(200).mean().iloc[-1])
    price = float(close.iloc[-1])
    mom12 = float(close.iloc[-1] / close.iloc[-253] - 1)
    if tbill is not None and len(tbill.dropna()) > 20:
        rate = float(tbill.dropna().iloc[-252:].mean())
    else:
        rate = DEFAULT_TBILL
    tbill_12m = rate / 100.0
    vol20 = float(np.log(close).diff().iloc[-20:].std() * math.sqrt(252))
    above = price > sma200
    momentum_ok = mom12 > tbill_12m
    risk_on = above or momentum_ok
    vol_scale = min(1.0, VOL_TARGET / vol20) if vol20 > 0 else 1.0
    exposure = (1.0 if risk_on else 0.0) * vol_scale

    if not risk_on:
        state, tone = "Risk-off", "bearish"
        trend = "The S&P 500 is in a downtrend: below its 200-day average and lagging T-bills over 12 months."
    elif above and momentum_ok:
        trend = "The S&P 500 is above its 200-day average and beating T-bills over 12 months."
    elif above:
        trend = "The S&P 500 is above its 200-day average, though its 12-month return trails T-bills."
    else:
        trend = ("The S&P 500 has slipped below its 200-day average, but is still beating T-bills over "
                 "12 months, so the trend rule stays invested.")
    if risk_on and vol_scale < 0.9:
        state, tone = "Turbulent", "warning"
        headline = (f"{trend} Prices are swinging {vol20 * 100:.0f}% a year, above the "
                    f"{VOL_TARGET * 100:.0f}% comfort level, so hold less.")
    elif risk_on:
        state, tone = "Risk-on", "bullish"
        headline = f"{trend} Calm enough to stay fully invested."
    else:
        headline = trend + " Hold cash or T-bills until it recovers."
    return {
        "state": state,
        "tone": tone,
        "headline": headline,
        "risk_on": risk_on,
        "exposure_pct": round(exposure * 100),
        "as_of": close.index[-1].date().isoformat(),
        "spy_price": round(price, 2),
        "sma200": round(sma200, 2),
        "above_200": above,
        "pct_from_200": round((price / sma200 - 1) * 100, 1),
        "mom12_pct": round(mom12 * 100, 1),
        "tbill_pct": round(rate, 2),
        "momentum_ok": momentum_ok,
        "vol20_pct": round(vol20 * 100, 1),
        "vol_target_pct": round(VOL_TARGET * 100),
    }
