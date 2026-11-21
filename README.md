# StockAnalysis

A local app that follows the stocks you care about (prices, news, earnings
reports and insider trades) and alerts you when its rules say to buy or sell,
with call and put ideas sized to a budget you set.

The rules come from published research on what has worked for timing trades.
See [docs/STRATEGIES.md](docs/STRATEGIES.md) for the evidence, sources and
known weaknesses of each one.

> Educational tool, not financial advice. Every trade can lose money, and a
> bought option can lose its entire cost.

## Quick start

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt
```

```bash
python run.py
```

Your browser opens at http://localhost:8000. Live data comes from Yahoo Finance
and needs no API key.

To try it offline with simulated data:

```bash
python run.py --demo
```

Options: `--port 8080`, `--host 0.0.0.0` (reach it from other devices on your
network), `--no-browser`.

## What it does

- **Dashboard:** your watchlist with a Buy / Hold / Sell signal, a score from
  −100 to +100, the main reason, a suggested trade sized to your budget, and
  the next earnings date. Add any ticker from the search box.
- **Stock page:** price chart with 50- and 200-day averages, every signal and
  why it scored what it did, a stock trade plan (shares, entry, stop, target,
  trailing stop), options ideas, earnings history, insider trades, headlines,
  and a backtest of the price rules on that stock.
- **Alerts:** in-app notifications (and optional desktop pop-ups) when a signal
  changes, the price breaks its trend or trailing stop, a held position hits
  its stop, an insider buys, earnings are a week away or just reported, news
  turns sharply, or a new options idea appears. The background scan runs every
  15 minutes by default.
- **News, Earnings, Insider trades:** combined feeds across your watchlist.
- **Positions:** record what you bought to get sell alerts and to subtract it
  from the cash available for new trades.
- **Settings:** budget (also editable from the top bar), risk per stock trade,
  largest position, options on/off, options risk per trade, refresh interval.
  Changing the budget immediately resizes every trade plan and options idea.

## How the signal is built

| Rule | Points |
|---|---|
| Long-term trend (price vs 200-day average) | ±25 |
| 12-month momentum, skipping the last month | ±15 |
| Distance from the 52-week high | ±10 |
| Entry timing (RSI pullbacks in an uptrend) | ±10 |
| MACD confirmation | ±5 |
| Earnings surprise, fading over ~60 trading days | ±10 |
| Insider buying (cluster buys score highest) | ±15 |
| Headline tone | ±10 |

+25 or more is Buy (+50 Strong buy), −25 or less is Sell (−50 Strong sell).
A stock below its 200-day average is never a Buy, whatever the other rules say.

Stock trades are sized so that hitting the stop (2.5 × the average daily range
below entry) loses your "risk per trade" share of the budget. Options ideas use
~45-day monthly expiries and ~0.60 delta, switch to spreads around earnings or
when options are expensive, and never risk more than the "options risk per
trade" setting.

## Project layout

```
run.py                      start the app
stockanalysis/
  indicators.py             moving averages, RSI, MACD, ATR, momentum, volatility
  strategies.py             the eight rules, the composite score, chart events
  sizing.py                 budget-based position sizing and stops
  options.py                call/put/spread/cash-secured-put selection
  sentiment.py              finance word-list headline tone
  backtest.py               day-by-day replay of the price rules
  engine.py                 analysis, notifications, background scheduler
  db.py                     SQLite: settings, watchlist, positions, alerts
  server.py                 HTTP API (FastAPI)
  providers/                Yahoo Finance (live) and demo data sources
  static/                   web interface (no build step)
docs/STRATEGIES.md          research behind the rules
tests/                      pytest suite (runs offline on demo data)
```

Data is stored in `data/stockanalysis.db`; set `STOCKANALYSIS_DB` to use
another file.

## Tests

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest
```

## Limits

- Yahoo Finance data is free but unofficial and can be delayed, rate-limited or
  briefly unavailable; the app keeps the last good values and says so.
  Option quotes outside market hours often lack a live bid/ask.
- Insider data covers each company's recent filings only, so routine and
  one-off insiders are not yet told apart.
- The backtest covers only the price rules and ignores costs and taxes.
