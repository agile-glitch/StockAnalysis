# Research: what has actually worked for following stocks and timing trades

This is the research behind the rules in `stockanalysis/strategies.py` and
`stockanalysis/options.py`. The short version: **nothing times the market
reliably**, but a handful of effects have survived independent, out-of-sample
testing. The app combines them so that no single signal triggers a trade, and
it sizes every trade so a wrong call costs a small, fixed share of your budget.

## Summary

| Strategy | What the evidence says | How strong | Weight in the app |
|---|---|---|---|
| Trend filter (price vs 200-day / 10-month average) | Similar returns to buy-and-hold with much smaller drawdowns | Strong, long history, but lags at turns | 25 pts + blocks buys in downtrends |
| 12-month momentum (skip last month) | Past 3–12 month winners keep winning for months, then reverse long-term | Strong, one of the most replicated anomalies | 15 pts |
| Nearness to 52-week high | Stocks near their high outperform; does not reverse | Good, partly overlaps momentum | 10 pts |
| Insider buying | Non-routine insider buys earn ~0.8%/month abnormal returns; routine trades ≈ 0 | Strong for buys, weak for sales | 15 pts |
| Post-earnings drift | Prices keep drifting after a surprise for ~60 trading days | Was strong; much weaker in large caps since ~2006 | 10 pts, decays with age |
| News tone | Negative wording predicts lower prices for 1–2 days, then reverts | Real but short-lived | 10 pts |
| RSI(2) pullbacks in an uptrend | Short dips in rising stocks bounce within days | Practitioner backtests only, no costs | 10 pts, timing only |
| MACD | Confirmation of short-term direction | Weak on its own | 5 pts |

## 1. Trend following

Mebane Faber's *A Quantitative Approach to Tactical Asset Allocation* (2007)
tested a rule of holding an asset only while its monthly close is above its
10-month moving average (roughly the 200-day average), back to 1900. The result
was equity-like returns with bond-like volatility and drawdowns. One
replication for 1973–2011 reports a worst drawdown of about −10% for the
timing rule against −46% for buy-and-hold. Critics point out that the rule
lags at turning points, had its worst stretch in 1980, and adds little in some
portfolio settings.

**Used as:** the largest single weight, and a hard gate: the app never says Buy
for a stock below its 200-day average.

- Faber paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461
- Alpha Architect replication: https://alphaarchitect.com/2014/09/are-uber-simple-asset-allocation-systems-robust/

## 2. Momentum and the 52-week high

Jegadeesh and Titman (1993) found that buying the past 3–12 month winners and
selling the losers was profitable, and not explained by risk; their 2001
follow-up shows the effect reverses over longer horizons. George and Hwang
(2004) showed that nearness to the 52-week high explains much of momentum and
does not reverse, which they attribute to investors anchoring on the old high.
Later work finds the two effects partly independent, and replications report
smaller returns than the original papers.

**Used as:** 12-month return skipping the latest month (which tends to reverse),
plus distance below the 52-week high.

- Jegadeesh & Titman: https://www.nber.org/system/files/working_papers/w7159/w7159.pdf
- George & Hwang: https://www.bauer.uh.edu/tgeorge/papers/gh5-paper.pdf

## 3. Following insider trades

Executives and directors report their trades to the SEC on Form 4 within two
business days. Cohen, Malloy and Pomorski, *Decoding Inside Information*
(2012), split insiders into "routine" traders (who trade at the same time every
year) and "opportunistic" ones. A portfolio of opportunistic trades earned about
**82 basis points a month** in abnormal returns; routine trades earned
essentially nothing. Over half of all insider trades are routine. Other studies
find that several insiders buying in the same window ("cluster buying") adds
information on top of that split. Sales say much less, because insiders sell
for taxes, diversification and pre-scheduled 10b5-1 plans.

**Used as:** buys score positive and cluster buys (3+ insiders in 90 days) score
highest; sales score only slightly negative; gifts, grants and option exercises
are ignored. Every insider purchase in the last 14 days triggers an alert.
The app does not yet separate routine from opportunistic insiders, which would
need several years of each insider's filing history.

- NBER paper: https://www.nber.org/papers/w16454

## 4. Earnings surprises

Bernard and Thomas (1989) documented post-earnings-announcement drift of about
2% over 60 trading days in the direction of the surprise. It persisted for
decades and across markets, but Martineau (2021, *Rest in Peace Post-Earnings
Announcement Drift*) finds no drift in recent large-cap data, and some work
finds it only in smaller stocks or with text-based surprise measures.

**Used as:** a modest weight that fades to zero about 85 calendar days after the
report. Upcoming reports trigger a warning a week ahead, because they cause big
moves either way and inflate option prices.

- Review: https://static.uni-graz.at/fileadmin/sowi/Working_Paper/2020-04_Fink.pdf
- Martineau: https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf

## 5. News tone

Tetlock (2007) found that pessimistic wording in a Wall Street Journal column
predicted lower prices the next day, followed by a reversal; firm-level
negative words also forecast weaker earnings, and prices underreact briefly. A
Federal Reserve study of 900,000+ stories found daily news predicts returns for
only one to two days.

**Used as:** a small, recency-weighted tie-breaker using a finance-specific word
list (general sentiment dictionaries misread words like "liability" or "tax").
General market stories in a stock's feed are shown but not scored.

- Tetlock: https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf

## 6. Entry timing: short-term pullbacks

Larry Connors' RSI(2) rule buys when the 2-day RSI falls below ~5–10 while the
price is above its 200-day average, and exits on a bounce. Its published
results are hypothetical backtests without trading costs or data-mining
corrections.

**Used as:** a small timing nudge inside an uptrend, never a reason to buy a
stock on its own.

- StockCharts: https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2
- CXO Advisory caveats: https://cxoadvisory.com/technical-trading/a-few-notes-on-short-term-trading-strategies-that-work

## 7. Position sizing and exits

The research on stop placement is mostly practitioner material; it shows that
volatility-based stops make risk consistent, not that they raise returns. The
app uses the standard method:

- **Stop:** 2.5 × ATR(14) below entry (ATR = average daily range).
- **Shares:** (budget × risk per trade) ÷ (entry − stop), then capped by the
  largest position allowed and by uncommitted cash.
- **Trailing stop:** the chandelier exit, 3 × ATR(22) under the 22-day high.
- **First target:** 2× the risk.

## 8. Options: what to avoid

- Bryzgalova, Pavlova and Sikorskaya (Journal of Finance, 2023): retail traders
  favour cheap, short-dated, lottery-like options with bid/ask spreads averaging
  12.6%, and lose money on average.
- de Silva, Smith and So, *Losing is Optional* (2023): retail traders buy options
  before earnings, overpay for the expected volatility, hold through the
  post-report volatility collapse, and lose 5–9% on average, 10–14% around
  high-volatility announcements.
- Cboe's PutWrite (PUT) and BuyWrite (BXM) indexes have historically delivered
  returns near the S&P 500 with lower volatility, which supports selling options
  when they are expensive.

**Used as:** options are suggested only when the stock signal is already Buy or
Sell; about 45 days to expiry (standard monthly expiries preferred); delta near
0.60 for bought options; spreads instead of outright buys near earnings or when
implied volatility is rich; cash-secured puts when implied volatility is well
above realised; covered calls on 100+ held shares when the signal is neutral;
every idea capped by the "options risk per trade" setting, with warnings for
wide spreads and thin open interest.

- MIT Sloan summary: https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows
- Losing is Optional: https://www.gsb.stanford.edu/faculty-research/working-papers/losing-optional-retail-option-trading-expected-announcement
- Cboe benchmark indexes: https://www.cboe.com/insights/posts/key-cboe-benchmark-indexes-using-spx-options-offer-strong-risk-adjusted-returns/

## What the app cannot tell you

- These effects are averages across thousands of stocks and decades. On any one
  stock, in any one month, they are often wrong.
- Several have weakened since publication as more traders use them.
- The built-in backtest replays only the price rules on one stock, ignores
  costs and taxes, and is in-sample. Expect trend rules to lag buy-and-hold in
  strong bull markets; their value is in avoiding deep declines.
- Nothing here is financial advice.
