# Portfolio-Level Techniques That Improve Investor Outcomes (Evidence and Numbers)

Scope note: US investor context, researched 2026-11-21. Primary PDFs on aqr.com and fairmodel.econ.yale.edu could not be fetched (network blocked in this session), so several figures come from search-result extracts of primary sources or from reputable secondary summaries (Alpha Architect, Quantpedia, CFA Institute). Each such case is flagged. "Backtest" vs "live" is marked throughout.

## 1. Time-series momentum / trend following

### Takeaway
Over a very long backtest (1880 onward), diversified trend following across futures markets earned positive returns in every decade, with near-zero correlation to stocks and bonds and good results in most large 60/40 drawdowns. Its main benefit is diversification and crisis protection, not beating equities on raw return. Live managed-futures results were weak through most of the 2010s, then had a record year in 2022.

### Cited Findings
**Hurst, Ooi & Pedersen, "A Century of Evidence on Trend-Following Investing" (AQR; JPM Fall 2017). BACKTEST**
- Universe and period: 67 markets (29 commodities, 11 equity indices, 15 bond markets, 12 currency pairs), January 1880 to December 2016. The authors say it was "consistently profitable" throughout. — [AQR](https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing)
- 2014 version (Jan 1880 to Dec 2013): 14.9% gross annualized return, 11.2% net of an assumed 2-and-20 fee, 9.7% volatility, net Sharpe 0.77, roughly zero correlation to stocks and bonds. — [TrendFollowing.com copy of AQR white paper](https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf); [Alpha Architect summary](https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/)
- 2017 version: net Sharpe about 0.76 after estimated trading costs and a 2% management / 20% performance fee with a high-water mark. — [Alpha Architect (Swedroe)](https://alphaarchitect.com/?p=29854)
- Positive net returns in every decade. Secondary summaries disagree on the worst decade: 5.7% (decade starting 1910, earlier version) vs 4.1% (decade starting 1919, 2017 version). — [Alpha Architect](https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/); [ETF.com (Swedroe)](https://www.etf.com/sections/index-investor-corner/swedroe-why-financial-trends-persist)
- Crisis performance: positive in 9 of the 10 largest 60/40 drawdowns in the 2012 draft (1903–2012), and 8 of 10 in the 1880–2016 published version. — [AQR](https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing); [Alpha Architect](https://alphaarchitect.com/diversification-benefits-time-series-momentum/)
- The "trend smile": returns are strongest in extreme up and down equity markets. The strategy still had multi-year drawdowns of up to about 25%. — [Alpha Architect](https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/)
- Caveats: AQR runs trend-following funds (commercial interest). Trading costs before modern futures markets are estimates. The 2/20 fee assumption is dated, since cheaper vehicles now exist. — [Alpha Architect](https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/); [Alpha Architect](https://alphaarchitect.com/trend-following-is-everywhere/)

**Live managed-futures / CTA results. LIVE**
- 2022: the SG Trend Index (the 10 largest trend-following CTAs) returned about +27.3%, its best year since launch in January 2000. Its previous double-digit year was 2014 (+15.66%). The SG CTA Index returned about +20.1% in 2022, also its best since 2000. In the same year a US 60/40 portfolio returned about −16%. — [The Full FX](https://thefullfx.com/year-end-drop-fails-to-dampen-stellar-2022-for-trend-followers/); [Hedgeweek](https://www.hedgeweek.com/flat-december-sees-ctas-complete-record-year-2022/); [Nasdaq](https://www.nasdaq.com/articles/managed-futures-as-a-strategy-massively-outperforms-in-2022)
- 2010s: commentators describe the decade as "lackluster" for trend following. AQR argues the macro conditions that held it back were exceptional compared with history. — [AQR, "Trend Following: Why Now? A Macro Perspective"](https://www.aqr.com/insights/research/white-papers/trend-following-why-now-a-macro-perspective)

**Faber (2007), 10-month simple moving average (SMA) timing. BACKTEST, largely in-sample**
- Claims "equity-like returns with bond-like volatility and drawdown" from holding an asset only when it is above its 10-month SMA, otherwise holding cash. Reviewers note the test is essentially in-sample. — [Scribd copy of SSRN 962461](https://www.scribd.com/doc/116881446/SSRN-id962461); [ThinkAdvisor](https://thinkadvisor.com/2015/09/02/most-downloaded-ssrn-paper-ever-says-you-should-be/?amp=1)
- Independent replication, 1973–2011: maximum drawdown −46.0% for buy-and-hold vs −9.56% for the timing model. — [Juniata College replication](https://admissions.juniata.edu/offices/juniata-voices/media/andrew-and-castro.pdf)
- Faber's 2013 update found drawdowns got larger once 2008–2012 data was included. Daily data or longer lookbacks also increase drawdowns. A 2012 critique of an SMA overlay on the Permanent Portfolio found little added value; its worst drawdown (March 1980) came when gold and stocks fell together from far above their SMAs. — [Scribd copy](https://www.scribd.com/document/331287034/SSRN-id962461-pdf); [Investing.com (Butler|Philbrick)](https://m.investing.com/analysis/permanent-portfolio-shakedown,-part-ii-134270?ampMode=1)

### Inferences
- Trend following mainly improves risk-adjusted returns and reduces tail losses (drawdown control, crisis alpha). It does not reliably beat equity buy-and-hold on raw return. In the Hurst data, net returns (about 11%) at about 10% volatility give a Sharpe ratio comparable to or higher than equities, but the source of value is low correlation, which is a different thing from higher returns.
- Single-index SMA timing (Faber style) cuts drawdowns in backtests, but it lags in V-shaped recoveries, causes whipsaws, and in a taxable account turns gains into short-term gains. Its advantage narrows out of sample.
- Live CTA results have long flat or losing stretches (most of the 2010s). Investors who give up during those stretches miss the payoff in years like 2022.

### Gaps
- Moskowitz, Ooi & Pedersen (2012, JFE) details were not verified this session. From prior knowledge (unverified): 58 liquid futures, roughly 1985–2009, 12-month lookback, diversified strategy Sharpe above 1 gross. The report writer should verify before citing.
- I did not retrieve SG Trend Index annual returns year by year for 2010–2019 or 2023–2026.
- I did not find a solid source on trend following applied to single stocks vs indexes. Single stocks have higher idiosyncratic noise, gap risk, and whipsaw.
- Faber's 2018 JPM "10 years later" revisit was not retrieved.

## 2. Volatility targeting / volatility-managed portfolios

### Takeaway
Scaling equity exposure inversely to recent volatility reliably reduces tail risk and the volatility of volatility. Gains in Sharpe ratio appear mostly for equities and other risk assets. The large in-sample alphas from Moreira & Muir (2017) largely disappear in implementable out-of-sample tests.

### Cited Findings
- **Moreira & Muir (2017, Journal of Finance). BACKTEST, in-sample.** The volatility-managed market portfolio produces an annualized alpha of 4.9%, an appraisal ratio of 0.33, and about a 25% increase in Sharpe ratio over buy-and-hold. — [NBER w22208](https://www.nber.org/papers/w22208)
- **Cederburg, O'Doherty, Wang & Yan (2020, JFE 138(1):95–117). Out-of-sample critique.** Spanning-regression alphas are positive in-sample, but the combination strategies are not implementable in real time. Realistic out-of-sample versions "generally earn lower certainty equivalent returns and Sharpe ratios than do simple unmanaged investments." Across 103 equity strategies, the managed version wins in 53 and the unmanaged in 50, roughly a coin flip. The authors attribute this to unstable regression parameters. — [Lehigh PDF](https://www.lehigh.edu/~xuy219/research/COWY.pdf); [RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:1:p:95-117); [Alpha Architect](https://alphaarchitect.com/does-portfolio-timing-based-on-volatility-signals-outperform-buy-and-hold/)
- Further debate: Barroso & Detzel (2021) find no positive alphas after transaction costs. DeMiguel, Martín-Utrera & Uppal (2024, JF) find a conditional multifactor volatility-managed portfolio that outperforms out of sample and net of costs. — [DeMiguel et al. 2024 (LBS)](https://lbsresearch.london.edu/id/eprint/3716/1/The%20Journal%20of%20Finance%20-%202024%20-%20DeMIGUEL%20-%20A%20Multifactor%20Perspective%20on%20Volatility%E2%80%90Managed%20Portfolios.pdf)
- **Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), "The Impact of Volatility Targeting," JPM 45(1):14–33. BACKTEST.** Tests more than 60 assets with daily data from as early as 1926, using a 10% volatility target. For US equities, Sharpe rises from 0.40 (unscaled) to 0.48–0.51 (scaled). For bonds, currencies and commodities the Sharpe effect is negligible. Volatility targeting consistently reduces extreme returns and maximum drawdowns for balanced and risk-parity portfolios. Volatility of volatility falls from 4.6% to 1.8%. Mechanism: the leverage effect (volatility rises when prices fall) gives scaling a built-in momentum tilt. — [Duke PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf); [Man Institute](https://www.man.com/maninstitute/the-impact-of-volatility-targeting); [Quantpedia](https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies)

### Inferences
- For a retail equity-heavy portfolio, the strongest case for volatility targeting is smoother risk and smaller tail losses. Return alpha is weakly supported once real-time and cost constraints apply.
- Volatility targeting often needs leverage in calm periods to reach its target. Without leverage, it reduces to cutting exposure when volatility is high, which lowers average returns along with risk.

### Gaps
- Liu, Tang & Zhou (2019), "Volatility-managed portfolio: Does it really work?" (JPM), was not retrieved. From prior knowledge (unverified): it argues that Moreira-Muir's results depend on look-ahead bias in the scaling constant and that the benefit vanishes in real-time implementation and is concentrated around 2008.
- I found no live track record of a retail volatility-targeted equity fund.

## 3. Rebalancing

### Takeaway
Vanguard's research finds no single optimal rebalancing frequency or threshold. Monthly, quarterly and annual rebalancing produce similar risk-adjusted returns, while costs rise with frequency. The main purpose of rebalancing is risk control (keeping the target allocation), not a return "bonus".

### Cited Findings
- Vanguard (2010, updated 2015), "Best Practices for Portfolio Rebalancing": "there is no optimal frequency or threshold." Risk-adjusted returns are not meaningfully different across monthly, quarterly or annual rebalancing, but the number of rebalancing events and costs rise sharply with frequency. The "annual plus 5% threshold" for a 60/40 portfolio appears as an illustrative assumption, not a recommendation. — [Vanguard 2010 PDF (Indexa mirror)](https://indexacapital.com/bundles/unaiadvisor/docs/papers/2010-Vanguard-Best-practices-for-portfolio-rebalancing.pdf?v=241)
- Vanguard target-date fund research (December 2024 and January 2025): Vanguard moved its target-date funds to threshold rebalancing with a 200 bp trigger and a 175 bp destination, monitored daily. — [Vanguard, "The Rebalancing Edge"](https://corporate.vanguard.com/content/dam/corp/research/pdf/the_rebalancing_edge_optimizing_target_date_fund_rebalancing_through_threshold_based_strategies.pdf); [Vanguard Workplace](https://workplace.vanguard.com/insights-and-research/perspective/vanguards-approach-to-target-date-fund-rebalancing.html)
- For self-directed investors, Vanguard notes threshold rebalancing requires regular monitoring and suggests quarterly or annual calendar reviews as a practical alternative. — [Vanguard investor guide](https://investor.vanguard.com/investor-resources-education/portfolio-management/rebalancing-your-portfolio)
- Vanguard's "Rational Rebalancing" paper offers an analytical method for multi-asset portfolios that trades off tracking error against transaction costs. — [Vanguard PDF](https://corporate.vanguard.com/content/dam/corp/research/pdf/rational_rebalancing_analytical_approach_to_multiasset_portfolio_rebalancing.pdf)

### Inferences
- For a roughly $10k investor, the cheapest approach is to rebalance with new contributions (buy the underweight asset) and run an annual check, selling only when drift exceeds about 5 percentage points. In a taxable account this avoids realizing gains.
- Any "rebalancing bonus" (from volatility harvesting among imperfectly correlated assets) is small and inconsistent. In strongly trending markets, rebalancing out of the rising asset lowers return compared with letting it drift.

### Gaps
- I did not retrieve a quantified rebalancing-bonus estimate (for example, basis points per year from academic work).

## 4. Dollar-cost averaging (DCA) vs lump sum

### Takeaway
Investing a lump sum immediately beats spreading it out about two-thirds of the time, because markets rise more often than they fall. DCA does better only in the worst downside scenarios. Its main value is behavioral (lower regret) and it beats staying in cash.

### Cited Findings
- Vanguard (February 2023), "Cost averaging: Invest now or temporarily hold your cash?": 1976–2022, MSCI World and Bloomberg US Aggregate indices, wealth compared after one year. Lump sum beat a three-month cost-averaging plan about 68% of the time. Cost averaging beat staying in cash 69% of the time. For 100% equity portfolios, lump sum produced about 2.2% more wealth on average. Lump sum has larger drawdowns in the worst environments, where cost averaging wins. — [Vanguard 2023 PDF](https://corporate.vanguard.com/content/dam/corp/research/pdf/cost_averaging_invest_now_or_temporarily_hold_your_cash.pdf); [Vanguard UK](https://vanguard.co.uk/professional/vanguard-365/financial-planning/financial-well-being/cost-averaging)
- Vanguard UK's summary: lump sum won between 61.6% and 73.7% of rolling one-year periods, depending on market or allocation. — [Vanguard UK](https://vanguard.co.uk/professional/vanguard-365/financial-planning/financial-well-being/cost-averaging)
- Earlier Vanguard study (2012), covering 1926–2011 in the US, UK and Australia: lump sum outperformed about 67% of the time (US rolling 10-year horizons in the 60/40 example). — [BenefitsPro](https://benefitspro.com/2012/10/31/lump-sum-investing-vs-dollar-cost-averaging)
- Common misreading: "68%" means lump sum won in 68% of periods. It does not mean returns were 68% higher. — [SmartAsset](https://smartasset.com/investing/lump-sum-investing-research)

### Inferences
- Investing from each paycheck is not "DCA" in the lump-sum sense. It is simply investing money when it arrives, which is optimal. The lump-sum vs DCA question only applies to a windfall already in hand.
- For a nervous investor with $10k, a short schedule (3–6 months) costs little in expectation and can prevent the much larger cost of panic selling after a bad first month.

### Gaps
- None material.

## 5. Tax-loss harvesting (TLH)

### Takeaway
Long-run backtests put TLH alpha at about 0.8–1.1% per year before costs for a high-bracket investor, with most of the benefit in early years and in volatile markets. The benefit is a tax deferral that is most valuable at high marginal rates. It is limited by the 61-day wash-sale window, which also applies to IRA purchases.

### Cited Findings
- Chaudhuri, Burnham & Lo (2020), "An Empirical Evaluation of Tax-Loss-Harvesting Alpha," Financial Analysts Journal 76(3):99–108. BACKTEST using CRSP data on the 500 largest stocks, 1926–2018, with 15% long-term and 35% short-term rates. Tax alpha is 1.08% per year before transaction costs, 0.82% under the wash-sale constraint, and about 0.95% (13 bp lower) including transaction costs in the CFA summary. Alpha is higher in volatile markets and positive in all four 23-year subperiods, but only about 0.51% in 1949–1972. The working paper gives 1.10% and 0.85%; the published figures are preferred. — [CFA Institute / FAJ](https://rpc.cfainstitute.org/research/financial-analysts-journal/2020/empirical-evaluation-tax-loss-harvesting-alpha); [MIT DSpace PDF](https://dspace.mit.edu/bitstream/handle/1721.1/135992/SSRN-id3351382.pdf)
- Wash-sale rule: a loss is disallowed if substantially identical securities are bought within 30 days before or after the sale (a 61-day window). — [SEC/Investor.gov](https://www.investor.gov/introduction-investing/investing-basics/glossary/wash-sales)
- Purchases in a traditional or Roth IRA trigger a wash sale. Under Rev. Rul. 2008-5 the disallowed loss is added to the IRA basis and is effectively lost permanently. Purchases by a spouse or a controlled corporation also count. Brokers are not required to report cross-account wash sales. — [Kitces](https://www.kitces.com/blog/irs-shuts-down-wash-sale-evasion-technique/); [Fidelity](https://www.fidelity.com/learning-center/personal-finance/wash-sales-rules-tax); [Schwab](https://www.schwab.com/learn/story/primer-on-wash-sales)
- "Substantially identical" is a facts-and-circumstances test. Different companies' stocks generally are not substantially identical. Funds tracking similar or the same index are a gray area. — [Kiplinger](https://www.kiplinger.com/taxes/604947/wash-sale-rule); [Schwab](https://www.schwab.com/learn/story/primer-on-wash-sales)

### Inferences
- For a roughly $10k investor, harvested losses offset gains and up to $3,000 per year of ordinary income (the $3,000 limit is standard US law, not re-verified here), so the dollar value is small: tens to low hundreds of dollars per year. TLH lowers basis, so it defers tax rather than eliminating it, unless the shares are held until death (step-up in basis) or donated.
- TLH is irrelevant in tax-advantaged accounts. An automatic IRA or 401(k) purchase of the same fund can accidentally trigger a wash sale.

### Gaps
- I did not retrieve current Wealthfront or Betterment published TLH estimates. Both are marketing claims and should be treated as such.
- The $3,000 ordinary-income offset was not verified against IRS Publication 550 (irs.gov was not fetched).

## 6. Costs, fees, trading and the behavior gap

### Takeaway
Costs and behavior compound into large drags. The most active retail traders lagged the market by about 6.5 percentage points per year. The average fund dollar earns about 1.2 points per year less than the funds it is invested in, because of bad timing. Most active large-cap funds trail the S&P 500.

### Cited Findings
- Barber & Odean (2000), "Trading Is Hazardous to Your Wealth," Journal of Finance 55(2):773–806: 66,465 discount-broker households, 1991–1996. The most active traders earned 11.4% per year vs 17.9% for the market, a gap of 6.5 points. Gross returns of frequent traders were similar to others, so the shortfall came from trading costs. — [Odean, Berkeley](https://faculty.haas.berkeley.edu/odean/papers/returns/returns.html); [RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:55:y:2000:i:2:p:773-806)
  - The 18.5% figure sometimes quoted alongside the 11.4% could not be verified in this session (it may be a gross return); 17.9% is the confirmed market return.
  - Counterpoint: Bonaparte & Cooper (NBER w16022, 2010) argue part of the gap may reflect selection effects. — [NBER](https://www.nber.org/papers/w16022.pdf)
- Morningstar "Mind the Gap" (US, 10 years ended 12/31/2025, the 2026 edition): the average dollar in US mutual funds and ETFs earned about 8.7% per year vs 9.9% total fund return, a gap of about 1.2 points per year (about 12% of total return). The gap comes from the timing of flows. The least-volatile funds had a gap of about −0.4% and the most volatile about −2.1%. ETFs had a wider gap than open-end funds, and crypto ETFs had among the worst timing. — [Morningstar Mind the Gap 2026 PDF](https://www.morningstar.com/content/cs-assets/v3/assets/blt9415ea4cc4157833/blt852a4301adc2f5db/6a7373d51f7b5ae2da78e1e8/US_Mind_the_Gap_2026.pdf); [Morningstar](https://www.morningstar.com/business/insights/research/mind-the-gap-2025); [Advisor Perspectives (Aug 2026)](https://www.advisorperspectives.com/commentaries/2026/08/21/what-advisors-can-learn-from-the-investor-return-gap?firm=vettafi)
  - Note: the prior edition (10 years to 2023) reported a gap of about 1.1% per year; that figure was not re-verified in this session.
- SPIVA US Year-End 2025: 79% of active large-cap US equity funds underperformed the S&P 500 in 2025, up from 65% in 2024 and the worst rate in the report's 25-year history. Mid-year 2026 showed improvement, but the exact percentage was not captured. — [S&P DJI SPIVA US Year-End 2025](https://www.spglobal.com/spdji/en/spiva/article/spiva-us-year-end-2025/); [InvestmentNews](https://investmentnews.com/equities/active-managers-stumble-again-in-2025-as-large-caps-dominate/265541)
- About 84% of large-cap funds underperformed over 10 years (SPIVA data cited in May 2025, likely through year-end 2024). — [Ritholtz](https://ritholtz.com/2025/05/the-data-on-active-large-cap-underperformance)

### Inferences
- Illustrative arithmetic (not from a source): $10,000 growing for 30 years at 7% gives about $76,100. At 6% (a 1% fee drag) it gives about $57,400, roughly 25% less. A 0.03–0.10% index ETF vs a 1% fund is a large and certain difference.
- The behavior gap (about 1.2%/yr) is similar in size to a high expense ratio. Holding calm, diversified, low-volatility funds and automating contributions narrows it.

### Gaps
- SPIVA 15-year large-cap underperformance for year-end 2025 was not captured. Historically it has been about 90%, but this is not verified.

## 7. Staying invested: the cost of missing the best days

### Takeaway
A few huge up-days drive a large share of long-run returns, and they tend to occur right next to the worst days during volatile periods. Exiting to avoid losses usually means also missing the rebounds.

### Cited Findings
- J.P. Morgan Asset Management (2025 Guide to Retirement data, 2005–2024): the S&P 500 returned about 10.4% annualized. Missing the 10 best days cut that to about 6.1%. $10,000 grew to about $71,750 fully invested vs about $32,871 if the 10 best days were missed. — [Nasdaq / Motley Fool](https://www.nasdaq.com/articles/market-timing-overrated-heres-why); [Webull](https://www.webull.com/news/15762946850827264)
  - Conflicting version of the same J.P. Morgan dataset: 10.6% fully invested, 6.4% missing the 10 best days, and 3.7% missing the 20 best (S&P 500 total return 2005–2024). The difference likely comes from the index series used. — [MarketScreener](https://www.marketscreener.com/news/why-you-can-t-afford-to-miss-the-market-s-biggest-rallies-ce7e50dbd98ef120)
- Clustering: 7 of the 10 best days occurred within two weeks of the 10 worst days over the past 20 years (J.P. Morgan). — [Nasdaq](https://www.nasdaq.com/articles/market-timing-overrated-heres-why); [Chase / J.P. Morgan](https://www.chase.com/personal/investments/learning-and-insights/article/four-reasons-investors-may-benefit-from-staying-invested)
- Wells Fargo Investment Institute makes a similar point about the perils of timing volatile markets. — [Wells Fargo](https://www.wellsfargo.com/investment-institute/sr-perils-time-volatile-markets)

### Inferences
- The "missing best days" statistic is one-sided: missing the worst days would raise returns by a similar amount. The honest lesson is that best and worst days cluster, so an investor cannot realistically dodge one set without the other. Trend rules (section 1) try to step aside during high-volatility regimes, accepting missed rebounds in exchange for avoiding extended bear markets. That is a different, rule-based bet from discretionary panic selling.

### Gaps
- I did not retrieve the J.P. Morgan 2026 Guide to Retirement update (2006–2025 window).

## 8. Asset allocation: stock/bond mixes and drawdowns; bond/cash sleeve for a ~$10k investor

### Takeaway
Adding bonds trades long-run return for much smaller losses. Since 1926, a 60/40 mix has returned about 1.5 points per year less than 100% stocks, while its worst calendar year was about −27% vs −43%. Bonds do not always hedge (2022), which is part of the case for diversifiers such as trend following.

### Cited Findings
- Vanguard portfolio allocation models (1926 onward; figures vary slightly by end date):
  - Average annual return: about 10.1–10.3% for 100% stocks, 8.7–8.8% for 60/40, 5.3% for 100% bonds.
  - Worst calendar year (1931): about −43.1% for 100% stocks, −26.6% for 60/40, about −18% for 40/60, about −8% for 100% bonds.
  — [Visual Capitalist (Vanguard data)](https://www.visualcapitalist.com/90-years-stock-and-bond-portfolio-performance/); [Vanguard Personal Investors (model assumptions)](https://personal.vanguard.com/us/content/MyPortfolio/analytics/pwIQAssumptionsContent.jsp); [Walnut](https://walnutinvest.com/stats/asset-allocation-statistics)
- 2022: about −16.1% for the US-only 60/40 portfolio and −15.7% for the global 60/40 (Vanguard), with stocks and bonds falling together. — [Vanguard, "Like the phoenix, the 60/40 will rise again"](https://advisors.vanguard.com/insights/article/likethephoenixthe6040portfoliowillriseagain)
- Vanguard has argued that the forward outlook for 60/40 improved after 2022 because of higher bond yields. — [Vanguard](https://corporate.vanguard.com/content/corporatesite/us/en/corp/articles/like-phoenix-6040-portfolio-will-rise-again.html)

### Inferences
- For a roughly $10k investor, the main roles of a bond or cash sleeve are: (1) emergency liquidity, so stocks never have to be sold in a crash; (2) behavioral ballast that lowers the chance of panic selling, which section 6 shows costs about 1–2%/yr; and (3) dry powder for rebalancing. With small dollar amounts, a single target-date fund or two to three low-cost ETFs (total US or world stock plus total bond or T-bills) provides diversification, automatic rebalancing and low fees.
- Intra-year drawdowns are much larger than calendar-year losses. For example, US stocks fell about 80%+ peak to trough in 1929–32 and about 50%+ in 2007–09. Peak-to-trough drawdowns by allocation were not verified in this session.

### Gaps
- Peak-to-trough (not calendar-year) drawdowns by stock/bond mix were not sourced.
- I did not source a specific retail guideline for sleeve size (for example, 3–6 months of expenses in cash).
