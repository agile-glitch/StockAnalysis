# Stop-Loss Placement Methods and Position Sizing for Retail US Stock Traders

Research notes, compiled 2026-11-21. Scope: US equities, retail account (~$10k). Every claim has an inline source. Numbers I computed myself (Monte Carlo and arithmetic) are labelled **[own computation]** and can be reproduced with the script described in the Q4 section.

**Access limits during research:** the sandbox's network blocked www.investor.gov, www.sec.gov and www.cxoadvisory.com, so I could not fetch the SEC/FINRA bulletins, the SEC-CFTC flash-crash report or CXO Advisory's pages directly. Facts about them come from search-result excerpts of those pages and from secondary sources, and are marked as such. Book texts (O'Neil, Faith, Tharp, Vince, LeBeau) were not retrieved, so book-based rules are cited through secondary summaries.

---

## Q1. Stop methods and their typical parameters

### Takeaway
The common stop methods all have standard parameters: O'Neil's 7-8% below cost, Chandelier at the 22-day high minus 3×ATR(22), Turtle at 2N (N = 20-day ATR) with 20/55-day breakout entries and 10/20-day exits, trailing stops of 10-20%, and a 200-day or 10-month moving-average trend filter. Almost all of these come from practitioners. Only fixed and trailing percentage stops, and moving-average timing rules, have been tested with academic rigor.

### Cited Findings
**Fixed percentage stop (O'Neil / IBD CAN SLIM, 7-8%)**
- O'Neil (2002 Motley Fool interview): "any stock that I buy that declines 7% or 8% below my actual purchase price, I will always without exception, sell to cut short my loss." — [Motley Fool interview](https://www.fool.com/specials/2002/06/20/foolcom-tmf-interview-bill-oneil-special.aspx)
- IBD pairs the rule with a profit target: "Take your profits at 20% to 25% and cut your losses at 7% to 8%." In practice IBD treats it as a 7% trigger, and some IBD pieces suggest cutting at 3-5% in weak markets. — [IBD content via inkl](https://inkl.com/news/when-to-sell-stocks); [IBD via inkl](https://inkl.com/news/when-to-sell-a-stock-cutting-losses-short-is-the-first-rule)
- The 7-8% is measured from the purchase price, not from the peak. AAII: "The 7% cutting losses rule does not apply" to a pullback from a high after a gain. — [AAII, Sell Rules](https://www.aaii.com/journal/article/sell-rules-to-build-your-stock-investing-performance)
- Other schools (e.g., Mark Minervini) size the stop from account risk rather than using a fixed percentage. — [Chartmill](https://www.chartmill.com/documentation/trading-and-investing/methodologies/527-William-ONeils-7-8-Sell-Rule-Explained)
- **Evidence status: practitioner lore.** I found no published independent backtest of the 7-8% rule on its own (see Gaps).

**ATR / volatility stop and the Chandelier exit (LeBeau)**
- Chandelier exit (long) = 22-day high − 3 × ATR(22). Short = 22-day low + 3 × ATR(22). 22 is roughly one trading month. — [StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit)
- Created by Chuck LeBeau (System Traders Club bulletins, late 1990s) and popularized by Alexander Elder's *Come Into My Trading Room* (2002). LeBeau's original version hung the stop from the highest high or highest close *since entry*; the fixed 22-bar lookback is a later charting adaptation. — [LuxAlgo](https://www.luxalgo.com/library/concept/chandelier-stop.md)
- The default multiplier is 3. A higher multiplier widens the stop. — [TradingView help](https://ru.tradingview.com/support/solutions/43000773013); [Barchart](https://www.barchart.com/education/technical-indicators/chandelier-exit)
- **Evidence status:** the 2-3×ATR convention comes from practitioners. I found no peer-reviewed test of the Chandelier exit on US stocks.

**Turtle Traders (Dennis/Eckhardt, documented by Curtis Faith, *Way of the Turtle*, 2007)**
- N = 20-day ATR. Initial stop = 2N from entry. An alternative "whipsaw" variant uses a ½N stop. — [IG](https://www.ig.com/en/trading-opportunities/turtle-trading--what-is-it-and-what-are-the-rules--180904); [TrendSpider](https://trendspider.com/learning-center/richard-dennis-turtle-trading-strategy/)
- Entries: System 1 enters on a 20-day breakout and System 2 on a 55-day breakout. Exits: System 1 on the opposite 10-day extreme, System 2 on the opposite 20-day extreme. — [TakeProfit](https://takeprofitapp.com/en/learn/turtle-trading-system); [Stockopedia](https://www.stockopedia.com/content/turtle-trading-rules-trend-following-investing-based-on-20-55-day-highs-58024)
- Sizing: one unit risks about 1% of equity, scaled by N. Add a unit every ½N in profit, up to 4 units per market. — [IG](https://www.ig.com/en/trading-opportunities/turtle-trading--what-is-it-and-what-are-the-rules--180904)
- Sources disagree on System 1's "skip the next breakout if the last one was a winner" filter: some include it and others say every breakout is taken. — [TakeProfit](https://takeprofitapp.com/en/learn/turtle-trading-system) vs. other retail guides in the same search. (Several sources are retail education pages or TradingView scripts, not primary.)
- **Context caveat:** the Turtle rules were designed for diversified *futures* portfolios, not single US stocks.

**Trailing stops (percentage)**
- The academic study (Dai et al.) tested trailing thresholds of 1%, 5%, 10% and 20% on US stocks. — [AUT ACFR summary](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)
- A practitioner site (Quant-Investing) recommends 15% or 20% trailing stops. Its test method is not described in detail and the site sells a monitoring product, so treat it as weak evidence. — [Quant-Investing](https://www.quant-investing.com/blog/best-trailing-stop-loss-settings-to-maximize-your-returns/)

**Moving-average stops / trend filters (200-day, 10-month)**
- The 10-month rule holds the S&P 500 for the next month if the index is above its 10-month total-return moving average at the monthly close. It is "consistent with the more ubiquitous 200-day moving average, except that price relative to the average is observed only at the end of the month." — [AAII](https://www.aaii.com/journal/article/missing-the-markets-worst-and-best-months)
- Faber's "Where the Black Swans Hide & the 10 Best Days Myth" (2011) defines a "declining" market as below the 200-day SMA. — [Hedge Fund Alpha summary](https://hedgefundalpha.com/?p=375814); [beSpacific](https://www.bespacific.com/?p=28027)
- Alpha Architect tested trailing stops of 3-15% after a 200-day MA breakout on the S&P 500 and concluded "the simple TF [trend-following] rule itself is the preferred stop-loss technique." — [Alpha Architect](https://alphaarchitect.com/trend-following-the-sp-500-some-practical-advice/)

**Support/structure stops, time stops, Parabolic SAR**
- I found no sourced parameters or tests for these in this research pass (see Gaps).

### Inferences
- The volatility-based methods (Chandelier, Turtle 2N, 2-3×ATR) use similar distances. For a stock with ATR ≈ 2% of price, a 2-3×ATR stop sits about 4-6% below the reference price, which is close to O'Neil's 7-8% for average-volatility stocks. For high-volatility stocks (ATR 4-5%), the ATR stop sits 8-15% away, so a fixed 7% stop would sit inside normal daily noise.
- O'Neil's rule assumes buying at a breakout ("pivot") point. Applied to arbitrary entries, the 7-8% figure has no special basis.

### Gaps
- No independent backtest of O'Neil's 7-8% rule, or of IBD's 20-25% take-profit, was found. IBD's own claims were not retrieved.
- No rigorous public test of the Chandelier exit, Parabolic SAR (Wilder's default 0.02 step / 0.20 max was not sourced here), support-based stops or time stops on US stocks was found.
- No source was found for typical time-stop parameters (e.g., "exit if no progress in N days"). IBD's "8-week hold rule" was referenced in search results ([inkl](https://inkl.com/news/how-to-invest-8-week-hold-rule-helps-latch-on-to-big-winners)) but not fetched. It is a hold rule for fast winners, not a time stop.
- Curtis Faith's book text was not retrieved, so Turtle details depend on secondary sources that partly disagree.

---

## Q2. What published backtests show (fixed vs. trailing vs. ATR vs. none)

### Takeaway
The best evidence says stops mainly **reduce volatility, drawdowns and left-tail losses**. They raise returns only when prices trend or show momentum. Under a random walk, stops lower expected return. Tight stops (under 10%) lose their benefit after transaction costs. Looser trailing stops (10-20%) and trend filters keep a downside-risk benefit.

### Cited Findings
**Theory and broad empirical evidence: Kaminski & Lo, "When Do Stop-Loss Rules Stop Losses?" *Journal of Financial Markets* 18 (2014): 234-254**
- If returns follow a random walk, simple stop-loss rules always lower expected return, because they move the portfolio out of the higher-yielding asset. — [MIT DSpace](https://dspace.mit.edu/handle/1721.1/114876); [RePEc](https://econpapers.repec.org/RePEc:eee:finmar:v:18:y:2014:i:c:p:234-254)
- If returns show momentum or regime-switching, stop-loss rules can add value. The authors derive the explicit conditions. — [MIT DSpace](https://dspace.mit.edu/handle/1721.1/114876)
- Using monthly US equity data from 1950-2004 and switching to bonds when stopped out, some rules added about 50-100 bp per month during stop-out periods, which the authors attribute to conditional momentum after equity losses. — [IDEAS/RePEc](https://ideas.repec.org/p/hhs/sifrwp/0063.html) (summarized from abstract; full text not fetched)
- **Quality:** peer-reviewed. Note the setup: it is an asset-allocation stop (equities to bonds), not a single-stock trading stop.

**Trailing stops on individual US stocks: Dai, Marshall, Nguyen & Visaltanachoti, "Risk reduction using trailing stop-loss rules," *International Review of Finance* 21(4) 2021: 1334-1352 (online Aug 2020)**
- Sample: daily returns of 25,997 US common stocks, including delisted ones, from July 1926 to Dec 2016. Thresholds tested: 1%, 5%, 10%, 20%. — [AUT ACFR](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk); [RePEc](https://econpapers.repec.org/RePEc:bla:irvfin:v:21:y:2021:i:4:p:1334-1352); CXO summary via search excerpt (cxoadvisory.com was blocked from fetching)
- Result: lower mean returns than the buy-and-hold / mean-variance benchmark, but lower total and downside risk, "especially during declining market states." — [AUT ACFR](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)
- **After transaction costs, the downside-risk advantage disappears for thresholds tighter than 10%. Thresholds of 10-20% still show lower downside risk.** — [AUT ACFR](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)
- Per the CXO summary (search excerpt), gross Sharpe ratios were mostly *lower* than buy-and-hold, turnover was higher, and the rules worked better in recent subperiods than early ones. — [CXO Advisory](https://www.cxoadvisory.com/technical-trading/trailing-stop-loss-effectiveness-for-stocks) (excerpt only)
- The same authors found that stop-loss rules in *international equity market allocation* produce "superior mean and risk-adjusted returns." — [IDEAS, Applied Economics 2022](https://ideas.repec.org/a/taf/applec/v54y2022i14p1584-1597.html) (this applies to country indices, not single stocks)

**Stop-loss on momentum portfolios: Han, Zhou & Zhu, "Taming Momentum Crashes: A Simple Stop-Loss Strategy"**
- 10% stop, 1926-2013: the worst monthly momentum loss falls from −49.79% to −11.36% for equal-weighted portfolios and from −64.97% to −23.28% for value-weighted ones. — [Alpha Architect review](https://alphaarchitect.com/2016/08/taming-the-momentum-roller-coaster-fact-or-fiction/)
- Average monthly return rises from 1.01% to 1.73%, per a secondary summary. — [Seeking Alpha](https://seekingalpha.com/article/3257295-momentum-and-stop-losses)
- Alpha Architect's replication on the winners portfolio: 5% stop 1.53%/mo, 10% stop 1.27%, 15% stop 1.20%, versus 1.24% for plain momentum. It warns that stops "will cause more trading, thus adding expense and reducing performance," and that daily monitoring of every position is "difficult for the average investor." — [Alpha Architect](https://alphaarchitect.com/2016/08/taming-the-momentum-roller-coaster-fact-or-fiction/)
- Conflict: Seeking Alpha's summary reports a large return gain, while Alpha Architect's replication shows little or no gain at 10% on the winners leg. Both agree drawdowns fall sharply.

**Trend filters (moving average) vs. stops on the S&P 500**
- Alpha Architect: a 200-day MA trend rule outperformed adding 3-15% trailing stops on top. The purchase-cost (fixed) stop had higher returns *and* higher volatility than the breakout and trailing versions. — [Alpha Architect](https://alphaarchitect.com/trend-following-the-sp-500-some-practical-advice/)
- Faber, "Where the Black Swans Hide" (2011): about 60-80% of both the best and worst days occurred when the market was already below its 200-day SMA, because volatility clusters. Across 15 international markets, 76% of worst days and 67% of best days fell in declining regimes. — [Hedge Fund Alpha](https://hedgefundalpha.com/?p=375814); [Proactive Advisor](https://proactiveadvisormagazine.com/?p=12840)
- Related academic work on extreme days: Estrada (2007), "Black Swans and Market Timing." — [Estrada PDF](https://blog.iese.edu/jestrada/files/2012/06/BlackSwans.pdf) (not fetched)

**Trend-following and alternative risk premia (practitioner)**
- With simple signals, stop losses "can decrease skewness and drawdowns for both alternative risk premia and trend-following strategies." The exit "may occur right before the rebound and thus lock in maximum losses." — [Advisor Perspectives, Oct 2025](https://www.advisorperspectives.com/commentaries/2025/10/23/stop-losses)

**Mean-reversion / short-term strategies**
- A *Journal of Investment Strategies* paper examines stops on short-term countertrend strategies and notes "a lack of empirical research regarding their effectiveness." — [Risk.net](https://www.risk.net/journal-of-investment-strategies/2293580/the-impact-of-stop-losses-on-short-term-countertrend-trading-strategies) (abstract only)
- Quantified Strategies argues that stop-losses often *hurt* backtested performance, especially in mean-reversion systems. Only a video/newsletter teaser was retrieved, with no numbers. — [Quantified Strategies Substack](https://quantifiedstrategies.substack.com/p/stop-doing-it-the-case-against-a-c2e)
- A practitioner who tested 87 stop variants found a fixed stop "cuts our losses, but really does nothing in relation to saving us from further declines." **Quality: low** (blog, unaudited). — [PaperToProfit](https://papertoprofit.substack.com/p/i-tested-87-different-stop-loss-strategies)

### Inferences
- The evidence agrees on direction. Stops are a **risk-reduction tool, not a return enhancer**, unless the underlying strategy is momentum or trend-following. For a mean-reversion (buy-the-dip) strategy, a tight stop works against the edge.
- For single US stocks, the Dai et al. results point to a **trailing stop of at least 10%** (tighter stops lose to costs and whipsaw). That is wider than O'Neil's 7-8% fixed stop.
- None of the major studies directly compares fixed vs. ATR vs. trailing vs. no stop on the same stock sample. The ATR-over-fixed preference rests on practitioner logic (normalizing for volatility), not on published head-to-head tests.

### Gaps
- No rigorous, published head-to-head test of ATR/Chandelier stops vs. fixed-% stops on US stocks was found.
- Faber's "Learning to Play Offense and Defense" and his specific trailing-stop studies were not located in this pass. His widely cited 10-month SMA results (*A Quantitative Approach to Tactical Asset Allocation*, SSRN 962461) were found only as a Scribd listing ([Scribd](https://www.scribd.com/document/559580322/SSRN-id962461)), so its return and drawdown numbers are not reported here.
- The CXO Advisory and Quantified Strategies pages could not be fetched (CXO host blocked; QS returned only a teaser), so their specific backtest numbers are missing.
- Lei & Li (2009) and Clare et al. stop-loss studies were not searched because of the tool-call budget.

---

## Q3. Order mechanics and execution risks

### Takeaway
A stop-market order becomes a market order when triggered, so it can fill far below the stop in a gap or a liquidity vacuum (May 6, 2010; Aug 24, 2015). A stop-limit order guarantees the price but not the fill. Stops cluster just below round numbers, which can feed price cascades. The realistic loss on a stopped trade is the gap-open price, not the stop price.

### Cited Findings
- SEC Investor Bulletin (Office of Investor Education and Advocacy): a stop-limit order becomes a limit order once triggered. It "can avoid the risk of an unexpected execution price, but the limit price may prevent the order from being executed," and stop-limit orders "may not be executed if there is significant price movement in a short period of time." Brokers may apply different trigger rules, so investors "should check with their brokerage firms." The bulletin has a later version that covers trailing stops. — [Investor.gov bulletin](https://www.investor.gov/additional-resources/news-alerts/alerts-bulletins/investor-bulletin-stop-stop-limit-trailing-stop); [SEC Fast Answers](https://www.sec.gov/fast-answers/answersstoplim) (content taken from search excerpts; host blocked from fetching); [Mondaq summary](https://www.mondaq.com/unitedstates/commoditiesderivativesstock-exchanges/613700/sec-educates-investors-on-stop-stop-limit-and-trailing-stop-orders)
- Once a stop is triggered, "the order becomes a market order and will be executed at the best available prevailing price—even if the price only exists for a few seconds or minutes." — [Seeking Alpha, Stop Order Drawbacks](https://seekingalpha.com/article/3469406-stop-order-drawbacks)

**May 6, 2010 Flash Crash**
- The SEC-CFTC joint staff report (Sept 30, 2010) has a dedicated section on "Stub Quotes." Trades executed at placeholder stub prices such as $0.01 and $100,000. — [SEC-CFTC report](https://SEC.GOV/files/marketevents-report.pdf) (TOC via excerpt); [academic study, core.ac.uk](https://core.ac.uk/download/213078723.pdf)
- The May 18, 2010 preliminary report flagged "the use of market orders, including automated stop-loss market orders designed to protect gains in recent market advances." — [SEC Historical Society](https://www.sechistorical.org/collection/papers/2010/2010_0518_PreliminaryPlunge.pdf)
- The trigger was a large automated sell order in E-mini S&P 500 futures. — [SEC-CFTC report](https://SEC.GOV/files/marketevents-report.pdf)
- (The often-cited Accenture trade at $0.01 was not confirmed in the retrieved sources.)

**August 24, 2015 ETF dislocations**
- Shortly after the open, dozens of equity ETFs traded far below their underlying index values. One analysis counted 317 ETPs tripping circuit breakers (LULD halts). — [SEC comment letter](https://www.sec.gov/comments/s7-11-15/s71115-38.pdf) (excerpt); [SEC DERA white paper](https://sec.gov/dera/staff-papers/white-papers/feb2016-dera-white-paper-etf-volatility)
- iShares Dow Jones U.S. ETF (IYY) traded about 20% below its prior close while the S&P 500 was down about 5%. — [AAII Editor's Note](https://www.aaii.com/journal/article/69-editors-note)
- "Retail investors' stop orders came in for significant blame, as quickly falling prices triggered many of these standing orders." A CFA Institute commentator argued the stop orders were symptoms, not the root cause. — [CFA Institute blog](https://blogs.cfainstitute.org/blog/2016/02/22/did-investor-stop-orders-or-liquidity-disincentives-cause-aug-15-flash-crash/)
- Since most brokers did not file clearly-erroneous trade reports within 30 minutes, many investors were stuck with those fills. — [Wall Street on Parade](https://wallstreetonparade.com/?p=4964) (secondary)
- Practitioner advice after the event: "Don't ever use stop-loss orders with ETFs, and don't enter market orders during periods of peak stress. Instead, use limit orders." — [ThinkAdvisor](https://thinkadvisor.com/2015/09/17/why-caution-is-needed-in-trading-etfs)

**Stop clustering**
- Osler (NY Fed Staff Reports 125 and 150, currency markets): executed stop-loss sell orders cluster just below round numbers, and stop-loss buy orders just above. Take-profit orders sit *at* round numbers. When rates reach stop-cluster levels, trends are "unusually rapid," with effects significant for hours but not days. Osler cautions that the statistics cannot prove causality and that stops are not the primary cause of large moves. — [NY Fed SR150](https://www.newyorkfed.org/research/staff_reports/sr150.html); [NY Fed SR125](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html)

### Inferences
- **Expected loss with gaps** [own computation, illustrative]: if a stock closes at $50 with a stop at $46 (−8%) and opens at $42 after bad earnings, a stop-market order fills near $42 (−16%). That is 2R instead of 1R. Position sizing should treat event risk (earnings, FDA decisions) as potentially larger than the stop distance, for example by cutting size or exiting before earnings.
- Avoid placing stops exactly at, or just below, obvious round numbers or prior lows (where Osler-type clusters form). An offset of a fraction of an ATR is the usual practitioner remedy. **This is lore; I found no tested evidence for equities.**
- Resting stop-market orders give certainty of execution but expose you to bad fills in the open auction and in flash events. Mental stops avoid showing orders but rely on discipline. Stop-limit orders risk no fill during a crash. No source quantified these trade-offs for retail equities.

### Gaps
- Broker GTC durations (e.g., Schwab/Fidelity GTC expiry, typically cited as 60-180 days) and whether stops trigger in extended hours were **not verified**, because broker pages were not fetched.
- No quantitative study of average slippage on retail stop-market orders in US stocks was found.
- I did not retrieve the FINRA stop-order guidance or the 2010-2012 market reforms (LULD, removal of stub quotes) in detail.

---

## Q4. Position sizing

### Takeaway
The standard retail rule is fixed-fractional risk of 0.5-2% of equity per trade, with **shares = (account × risk%) / (entry − stop)**. Van Tharp's R-multiples express results in units of that initial risk. Full Kelly is too aggressive for real trading: betting twice Kelly drives growth to zero, and half Kelly keeps about 75% of the growth with half the volatility. Simulations show that drawdown risk explodes above roughly 2-3% risk per trade.

### Cited Findings
**Fixed-fractional and the share formula**
- Position size = (Account × f) / R, where R is the per-share risk from entry to stop and f is commonly 0.01 (1%). — [LuxAlgo R-multiple framework](https://www.luxalgo.com/library/concept/r-multiple-framework.md)
- Turtle units: about 1% of equity at risk per unit, scaled by ATR (e.g., N = $1.00 on a $100,000 account means a unit risks about $1,000). — [IG](https://www.ig.com/en/trading-opportunities/turtle-trading--what-is-it-and-what-are-the-rules--180904)
- Prop-firm practice: "typically 0.25-0.5% per trade max" when the firm liquidates at a 5% drawdown. — [risk-of-ruin search results, e.g., Tradeify](https://tradeify.co/education/risk-of-ruin) (secondary)

**Van Tharp R-multiples and expectancy**
- R = initial risk defined by the initial stop. A trade's R-multiple = P&L / R. Expectancy = the mean R-multiple. — [Scribd, Tharp "A Short Lesson on R and R-multiple"](https://www.scribd.com/document/396639530/A-Short-Lesson-on-R-and-R-multiple)
- Example: 0.84R expectancy at 1% risk per trade means about 0.84% expected gain per trade, but "the average however is not the total picture" (the distribution and streaks matter). — [Scribd, Expectancy](https://www.scribd.com/document/497478389/Expectancy)
- Critique: a forum critic calls averaging R-multiples "mathematical nonsense" without considering the distribution. — [NexusFi](https://nexusfi.com/showthread.php?p=57165) (low-quality source; included as a dissent)

**Kelly criterion and fractional Kelly**
- MacLean, Thorp & Ziemba, "Good and Bad Properties of the Kelly Criterion": fractional Kelly blends the Kelly bet with cash, and half Kelly is the standard worked example. — [Berkeley PDF](https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf)
- Fractional Kelly trades growth for security. Betting twice the Kelly wager reduces growth to the risk-free rate. — [MacLean, Thorp & Ziemba, eScholarship](https://escholarship.org/content/qt5mr5k8qj/qt5mr5k8qj.pdf)
- Busseti, Ryu & Boyd ("Risk-Constrained Kelly Gambling"): fractional Kelly is the best-known ad hoc way to limit drawdown risk at the cost of growth, and a drawdown-constrained optimization can beat it at equal drawdown risk. — [Stanford PDF](https://web.stanford.edu/~boyd/papers/pdf/kelly.pdf)
- [own computation from the standard continuous-time growth formula] Betting a fraction α of Kelly gives growth ≈ α(2−α) × the Kelly growth rate. Half Kelly therefore gives 75% of the growth with 50% of the volatility.
- [own computation] Binary-bet Kelly fraction f* = p − (1−p)/b, where b is the win/loss ratio:
  - 40% win rate, 2R winners: f* = 10%
  - 50% win, 1.5R: f* = 16.7%
  - 55% win, 1R: f* = 10%
  - 35% win, 3R: f* = 13.3%
  - These "risk per trade" figures are 5-15× the conventional 1% and are highly sensitive to estimation error in p and b. This is the main practical reason full Kelly is too aggressive.

**Risk of ruin / drawdown tables**
- Published risk-of-ruin tables use different formulas (gambler's-ruin ((1−E)/(1+E))^N vs. (q/(p·b))^(T/f)), and their outputs disagree. Example: about 1.73% vs. about 4.43% for a similar setup (50% win, 1.5 payoff, 5% risk, 50% ruin threshold). — [LuxAlgo risk of ruin](https://www.luxalgo.com/library/concept/risk-of-ruin.md); [FXStreet tables](https://www.fxstreet.com/education/the-risk-of-ruin-tables-you-should-know-201911041256); [arongroups table, no methodology](https://arongroups.co/forex-articles/risk-of-ruin-table/)
- **[own computation] Monte Carlo, 20,000 paths × 250 trades, fixed-fractional compounding: probability of a ≥50% peak-to-trough drawdown:**

| Win rate / payoff (edge E) | 0.5% | 1% | 2% | 3% | 5% | 10% risk |
|---|---|---|---|---|---|---|
| 35% / 2R (+0.05R) | 0% | 0% | 13.5% | 47.2% | 90.9% | 100% |
| 40% / 1.5R (0R) | 0% | 0% | 16.3% | 51.2% | 91.5% | 100% |
| 40% / 2R (+0.20R) | 0% | 0% | 0.8% | 9.7% | 58.9% | 99.7% |
| 50% / 1R (0R) | 0% | 0% | 6.7% | 33.0% | 79.0% | 99.8% |
| 50% / 1.5R (+0.25R) | 0% | 0% | 0% | 0.8% | 20.4% | 95.7% |
| 55% / 1R (+0.10R) | 0% | 0% | 0.2% | 3.8% | 34.5% | 96.5% |

- **[own computation] Probability of at least one losing streak of ≥k trades in 100 trades:**

| Win rate | ≥5 losses | ≥8 losses | ≥10 losses | Median longest streak |
|---|---|---|---|---|
| 35% | 99.5% | 68.9% | 36.7% | 9 |
| 40% | 97.6% | 48.8% | 20.5% | 7 |
| 50% | 80.9% | 17.0% | 4.3% | 6 |
| 60% | 45.5% | 3.5% | 0.5% | 4 |

- **[own computation] Drawdown from n consecutive losses, 1 − (1−r)^n:**
  - 1% risk: 4.9% (5 losses), 9.6% (10), 18.2% (20)
  - 2% risk: 9.6%, 18.3%, 33.2%
  - 5% risk: 22.6%, 40.1%, 64.2%
- A secondary source makes the same point: at 2% risk an 8-loss streak costs about 15%, while at 10% risk it costs more than 55%. — [risk-of-ruin search results, newsghana](https://www.newsghana.com.gh/why-traders-blow-up-winning-strategies-the-hidden-math-of-risk-of-ruin/)
- (Simulation script: `/tmp/claude-0/-home-user-StockAnalysis/1f2581d5-9c09-5188-92ff-104e91769cf8/scratchpad/ror.py`. Scratch location, may be cleared. Method: i.i.d. binary trades, win = +r·b, loss = −r, compounding, seed 42.)

**Volatility parity / ATR sizing**
- Turtle N-based sizing is the classic volatility-normalized method: unit size = 1% of equity / (N × dollars per point), so every position carries about the same daily dollar volatility. — [IG](https://www.ig.com/en/trading-opportunities/turtle-trading--what-is-it-and-what-are-the-rules--180904)

### Inferences
- The simulations support the conventional **0.5-1% per trade** for retail traders with an unproven edge. At 1% or less, a 50% drawdown essentially never occurred in 250 trades even with zero edge. At 3% or more, drawdowns become likely even with a positive edge. Note that the simulation assumes losses equal exactly 1R; gaps through stops (Q3) make real tails worse.
- A common practitioner cap is a maximum position size of about 20-25% of equity, so a tight stop does not produce an outsized position. **No tested source for a specific cap was found; treat as lore.** Arithmetic: 1% risk with a 2% stop distance implies a position of 50% of the account.

### Gaps
- Ralph Vince's optimal-f and Thorp's original papers were not fetched.
- No authoritative, methodology-documented risk-of-ruin table was found, which is why the tables above are my own simulations.
- No sourced evidence was found on volatility-parity sizing vs. equal-dollar sizing for single-stock retail portfolios.

---

## Q5. Profit-taking: fixed targets vs. trailing exits, and the case for letting winners run

### Takeaway
Trend and momentum returns depend on a few large outliers, and Faber's extreme-days work shows those outliers cluster in volatile regimes. That favors trailing exits over fixed targets for trend strategies. IBD nevertheless pairs its 7-8% stop with a 20-25% target, which is about a 3:1 reward:risk. Rigorous head-to-head evidence on fixed targets vs. trailing exits for stocks was not found.

### Cited Findings
- IBD: take profits at 20-25%, cut losses at 7-8%. — [IBD via inkl](https://inkl.com/news/when-to-sell-stocks)
- Turtles used trailing channel exits (10-day / 20-day opposite extreme) rather than fixed targets. — [TakeProfit](https://takeprofitapp.com/en/learn/turtle-trading-system)
- Best and worst days cluster together in high-volatility, below-200-day-SMA periods, so exiting to avoid the worst days also tends to miss some of the best. — [Hedge Fund Alpha, Faber summary](https://hedgefundalpha.com/?p=375814)
- Stops reduce skewness in trend-following and risk-premia strategies, and can "lock in maximum losses" right before a rebound. — [Advisor Perspectives](https://www.advisorperspectives.com/commentaries/2025/10/23/stop-losses)
- Osler: take-profit orders cluster *at* round numbers, while stop-losses sit just beyond them. — [NY Fed SR150](https://www.newyorkfed.org/research/staff_reports/sr150.html)

### Inferences
- [own computation] Breakeven win rate for a reward:risk of b is 1/(1+b): 50% at 1:1, 40% at 1.5:1, 33% at 2:1, 25% at 3:1. IBD's 20-25% target with a 7-8% stop needs only about a 25-27% win rate to break even before costs.
- Low win rates are normal for trend systems. Combined with the losing-streak table in Q4, a trader with a 35-40% win rate should expect 7-9 losses in a row within 100 trades.

### Gaps
- No primary-source statistic on trend-following return skew (e.g., "X% of profits come from Y% of trades") was retrieved.
- No published head-to-head test of fixed targets vs. trailing exits for US stocks was found.

---

## Q6. Practical rules for a ~$10k account

### Takeaway
With 1% risk ($100) and a 7-8% stop, a single position is about $1,250-1,430, or roughly 12-14% of the account. That allows about 7-8 concurrent positions. The dollar risk is small enough that spreads, gaps and slippage, rather than commissions, are the main frictions.

### Cited Findings
- The sizing formula (account × f / per-share risk) is as given in Q4. — [LuxAlgo](https://www.luxalgo.com/library/concept/r-multiple-framework.md)
- Tight stops (under 10% trailing) lose their downside-risk benefit after transaction costs. — [AUT ACFR, Dai et al.](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)
- Stop-loss overlays increase trading and require daily monitoring. — [Alpha Architect](https://alphaarchitect.com/2016/08/taming-the-momentum-roller-coaster-fact-or-fiction/)

### Inferences
**[own computation] Worked example: $10,000 account, 1% risk = $100.**
- 8% stop on a $50 stock: risk is $4/share, so 25 shares = $1,250 (12.5% of the account).
- 3×ATR stop with ATR = $1.50: risk is $4.50/share, so 22 shares = $1,100.
- 3% stop on a $50 stock: risk is $1.50/share, so 66 shares = $3,300 (33% of the account). This is where a position cap matters.
- Gap example: the 25-share position gaps from a $46 stop to $42, a loss of $200 (2R) instead of $100.

**Other practical rules**
- At 0.5% risk ($50), positions of a few hundred dollars still work with fractional shares, but the spread becomes a meaningful share of R. For example, a $0.05 spread on a $1.50 per-share risk is 3% of R per round trip. **Unsourced, illustrative.**
- Prefer liquid names and limit-type orders around the open, and avoid resting stop-market orders on thinly traded ETFs (lesson of Aug 24, 2015). — [ThinkAdvisor](https://thinkadvisor.com/2015/09/17/why-caution-is-needed-in-trading-etfs)

### Gaps
- Not verified: broker specifics on fractional shares (which brokers allow stop orders on fractional positions, which is often restricted), zero-commission policies, PFOF/spread costs, PDT rule implications (the $25k pattern-day-trader threshold) and GTC expiry. Schwab, Fidelity and FINRA pages were not fetched in this pass.
- No sourced data on typical bid-ask spreads for large- vs. small-cap US stocks.
