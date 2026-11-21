# Stock-Selection Techniques (Factors and Anomalies): Durable Out-of-Sample Evidence After Costs, as of 2026

Research notes compiled 2026-11-21. US focus, with global evidence where relevant.

**Method caveat for the report writer:** In this session, WebFetch could not reach spglobal.com, nber.org or econpapers.repec.org (the hosts are blocked by the session's network settings). As a result, most figures below come from search-engine snippets of primary sources rather than full-text reads. Where a figure comes only from a secondary blog, or only from my knowledge of a paper's abstract that I could not re-open here, the bullet says so. Treat those bullets as "verify before quoting exactly."

---

## 1. Cross-sectional momentum: premium, crashes and trading costs

### Takeaway
Momentum is one of the most robust anomalies in historical backtests, but it has two big problems. It suffers rare, severe crashes, mainly when its short "loser" leg rebounds after a bear market (March-May 2009 is the textbook case). It also has high turnover, so its net-of-cost premium depends heavily on how the portfolio is built and traded. Institutional evidence from real trades suggests it survives costs for large, patient implementers. The evidence is weaker for small or naive implementations.

### Cited Findings
- **2009 crash, Daniel & Moskowitz "Momentum Crashes".** From March to May 2009 the market rose 29% while the loser decile rose 156% (163% in another version of the paper). The crash came mainly from the short loser side rebounding. — [Daniel & Moskowitz, NBER WP w20439](https://www.nber.org/system/files/working_papers/w20439/w20439.pdf); [published version, kentdaniel.net](https://www.kentdaniel.net/papers/published/mom12.pdf)
- **Size of the 2009 drawdown varies by construction.** Secondary sources give a ~65% crash for the long-short portfolio in 2009, "roughly three-quarters" of its value lost in a few months, and a 55% drawdown (Verdad). I could not confirm the commonly quoted "-73%" figure. — [hmaquant substack](https://hmaquant.substack.com/p/momentum-the-anomaly-that-refuses); [Verdad, "A Momentum Crash Course"](https://verdadcap.com/archive/a-momentum-crash-course); [quantmemo summary](https://quantmemo.com/writing/paper-daniel-moskowitz-momentum-crashes)
- **Crash mitigation (backtest only).** Volatility scaling of momentum (Barroso & Santa-Clara; Daniel & Moskowitz's dynamic strategy) substantially reduces crash severity in backtests. This is in-sample or backtest evidence, not live results. — [hmaquant substack, secondary](https://hmaquant.substack.com/p/momentum-the-anomaly-that-refuses)
- **Trading costs from real institutional trades.** Frazzini, Israel & Moskowitz ("Trading Costs," 2018) used AQR's own live execution data. A secondary summary reports, for momentum over 1998-2011, about a 3.51% annual cost drag against a 4.34% net expected return. I could not open the original paper to confirm these exact numbers. The paper's general conclusion, as I understand it, is that actual institutional trading costs are much lower than earlier academic estimates. As a result, size, value and momentum survive costs at sizable fund capacity, while short-term reversal strategies do not. — [secondary blog figure via hmaquant](https://hmaquant.substack.com/p/momentum-the-anomaly-that-refuses). The original paper is SSRN abstract 3229719 (not fetched).
- **Novy-Marx & Velikov (2016), "A Taxonomy of Anomalies and Their Trading Costs" (RFS 29(1):104-147).** Most anomalies with monthly turnover below 50% still earn significant net spreads when designed to reduce costs, while few with higher turnover do. A buy/hold spread (keep a stock until it falls well out of the buy zone) is the single most effective simple cost-mitigation tool. Capacity is greatest for size, value and profitability, and the capacity hit from new capital rises with turnover. — [NBER w20721](https://www.nber.org/papers/w20721); [author PDF](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf); [IDEAS/RePEc](https://ideas.repec.org/a/oup/rfinst/v29y2016i1p104-147..html)
- **Live momentum ETF (MTUM, iShares MSCI USA Momentum Factor, 0.15% expense ratio).** Ten-year comparisons with IVV/S&P 500 conflict by source and date. One gives MTUM 16.51%/yr vs IVV 15.39%/yr. Another gives MTUM 14.70%/yr, with cumulative 10-year returns of 290.56% (MTUM) vs 285.84% (IVV). In calendar 2025, MTUM returned +22.15%. — [portfolioslab MTUM vs IVV](https://portfolioslab.com/tools/stock-comparison/MTUM/IVV); [financecharts MTUM](https://www.financecharts.com/etfs/MTUM/performance/total-return); [pearler MTUM vs IVV](https://pearler.com/explore/invest/us-shares/compare/MTUM-vs-IVV); [totalrealreturns](https://totalrealreturns.com/n/MTUM,QUAL,VLUE)

### Inferences
- Live momentum ETF evidence is roughly "match to slightly beat the S&P 500 over ~10 years" before taxes. That is far below long-short academic premiums. The long-only, cap-weighted, semi-annually rebalanced design gives up much of the paper premium but keeps costs low.
- For a retail investor, momentum is most defensible as one sleeve of a multi-factor portfolio. Its negative correlation with value helps (see section 6). Holding it alone exposes the investor to crash risk after market rebounds.
- Even the momentum survival result from the institutional cost study depends on careful execution. A retail investor trading individual stocks monthly with a naive 12-1 sort would likely face higher relative costs and tax drag.

### Gaps
- I could not verify Jegadeesh & Titman's (1993) original monthly premium figure, or Asness, Moskowitz & Pedersen's (2013) "Value and Momentum Everywhere" Sharpe ratios and value-momentum correlation, because the primary PDFs were not reachable.
- I could not confirm Frazzini-Israel-Moskowitz's exact break-even fund sizes or cost estimates from the primary paper.
- I found no reliable 2021-2025 annual momentum factor returns from the Kenneth French library in this session.

---

## 2. Value, quality/profitability, low volatility/BAB and the size debate

### Takeaway
Value had its worst and longest drawdown on record from 2007 to 2020: roughly a 55% peak-to-trough loss for HML. The cause was mostly growth stocks getting relatively more expensive rather than value companies' fundamentals deteriorating. Value rebounded strongly in early 2022 and in some vehicles in 2025, but the Fama-French HML factor has not regained its December 2006 peak. Quality/profitability and low-beta have strong published, out-of-sample and multi-country evidence. The size premium alone is weak, and it reappears mainly when "junk" (low-quality) small stocks are controlled for.

### Cited Findings
**Value**
- Value (Fama-French HML) has underperformed growth since 2007, with a 55% drawdown as of mid-2020. That was the largest drawdown since June 1963, or a cumulative loss of 54.8% (about -6.2% per year). — [Arnott, Harvey, Kalesnik & Linnainmaa, "Reports of Value's Death May Be Greatly Exaggerated," Financial Analysts Journal 2021](https://www.tandfonline.com/doi/full/10.1080/0015198X.2020.1842704); [Duke PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P149_Reports_of_values.pdf); [SSRN 3488748](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3488748)
- The same paper finds that the widening valuation spread between growth and value explains the entire drawdown "with room to spare". The spread moved from the 25th percentile in 2007 to the 100th percentile, the cheapest value relative to growth since 1963, by June 2020. — [Arnott et al. (Duke PDF)](https://people.duke.edu/~charvey/Research/Published_Papers/P149_Reports_of_values.pdf)
- AQR: losses in Q1 2020 made this the longest and deepest drawdown in HML's history. AQR also argues that interest rates do not explain value's underperformance well. — [AQR, "Value and Interest Rates" (2020)](https://images.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Value-and-Interest-Rates.pdf/1000); [JPM version PDF](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Value-and-Interest-Rates.pdf); [Alpha Architect summary](https://alphaarchitect.com/do-interest-rates-explain-values-underperformance/)
- Alpha Architect gives alternative drawdown measures: about 51% from January 2007, and 59% from January 2007 to March 2020 using a univariate sort. — [Alpha Architect](https://alphaarchitect.com/do-interest-rates-explain-values-underperformance/)
- **Recovery is partial.** Monthly HML was +12.75% in January 2022 but -6.01% in June 2022, and the series is still volatile through 2025. A factor-tracking site lists HML's all-time peak as December 2006, which implies HML had not regained that peak as of the page's (undated) snapshot. — [YCharts HML](https://ycharts.com/indicators/fama_french_monthly_5_factor_hml_benchmark_return); [finobservatory factors page](https://finobservatory.org/factors)
- Live value ETF: VLUE (iShares MSCI USA Value Factor, 0.15% expense ratio) returned +32.67% in calendar 2025. I found no reliable 10-year figure. — [totalrealreturns](https://totalrealreturns.com/n/MTUM,QUAL,VLUE)

**Quality / profitability**
- Asness, Frazzini & Pedersen, "Quality Minus Junk" (Review of Accounting Studies 2019). QMJ is long high-quality stocks and short low-quality stocks, with quality defined as profitability, growth and safety, built within both small and large stocks. Quality stocks are low-beta and tend to benefit from flight-to-quality episodes rather than crash. The test covers 24 countries over about six decades. — [Springer (RAS 2019)](https://link.springer.com/article/10.1007/s11142-018-9470-2); [working-paper PDF (Yale)](http://www.econ.yale.edu/~shiller/behfin/2013_04-10/asness-frazzini-pedersen.pdf)
- Novy-Marx (2013), gross profitability: firms with higher gross profits-to-assets earn higher average returns, and gross profit is presented as the cleanest profitability measure. I could not retrieve exact return magnitudes. — [summitward summary (secondary)](https://summitward.com/learn/quality-minus-junk)
- Profitability is among the highest-capacity, low-turnover anomalies after costs (see Novy-Marx & Velikov in section 1). — [NBER w20721](https://www.nber.org/papers/w20721)
- RMW (Fama-French profitability factor) hit an all-time peak in October 2023 according to finobservatory (snapshot undated). This means the factor was still making new highs in the 2020s, unlike HML. — [finobservatory](https://finobservatory.org/factors)
- Live quality ETF: QUAL (0.15% expense ratio) returned about 14.19%/yr over 10 years vs 15.32%/yr for IVV, so it trailed. Another source puts QUAL at 13.80% or 14.28%/yr over 10 years. QUAL returned +12.65% in 2025. — [portfolioslab QUAL vs IVV](https://portfolioslab.com/tools/stock-comparison/QUAL/IVV); [portfolioslab USMV vs QUAL](https://portfolioslab.com/tools/stock-comparison/USMV/QUAL); [totalrealreturns](https://totalrealreturns.com/n/MTUM,QUAL,VLUE)

**Low volatility / betting against beta**
- Frazzini & Pedersen, "Betting Against Beta" (JFE 2014): the BAB portfolio earned abnormal returns of 0.56% per month (t = 4.02) in the working-paper version. — [NBER WP w16601](https://www.nber.org/system/files/working_papers/w16601/w16601.pdf)
- Live min-vol ETF: USMV (iShares MSCI USA Min Vol Factor, 0.15% expense ratio) returned about 10.20%/yr over 10 years vs about 14.28%/yr for QUAL, well behind the S&P 500 (about 15%/yr) over the same window. — [portfolioslab USMV vs QUAL](https://portfolioslab.com/tools/stock-comparison/USMV/QUAL); [myetfjourney USMV vs QUAL](https://myetfjourney.com/compare/usmv-vs-qual)

**Size**
- Asness, Frazzini, Israel, Moskowitz & Pedersen, "Size Matters, if You Control Your Junk" (JFE 2018). Very low-quality ("junk") stocks are typically very small, distressed and illiquid, and they have low average returns. The paper argues the size premium is masked by this junk and reappears once quality is controlled for. I could not retrieve the exact numbers. — [Wharton Jacobs Levy PDF](https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2015/05/Size-Matters-if-You-Control-Your-Junk.pdf); [presentation](https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2015/05/Size-Matters-if-You-Control-Your-Junk-Presentation.pdf)
- Hou, Xue & Zhang (2020) show that many anomalies depend on microcaps and equal-weighting, a key reason raw size-related results weaken under value-weighting with NYSE breakpoints. — [NBER w23394](https://www.nber.org/papers/w23394)
- SMB monthly values through December 2025 are volatile and do not show a consistent premium in the snippet (December 2025: -1.02%). — [YCharts SMB](https://ycharts.com/indicators/fama_french_monthly_smb_benchmark_return)

### Inferences
- **Value:** the long-run premium is intact on 1963-2026 data, but the 2007-2020 episode shows that a retail investor must tolerate a decade or more of underperformance. Most of the loss was valuation re-rating, not deteriorating fundamentals, which supports (but does not prove) the view that the premium is still alive.
- **Quality/profitability:** this has the cleanest post-publication record of the major factors. It has low turnover, high capacity and new highs in the 2020s. However, the long-only ETF (QUAL) did not beat the cap-weighted S&P 500 over the last ~10 years, which was dominated by mega-cap growth.
- **Low volatility:** the evidence supports better risk-adjusted returns (higher Sharpe), not higher raw returns. In the 2015-2025 bull market, USMV badly lagged the S&P 500 on raw return.
- **Size:** on its own, size is the weakest of these premiums. It is defensible only in combination with quality or value screens, as Dimensional and AQR-style small-cap value products do.

### Gaps
- No verified annual HML/SMB/RMW/UMD returns for 2021-2025 from the Kenneth French library. The ycharts and finobservatory snippets are partial and finobservatory is undated.
- No verified Sharpe ratios for BAB or QMJ, and no gross-profitability spread magnitudes.
- I found no reliable data on Dimensional (DFA) fund performance vs indexes. Morningstar's work on DFA and on factor ETF success rates was not retrieved.
- Baker, Bradley & Wurgler (2011, "Benchmarks as Limits to Arbitrage") was not retrieved.
- I found no reliable VLUE 10-year return.

---

## 3. Event-driven and information signals: PEAD, insider buying, analyst revisions, short interest

### Takeaway
Post-earnings-announcement drift (PEAD), the classic "information anomaly," appears to have largely disappeared for large US stocks since the 2000s (Martineau 2022). Insider-trading evidence mainly shows insiders' trades containing information, and their effect on drift. Clean, recent, net-of-cost evidence for retail strategies based on insider buying, analyst revisions or short interest was not found in this session.

### Cited Findings
- **PEAD has vanished in large caps.** Martineau (2022) is summarized as finding that PEAD began disappearing from non-microcap stocks around 2001 and was essentially zero for large-cap stocks by 2006. — [secondary summary, truthsayer](https://www.truthsayer.com/insights/post-earnings-announcement-drift); [freeportlogbook](https://freeportlogbook.substack.com/p/post-earnings-announcement-drift). Primary source not fetched.
- **Contrary evidence (weak).** A Stockholm School of Economics student thesis reports that 60-day large-cap drift rose from 0.52% (2005-2020) to 1.99% after 2020. It is a thesis, not peer-reviewed. — [cited via quantseeker/truthsayer secondary](https://www.truthsayer.com/insights/post-earnings-announcement-drift)
- **Earnings-announcement reversals.** A working paper finds that earnings-specific short-term reversals fell from 0.73 percentage points (1996-2011) to an insignificant -0.06 (2012-2024). — [QuantSeeker weekly recap](https://quantseeker.com/p/weekly-research-recap-a18)
- **Insider trading and PEAD.** PEAD is significantly lower when the earnings announcement was preceded by insider trading, mainly trades against the coming news (buys before bad news or sells before good news). — [Dargenidou et al., Journal of Business Finance & Accounting 2018](https://onlinelibrary.wiley.com/doi/10.1111/jbfa.12305); [CLS Blue Sky summary](https://clsbluesky.law.columbia.edu/2018/06/05/post-earnings-announcement-drift-and-corporate-insider-trading/)
- One study finds no drift for announcements preceded by insider purchases. Its sample is not US-only. — [Brochet, Lee & Srinivasan 2017 (NYU Stern PDF)](https://www.stern.nyu.edu/sites/default/files/assets/documents/Brochet%20Lee%20Srinivasan%202017%20-%20The%20Role%20of%20Insider%20Trading%20in%20the%20Market%20Reaction%20to%20Earnings%20News.pdf)
- The positive link between insider net purchases and later returns is not driven by large caps. — [ScienceDirect, "Insider trading, future earnings, and post-earnings announcement drift" (2023)](https://www.sciencedirect.com/science/article/abs/pii/S0278425423000662)
- Hou, Xue & Zhang (2020): 96% of anomalies in the "trading frictions" category fail to clear |t| ≥ 1.96 once microcaps are handled. Many liquidity- and event-type signals depend on tiny, costly-to-trade stocks. — [NBER w23394](https://www.nber.org/papers/w23394); [IDEAS](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html)

### Inferences
- Event and information signals (PEAD, revisions, reversals) tend to be high-turnover. Under Novy-Marx & Velikov's rule (turnover above 50% per month rarely survives costs), retail implementations face steep odds even where gross effects persist.
- Where these signals survive, it is mostly in small or illiquid stocks, where costs are highest. This is consistent with Hou-Xue-Zhang's microcap finding.

### Gaps
- No current (2015-2026) evidence was retrieved on short interest as a return predictor, or on whether it has decayed.
- No current evidence on analyst-revision (earnings-momentum) strategies net of costs.
- No net-of-cost, live (fund or ETF) evidence for insider-buying strategies.
- Martineau (2022) primary text not fetched.

---

## 4. Publication decay and the replication debate

### Takeaway
Published anomalies lose roughly half their return after publication (McLean & Pontiff). Under strict, microcap-light testing most of the "factor zoo" fails (Hou, Xue & Zhang: 65% fail |t| ≥ 1.96; 82% fail a multiple-testing hurdle of 2.78). However, a global Bayesian replication (Jensen, Kelly & Pedersen 2023) finds that most factors, grouped into 13 themes, do replicate and work out-of-sample in 93 countries. Reconciliation: the main themes (value, momentum, quality/profitability, low-risk, investment) are real but smaller than first reported. Many niche, microcap-dependent anomalies are not.

### Cited Findings
- **McLean & Pontiff (2016), Journal of Finance 71(1):5-32.** The study covers 97 published predictors and compares three periods: the original sample, out-of-sample but pre-publication, and post-publication. It reports a lower-bound publication effect of about 32%. It rejects both "predictability disappears entirely" and "post-publication predictability is unchanged." Trading volume and short interest rise in anomaly stocks after publication, consistent with investors learning from academic research. — [Gwern mirror of JF paper](https://Www.Gwern.net/doc/economics/2016-mclean.pdf); [CFA Institute digest](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary); [Ivey PDF](https://ivey.uwo.ca/media/3775549/pontiff.pdf)
  - The headline split, returns 26% lower out-of-sample and 58% lower post-publication, is from the paper's abstract, and 58% - 26% = 32% matches the publication effect confirmed above. I could not re-open the abstract in this session. — [paper as above](https://Www.Gwern.net/doc/economics/2016-mclean.pdf)
- **Hou, Xue & Zhang (2020), "Replicating Anomalies," RFS 33(5):2019-2133.** 65% of 452 anomalies, including 96% of trading-frictions anomalies, fail |t| ≥ 1.96 with NYSE breakpoints and value-weighted returns. A multiple-testing hurdle of t ≥ 2.78 raises the failure rate to 82%. Even replicated anomalies have much smaller economic magnitudes than originally reported. "The key word is microcaps." In the 2017 working paper, 64% of 447 failed. — [NBER w23394](https://www.nber.org/papers/w23394); [IDEAS](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html); [Federal Reserve FEDS 2021-037 citing 65.4%](https://www.federalreserve.gov/econres/feds/files/2021-037pap.pdf)
- **Jensen, Kelly & Pedersen (2023), "Is There a Replication Crisis in Finance?," Journal of Finance 78(5):2465-2518.** The majority of factors replicate. They cluster into 13 themes and work out-of-sample in a new dataset of 93 countries. A Bayesian model that accounts for publication bias and multiple testing finds the evidence is strengthened, not weakened, by the large number of factors. Code and data are public. — [CBS publisher's version PDF](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf); [NBER w28432](https://www.nber.org/papers/w28432); [GitHub data/code](https://github.com/bkelly-lab/ReplicationCrisis); [Alpha Architect summary](https://alphaarchitect.com/factors-are-global-respectable-and-repeatable/)
  - The widely quoted figure of about 82% of factors replicating is not confirmed by search snippets. Verify it in the JF paper before quoting.
- **Harvey, Liu & Zhu (2016), "...and the Cross-Section of Expected Returns" (RFS 29(1)).** The paper argues that, given hundreds of tested factors (316 catalogued), a new factor should clear a t-statistic of about 3.0 rather than 2.0. This is from my knowledge of the paper. It was not retrieved in this session; the closely related multiple-testing threshold (2.78) used by Hou-Xue-Zhang is confirmed above. — the paper is SSRN 2249314 (not fetched)

### Inferences
- A practical rule of thumb for investors: expect roughly half or less of a published backtest premium going forward. Then subtract costs, fees and taxes.
- The JKP and HXZ results agree on more than headlines suggest. HXZ's failures cluster in microcap and trading-friction signals, while JKP's successes cluster in broad themes such as value, momentum, quality, low-risk and investment. "Real but smaller, and concentrated in a few themes" is the defensible synthesis.

### Gaps
- The exact JKP replication rate and the Harvey-Liu-Zhu numbers were not verified from primary text this session.
- No post-2016 updates of the McLean-Pontiff decay estimates were retrieved.

---

## 5. Real-world implementation: factor ETFs, fees and SPIVA

### Takeaway
Single-factor ETFs are cheap (about 0.15% for the iShares MSCI factor lineup vs about 0.03% for an S&P 500 ETF). Over the last ~10 years, live long-only results have mostly not beaten the S&P 500: quality slightly behind, min-vol well behind, and momentum roughly even to slightly ahead depending on source and dates. Meanwhile, SPIVA shows about 90% of active US large-cap funds trailing the S&P 500 over 15 years and about 93% over 20 years (to December 2025), with 79% trailing in 2025 alone.

### Cited Findings
- **SPIVA US, Year-End 2025.** 79% of active large-cap funds trailed the S&P 500 in 2025, worse than 65% in 2024 and the fourth-worst year in the 25-year series. — [S&P DJI U.S. Persistence Scorecard Year-End 2025](https://www.spglobal.com/spdji/en/spiva/article/us-persistence-scorecard/); [InvestmentNews](https://www.investmentnews.com/equities/active-managers-stumble-again-in-2025-as-large-caps-dominate/265541); [SPIVA US Year-End 2025 PDF (mirror)](https://www.ariesadvisors.com/files/spiva-us-year-end-2025.pdf)
- **Long-horizon underperformance (to Dec 31, 2025).** About 89.9-90% of large-cap funds trailed over 15 years and about 92.9-93% over 20 years. These come from secondary sources, and one aggregator table shows different values. Verify against the official PDF. — [Evidence Investor](https://www.evidenceinvestor.com/post/has-your-fund-family-outperformed); [GetHossa](https://gethossa.com/blog/spiva-active-funds-vs-sp-500-statistics); [Walnut stats](https://walnutinvest.com/stats/active-fund-underperformance-spiva); conflicting: [cargopantsfinance](https://cargopantsfinance.com/investing/spiva-reports/)
- **SPIVA Mid-Year 2025.** 54% of large-cap funds trailed the S&P 500 in H1 2025. The SPIVA US Mid-Year 2026 report also exists; its search snippet says the S&P 400 and S&P 600 outperformed the S&P 500 in H1 2026. — [SPIVA US Mid-Year 2025](https://www.spglobal.com/spdji/en/spiva/article/spiva-us-mid-year-2025); [SPIVA US Mid-Year 2026 PDF](https://www.spglobal.com/spdji/en/documents/spiva/spiva-us-mid-year-2026.pdf)
- **SPIVA methodology.** It counts funds that closed or merged, correcting for survivorship bias. — [GetHossa summary](https://gethossa.com/blog/spiva-active-funds-vs-sp-500-statistics)
- **Factor ETF fees.** MTUM, QUAL, VLUE and USMV each charge 0.15% a year, vs 0.03% for IVV. — [portfolioslab](https://portfolioslab.com/tools/stock-comparison/QUAL/IVV); [pearler](https://pearler.com/explore/invest/us-shares/compare/MTUM-vs-IVV)
- **Factor ETF 10-year returns** (sources and dates differ; data around late 2025 to 2026):
  - MTUM: 16.51% vs IVV 15.39% in one source; 14.70% in another (cumulative 290.56% vs 285.84%).
  - QUAL: 14.19% vs IVV 15.32%.
  - USMV: 10.20% vs QUAL 14.28%.
  - Sources: [portfolioslab MTUM/IVV](https://portfolioslab.com/tools/stock-comparison/MTUM/IVV); [portfolioslab QUAL/IVV](https://portfolioslab.com/tools/stock-comparison/QUAL/IVV); [portfolioslab USMV/QUAL](https://portfolioslab.com/tools/stock-comparison/USMV/QUAL); [financecharts](https://www.financecharts.com/etfs/MTUM/performance/total-return); [myetfjourney](https://myetfjourney.com/compare/usmv-vs-qual)
- **2025 calendar-year returns:** MTUM +22.15%, QUAL +12.65%, VLUE +32.67%. — [totalrealreturns](https://totalrealreturns.com/n/MTUM,QUAL,VLUE)
- **Capacity and turnover matter for implementation.** Low-turnover factors (size, value, profitability) have the most capacity, and cost-aware design (buy/hold bands) is the most effective way to keep net returns. — [Novy-Marx & Velikov, NBER w20721](https://www.nber.org/papers/w20721)

### Inferences
- The SPIVA numbers set the bar. A cheap single-factor ETF that roughly matches the S&P 500 over 10 years already beats about 85-90% of active large-cap funds. Even so, none of the single-factor ETFs above clearly and reliably beat the S&P 500 over 2015-2025, a decade dominated by mega-cap growth.
- The gap between paper premiums (long-short, equal or value-weighted, frictionless) and long-only cap-weighted ETF results is large. Retail investors should expect ETF tracking of factor premiums to be partial.

### Gaps
- The official 10-, 15- and 20-year SPIVA tables could not be fetched (spglobal.com was blocked). The 15- and 20-year figures are secondary.
- No Morningstar research on factor ETF success or survival rates, or on Dimensional fund performance vs indexes, was retrieved.
- No standardized, same-end-date 10-year return table for MTUM, QUAL, USMV, VLUE and IVV. The figures above mix dates.

---

## 6. Multi-factor diversification

### Takeaway
The theoretical and backtest case for combining factors rests on low or negative correlations, especially value vs momentum (Asness, Moskowitz & Pedersen 2013) and on quality acting as a defensive "flight-to-quality" hedge. Live multi-factor evidence was not retrieved in this session.

### Cited Findings
- Quality stocks tend to benefit during flight-to-quality episodes rather than crash, which makes QMJ a natural diversifier for value and momentum. — [Asness, Frazzini & Pedersen, RAS 2019](https://link.springer.com/article/10.1007/s11142-018-9470-2)
- JKP group factors into 13 themes that work across 93 countries, which supports diversifying across themes rather than relying on any single anomaly. — [CBS PDF of JKP 2023](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf)
- Controlling for junk (quality) revives the size premium. This interaction effect supports multi-factor screens such as small + quality or small + value. — [Asness et al., "Size Matters, if You Control Your Junk"](https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2015/05/Size-Matters-if-You-Control-Your-Junk.pdf)
- Value and momentum are negatively correlated across asset classes and countries ("Value and Momentum Everywhere," JF 2013). This is from my knowledge of the paper's abstract and was not retrieved this session.

### Inferences
- In 2025, value ETFs (VLUE +32.67%) and quality ETFs (QUAL +12.65%) diverged sharply. This illustrates the low year-to-year correlation that makes a multi-factor blend smoother than any single factor. — [totalrealreturns](https://totalrealreturns.com/n/MTUM,QUAL,VLUE)
- A defensible synthesis for retail investors: if pursuing factors at all, use a low-cost, low-turnover blend of value, momentum, quality/profitability and possibly small-cap value. Accept possible decade-long underperformance and expect net premiums well below published backtests.

### Gaps
- No live performance data for multi-factor ETFs (for example, iShares LRGF, or Dimensional/Avantis funds vs benchmarks).
- No retrieved quantitative estimates of the value-momentum correlation or of combined-portfolio Sharpe ratios.
