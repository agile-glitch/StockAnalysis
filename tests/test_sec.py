import urllib.error
from datetime import date

import pytest

from stockanalysis import sec

from .sec_fakes import FakeEdgar, fixture


def test_contact_validation():
    assert sec.valid_contact("Jane Doe jane@example.com")
    assert sec.valid_contact("Acme Research admin@acme.co")
    assert not sec.valid_contact("jane@example.com")      # needs a name too
    assert not sec.valid_contact("Jane Doe")               # needs an email
    assert not sec.valid_contact("")
    assert not sec.valid_contact(None)


def test_parse_purchase_filing():
    text = fixture("form4_buy.txt")
    assert sec.acceptance_time(text) == "2026-11-20T16:35:12"
    doc = sec.parse_form4(sec.extract_xml(text))
    assert doc["issuer"] == {"cik": "111111", "name": "Acme Robotics, Inc.", "symbol": "ACME"}
    owner = doc["owners"][0]
    assert owner["cik"] == "2222222" and owner["name"] == "RIVERA ANA M"
    assert owner["is_director"] and owner["is_officer"] and owner["role"] == "Chief Executive Officer"
    assert not doc["plan_10b5_1"]
    stock = [t for t in doc["transactions"] if not t["derivative"]]
    assert [t["code"] for t in stock] == ["P", "P"]
    first = stock[0]
    assert first["shares"] == 10000 and first["price"] == 50.0 and first["value"] == 500000.0
    assert first["acquired"] and first["direct"] and first["shares_after"] == 60000
    assert first["date"] == "2026-11-18" and "weighted average" in first["footnote"]
    option = next(t for t in doc["transactions"] if t["derivative"])
    assert option["code"] == "A" and option["label"] == "Grant or award from the company"


def test_parse_sale_under_10b5_1_plan_from_footnote_and_namespaces():
    doc = sec.parse_form4(fixture("form4_sale_plan.xml"))
    sale, withheld = doc["transactions"]
    assert sale["code"] == "S" and sale["shares"] == 40000 and not sale["acquired"]
    assert sale["plan_10b5_1"] and not sale["direct"]
    assert withheld["code"] == "F" and not withheld["plan_10b5_1"]
    assert doc["owners"][0]["is_officer"] and not doc["owners"][0]["is_director"]


def test_plan_checkbox_marks_every_transaction():
    xml = fixture("form4_sale_plan.xml").replace("<periodOfReport>", "<aff10b5One>1</aff10b5One><periodOfReport>")
    assert all(t["plan_10b5_1"] for t in sec.parse_form4(xml)["transactions"])


def test_bad_documents_raise_sec_error():
    with pytest.raises(sec.SecError):
        sec.extract_xml("<html>nothing here</html>")
    with pytest.raises(sec.SecError):
        sec.parse_form4("<ownershipDocument><unclosed>")
    with pytest.raises(sec.SecError):
        sec.parse_form4("<somethingElse/>")


def test_feed_keeps_form4_only_and_merges_issuer_and_owner():
    items = sec.parse_current_feed(fixture("current_form4.atom"))
    assert [i["accession"] for i in items] == ["0000950170-26-001234", "0000444444-26-000009"]
    first = items[0]
    assert first["issuer_cik"] == "111111" and first["issuer_name"] == "Acme Robotics, Inc."
    assert first["owner_names"] == ["RIVERA ANA M"] and first["owner_cik"] == "2222222"
    assert items[1]["form"] == "4/A"


def test_routine_rule():
    months = {(2025, 11), (2024, 11), (2023, 11)}
    assert sec.is_routine(months, date(2026, 11, 18))
    assert not sec.is_routine({(2025, 11), (2023, 11)}, date(2026, 11, 18))
    assert not sec.is_routine({(2025, 10), (2024, 11), (2023, 11)}, date(2026, 11, 18))


def test_client_requires_contact_and_sends_it():
    fake = FakeEdgar()
    client = sec.SecClient(lambda: "", opener=fake, per_second=1000)
    assert not client.configured
    with pytest.raises(sec.SecError, match="name and email"):
        client.ticker_map()
    assert fake.requests == []

    client = sec.SecClient(lambda: "Jane Doe jane@example.com", opener=fake, per_second=1000)
    assert client.cik_for("acme") == "111111" and client.cik_for("NOPE") is None
    agent = fake.requests[0].get_header("User-agent")
    assert agent.startswith("StockAnalysis/") and agent.endswith("Jane Doe jane@example.com")


def test_client_explains_a_refusal():
    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
    client = sec.SecClient(lambda: "Jane Doe jane@example.com", opener=refuse, per_second=1000)
    with pytest.raises(sec.SecError, match="refused"):
        client.ticker_map()


def test_fetch_and_recent_form4s():
    fake = FakeEdgar()
    fake.add_filing("111111", "0000950170-26-001234", fixture("form4_buy.txt"))
    fake.add_submissions("111111", [
        {"accession": "0000950170-26-001234", "filed": "2026-11-20"},
        {"accession": "0000950170-26-000001", "filed": "2026-11-20", "form": "8-K"},
        {"accession": "0000950170-25-000777", "filed": "2025-01-05"},
    ])
    client = sec.SecClient(lambda: "Jane Doe jane@example.com", opener=fake, per_second=1000)
    recent = client.recent_form4s("111111", date(2026, 1, 1))
    assert [f["accession"] for f in recent] == ["0000950170-26-001234"]
    doc = client.fetch_form4("111111", "0000950170-26-001234")
    assert doc["accepted"] == "2026-11-20T16:35:12"
    assert doc["url"].endswith("/111111/000095017026001234/0000950170-26-001234-index.htm")
