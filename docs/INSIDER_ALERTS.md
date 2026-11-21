# How to get alerts when insiders trade

Research notes on every practical way to be notified when a company insider
(or a member of Congress) buys or sells stock, and how StockAnalysis does it.

## 1. Where insider trades come from

Every insider alert, free or paid, starts from the same public filings.

| Filing | Who files | Deadline after the trade | What it tells you |
|---|---|---|---|
| **Form 4** | Officers, directors, 10%+ owners | **2 business days** (since Aug 2002, Sarbanes-Oxley) | The trade itself: date, shares, price, holdings after, transaction code, 10b5-1 flag |
| Form 3 | New insiders | 10 days after becoming an insider | Starting holdings, no trade |
| Form 5 | Insiders with exempt or late items | 45 days after fiscal year end | Small or exempt transactions missed on Form 4 |
| Form 144 | Affiliates planning to sell restricted or control stock | Filed around the time of the sale order | Advance notice of a **sale** (now filed electronically on EDGAR) |
| Schedule 13D | Anyone crossing 5% with intent to influence | **5 business days** (shortened from 10 days in the 2023 amendments) | Activist stakes |
| 13F | Funds over $100M | 45 days after quarter end | Quarterly fund holdings, too slow to time trades |
| Congressional PTR | Members of Congress and spouses | **45 days** (STOCK Act), trades over $1,000 | Politicians' trades, often weeks old by the time they appear |

So the fastest an insider trade can become public is minutes after the Form 4
is accepted by EDGAR, which is usually 1 to 2 business days after the trade.
Many companies file in the evening (EDGAR accepts filings until 10 p.m. ET), so
alerts often arrive after the market closes.

Sources: [SEC final rule 34-46421](https://www.sec.gov/rules/final/34-46421.htm),
[Investor.gov bulletin on Forms 3, 4 and 5](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-69),
[SEC 13D/13G amendments fact sheet](https://www.sec.gov:443/files/33-11253-fact-sheet.pdf),
[Ballard Spahr on the 13D changes](https://www.ballardspahr.com/Insights/Alerts-and-Articles/2023/10/SEC-Modernizes-Beneficial-Ownership-Reporting-Rules),
[CRS: Taking Stock of the STOCK Act](https://www.everycrsreport.com/reports/TE10119.html).

### Form 4 transaction codes that matter

| Code | Meaning | Signal? |
|---|---|---|
| **P** | Open-market or private **purchase** | Yes, the main one |
| **S** | Open-market or private **sale** | Weak |
| A | Grant or award from the company | No (compensation) |
| M | Option exercise or conversion | No |
| F | Shares withheld to pay tax or the exercise price | No |
| G | Gift | No |
| D | Sold back to the company | No |

Since 2023 Form 4 has a checkbox (`aff10b5One` in the XML) for trades made
under a pre-arranged **Rule 10b5-1 plan**. Those were scheduled months earlier,
so they say less about the insider's current view. Older filings only mention
the plan in a footnote. Source: [SEC General Transaction Codes](https://www.sec.gov/edgar/searchedgar/ownershipformcodes.html).

## 2. Which insider trades are worth an alert

- **Purchases, not sales.** Lakonishok and Lee (Review of Financial Studies,
  2001) found insider buying predicts returns, mostly in smaller firms, while
  insider selling shows no predictive ability. Seyhun's work finds trades by
  insiders closer to top management, and at smaller firms, more informative.
  ([RePEc listing](https://ideas.repec.org/a/oup/rfinst/v14y2001i1p79-111.html),
  [NBER w6656](https://ideas.repec.org/p/nbr/nberwo/6656.html))
- **Opportunistic, not routine.** Cohen, Malloy and Pomorski (*Decoding Inside
  Information*, Journal of Finance 2012) separated insiders who trade in the
  same calendar month year after year ("routine", over half of all trades) from
  everyone else. Opportunistic trades earned about 0.82% a month in
  value-weighted abnormal returns; routine trades earned essentially zero.
  ([NBER w16454](https://www.nber.org/papers/w16454))
  *Note:* the exact rule used here, same month in each of the previous three
  years, is the one commonly cited for that paper; check the paper for the
  precise definition.
- **Several insiders at once (cluster buying)** adds information on top of the
  routine/opportunistic split.
- **Not under a 10b5-1 plan.**

## 3. Every way to get the alerts

### Free, straight from the SEC

| Method | How | Speed | Effort |
|---|---|---|---|
| EDGAR "Latest Filings" feed | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=100&output=atom` in any RSS reader | Minutes | Low, but floods you with every Form 4 in the US (thousands a day) |
| One company's Form 4 feed | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=4&owner=only&count=40&output=atom` in an RSS reader | Minutes | Low; one feed per stock, still includes grants and tax withholding |
| data.sec.gov submissions API | `https://data.sec.gov/submissions/CIK0000320193.json` lists every filing by a company or person as JSON | Near real time | Needs a script |
| EDGAR full-text search | `efts.sec.gov` behind the EDGAR search page | Minutes | Needs a script |
| **This app** | Settings > Insider alerts | Checks every 2 min by default | Enter your name and email once |

Rules for automated access ([SEC: Accessing EDGAR data](https://www.sec.gov/os/accessing-edgar-data),
[SEC developer resources](https://www.sec.gov/developer)):
- Declare a User-Agent with a name and contact email. Without one, www.sec.gov
  answers with an "Undeclared Automated Tool" page (confirmed while building this).
- Stay under 10 requests per second, across all your machines.

RSS readers and the feed templates: [SEC RSS feeds page](https://www.sec.gov/about/secrss.shtml),
[Feeder guide to EDGAR feeds](https://feeder.co/knowledge-base/rss-feed-creation/sec-edgar-rss-feeds/).

### Websites and apps

Rankings in these roundups conflict and several are affiliate pages; check
current prices on each vendor's site.

| Service | Insider alerts | Notes |
|---|---|---|
| OpenInsider | Screens of the latest buys, cluster buys, CEO/CFO buys | Free; good for research, not built for real-time push |
| Finviz | Insider table in the screener | Alerts and exports need the paid tier |
| InsiderTradeAlerts | Email and Telegram, claims under 1 second after EDGAR | Specialist alert service |
| Form4.ai | Insider-only alerts | Specialist |
| ChartingLens | Cluster detection, insider alerts | About $9.99/month premium |
| Unusual Whales | Insider and congressional trade alerts | Also options flow |
| Quiver Quantitative | Insider, congressional and lobbying data | Alternative data |
| Insider Monkey | Insider trades plus hedge fund holdings | Newsletter style |
| Capitol Trades | Congressional trades, alerts for new filings | Congress only |

Sources: [SentiSense roundup](https://sentisense.ai/blog/best-insider-trading-trackers-2026/),
[InsiderTradeAlerts comparison](https://insidertradealerts.com/blog/best-sec-form-4-alert-services-august-2026-which-one-is-worth-paying-for/),
[Unusual Whales guide](https://unusualwhales.com/guides/best-insider-trading-trackers),
[Will Kopec roundup](https://willkopec.com/blog/best-insider-trading-tracker-tools),
[TIKR free tools](https://www.tikr.com/blog/best-free-tools-to-track-insider-ownership-changes-in-stocks).

### Data APIs (for building your own)

| API | Insider data | Free tier |
|---|---|---|
| SEC EDGAR (data.sec.gov + Archives) | Raw Form 4 XML | Free, 10 requests/second |
| Form4API | Parsed Form 4 with webhooks and 10b5-1 flag | Free tier without a card |
| sec-api.io | Insider trading API and Form 4 dataset from 2009 | Paid |
| Financial Modeling Prep | Insider endpoint by ticker or CIK | 250 calls/day free; insider data reported on mid tier |
| Finnhub | Insider transactions endpoint | 60 calls/minute free for personal use |

Sources: [StockFit comparison](https://developer.stockfit.io/blog/best-insider-trading-api),
[Edgrapi comparison](https://edgrapi.com/blog/best-insider-trading-api),
[FMP API docs](https://github.com/FinancialModelingPrepAPI/Financial-Modeling-Prep-API),
[sec-api.io Form 4 dataset](https://sec-api.io/datasets/form-4).

### Congress (STOCK Act)

Members of Congress report trades over $1,000 within 45 days, so these alerts
are always weeks late. Official sources are the House Clerk
(disclosures.house.gov) and Senate (efdsearch.senate.gov); Capitol Trades,
Quiver and Unusual Whales send alerts when new reports are filed. Bills to
shorten the window or ban member trading had stalled as of early 2026.
Sources: [Campaign Legal Center](https://campaignlegal.org/update/congressional-stock-trading-continues-raise-conflicts-interest-concerns),
[House hearing transcript](https://www.govinfo.gov/content/pkg/CHRG-119hhrg61940/html/CHRG-119hhrg61940.htm).
The app does not track congressional trades yet.

### Getting alerts onto your phone

- **ntfy** (free, open source): install the app, subscribe to a topic name,
  and anything posted to `https://ntfy.sh/<topic>` arrives as a push
  notification. Priority 1 to 5, tags and a click-through link are supported.
  Anyone who knows the topic name can read it, so use a long random one.
  ([ntfy publishing docs](https://docs.ntfy.sh/publish))
- **Discord or Slack**: create an incoming webhook for a channel and turn on
  mobile notifications for it.
- **Browser pop-ups**: StockAnalysis can show desktop notifications while its
  page is open (Alerts > Desktop pop-ups).

## 4. What StockAnalysis does

Settings > Insider trade alerts, after entering a name and email for the SEC:

1. **Watchlist, every 2 minutes:** reads each watched company's filing list
   from data.sec.gov, downloads new Form 4s, and alerts on every open-market
   purchase (and on sales above a size you choose, if turned on). The first
   sync loads 120 days of history so the insider score has data.
2. **Whole market, every 2 minutes:** reads EDGAR's live Form 4 feed and alerts
   on open-market purchases by officers and directors above a minimum size
   ($500K by default), skipping pre-planned 10b5-1 buys.
3. **Cluster buying:** alerts when 3 or more insiders buy the same stock within
   30 days.
4. **Routine or opportunistic:** for each purchase it checks the insider's own
   past filings for the same calendar month in the previous three years and
   labels the trade.
5. **Alert text** says who bought, their role, shares, average price, total
   value, trade and filing dates, how much it raised their stake, whether it was
   under a 10b5-1 plan, and whether it fits a routine pattern, with a link to
   the filing on sec.gov.
6. **Scoring:** the stock's insider signal now ignores 10b5-1 purchases and
   counts routine buyers at half weight.
7. **Phone push** via ntfy, Discord or Slack, for insider alerts only or for
   every alert.

Limits: the market-wide feed only covers filings published while the app is
running (the watchlist catches up on restart); the routine check looks at up to
three years of the insider's filings; Form 144 (planned sales) and
congressional trades are not tracked yet.
