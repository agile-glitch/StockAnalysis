"""SEC EDGAR client for insider (Form 4) filings.

Insiders (officers, directors and 10% owners) must report a trade on Form 4
within two business days. EDGAR publishes each filing the moment it is
accepted, for free, and every paid insider-alert service is built on it.

Sources used here:

  www.sec.gov/cgi-bin/browse-edgar?action=getcurrent   live feed of new filings (Atom)
  data.sec.gov/submissions/CIK##########.json         every filing by one company or person
  www.sec.gov/Archives/edgar/data/<cik>/<acc>/<acc>.txt  the filing itself (the Form 4 XML)
  www.sec.gov/files/company_tickers.json               ticker -> CIK map

EDGAR's fair-access policy requires automated tools to send a User-Agent with
a contact name and email, and to stay under 10 requests per second. Requests
without a declared contact are refused, so nothing here runs until the user
enters one in Settings. The contact is only ever sent to sec.gov.
"""

from __future__ import annotations

import gzip
import json
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime

from . import __version__

WWW = "https://www.sec.gov"
DATA = "https://data.sec.gov"
MAX_REQUESTS_PER_SECOND = 5  # SEC allows 10; stay well under it
FORM4_TYPES = {"4", "4/A"}

# Form 4 transaction codes (SEC "General Transaction Codes").
CODE_LABELS = {
    "P": "Open-market purchase",
    "S": "Open-market sale",
    "A": "Grant or award from the company",
    "D": "Sold or returned to the company",
    "F": "Shares withheld to pay tax or exercise price",
    "I": "Discretionary transaction",
    "M": "Option exercise or conversion",
    "C": "Conversion of a derivative",
    "E": "Expiration of a short derivative position",
    "H": "Expiration of a long derivative position",
    "O": "Exercise of an out-of-the-money derivative",
    "X": "Exercise of an in-the-money derivative",
    "G": "Gift",
    "L": "Small acquisition",
    "W": "Acquired or disposed of by will or inheritance",
    "Z": "Deposit into or withdrawal from a voting trust",
    "J": "Other acquisition or disposition",
    "K": "Equity swap or similar",
    "U": "Disposition in a change-of-control transaction",
    "V": "Voluntarily reported early",
}

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")


class SecError(Exception):
    """EDGAR could not answer (not configured, blocked, network, bad data)."""


def valid_contact(contact: str | None) -> bool:
    """SEC asks for a name and an email address, e.g. 'Jane Doe jane@example.com'."""
    contact = (contact or "").strip()
    match = _EMAIL.search(contact)
    return bool(match) and len(contact.replace(match.group(0), "").strip()) >= 2


def _text(node, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path)
    if found is None:
        return None
    value = (found.text or "").strip()
    return value or None


def _num(value) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _flag(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _strip_namespaces(root):
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    return root


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def extract_xml(document: str) -> str:
    """Pull the ownershipDocument XML out of a full EDGAR submission (.txt)."""
    start = document.find("<ownershipDocument")
    end = document.rfind("</ownershipDocument>")
    if start < 0 or end < 0:
        raise SecError("No Form 4 XML found in the filing")
    return document[start:end + len("</ownershipDocument>")]


def acceptance_time(document: str) -> str | None:
    """ISO timestamp (US Eastern, as EDGAR reports it) from the submission header."""
    match = re.search(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", document)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").isoformat()


def describe_role(owner: dict) -> str:
    if owner.get("officer_title"):
        return owner["officer_title"]
    roles = []
    if owner.get("is_director"):
        roles.append("Director")
    if owner.get("is_officer"):
        roles.append("Officer")
    if owner.get("is_ten_pct"):
        roles.append("10% owner")
    return ", ".join(roles) or "Insider"


def parse_form4(xml_text: str) -> dict:
    """Parse a Form 4 (or 4/A) ownershipDocument into plain dicts.

    Returns {document_type, period, issuer: {cik, name, symbol}, owners: [...],
    plan_10b5_1, transactions: [...]}. Each transaction has code, label, shares,
    price, value, acquired (bool), shares_after, direct, derivative, date,
    plan_10b5_1 and the footnote text attached to it.
    """
    try:
        root = _strip_namespaces(ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text))
    except ET.ParseError as exc:
        raise SecError(f"Could not read the Form 4 XML: {exc}") from exc
    if root.tag != "ownershipDocument":
        raise SecError("Not a Form 3/4/5 ownership document")

    footnotes = {fn.get("id"): " ".join((fn.text or "").split()) for fn in root.iter("footnote")}
    plan_box = root.find("aff10b5One")
    plan_checked = _flag(plan_box.text) if plan_box is not None else False

    issuer = root.find("issuer")
    issuer_info = {
        "cik": (_text(issuer, "issuerCik") or "").lstrip("0") or None,
        "name": _text(issuer, "issuerName"),
        "symbol": (_text(issuer, "issuerTradingSymbol") or "").upper() or None,
    }

    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        owner = {
            "cik": (_text(ro, "reportingOwnerId/rptOwnerCik") or "").lstrip("0") or None,
            "name": _text(ro, "reportingOwnerId/rptOwnerName") or "Unknown",
            "is_director": _flag(_text(rel, "isDirector")),
            "is_officer": _flag(_text(rel, "isOfficer")),
            "is_ten_pct": _flag(_text(rel, "isTenPercentOwner")),
            "is_other": _flag(_text(rel, "isOther")),
            "officer_title": _text(rel, "officerTitle"),
        }
        owner["role"] = describe_role(owner)
        owners.append(owner)

    transactions = []
    for table, tag, derivative in (("nonDerivativeTable", "nonDerivativeTransaction", False),
                                   ("derivativeTable", "derivativeTransaction", True)):
        for tx in root.findall(f"{table}/{tag}"):
            code = _text(tx, "transactionCoding/transactionCode") or "?"
            shares = _num(_text(tx, "transactionAmounts/transactionShares/value"))
            price = _num(_text(tx, "transactionAmounts/transactionPricePerShare/value"))
            notes = [footnotes.get(ref.get("id"), "") for ref in tx.iter("footnoteId")]
            note_text = " ".join(n for n in notes if n)
            transactions.append({
                "security": _text(tx, "securityTitle/value"),
                "date": (_text(tx, "transactionDate/value") or "")[:10] or None,
                "code": code,
                "label": CODE_LABELS.get(code, "Other"),
                "shares": shares,
                "price": price,
                "value": round(shares * price, 2) if shares is not None and price is not None else None,
                "acquired": (_text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value") or "") == "A",
                "shares_after": _num(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                "direct": (_text(tx, "ownershipNature/directOrIndirectOwnership/value") or "D") == "D",
                "derivative": derivative,
                # The checkbox exists since 2023; older filings only say so in a footnote.
                "plan_10b5_1": plan_checked or "10b5-1" in note_text,
                "footnote": note_text[:400] or None,
            })

    return {
        "document_type": _text(root, "documentType"),
        "period": _text(root, "periodOfReport"),
        "issuer": issuer_info,
        "owners": owners,
        "plan_10b5_1": plan_checked,
        "transactions": transactions,
    }


def parse_current_feed(atom_text: str) -> list[dict]:
    """New filings from EDGAR's 'latest filings' Atom feed.

    Each filing is listed once per filer (the company as Issuer, the insider as
    Reporting), so entries are merged by accession number.
    """
    try:
        root = _strip_namespaces(ET.fromstring(atom_text.encode("utf-8")))
    except ET.ParseError as exc:
        raise SecError(f"Could not read the EDGAR feed: {exc}") from exc
    merged: dict[str, dict] = {}
    for entry in root.findall("entry"):
        category = entry.find("category")
        form = (category.get("term") if category is not None else "") or ""
        title = _text(entry, "title") or ""
        if not form:
            form = title.split(" - ", 1)[0].strip()
        if form not in FORM4_TYPES:
            continue
        raw = " ".join(filter(None, [_text(entry, "id"), _text(entry, "summary"), title]))
        link = entry.find("link")
        href = link.get("href") if link is not None else ""
        match = _ACCESSION.search(raw) or _ACCESSION.search(href or "")
        if not match:
            continue
        accession = match.group(0)
        item = merged.setdefault(accession, {"accession": accession, "form": form, "issuer_cik": None,
                                             "issuer_name": None, "owner_names": [], "updated": None})
        who = re.match(r".+? - (.+?) \((\d+)\) \((Issuer|Reporting)\)", title)
        if who:
            name, cik, role = who.group(1), who.group(2).lstrip("0"), who.group(3)
            if role == "Issuer":
                item["issuer_cik"], item["issuer_name"] = cik, name
            else:
                item["owner_names"].append(name)
                item.setdefault("owner_cik", cik)
        item["updated"] = item["updated"] or _text(entry, "updated")
    return list(merged.values())


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


class SecClient:
    """Thin EDGAR client with the SEC's required User-Agent and rate limit."""

    def __init__(self, contact_fn, opener=None, per_second: float = MAX_REQUESTS_PER_SECOND):
        self._contact_fn = contact_fn
        self._opener = opener or urllib.request.urlopen
        self._limiter = _RateLimiter(per_second)
        self._tickers: tuple[float, dict] | None = None
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return valid_contact(self._contact_fn())

    def user_agent(self) -> str:
        contact = (self._contact_fn() or "").strip()
        if not valid_contact(contact):
            raise SecError("Add your name and email under Settings > Insider alerts. "
                           "The SEC refuses automated requests without a contact.")
        return f"StockAnalysis/{__version__} {contact}"

    def get(self, url: str, ttl: float = 0) -> str:
        if ttl:
            with self._lock:
                hit = self._cache.get(url)
                if hit and time.time() - hit[0] < ttl:
                    return hit[1]
        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent(),
            "Accept-Encoding": "gzip, deflate",
        })
        for attempt in range(3):
            self._limiter.wait()
            try:
                with self._opener(request, timeout=20) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    text = body.decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 403:
                    raise SecError("The SEC refused the request (HTTP 403). Check the contact under "
                                   "Settings > Insider alerts; it must include a real email address.") from exc
                if exc.code == 404:
                    raise SecError(f"Not found on EDGAR: {url}") from exc
                if exc.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise SecError(f"EDGAR error {exc.code} for {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise SecError(f"Could not reach EDGAR: {exc}") from exc
        if "Undeclared Automated Tool" in text[:2000]:
            raise SecError("The SEC flagged these requests as undeclared. Check the contact under "
                           "Settings > Insider alerts.")
        if ttl:
            with self._lock:
                self._cache[url] = (time.time(), text)
        return text

    # ---- lookups ----
    def ticker_map(self) -> dict[str, dict]:
        """{TICKER: {cik, name}}, refreshed daily."""
        if self._tickers and time.time() - self._tickers[0] < 86400:
            return self._tickers[1]
        raw = json.loads(self.get(f"{WWW}/files/company_tickers.json"))
        mapping = {
            row["ticker"].upper(): {"cik": str(row["cik_str"]), "name": row.get("title")}
            for row in raw.values()
        }
        self._tickers = (time.time(), mapping)
        return mapping

    def cik_for(self, symbol: str) -> str | None:
        entry = self.ticker_map().get(symbol.upper()) or self.ticker_map().get(symbol.upper().replace(".", "-"))
        return entry["cik"] if entry else None

    def submissions(self, cik: str, ttl: float = 90) -> dict:
        return json.loads(self.get(f"{DATA}/submissions/CIK{int(cik):010d}.json", ttl=ttl))

    def recent_form4s(self, cik: str, since: date, ttl: float = 90) -> list[dict]:
        """Form 4 filings for a company (or by a person) filed on or after `since`."""
        recent = self.submissions(cik, ttl=ttl)["filings"]["recent"]
        out = []
        for i, form in enumerate(recent.get("form", [])):
            if form not in FORM4_TYPES:
                continue
            filed = recent["filingDate"][i]
            if filed < since.isoformat():
                continue
            out.append({
                "accession": recent["accessionNumber"][i],
                "form": form,
                "filed": filed,
                "report_date": recent["reportDate"][i] or None,
                "accepted": recent["acceptanceDateTime"][i] or None,
            })
        return out

    def current_form4s(self, pages: int = 5, stop_at: set[str] | None = None) -> list[dict]:
        """Newest Form 4 filings across all companies, newest first. Stops paging
        once it reaches an accession number already seen."""
        out: list[dict] = []
        seen: set[str] = set()
        for page in range(pages):
            url = (f"{WWW}/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb="
                   f"&owner=include&start={page * 100}&count=100&output=atom")
            items = parse_current_feed(self.get(url))
            fresh = [i for i in items if i["accession"] not in seen]
            seen.update(i["accession"] for i in fresh)
            out.extend(fresh)
            if not items or (stop_at and any(i["accession"] in stop_at for i in items)):
                break
        return out

    def filing_url(self, cik: str, accession: str) -> str:
        return f"{WWW}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"

    def fetch_form4(self, cik: str, accession: str) -> dict:
        """Download and parse one Form 4. `cik` can be the issuer's or the owner's."""
        text = self.get(f"{WWW}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}.txt")
        parsed = parse_form4(extract_xml(text))
        parsed["accession"] = accession
        parsed["accepted"] = acceptance_time(text)
        parsed["url"] = self.filing_url(parsed["issuer"]["cik"] or cik, accession)
        return parsed


# --------------------------------------------------------------------------
# Routine vs opportunistic (Cohen, Malloy & Pomorski 2012)
# --------------------------------------------------------------------------

def is_routine(trade_months: set[tuple[int, int]], trade_date: date, years: int = 3) -> bool:
    """An insider is 'routine' if they traded in this same calendar month in
    each of the previous `years` years. Routine trades (bonus-driven, annual
    plans) carried essentially no information in Cohen, Malloy & Pomorski."""
    return all((trade_date.year - k, trade_date.month) in trade_months for k in range(1, years + 1))
