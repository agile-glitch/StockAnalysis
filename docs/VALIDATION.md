# Track record: does the program hold up on past data?

Generated 2026-11-21T07:36:13+00:00 by `python -m stockanalysis.validation` (runs in under a minute once prices are cached). The same results are on the app's **Track record** page.

## Bottom line

1. **Every version of the rules made money** in every period tested.
2. **The per-stock Buy and Sell ratings did not beat the market.** For example, on 2015–today data, 3,337 new Buy signals beat the S&P 500 over the next 3 months 45.8% of the time, with an average excess return of -0.02%. Stocks rated Sell did no worse than average, and in some periods better.
3. **Market-level risk control held up.** Following a market-timing rule chosen year by year with only past data, on 58 stocks never used for tuning (20.9 years): worst loss -34.6% instead of -54.8%, Sharpe 0.68 vs 0.65.
4. **It did not make more money than staying invested:** 9.44% a year vs 12.13%. On the S&P 500 itself: 8.42% vs 10.44% a year, worst loss -24.9% vs -55.2%. The cost comes from missing fast rebounds (2019, 2020, 2023).

So the app now shows a **Market risk** indicator on the dashboard (suggested share of the budget in stocks) based on the rule that held up, and the per-stock ratings are presented as information, not as a proven trading system.

## How the test works

- **What is replayed:** price rules (trend, momentum, 52-week high, pullback, MACD) and earnings surprise. Not replayed: insider trades and news tone (no free history). The replayed scorer is checked against the live app's code to give identical scores.
- **No peeking:** signals use only data up to each day's close; trades happen at the next open. Earnings surprises count from the day after the report.
- **Costs:** 10.0 basis points per buy and per sell. Idle cash earns the 3-month T-bill rate.
- **Training data:** 73 stocks, 2003-2014. **Test data:** same stocks 2015-today, plus 57 held-out stocks over both periods.
- **Final exam:** 58 further stocks, untouched until round 2 had picked its rules, run once.
- **Survivorship bias:** only companies that still trade could be downloaded, which flatters every long-only result. Comparisons are against buying and holding the *same* stocks, which shares the bias.
- **Win** for a Buy signal means the stock beat the S&P 500 afterwards (not merely went up).

## Round 1: the app's original rules

| Period | Buy signals beat market (3 mo) | Avg excess (3 mo) | Rules: yearly | Rules: worst drop | Hold same: yearly | Hold same: worst drop | Holds up? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Training stocks, 2003–2014 (used for tuning) | 50.0% of 3,384 | +0.39% | +5.6% | -44.1% | +14.2% | -52.6% | No |
| Training stocks, 2015–today | 45.8% of 3,337 | -0.02% | +10.4% | -25.3% | +15.1% | -36.6% | No |
| Held-out stocks, 2003–2014 | 53.6% of 2,565 | +0.99% | +4.5% | -42.5% | +16.6% | -50.7% | No |
| Held-out stocks, 2015–today | 46.7% of 2,635 | -0.60% | +6.6% | -22.6% | +12.0% | -37.1% | No |

Round 1 also compared 18 variants on the training data. The best there ("Market filter + strongest buys") did not hold up on the test data either.

## Round 2: hold a basket, decide when to be in the market

Selection: made money in all four periods, then highest median Sharpe advantage over holding the same stocks.

| Idea | Median Sharpe advantage | Worst period | Always profitable |
| --- | --- | --- | --- |
| Hold all except Sell-rated, market filter **(chosen)** | +0.17 | -0.22 | Yes |
| Hold all, market filter | +0.16 | -0.23 | Yes |
| Top 25 momentum, market filter | +0.11 | -0.26 | Yes |
| Hold Buy-rated stocks, market filter | +0.10 | -0.19 | Yes |
| Top 15 by app score, market filter | +0.06 | -0.29 | Yes |
| Top 15 momentum, market filter | +0.00 | -0.34 | Yes |
| Hold Buy-rated stocks | -0.03 | -0.09 | Yes |
| Hold stocks above their 200-day average | -0.08 | -0.24 | Yes |
| Market filter | -0.20 | -0.25 | Yes |
| App rules (baseline) | -0.24 | -0.48 | Yes |

### Final exam (58 untouched stocks)

| Period | Rule: yearly | Rule: worst drop | Hold same: yearly | Hold same: worst drop | S&P 500: yearly | Original rules: yearly | Holds up? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2003–2014 | +15.6% | -20.7% | +15.9% | -52.2% | +9.2% | +9.7% | Yes |
| 2015–today | +6.3% | -25.9% | +13.1% | -41.5% | +12.6% | +4.2% | No |

## Round 3: walk-forward test of market-timing rules

Each year, the rule with the best Sharpe ratio over all *earlier* years (on stocks already seen and the S&P 500 back to 1996) is applied to the next year on the final-exam stocks. The candidate list was written after seeing the round 2 final exam; the year-by-year choices were not.

| Basket | Rule: yearly | Rule: worst drop | Rule: Sharpe | Always invested: yearly | Always invested: worst drop | Always invested: Sharpe |
| --- | --- | --- | --- | --- | --- | --- |
| Final-exam stocks (unseen) | +9.4% | -34.6% | 0.68 | +12.1% | -54.8% | 0.65 |
| Training stocks | +10.5% | -27.9% | 0.79 | +13.4% | -54.0% | 0.74 |
| S&P 500 (SPY) | +8.4% | -24.9% | 0.66 | +10.4% | -55.2% | 0.61 |

Rule used each year: 2006: Both filters must agree, 2007: Both filters must agree, 2008: Both filters must agree, 2009: Both filters must agree, 2010: Both filters must agree, 2011: Both filters must agree, 2012: Volatility target 15% + both filters, 2013: Volatility target 15% + both filters, 2014: Volatility target 15% + both filters, 2015: Volatility target 15% + both filters, 2016: Volatility target 15% + both filters, 2017: 200-day filter, 2018: 200-day filter, 2019: Volatility target 15% + both filters, 2020: Volatility target 15% + both filters, 2021: 200-day filter, 2022: 200-day filter, 2023: Volatility target 15% + 200-day filter, 2024: Volatility target 15% + both filters, 2025: Volatility target 15% + both filters, 2026: Volatility target 15% + both filters.

## What this cannot tell you

- Insider trades and news tone (25 of the score's 100 points) have no free history, so they were not tested. Insider history exists in the SEC's bulk Form 4 datasets, which need a declared contact to download.
- Options ideas were not tested: free historical option prices do not exist.
- Survivorship bias (above), and the usual: past results do not guarantee future ones.
