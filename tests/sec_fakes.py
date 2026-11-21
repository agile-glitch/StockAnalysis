"""An in-memory stand-in for EDGAR, so SEC tests run offline."""

import io
import json
import urllib.error
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def wrap_txt(xml: str, accepted: str = "20261119170000") -> str:
    return (f"<SEC-DOCUMENT>\n<SEC-HEADER>\n<ACCEPTANCE-DATETIME>{accepted}\n</SEC-HEADER>\n"
            f"<DOCUMENT>\n<TYPE>4\n<TEXT>\n<XML>\n{xml}\n</XML>\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>")


def form4_xml(*, owner_cik="5555555", owner="DOE JANE", issuer_cik="111111", symbol="ACME", code="P",
              day="2026-11-18", shares=1000, price=50.0, after=11000, officer=True, director=False,
              title="Chief Operating Officer", plan=False) -> str:
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <aff10b5One>{1 if plan else 0}</aff10b5One>
  <issuer><issuerCik>{int(issuer_cik):010d}</issuerCik><issuerName>Acme Robotics, Inc.</issuerName>
    <issuerTradingSymbol>{symbol}</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>{int(owner_cik):010d}</rptOwnerCik><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>{int(director)}</isDirector><isOfficer>{int(officer)}</isOfficer>
      <officerTitle>{title}</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <securityTitle><value>Common Stock</value></securityTitle>
    <transactionDate><value>{day}</value></transactionDate>
    <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>{shares}</value></transactionShares>
      <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
      <transactionAcquiredDisposedCode><value>{'A' if code == 'P' else 'D'}</value></transactionAcquiredDisposedCode></transactionAmounts>
    <postTransactionAmounts><sharesOwnedFollowingTransaction><value>{after}</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""


def submissions(filings: list[dict]) -> str:
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "primaryDocument"]
    recent = {k: [] for k in keys}
    for f in filings:
        recent["accessionNumber"].append(f["accession"])
        recent["filingDate"].append(f["filed"])
        recent["reportDate"].append(f.get("report", f["filed"]))
        recent["acceptanceDateTime"].append(f["filed"] + "T21:00:00.000Z")
        recent["form"].append(f.get("form", "4"))
        recent["primaryDocument"].append("xslF345X06/form4.xml")
    return json.dumps({"cik": "0", "name": "x", "filings": {"recent": recent, "files": []}})


class _Response(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeEdgar:
    """Callable used as SecClient's `opener`. Serves registered URLs."""

    def __init__(self):
        self.routes: dict[str, str] = {}
        self.requests: list = []
        self.add("https://www.sec.gov/files/company_tickers.json", json.dumps({
            "0": {"cik_str": 111111, "ticker": "ACME", "title": "Acme Robotics, Inc."},
            "1": {"cik_str": 444444, "ticker": "OTHR", "title": "Other Co"},
        }))

    def add(self, url: str, body: str):
        self.routes[url] = body

    def add_filing(self, cik: str, accession: str, txt: str):
        self.add(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}.txt", txt)

    def add_submissions(self, cik: str, filings: list[dict]):
        self.add(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", submissions(filings))

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        url = request.full_url
        if url.startswith("https://www.sec.gov/cgi-bin/browse-edgar") and "start=0&" not in url:
            body = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'  # later pages: empty
        elif url in self.routes:
            body = self.routes[url]
        elif url.startswith("https://www.sec.gov/cgi-bin/browse-edgar"):
            body = self.routes.get("feed", '<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Response(body.encode("utf-8"))
