"""Stocks used for the historical test.

Two separate lists so the rules can be checked on stocks they were never
tuned on. Both are large, long-listed US companies across every sector,
including many that did badly for long stretches (Intel, GE, Citigroup, AT&T,
Boeing, Pfizer, energy and telecoms) so the test is not only last decade's
winners.

Survivorship bias: Yahoo drops companies that were acquired or went bust, so
every stock here survived to today. That flatters any long-only strategy. The
reports compare against buying and holding these same stocks, which carries
the same bias, so the comparison is fair even if the absolute returns are not.
"""

TRAIN = [
    # technology
    "AAPL", "MSFT", "INTC", "CSCO", "ORCL", "IBM", "QCOM", "TXN", "ADBE", "AMD",
    "NVDA", "MU", "HPQ", "AMAT",
    # consumer
    "AMZN", "HD", "LOW", "MCD", "NKE", "SBUX", "TGT", "WMT", "COST", "KO", "PEP",
    "PG", "CL", "MO", "F", "GM",
    # health
    "JNJ", "PFE", "MRK", "ABT", "LLY", "BMY", "AMGN", "GILD", "UNH", "MDT",
    # financial
    "JPM", "BAC", "C", "WFC", "GS", "MS", "AXP", "AIG", "USB", "MET",
    # industrial and materials
    "GE", "BA", "CAT", "MMM", "HON", "UPS", "LMT", "DE", "DD", "FCX", "NEM",
    # energy, utilities, telecom
    "XOM", "CVX", "COP", "SLB", "HAL", "OXY", "DUK", "SO", "T", "VZ", "CMCSA", "DIS",
]

HOLDOUT = [
    "ADP", "ADSK", "APD", "BBY", "BDX", "BK", "CAH", "CB", "CI", "CLX", "CMI",
    "CSX", "CVS", "D", "DHR", "DOV", "ECL", "ED", "EMR", "EOG", "ETN", "EXC",
    "FDX", "GIS", "GLW", "GPC", "GWW", "HIG", "HSY", "ITW", "K", "KMB", "KR",
    "LEN", "LUV", "MAS", "MCK", "MMC", "MSI", "NOC", "NSC", "NUE", "PCAR", "PGR",
    "PH", "PNC", "PPG", "ROK", "SHW", "SJM", "SPGI", "SWK", "SYY", "TJX", "TRV",
    "UNP", "VFC", "WHR", "WY", "XRX",
]

# Final exam: never used for tuning or for choosing between rule variants.
# Run exactly once, after round 2 has picked its rules.
FINAL_EXAM = [
    "AFL", "ALL", "AON", "APH", "AZO", "BAX", "BEN", "BIIB", "BSX", "CCL", "CHRW",
    "CINF", "CME", "CTAS", "DRI", "DVN", "EBAY", "EFX", "FAST", "FITB", "HAS",
    "HUM", "IFF", "IP", "JBHT", "KEY", "L", "LH", "MAR", "MCO", "MKC", "MTB",
    "NTRS", "NVR", "OMC", "ORLY", "PAYX", "PHM", "PKG", "PNR", "PSA", "RF", "RHI",
    "ROST", "SNA", "SRE", "STT", "SYK", "TROW", "TSN", "TXT", "VLO", "VMC", "WAT",
    "WM", "YUM", "ZBH", "A",
]

BENCHMARK = "SPY"
TBILL = "^IRX"  # 13-week Treasury bill yield, for interest on idle cash
