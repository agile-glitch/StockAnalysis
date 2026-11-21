"""TradingView integration.

Three pieces:

* chart studies: which TradingView indicators (with which settings) show a
  tactic on the embedded TradingView chart;
* Pine Script export: each Indicator Lab tactic as a Pine v5 strategy, so it
  can be checked in TradingView's Strategy Tester;
* webhook alerts: TradingView alerts posted to the app become app alerts.

TradingView has no public market-data API and its terms forbid scraping, so
it is used for charts and alerts only; prices still come from Yahoo Finance.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

from . import tactics as T

# Widget study ids; checked against the live widget, which accepts these input
# names. The MACD study ignores custom inputs, so non-default MACD settings
# are drawn as their two EMAs instead (MACD above zero = fast EMA above slow).
STUDY_SMA = "MASimple@tv-basicstudies"
STUDY_EMA = "MAExp@tv-basicstudies"


def tv_symbol(symbol: str) -> str:
    """Yahoo ticker -> TradingView ticker (class shares use a dot on TradingView)."""
    special = {"^GSPC": "SP:SPX", "^IXIC": "NASDAQ:IXIC", "^DJI": "DJ:DJI", "^IRX": "TVC:US03MY"}
    if symbol in special:
        return special[symbol]
    return symbol.replace("-", ".")


def studies(tactic: str | None, params: dict | None = None) -> list[dict]:
    """TradingView chart studies that show a tactic, with its settings."""
    if not tactic:  # the stock page: the app's own averages plus RSI
        return [{"id": STUDY_SMA, "inputs": {"length": 50}}, {"id": STUDY_SMA, "inputs": {"length": 200}},
                {"id": "RSI@tv-basicstudies", "inputs": {"length": 14}}]
    p = T.clean_params(tactic, params)
    if tactic == "price_ma":
        return [{"id": STUDY_SMA, "inputs": {"length": p["n"]}}]
    if tactic == "ma_cross":
        sid = STUDY_EMA if p["ema"] else STUDY_SMA
        return [{"id": sid, "inputs": {"length": p["fast"]}}, {"id": sid, "inputs": {"length": p["slow"]}}]
    if tactic == "rsi_reversion":
        out = [{"id": "RSI@tv-basicstudies", "inputs": {"length": p["period"]}}]
        if p["trend_filter"]:
            out.append({"id": STUDY_SMA, "inputs": {"length": 200}})
        return out
    if tactic in ("bollinger_reversion", "bollinger_breakout"):
        return [{"id": "BB@tv-basicstudies", "inputs": {"length": p["n"], "stdDev": p["k"]}}]
    if tactic == "macd":
        if (p["fast"], p["slow"], p["signal"]) == (12, 26, 9):
            return [{"id": "MACD@tv-basicstudies"}]
        return [{"id": STUDY_EMA, "inputs": {"length": p["fast"]}}, {"id": STUDY_EMA, "inputs": {"length": p["slow"]}}]
    if tactic == "donchian":
        return [{"id": "DONCH@tv-basicstudies", "inputs": {"length": p["entry"]}},
                {"id": "DONCH@tv-basicstudies", "inputs": {"length": p["exit"]}}]
    if tactic == "momentum":
        return [{"id": "ROC@tv-basicstudies", "inputs": {"length": p["lookback"]}}]
    return []


# --------------------------------------------------------------------------
# Pine Script
# --------------------------------------------------------------------------

def _b(x) -> str:
    return "true" if x else "false"


def pine_script(tactic: str, params: dict | None = None) -> str:
    """A Pine Script v5 strategy that trades exactly like the Lab tactic."""
    p = T.clean_params(tactic, params)
    label = T.describe(tactic, p)
    lines = [
        "//@version=5",
        f'strategy("StockAnalysis: {label}", overlay=true, initial_capital=10000,',
        "     default_qty_type=strategy.percent_of_equity, default_qty_value=100,",
        "     commission_type=strategy.commission.percent, commission_value=0.1, pyramiding=0)",
        "",
        "// Exported from the StockAnalysis Indicator Lab.",
        "// Signals use each bar's close and fill at the next bar's open, like the app's tests.",
        "// Use a daily chart. Strategy Tester results will differ slightly from the app's",
        "// (different price data, dividends and fill details).",
        "",
    ]
    hold_based = True
    if tactic == "price_ma":
        lines += [f'n = input.int({p["n"]}, "Average length (days)", minval=2)',
                  "ma = ta.sma(close, n)",
                  "hold = close > ma",
                  'plot(ma, "Average", color=color.blue)']
    elif tactic == "ma_cross":
        lines += [f'fastLen = input.int({p["fast"]}, "Fast average (days)", minval=1)',
                  f'slowLen = input.int({p["slow"]}, "Slow average (days)", minval=2)',
                  f'useEma = input.bool({_b(p["ema"])}, "Use exponential averages")',
                  "fastMa = useEma ? ta.ema(close, fastLen) : ta.sma(close, fastLen)",
                  "slowMa = useEma ? ta.ema(close, slowLen) : ta.sma(close, slowLen)",
                  "hold = fastMa > slowMa",
                  'plot(fastMa, "Fast", color=color.orange)',
                  'plot(slowMa, "Slow", color=color.blue)']
    elif tactic == "rsi_reversion":
        hold_based = False
        lines += [f'rsiLen = input.int({p["period"]}, "RSI length (days)", minval=2)',
                  f'buyBelow = input.int({p["buy_below"]}, "Buy when RSI is below")',
                  f'sellAbove = input.int({p["sell_above"]}, "Sell when RSI is above")',
                  f'trendFilter = input.bool({_b(p["trend_filter"])}, "Only buy above the 200-day average")',
                  "r = ta.rsi(close, rsiLen)",
                  "sma200 = ta.sma(close, 200)",
                  "enter = r < buyBelow and (not trendFilter or close > sma200)",
                  "leave = r > sellAbove",
                  'plot(trendFilter ? sma200 : na, "200-day average", color=color.gray)']
    elif tactic in ("bollinger_reversion", "bollinger_breakout"):
        hold_based = False
        lines += [f'n = input.int({p["n"]}, "Band length (days)", minval=2)',
                  f'k = input.float({p["k"]}, "Band width (standard deviations)", step=0.1)',
                  "basis = ta.sma(close, n)",
                  "dev = k * ta.stdev(close, n, false)",
                  "upper = basis + dev",
                  "lower = basis - dev"]
        if tactic == "bollinger_reversion":
            lines += ["enter = close < lower", "leave = close > basis"]
        else:
            lines += ["enter = close > upper", "leave = close < basis"]
        lines += ['plot(basis, "Middle", color=color.gray)', 'plot(upper, "Upper", color=color.teal)',
                  'plot(lower, "Lower", color=color.teal)']
    elif tactic == "macd":
        lines += [f'fastLen = input.int({p["fast"]}, "Fast EMA (days)", minval=1)',
                  f'slowLen = input.int({p["slow"]}, "Slow EMA (days)", minval=2)',
                  f'sigLen = input.int({p["signal"]}, "Signal line (days)", minval=1)',
                  f'zeroLine = input.bool({_b(p["zero_line"])}, "Use the zero line instead of the signal line")',
                  "[macdLine, signalLine, _] = ta.macd(close, fastLen, slowLen, sigLen)",
                  "hold = zeroLine ? macdLine > 0 : macdLine > signalLine"]
    elif tactic == "donchian":
        hold_based = False
        lines += [f'entryLen = input.int({p["entry"]}, "Breakout length (days)", minval=2)',
                  f'exitLen = input.int({p["exit"]}, "Exit length (days)", minval=2)',
                  "hi = ta.highest(close, entryLen)[1]",
                  "lo = ta.lowest(close, exitLen)[1]",
                  "enter = close > hi",
                  "leave = close < lo",
                  'plot(hi, "Breakout level", color=color.green)',
                  'plot(lo, "Exit level", color=color.red)']
    elif tactic == "momentum":
        lines += [f'lookback = input.int({p["lookback"]}, "Lookback (trading days)", minval=2)',
                  f'skip = input.int({p["skip"]}, "Skip the most recent (days)", minval=0)',
                  "ret = close[skip] / close[lookback] - 1",
                  "hold = ret > 0"]
    else:
        raise KeyError(tactic)

    lines.append("")
    if hold_based:
        lines += ["if hold and strategy.position_size == 0",
                  '    strategy.entry("Long", strategy.long)',
                  "if not hold and strategy.position_size > 0",
                  '    strategy.close("Long")']
    else:
        lines += ["// An exit signal wins if both fire on the same bar, as in the app.",
                  "if leave and strategy.position_size > 0",
                  '    strategy.close("Long")',
                  "else if enter and not leave and strategy.position_size == 0",
                  '    strategy.entry("Long", strategy.long)']
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Webhook alerts
# --------------------------------------------------------------------------

MAX_BODY = 10_000
SUGGESTED_MESSAGE = json.dumps({
    "ticker": "{{ticker}}",
    "action": "{{strategy.order.action}}",
    "price": "{{close}}",
    "title": "{{ticker}}: TradingView {{strategy.order.action}}",
    "message": "{{strategy.order.comment}} at {{close}} on {{interval}}",
}, indent=2)

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_BULL = {"buy", "long", "bullish", "enter", "entry"}
_BEAR = {"sell", "short", "bearish", "exit", "close", "flat"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def parse_alert(text: str) -> dict:
    """Turn a TradingView alert body (JSON or plain text) into an app alert."""
    text = (text or "").strip()
    data: dict = {}
    if text.startswith("{"):
        try:
            loaded = json.loads(text)
            data = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            data = {}
    raw_symbol = str(data.get("ticker") or data.get("symbol") or "").upper().split(":")[-1].strip()
    symbol = raw_symbol.replace(".", "-") if _SYMBOL.match(raw_symbol) else None
    action = str(data.get("action") or data.get("side") or "").strip().lower()
    if not data and text:
        words = text.split()
        action = next((w.strip(".,:;!").lower() for w in words if w.strip(".,:;!").lower() in _BULL | _BEAR), "")
        lead = words[0].upper().split(":")[-1].strip(".,:;!")
        if _SYMBOL.match(lead) and lead == words[0].split(":")[-1].strip(".,:;!"):
            raw_symbol, symbol = lead, lead.replace(".", "-")
    tone = "bullish" if action in _BULL else "bearish" if action in _BEAR else "info"
    first_line = text.splitlines()[0] if text else "TradingView alert"
    title = str(data.get("title") or (f"{raw_symbol}: TradingView {action}".strip() if raw_symbol else "") or first_line)
    body = str(data.get("message") or (text if not data else ""))
    price = data.get("price") or data.get("close")
    if price and str(price) not in body:
        body = f"{body.rstrip('.')} (price {price})." if body else f"Price {price}."
    if not body:
        body = "Alert from TradingView."
    return {"symbol": symbol, "tone": tone, "title": title[:150], "body": body[:1000], "action": action or None}


def dedup_key(text: str) -> str:
    """Same body within the same minute = a retry, not a new alert."""
    minute = int(time.time() // 60)
    return "tradingview:" + hashlib.sha256(f"{minute}:{text}".encode()).hexdigest()[:24]
