#!/usr/bin/env python3
"""Start StockAnalysis.

    python run.py            live data from Yahoo Finance
    python run.py --demo     simulated data, works offline
"""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="Follow stocks, news and earnings with trade alerts.")
    parser.add_argument("--demo", action="store_true", help="use simulated data instead of live market data")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # yfinance logs an error for every symbol quirk; the app reports those itself.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    import uvicorn

    from stockanalysis.server import create_app

    app = create_app(demo=args.demo)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"\n  StockAnalysis is running at {url}" + ("  (demo data)" if args.demo else "") + "\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
