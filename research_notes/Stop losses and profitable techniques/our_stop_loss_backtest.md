# Our own stop-loss backtest (StockAnalysis app data)

## Takeaway

On ~190 large US stocks over 2003–2026, every stop-loss rule tested lowered average annual return versus holding with no stop. Wide trailing stops (20–30%) and the 200-day-average exit cut the worst drawdown substantially and nudged the Sharpe ratio up slightly; tight stops (10% trailing, chandelier 3 ATR, 50-day average) cost 7–9 percentage points a year and lowered the Sharpe ratio. Fixed stops measured from the entry price barely mattered because a held stock rarely falls 8–25% below its purchase price and stays there. After a stop-out, the stock was higher 60 trading days later 62–72% of the time (whipsaw).

## Method

- Source: `stockanalysis/validation/stops.py` in the app repository, run on 2026-11-21 using Yahoo Finance adjusted daily prices.
- Universe: 73 training, 57 held-out and 58 final-exam large US stocks (stocks still listed today: survivorship bias flatters all long-only results equally).
- Each stock gets an equal slice of money, starts fully invested, and follows one exit rule; after a stop-out the slice earns the 3-month T-bill rate until its re-entry rule triggers.
- Intraday stops fill at the stop price, or at the open if the stock gaps below it. Close-based stops sell at the next open. 10 basis points cost per trade. No look-ahead.
- Benchmark: the same slices with no stop (buy and hold).
- Six test sets: three stock groups × two periods (2003–2014, which includes 2008; and 2015–2026).

## Benchmark (no stop)

| Test set | Yearly return | Worst drawdown | Sharpe |
| --- | --- | --- | --- |
| Training stocks 2003–2014 | 15.36% | -51.9% | 0.81 |
| Training stocks 2015–2026 | 21.3% | -38.4% | 0.9 |
| Held-out stocks 2003–2014 | 14.82% | -54.3% | 0.76 |
| Held-out stocks 2015–2026 | 11.37% | -36.4% | 0.72 |
| Final-exam stocks 2003–2014 | 13.91% | -52.9% | 0.73 |
| Final-exam stocks 2015–2026 | 11.9% | -41.1% | 0.73 |

## Every rule, averaged over the six test sets

Differences are versus no stop. Positive drawdown difference = shallower worst loss. 'Sets won' counts the six test sets where the rule beat holding.

| Rule | Yearly return vs hold (pts) | Worst drawdown vs hold (pts) | Sharpe vs hold | Sets won on return | Sets won on Sharpe | Time invested | Stop-outs per stock per year | Stock higher 60 days after stop-out | Avg move 60 days after stop-out |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Trailing 20% stop, re-buy on new 20-day high | -2.58 | +13.5 | +0.057 | 0/6 | 4/6 | 90% | 0.86 | 66% | +6.6% |
| Trailing 30% stop, re-buy on new 20-day high | -1.46 | +8.2 | +0.043 | 0/6 | 5/6 | 96% | 0.36 | 67% | +9.2% |
| Close below 200-day average, re-buy above it | -4.79 | +24.3 | +0.040 | 0/6 | 4/6 | 70% | 3.97 | 63% | +3.5% |
| Trailing 20% stop, re-buy next month | -1.99 | +6.2 | +0.027 | 0/6 | 4/6 | 95% | 1.02 | 67% | +7.8% |
| Trailing 30% stop, re-buy next month | -1.40 | +2.6 | +0.018 | 1/6 | 5/6 | 98% | 0.42 | 68% | +11.6% |
| Trailing 10% stop, re-buy next month | -4.67 | +14.9 | +0.000 | 0/6 | 4/6 | 83% | 3.54 | 64% | +5.5% |
| Fixed 25% stop, re-buy next month | -0.26 | -0.3 | -0.003 | 1/6 | 1/6 | 100% | 0.08 | 70% | +23.4% |
| Fixed 15% stop, re-buy next month | -0.41 | +0.1 | -0.005 | 0/6 | 0/6 | 100% | 0.16 | 70% | +15.7% |
| 2.5 ATR stop at entry, re-buy next month | -0.54 | +0.3 | -0.007 | 0/6 | 1/6 | 99% | 0.28 | 72% | +11.0% |
| Fixed 25% stop, re-buy on new 20-day high | -0.34 | +0.2 | -0.007 | 0/6 | 0/6 | 100% | 0.07 | 69% | +14.6% |
| Fixed 8% stop, re-buy next month | -0.64 | +0.5 | -0.010 | 1/6 | 1/6 | 99% | 0.33 | 69% | +12.2% |
| Time stop (losing after 60 days), re-buy next month | -0.37 | +0.1 | -0.010 | 0/6 | 0/6 | 99% | 0.19 | 70% | +10.3% |
| Time stop (losing after 60 days), re-buy on new 20-day high | -0.33 | +0.1 | -0.010 | 1/6 | 0/6 | 99% | 0.19 | 69% | +9.9% |
| Fixed 15% stop, re-buy on new 20-day high | -0.77 | +0.9 | -0.013 | 0/6 | 0/6 | 99% | 0.16 | 70% | +12.9% |
| 2.5 ATR stop at entry, re-buy on new 20-day high | -1.07 | +1.5 | -0.018 | 0/6 | 1/6 | 97% | 0.31 | 69% | +8.9% |
| Fixed 8% stop, re-buy on new 20-day high | -1.06 | +1.6 | -0.020 | 0/6 | 1/6 | 98% | 0.31 | 67% | +7.9% |
| Trailing 10% stop, re-buy on new 20-day high | -7.52 | +24.5 | -0.058 | 0/6 | 2/6 | 71% | 2.70 | 64% | +4.9% |
| Chandelier (22-day high minus 3 ATR), re-buy on new 20-day high | -8.59 | +25.4 | -0.100 | 0/6 | 1/6 | 54% | 4.46 | 63% | +3.7% |
| Close below 50-day average, re-buy above it | -8.59 | +22.3 | -0.170 | 0/6 | 1/6 | 60% | 8.46 | 62% | +3.6% |
| Chandelier (22-day high minus 3 ATR), re-buy next month | -9.42 | +22.8 | -0.180 | 0/6 | 1/6 | 53% | 7.85 | 63% | +4.3% |

## Detail for selected rules, per test set (yearly return / worst drawdown / Sharpe)

| Test set | No stop | Trailing 20% stop, re-buy on new 20-day high | Trailing 30% stop, re-buy on new 20-day high | Close below 200-day average, re-buy above it | Fixed 8% stop, re-buy next month | Trailing 10% stop, re-buy on new 20-day high | Chandelier (22-day high minus 3 ATR), re-buy next month |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Training stocks 2003–2014 | 15.36% / -51.9% / 0.81 | 12.73% / -42.5% / 0.91 | 14.73% / -45.4% / 0.91 | 12.68% / -22.6% / 1.09 | 14.46% / -51.6% / 0.8 | 8.27% / -25.2% / 0.82 | 5.49% / -32.5% / 0.57 |
| Training stocks 2015–2026 | 21.3% / -38.4% / 0.9 | 17.33% / -29.0% / 0.97 | 17.66% / -34.9% / 0.92 | 18.17% / -25.9% / 0.97 | 21.36% / -38.1% / 0.91 | 10.13% / -12.5% / 0.96 | 9.15% / -17.2% / 0.99 |
| Held-out stocks 2003–2014 | 14.82% / -54.3% / 0.76 | 13.71% / -40.5% / 0.89 | 14.65% / -45.0% / 0.86 | 9.88% / -26.0% / 0.84 | 14.29% / -53.3% / 0.76 | 8.02% / -30.5% / 0.75 | 4.01% / -29.1% / 0.42 |
| Held-out stocks 2015–2026 | 11.37% / -36.4% / 0.72 | 8.26% / -20.0% / 0.67 | 9.06% / -25.9% / 0.67 | 4.67% / -13.5% / 0.53 | 10.7% / -35.4% / 0.7 | 4.94% / -13.5% / 0.55 | 4.08% / -13.5% / 0.55 |
| Final-exam stocks 2003–2014 | 13.91% / -52.9% / 0.73 | 12.05% / -41.5% / 0.83 | 13.4% / -46.7% / 0.81 | 8.54% / -28.1% / 0.8 | 13.21% / -53.2% / 0.73 | 6.89% / -31.7% / 0.65 | 5.12% / -32.2% / 0.51 |
| Final-exam stocks 2015–2026 | 11.9% / -41.1% / 0.73 | 9.12% / -20.7% / 0.72 | 10.37% / -27.9% / 0.74 | 5.97% / -13.2% / 0.66 | 10.81% / -40.1% / 0.69 | 5.27% / -14.7% / 0.57 | 4.26% / -13.4% / 0.53 |

## Inferences

- Consistent with Kaminski & Lo and Lo & Remorov: on individual large-cap stocks, stops mainly trade return for smaller drawdowns; they do not add return.
- The width of the stop dominates: tight stops get hit by ordinary noise (2.7–8.5 stop-outs per stock per year) and miss the rebound.
- Re-entry rules matter as much as exit rules: re-buying on strength (new 20-day high) worked better with trailing stops than re-buying on the calendar.
- In the app's own active trading rules (round 1 of the app's validation), removing the trailing stop raised training-period returns but did not hold up out of sample, another sign that stop choice is fragile.

## Gaps

- Tested on large, surviving US stocks; small caps, momentum portfolios and lottery-like stocks (where studies find stops help more) were not tested.
- Taxes not modelled: every stop-out in a taxable account can realise a gain or loss.
