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

## Profit plan: the goal is profit

The dashboard leads with a **Profit plan**: one clear instruction (what to
hold now) and an alert the day it changes. It comes from the profit study
([docs/PROFIT.md](docs/PROFIT.md)), which tested index funds, 2x and 3x
leveraged funds, trend switches and dual momentum over 1961–today.

| Plan | Rule | S&P 500 since 1961: per year / worst drop | SPY since 1994 |
| --- | --- | --- | --- |
| Hold the index (baseline) | always invested | +7.3% / −57% | +10.5% / −55% |
| Steady | S&P 500 fund while the market switch is on, else T-bills | +9.0% / −33% | +10.4% / −28% |
| **Growth** (default) | 2x S&P 500 fund (SSO) while the S&P 500 is above its 200-day average, else T-bills | +9.6% / −45% | +12.5% / −44% |
| Aggressive | 3x S&P 500 fund (UPRO) while the market switch is on, else T-bills | +12.6% / −78% | +19.8% / −66% |

Index figures since 1961 exclude dividends for every row (about 2 points a
year low). Growth was picked before testing by a fixed rule (the highest
return with a worst drop no deeper than holding) and then beat holding in both
halves of history, in the fund era and on the Nasdaq-100. Leverage *without*
the switch was a disaster (3x held all the time lost 99% at its worst). The
simulated leveraged funds match the real SSO, UPRO, QLD and TQQQ closely.
Choose the plan on the dashboard (or turn it off); rerun the study with
`python -m stockanalysis.validation.profit`.

## Does it work? The track record

The rules were replayed day by day on 20+ years of prices for about 190 large
US stocks, with costs, no peeking ahead, and separate stocks and years held
back for testing. Full results are on the app's **Track record** page and in
[docs/VALIDATION.md](docs/VALIDATION.md). In short:

- Every version of the rules made money in every period.
- The per-stock Buy and Sell ratings did **not** beat the market: new Buy
  signals beat the S&P 500 about half the time.
- What came closest to holding up was **market-level risk control**: holding
  less stock when the whole market is in a downtrend or very turbulent made
  crashes smaller (worst loss −45% instead of −55% on unseen stocks, 2006–2026,
  when the rule was chosen year by year in real time), with about the same
  return per unit of risk.
- It did **not** make more money than staying invested: about 9.6% a year
  against 12.1%, mostly from missing fast rebounds.
- None of 172 indicator settings (moving averages, RSI, Bollinger bands, MACD,
  breakouts, momentum) beat holding on unseen stocks. See the Indicator Lab.

So the dashboard leads with a **Market risk** indicator (a suggested share of
your budget in stocks, with an alert when the market turns), and the stock
ratings are best read as information, not as a proven trading system.

**Scorecard** ([docs/SCORECARD.md](docs/SCORECARD.md), top of the Track
record page): every method the app recommends, on past prices with costs.

| Method | Period | Yearly return | Worst drop | Compared with |
| --- | --- | --- | --- | --- |
| Stock Buy/Sell signals (unseen stocks) | 2006–2026 | +9.6% | −45% | holding them: +12.1%, −55% |
| Market risk switch | 1994–2026 | +9.1% | −21% | S&P 500: +10.4%, −55% |
| Profit plan: Growth (2x with 200-day switch) | 1994–2026 | +12.3% | −44% | S&P 500: +10.4%, −55% |
| Trend portfolio (8 assets, 2% band) | 2006–2026 | +5.1% | −12% | 60/40: +8.0%, −31% |
| Market trend alerts (picked on data to 2015, 2% band) | 2016–2026 | +5.8% | −16% | holding them: +5.1%, −34% |

All made money and beat T-bills; the Growth profit plan and the market trend
alerts made more than their comparisons. The real gain is smaller worst
drops. Rerun with `python -m stockanalysis.validation.scorecard`.

**Cutting losing entries** ([docs/ENTRIES.md](docs/ENTRIES.md)): entry
filters were chosen on early data and then tested on later years and other
stocks. A **2% band** on the 10-month trend rule (buy only on a month-end
close more than 2% above the average, sell only 2% below) cut losing trades
from 63% to 55% across 23 funds in 2016–2026 and halved the number of trades,
with the same return. It is now the default for market trend alerts and the
trend portfolio (change it on the Markets page). For stocks, the combined
filters cut losing trades (73% to 68%) but also cut the return, so the Buy
rule is unchanged; Buy alerts now say whether volume confirmed the signal,
the single filter that did best. Rerun with
`python -m stockanalysis.validation.entries`.

To rerun the test (downloads about 190 price histories the first time):

```bash
python -m stockanalysis.validation
```

## Indicator Lab

Indicator settings (moving-average lengths, RSI thresholds, band widths) work
like a model's weights, so the **Indicator lab** page lets you change them with
sliders and immediately see how that tactic would have traded any stock over
the last 10 years, against simply holding it. You can save a tactic as **my
indicator alert** to get buy and sell alerts for your watchlist.

172 settings across 8 indicators were also fitted the machine-learning way
(train on some stocks and years, validate and test on others). None beat
holding on data they were not tuned on. Two follow-up experiments, learning
the score's weights by ridge regression and 560 indicator combinations, also
failed on 92 fresh stocks, so the app's rules were left unchanged. See
[docs/INDICATOR_LAB.md](docs/INDICATOR_LAB.md) and
[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md). To rerun:

```bash
python -m stockanalysis.validation.lab
```

## Markets: gold, silver, oil, bonds, currencies, crypto

The **Markets** page tracks 27 markets beyond single stocks (gold, silver,
platinum, oil, natural gas, copper, broad commodities, agriculture, Treasury,
inflation-linked, corporate and high-yield bonds, the dollar, euro and yen,
real estate, US, foreign and emerging stock indexes, Bitcoin and Ether), with
each one's live trend under the 10-month rule and how trend rules did against
holding it over its history. Any of them, or any symbol such as `GC=F`,
`BTC-USD` or `^GSPC`, can be added to the watchlist.

Findings ([docs/MARKETS.md](docs/MARKETS.md)): trend rules helped most in
commodity funds (oil, natural gas, broad commodities, farm goods) and Ether;
holding did as well or better in gold, bonds, real estate and most stock
markets. A diversified 10-month trend portfolio (Faber 2007) had by far the
smallest crashes but less return than a 60/40 mix. "Stocks we are best at"
did not persist: the stocks where a rule did best in 2003–2014 did no better
than the rest in 2015–2026.

**Trend alerts.** Each market has an alert switch (🔔). When a market's
10-month rule changes at a month end, you get an alert in the app, and on your
phone if push is set up. Alerts start out on for the markets where most trend
rules beat holding in testing (oil, natural gas, broad commodities,
agriculture, euro, Nasdaq, Ether). The first scan after a change only records
the current state, so turning an alert on never fires an old signal.

**Your trend portfolio.** The Markets page also tracks the 8-asset trend
portfolio with your budget: what to hold now and how many dollars go in each
(budget ÷ 8 per asset held, the rest in cash or T-bills), how far each asset
is from its average, which ones would change if the month ended today, the
next month-end check, and the last two years of changes. It sends one alert
when the holdings change (switch it off on the card). Trend and market-risk
alerts go to your phone with the default push setting, because they come only
a few times a year.

To rerun the market tests:

```bash
python -m stockanalysis.validation.markets
```

## TradingView

- **Charts:** every stock page (and the Indicator Lab) can show a TradingView
  chart with all of TradingView's indicators and drawing tools, pre-loaded with
  the app's averages or the tactic you are testing. It loads only after you
  click, because TradingView's script then sees which stocks you view.
- **Pine Script:** "Get Pine Script for TradingView" in the Indicator Lab
  exports the tactic as a Pine v5 strategy (signals at the close, fills at the
  next open, 0.1% commission, like the app's tests). Paste it into TradingView's
  Pine Editor and open the Strategy Tester to check the results yourself.
- **Alerts in:** Settings › TradingView alerts gives a private webhook address
  and a ready-made alert message. TradingView webhooks need a paid TradingView
  plan with two-factor sign-in, and TradingView must reach the app over
  HTTPS, so run a tunnel such as `cloudflared tunnel --url http://localhost:8000`
  or `ngrok http 8000`. Requests through a tunnel can reach only the webhook,
  not the rest of the app.
- TradingView is not used for price data: it has no public data API and its
  terms do not allow scraping.

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
  market.py                 market risk indicator
  tactics.py                indicator tactics with adjustable settings
  lab_runner.py             runs a tactic on one stock (Indicator Lab)
  tradingview.py            TradingView charts, Pine Script export, webhook alerts
  markets_view.py           live view of other markets for the Markets page
  trend_watch.py            10-month-rule market alerts and the trend portfolio tracker
  profit_plan.py            the Profit plan (steady / growth / aggressive) and its alerts
  validation/               historical test: replay, signal study, portfolio, walk-forward
  sec.py                    SEC EDGAR client and Form 4 parser
  insiders.py               live insider-trade watcher and alerts
  push.py                   phone push (ntfy, Discord, Slack)
  providers/                Yahoo Finance (live) and demo data sources
  static/                   web interface (no build step)
docs/STRATEGIES.md          research behind the rules
docs/INSIDER_ALERTS.md      how to get insider-trade alerts, compared
docs/VALIDATION.md          the historical test results (generated)
docs/INDICATOR_LAB.md       indicator-settings test results (generated)
docs/EXPERIMENTS.md         fitted weights and indicator combinations (generated)
docs/MARKETS.md             other markets and stock persistence (generated)
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
