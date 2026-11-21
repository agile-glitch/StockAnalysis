"""Ticker symbol format shared by the API and settings."""

import re

# Stocks and ETFs (AAPL, BRK-B), futures (GC=F), currencies (EURUSD=X), crypto (BTC-USD), indexes (^GSPC).
SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-]{0,11}(=F|=X)?$")
