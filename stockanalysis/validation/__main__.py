import argparse
import logging

from .run import main

parser = argparse.ArgumentParser(description="Replay the app's rules on 20+ years of history.")
parser.add_argument("--refresh", action="store_true", help="re-download prices and earnings")
args = parser.parse_args()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
main(refresh=args.refresh)
