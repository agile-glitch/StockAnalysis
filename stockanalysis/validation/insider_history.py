"""Copying insiders: would buying after every insider purchase have made money?

    SEC_CONTACT="Your Name you@example.com" python -m stockanalysis.validation.insider_history download
    python -m stockanalysis.validation.insider_history run

Data: the SEC's Insider Transactions Data Sets - every Form 3/4/5 filed since
2006, one zip per quarter. Only open-market purchases (transaction code P) on
Form 4 are kept: grants, option exercises and sales mostly say nothing about
what an insider expects. The SEC requires a contact in the User-Agent; it is
read from the SEC_CONTACT environment variable and only sent to sec.gov.

Copying rule: a filing is public by 10 pm on its filing date, so the copy buys
at the next trading day's open and holds for six months (the horizon most
studies use), then sells. One shared pot: every open copy gets an equal share
(at most 5%), the rest earns T-bills. 0.1% per trade, plus 0.4% extra in small
and thinly traded stocks where spreads are wider.

Variants, all from the published research (none tuned here):
  all           every open-market purchase
  big           purchases of $100,000 or more
  officers      bought by the CEO, CFO, president or COO
  cluster       2+ different insiders buying the same stock within 30 days
  opportunistic not a routine buyer (Cohen, Malloy & Pomorski 2012: routine =
                bought in the same calendar month in each of the previous 3 years)
  combined      big AND (officer OR cluster) AND opportunistic

Each is tested on tradeable stocks (price >= $5 and >= $1M traded per day) and
on everything. The pick is fixed in advance: the variant with the highest
return over the S&P 500 in 2006-2015, tradeable stocks only; it is then tested
on 2016-today.

Biases, stated plainly:
* Companies that were delisted (bankrupt, acquired) mostly have no Yahoo
  prices, so their events are missing. Insider buying is common in struggling
  small companies, so this flatters results; the share of events without
  prices is reported.
* Tickers are matched by today's symbol; a recycled ticker can point at a
  different company. That adds noise rather than a systematic bias.
* Illegal insider trading is not reported on Form 4 and cannot be copied.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("stockanalysis.validation")

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "insider_history"
REPORT_DIR = ROOT / "data" / "validation"
BUNDLED = Path(__file__).resolve().parent / "latest_insider_backtest.json"
DOC = ROOT / "docs" / "INSIDER_BACKTEST.md"
URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip"
FIRST_YEAR = 2006

HOLD_DAYS = 126
COST = 0.001
SMALL_EXTRA_COST = 0.004
MAX_WEIGHT = 0.05
MIN_PRICE, MIN_DOLLAR_VOLUME = 5.0, 1_000_000.0
OFFICER = re.compile(r"\b(?:CEO|CFO|COO|CHIEF EXECUTIVE|CHIEF FINANCIAL|CHIEF OPERATING|PRESIDENT)\b", re.I)
TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")
VARIANTS = {
    "all": "Every open-market purchase",
    "big": "Purchases of $100,000 or more",
    "officers": "Bought by the CEO, CFO, president or COO",
    "cluster": "2+ insiders buying within 30 days",
    "opportunistic": "Not a routine buyer",
    "combined": "$100K+, by an officer or a cluster, not routine",
}


# --------------------------------------------------------------------------
# Download and parse
# --------------------------------------------------------------------------

def quarters(today: date | None = None):
    today = today or date.today()
    for y in range(FIRST_YEAR, today.year + 1):
        for q in range(1, 5):
            if (y, q) <= (today.year, (today.month - 1) // 3 + 1):
                yield y, q


def _read(z: zipfile.ZipFile, name: str, cols: list[str]) -> pd.DataFrame:
    member = next((n for n in z.namelist() if n.upper().endswith(name)), None)
    if member is None:
        return pd.DataFrame(columns=cols)
    with z.open(member) as fh:
        df = pd.read_csv(fh, sep="\t", dtype=str, quoting=3, on_bad_lines="skip", low_memory=False)
    df.columns = [c.strip().upper() for c in df.columns]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def _date(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    miss = out.isna() & s.notna()
    if miss.any():
        out[miss] = pd.to_datetime(s[miss], errors="coerce")
    return out


def parse_zip(blob: bytes) -> pd.DataFrame:
    """Open-market purchases (Form 4, code P, acquired) with filer and issuer details."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        sub = _read(z, "SUBMISSION.TSV", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK",
                                           "ISSUERNAME", "ISSUERTRADINGSYMBOL"])
        own = _read(z, "REPORTINGOWNER.TSV", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME",
                                               "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"])
        tr = _read(z, "NONDERIV_TRANS.TSV", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                              "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD",
                                              "SHRS_OWND_FOLWNG_TRANS"])
    tr = tr[(tr["TRANS_CODE"].str.strip() == "P") & (tr["TRANS_ACQUIRED_DISP_CD"].str.strip() == "A")]
    sub = sub[sub["DOCUMENT_TYPE"].str.strip().isin(["4", "4/A"])]
    owner = own.groupby("ACCESSION_NUMBER").agg(
        owner_cik=("RPTOWNERCIK", "first"), owner=("RPTOWNERNAME", "first"),
        relationship=("RPTOWNER_RELATIONSHIP", lambda x: ",".join(sorted(set(str(v) for v in x if v)))),
        title=("RPTOWNER_TITLE", lambda x: "; ".join(sorted(set(str(v) for v in x if v and str(v) != "nan")))),
        owners=("RPTOWNERCIK", "nunique"))
    df = tr.merge(sub, on="ACCESSION_NUMBER").merge(owner, left_on="ACCESSION_NUMBER", right_index=True, how="left")
    out = pd.DataFrame({
        "accession": df["ACCESSION_NUMBER"],
        "filed": _date(df["FILING_DATE"]),
        "trade_date": _date(df["TRANS_DATE"]),
        "issuer_cik": df["ISSUERCIK"],
        "issuer": df["ISSUERNAME"],
        "symbol_raw": df["ISSUERTRADINGSYMBOL"],
        "owner_cik": df["owner_cik"],
        "owner": df["owner"],
        "relationship": df["relationship"],
        "title": df["title"],
        "shares": pd.to_numeric(df["TRANS_SHARES"], errors="coerce"),
        "price": pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce"),
        "owned_after": pd.to_numeric(df["SHRS_OWND_FOLWNG_TRANS"], errors="coerce"),
    })
    out["value"] = out["shares"] * out["price"]
    return out.dropna(subset=["filed", "shares"])


def download(contact: str, today: date | None = None) -> dict:
    from .. import __version__
    from ..sec import valid_contact
    if not valid_contact(contact):
        raise SystemExit("Set SEC_CONTACT to your name and email, e.g. SEC_CONTACT=\"Jane Doe jane@example.com\". "
                         "The SEC refuses requests without one; it is only sent to sec.gov.")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    agent = f"StockAnalysis/{__version__} {contact.strip()}"
    got, skipped = 0, []
    for y, q in quarters(today):
        path = RAW_DIR / f"{y}q{q}_purchases.csv.gz"
        if path.exists():
            continue
        req = urllib.request.Request(URL.format(y=y, q=q), headers={"User-Agent": agent})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    blob = resp.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:      # not published yet
                    blob = None
                    break
                log.warning("%sq%s: HTTP %s, retrying", y, q, exc.code)
                time.sleep(5 * (attempt + 1))
            except Exception as exc:
                log.warning("%sq%s: %s, retrying", y, q, exc)
                time.sleep(5 * (attempt + 1))
        else:
            skipped.append(f"{y}q{q}")
            continue
        if blob is None:
            skipped.append(f"{y}q{q} (not published)")
            continue
        df = parse_zip(blob)
        df.to_csv(path, index=False)
        got += 1
        print(f"{y}q{q}: {len(df):,} open-market purchases", flush=True)
        time.sleep(1.0)       # far below the SEC's 10 requests per second
    return {"downloaded": got, "skipped": skipped}


def load_purchases() -> pd.DataFrame:
    files = sorted(RAW_DIR.glob("*_purchases.csv.gz"))
    if not files:
        raise SystemExit("No insider history yet. Run the download step first (see the module docstring).")
    df = pd.concat([pd.read_csv(f, dtype={"issuer_cik": str, "owner_cik": str}, parse_dates=["filed", "trade_date"])
                    for f in files], ignore_index=True)
    return df.drop_duplicates(subset=["accession", "trade_date", "shares", "price"])


def clean_symbol(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper().split()[0] if raw.strip() else ""
    s = s.split(":")[-1].replace(".", "-").replace("/", "-")
    return s if TICKER.match(s) else None


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

def events(purchases: pd.DataFrame) -> pd.DataFrame:
    """One row per stock per filing date, with the facts the variants need."""
    p = purchases.copy()
    p["symbol"] = p["symbol_raw"].map(clean_symbol)
    p = p.dropna(subset=["symbol"])
    p = p[(p["price"] > 0) & (p["value"] > 0)]
    title = (p["title"].fillna("") + " " + p["relationship"].fillna(""))
    p["is_officer"] = p["title"].fillna("").str.contains(OFFICER)
    p["is_ten_pct_only"] = p["relationship"].fillna("").str.contains("TenPercent", case=False) & ~title.str.contains(
        "Director|Officer", case=False)
    # Routine buyers (Cohen, Malloy & Pomorski): bought in the same calendar month in each of the prior 3 years.
    p["ym"] = p["trade_date"].dt.year * 12 + p["trade_date"].dt.month
    months = p.dropna(subset=["trade_date"]).groupby("owner_cik")["ym"].apply(set).to_dict()
    def routine(row):
        ms = months.get(row["owner_cik"], set())
        if pd.isna(row["ym"]):
            return False
        return all(row["ym"] - 12 * k in ms for k in (1, 2, 3))
    p["routine"] = p.apply(routine, axis=1)
    g = p.groupby(["symbol", "filed"])
    ev = g.agg(issuer=("issuer", "first"), value=("value", "sum"), insiders=("owner_cik", "nunique"),
               officer=("is_officer", "any"), routine=("routine", "all"), ten_pct_only=("is_ten_pct_only", "all"),
               price=("price", "median"), trade_date=("trade_date", "min")).reset_index()
    ev = ev.sort_values(["symbol", "filed"])
    # Cluster: 2+ different insiders filing purchases of the same stock within 30 days.
    owners = p.groupby(["symbol", "filed"])["owner_cik"].apply(set)
    cluster = []
    for sym, grp in ev.groupby("symbol", sort=False):
        dates = grp["filed"].tolist()
        for i, d in enumerate(dates):
            seen = set()
            for j in range(i, -1, -1):
                if (d - dates[j]).days > 30:
                    break
                seen |= owners[(sym, dates[j])]
            cluster.append(len(seen) >= 2)
    ev["cluster"] = cluster
    ev["big"] = ev["value"] >= 100_000
    ev["opportunistic"] = ~ev["routine"] & (ev["filed"].dt.year >= FIRST_YEAR + 3)
    ev["combined"] = ev["big"] & (ev["officer"] | ev["cluster"]) & ev["opportunistic"]
    return ev


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def attach_prices(ev: pd.DataFrame, prices: dict) -> pd.DataFrame:
    """Entry day (next trading day after filing), tradeability and event returns."""
    rows = []
    for sym, grp in ev.groupby("symbol"):
        df = prices.get(sym)
        if df is None:
            continue
        idx = df.index
        dv = (df["close"] * df["volume"]).rolling(20, min_periods=5).mean()
        for _, e in grp.iterrows():
            i = idx.searchsorted(e["filed"], side="right")          # first trading day after the filing date
            if i >= len(idx) - 1:
                continue
            entry_open = float(df["open"].iloc[i])
            if not entry_open > 0:
                continue
            row = e.to_dict()
            row["entry"] = idx[i]
            row["entry_i"] = i
            row["tradeable"] = bool(df["close"].iloc[i - 1] >= MIN_PRICE and (dv.iloc[i - 1] or 0) >= MIN_DOLLAR_VOLUME) if i > 0 else False
            # Price sanity: Yahoo close near the reported purchase price (before later splits / dividends).
            near = df["close"].iloc[max(0, i - 3):i + 1].mean()
            row["price_ratio"] = float(e["price"] / near) if near else np.nan
            for h in (21, 63, 126, 252):
                j = i + h - 1
                row[f"ret_{h}"] = float(df["close"].iloc[j] / entry_open - 1) if j < len(idx) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def market_relative(evp: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    idx = spy.index
    for h in (21, 63, 126, 252):
        i = idx.searchsorted(evp["entry"])
        j = i + h - 1
        ok = j < len(idx)
        spy_ret = np.full(len(evp), np.nan)
        spy_ret[ok] = spy["close"].to_numpy()[j[ok]] / spy["open"].to_numpy()[i[ok]] - 1
        evp[f"spy_{h}"] = spy_ret
        evp[f"excess_{h}"] = evp[f"ret_{h}"] - evp[f"spy_{h}"]
    return evp


def portfolio(evp: pd.DataFrame, prices: dict, spy: pd.DataFrame, cash: pd.Series, start: str, end: str | None) -> dict:
    """Copy every event (buy next open, hold HOLD_DAYS), equal shares of one pot, rest in T-bills."""
    from .. import tactics as T
    from .portfolio import curve_metrics
    idx = spy.loc[start:end].index
    if evp.empty or not len(idx):
        return {}
    # Work on the window plus room for positions opened near its end.
    lo = max(0, spy.index.searchsorted(idx[0]) - 5)
    hi = min(len(spy.index), spy.index.searchsorted(idx[-1]) + 1)
    days = spy.index[lo:hi]
    syms = sorted(evp["symbol"].unique())
    col = {s: k for k, s in enumerate(syms)}
    held = np.zeros((len(days), len(syms)), dtype=bool)
    for sym, entry in zip(evp["symbol"], evp["entry"]):
        a = days.searchsorted(entry) - 1             # decided after the filing day's close, bought at the next open
        if a < 0:
            continue
        held[a:a + HOLD_DAYS, col[sym]] = True
    close = pd.DataFrame({s: prices[s]["close"] for s in syms}).reindex(days)
    open_ = pd.DataFrame({s: prices[s]["open"] for s in syms}).reindex(days)
    held = pd.DataFrame(held, index=days, columns=syms) & close.notna()
    small = evp.groupby("symbol")["tradeable"].mean() < 0.5
    c = cash.reindex(days).fillna(0.0)
    parts = []
    for cost, cols in ((COST, [s for s in syms if not small.get(s, False)]),
                       (COST + SMALL_EXTRA_COST, [s for s in syms if small.get(s, False)])):
        if cols:
            parts.append(T.backtest(open_[cols], close[cols], held[cols], c, cost))
    r = pd.concat(parts, axis=1)[syms]
    pooled = T.pooled_returns(r, held, c, max_weight=MAX_WEIGHT).loc[idx[0]:idx[-1]]
    spy_r = spy["close"].pct_change().loc[idx[0]:idx[-1]].fillna(0.0)
    m = curve_metrics((1 + pooled).cumprod(), cash)
    s = curve_metrics((1 + spy_r).cumprod(), cash)
    active = held.loc[idx[0]:idx[-1]].sum(axis=1)
    weekly = (1 + pooled).cumprod().resample("W-FRI").last()
    weekly_spy = (1 + spy_r).cumprod().resample("W-FRI").last()
    return {"strategy": m, "spy": s, "avg_positions": round(float(active.mean()), 1),
            "invested_pct": round(float(np.minimum(1.0, active * MAX_WEIGHT).mean()) * 100, 1),
            "curve": {"dates": [d.date().isoformat() for d in weekly.index],
                      "strategy": [round(float(x) * 100, 2) for x in weekly],
                      "spy": [round(float(x) * 100, 2) for x in weekly_spy]}}


def event_stats(evp: pd.DataFrame) -> dict:
    out = {"events": int(len(evp))}
    for h in (21, 63, 126, 252):
        x = evp[f"excess_{h}"].dropna()
        if len(x) < 20:
            continue
        months = evp.loc[x.index, "entry"].dt.to_period("M")
        monthly = x.groupby(months).mean()          # one number per month, so busy months do not dominate
        t = monthly.mean() / (monthly.std() / math.sqrt(len(monthly))) if len(monthly) > 2 and monthly.std() > 0 else None
        out[f"h{h}"] = {"avg_excess_pct": round(float(x.mean()) * 100, 2), "median_excess_pct": round(float(x.median()) * 100, 2),
                        "beat_market_pct": round(float((x > 0).mean()) * 100, 1),
                        "avg_return_pct": round(float(evp.loc[x.index, f"ret_{h}"].mean()) * 100, 2),
                        "t_stat": round(float(t), 2) if t is not None else None}
    return out


def run() -> dict:
    from . import data
    from .portfolio import _daily_cash_rate
    purchases = load_purchases()
    ev = events(purchases)
    symbols = sorted(ev["symbol"].unique())
    log.info("insiders: %d purchases, %d events, %d symbols; loading prices", len(purchases), len(ev), len(symbols))
    prices = data.load_prices(symbols + ["SPY"])
    spy = prices["SPY"]
    tbill = data.load_tbill()
    cash = pd.Series(_daily_cash_rate(spy.index, tbill), index=spy.index)
    evp = market_relative(attach_prices(ev, prices), spy)
    coverage = {"purchases": int(len(purchases)), "events": int(len(ev)), "symbols": int(len(symbols)),
                "events_with_prices": int(len(evp)), "symbols_with_prices": int(evp["symbol"].nunique()),
                "price_match_pct": round(float(evp["price_ratio"].between(0.67, 1.5).mean()) * 100, 1),
                "first": str(ev["filed"].min().date()), "last": str(ev["filed"].max().date())}
    periods = {"first": ("2006-01-01", "2015-12-31"), "second": ("2016-01-01", None)}
    results = {}
    for key, label in VARIANTS.items():
        sel = evp[evp[key]] if key != "all" else evp
        for universe in ("tradeable", "everything"):
            u = sel[sel["tradeable"]] if universe == "tradeable" else sel
            row = {"label": label, "universe": universe}
            for p, (a, b) in periods.items():
                w = u[(u["entry"] >= a) & ((u["entry"] <= b) if b else True)]
                log.info("insiders: %s / %s / %s (%d events)", key, universe, p, len(w))
                row[p] = {"events": event_stats(w), "portfolio": portfolio(w, prices, spy, cash, a, b)}
            results[f"{key}:{universe}"] = row
    def excess(k, p):
        pf = results[k][p]["portfolio"]
        return (pf["strategy"]["cagr_pct"] - pf["spy"]["cagr_pct"]) if pf else -99
    pick = max((k for k in results if k.endswith(":tradeable")), key=lambda k: excess(k, "first"))
    report = {"design": __doc__, "coverage": coverage, "results": results, "pick": pick,
              "pick_test": {"excess_cagr_first": round(excess(pick, "first"), 2),
                            "excess_cagr_second": round(excess(pick, "second"), 2)},
              "generated": pd.Timestamp.now().isoformat(timespec="seconds")}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    evp.drop(columns=["entry_i"]).to_csv(REPORT_DIR / "insider_events.csv.gz", index=False)
    slim = json.loads(json.dumps(report, default=str))
    (REPORT_DIR / "insider_backtest.json").write_text(json.dumps(slim, separators=(",", ":")))
    BUNDLED.write_text(json.dumps(slim, separators=(",", ":")))
    DOC.write_text(write_markdown(slim))
    return report


def write_markdown(r: dict) -> str:
    c = r["coverage"]

    def pf(x):
        p = x.get("portfolio") or {}
        if not p:
            return "—"
        s, m = p["strategy"], p["spy"]
        return f"{s['cagr_pct']:+.1f}% vs {m['cagr_pct']:+.1f}% / {s['max_drawdown_pct']:.0f}%"

    def ev(x, h="h126"):
        e = (x.get("events") or {}).get(h)
        return "—" if not e else f"{e['avg_excess_pct']:+.1f}% (beat {e['beat_market_pct']:.0f}%, t {e['t_stat']})"

    out = ["# Copying insider purchases", "",
           "Generated by `python -m stockanalysis.validation.insider_history run`. Method and biases: see the module docstring.", "",
           f"Data: {c['purchases']:,} open-market purchases in {c['events']:,} filing events ({c['symbols']:,} tickers), "
           f"{c['first']} to {c['last']}. Yahoo had prices for {c['events_with_prices']:,} events "
           f"({c['symbols_with_prices']:,} tickers); the rest are mostly delisted companies, which flatters the results. "
           f"Reported purchase prices matched Yahoo's within ±50% for {c['price_match_pct']}% of events "
           "(later splits and dividends explain most of the rest).", "",
           "| Variant | Stocks | 2006–2015: copy vs S&P 500 per year / worst drop | 6-month return over the S&P 500 per event | "
           "2016–today: copy vs S&P 500 / worst drop | 6-month excess per event |", "| --- | --- | --- | --- | --- | --- |"]
    for k, x in r["results"].items():
        mark = " **(pick)**" if k == r["pick"] else ""
        out.append(f"| {x['label']}{mark} | {x['universe']} | {pf(x['first'])} | {ev(x['first'])} | {pf(x['second'])} | {ev(x['second'])} |")
    pt = r["pick_test"]
    out += ["", f"**Pick (fixed rule: best 2006–2015 tradeable variant): {r['results'][r['pick']]['label']}.** "
            f"It beat the S&P 500 by {pt['excess_cagr_first']:+.1f} points a year in 2006–2015 and by "
            f"{pt['excess_cagr_second']:+.1f} points a year in 2016–today.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "download":
        print(download(os.environ.get("SEC_CONTACT", "")))
    else:
        run()
