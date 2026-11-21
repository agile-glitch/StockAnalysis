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
- **Insider trade alerts (live from the SEC):** enter a name and email under
  Settings > Insider trade alerts (the SEC requires a contact from automated
  tools; it is only sent to sec.gov). The app then reads Form 4 filings every
  2 minutes and alerts on:
  - every open-market purchase at a stock on your watchlist, and large sales
    if you turn them on;
  - big purchases by officers and directors at any US company ($500K and up by
    default);
  - cluster buying, when 3 or more insiders buy one stock within 30 days.
  Each alert says who bought, their role, size, price, stake change, whether it
  was a pre-planned 10b5-1 trade, and whether it fits a routine yearly pattern,
  with a link to the filing. See [docs/INSIDER_ALERTS.md](docs/INSIDER_ALERTS.md)
  for every other way to get insider alerts and the research behind the filters.
- **Phone notifications:** paste an [ntfy](https://ntfy.sh) topic link (free
  app), or a Discord or Slack webhook, under Settings > Phone notifications.
- **News, Earnings, Insider trades:** combined feeds across your watchlist,
  plus a live market-wide feed of insider purchases.
- **Positions:** record what you bought to get sell alerts and to subtract it
  from the cash available for new trades.
- **Settings:** budget (also editable from the top bar), risk per stock trade,
  largest position, options on/off, options risk per trade, refresh interval.
  Changing the budget immediately resizes every trade plan and options idea.

## Does it work? The track record

The rules were replayed day by day on 20+ years of prices for about 190 large
US stocks, with costs, no peeking ahead, and separate stocks and years held
back for testing. Full results are on the app's **Track record** page and in
[docs/VALIDATION.md](docs/VALIDATION.md). In short:

- Every version of the rules made money in every period.
- The per-stock Buy and Sell ratings did **not** beat the market: new Buy
  signals beat the S&P 500 about half the time.
- What held up was **market-level risk control**: holding less stock when the
  whole market is in a downtrend or very turbulent roughly halved the worst
  losses (−35% instead of −55% on unseen stocks, 2006–2026), with a similar
  return per unit of risk.
- It did **not** make more money than staying invested: about 9.4% a year
  against 12.1%, mostly from missing fast rebounds.

So the dashboard leads with a **Market risk** indicator (a suggested share of
your budget in stocks, with an alert when the market turns), and the stock
ratings are best read as information, not as a proven trading system.

To rerun the test (downloads about 190 price histories the first time):

```bash
python -m stockanalysis.validation
```

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
  market.py                 market risk indicator (the rule that held up)
  validation/               historical test: replay, signal study, portfolio, walk-forward
  sec.py                    SEC EDGAR client and Form 4 parser
  insiders.py               live insider-trade watcher and alerts
  push.py                   phone push (ntfy, Discord, Slack)
  providers/                Yahoo Finance (live) and demo data sources
  static/                   web interface (no build step)
docs/STRATEGIES.md          research behind the rules
docs/INSIDER_ALERTS.md      how to get insider-trade alerts, compared
docs/VALIDATION.md          the historical test results (generated)
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
- Without an SEC contact, insider data falls back to Yahoo's delayed summary.
  The market-wide insider feed only covers filings published while the app is
  running. Form 144 and congressional trades are not tracked.
- The historical test covers the price rules and earnings surprises; insider
  trades, news tone and options could not be replayed. Only companies still
  listed today could be downloaded, which flatters all long-only results.
