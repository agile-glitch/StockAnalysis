from datetime import date

import pytest

from stockanalysis.db import Database
from stockanalysis.engine import Engine
from stockanalysis.insiders import InsiderService, display_name, short_role, summarize_filing
from stockanalysis.providers import CachedProvider
from stockanalysis.providers.demo import DemoProvider
from stockanalysis.sec import SecClient

from .sec_fakes import FakeEdgar, fixture, form4_xml, wrap_txt

TODAY = date(2026, 11, 21)
BUY = "0000950170-26-001234"     # CEO buys $1.02M (fixture)
SALE = "0000950170-26-001200"    # CFO sells $2.05M under a 10b5-1 plan


@pytest.fixture
def edgar():
    fake = FakeEdgar()
    fake.add_filing("111111", BUY, fixture("form4_buy.txt"))
    fake.add_filing("111111", SALE, wrap_txt(fixture("form4_sale_plan.xml")))
    fake.add_submissions("111111", [
        {"accession": BUY, "filed": "2026-11-20", "report": "2026-11-18"},
        {"accession": SALE, "filed": "2026-11-19", "report": "2026-11-17"},
    ])
    fake.add_submissions("2222222", [{"accession": BUY, "filed": "2026-11-20", "report": "2026-11-18"}])
    return fake


@pytest.fixture
def db():
    database = Database(":memory:", seed_watchlist=False)
    database.update_settings({"sec_contact": "Jane Doe jane@example.com"})
    yield database
    database.close()


def service(db, edgar):
    client = SecClient(lambda: db.get_settings()["sec_contact"], opener=edgar, per_second=1000)
    return InsiderService(db, client, today_fn=lambda: TODAY)


def test_names_and_roles():
    assert display_name("COOK TIMOTHY D") == "Timothy D Cook"
    assert display_name("SMITH JOHN A JR") == "John A Smith Jr"
    assert display_name("BERKSHIRE HATHAWAY INC") == "Berkshire Hathaway Inc"
    assert display_name("RIVERA ANA M & CHEN DAVID") == "Ana M Rivera & David Chen"
    assert short_role("Chief Executive Officer") == "CEO"
    assert short_role("Director") == "Director"
    assert short_role(None) == "Insider"


def test_not_configured_does_nothing(edgar):
    db = Database(":memory:", seed_watchlist=False)
    db.add_symbol("ACME")
    status = service(db, edgar).poll()
    assert status["configured"] is False and edgar.requests == []


def test_watchlist_sync_alerts_on_purchase_and_skips_planned_sale(db, edgar):
    db.add_symbol("ACME")
    svc = service(db, edgar)
    status = svc.poll()
    assert status["last_error"] is None and status["filings_seen"] == 2
    notes = db.notifications()
    assert [n["kind"] for n in notes] == ["insider_buy"]   # sales alerts are off by default
    buy = notes[0]
    assert buy["title"] == "ACME: CEO bought $1.0M" and buy["tone"] == "bullish"
    assert "Ana M Rivera (Chief Executive Officer) bought 20,000 shares at $51.00" in buy["body"]
    assert "filed Nov 20, 2 days later" in buy["body"]
    assert "Raises their holding by 40% to 70,000 shares" in buy["body"]
    assert "Not a pre-planned" in buy["body"] and "Not a routine pattern" in buy["body"]
    assert buy["link"].endswith(f"{BUY}-index.htm")
    # A second poll finds nothing new and repeats nothing.
    svc.poll()
    assert len(db.notifications()) == 1


def test_sales_alert_when_enabled_and_large(db, edgar):
    db.add_symbol("ACME")
    db.update_settings({"insider_alert_sells": True, "insider_sell_min_value": 1_000_000})
    service(db, edgar).poll()
    sale = next(n for n in db.notifications() if n["kind"] == "insider_sell")
    assert sale["title"] == "ACME: CFO sold $2.0M" and sale["tone"] == "bearish"
    assert "Rule 10b5-1 plan" in sale["body"]
    db.clear_notifications()
    db.update_settings({"insider_sell_min_value": 5_000_000})
    db.set_state("sec_synced:ACME", None)
    with db._lock:
        db._conn.execute("DELETE FROM sec_filings")
        db._conn.execute("DELETE FROM sec_trades")
    service(db, edgar).poll()
    assert not [n for n in db.notifications() if n["kind"] == "insider_sell"]


def test_routine_insider_is_labelled(db, edgar):
    history = []
    for year in (2023, 2024, 2025):
        acc = f"0000950170-{year % 100}-00{year}"
        edgar.add_filing("2222222", acc, wrap_txt(form4_xml(owner_cik="2222222", owner="RIVERA ANA M",
                                                            day=f"{year}-11-15")))
        history.append({"accession": acc, "filed": f"{year}-11-17", "report": f"{year}-11-15"})
    edgar.add_submissions("2222222", [{"accession": BUY, "filed": "2026-11-20", "report": "2026-11-18"}] + history)
    db.add_symbol("ACME")
    service(db, edgar).poll()
    buy = next(n for n in db.notifications() if n["kind"] == "insider_buy")
    assert "Routine: they traded in this same month" in buy["body"]
    stored = [r for r in db.sec_trades(symbol="ACME", codes=("P",)) if r["accession"] == BUY]
    assert stored and all(r["routine"] == "routine" for r in stored)


def test_market_scan_alerts_on_big_officer_buys_off_the_watchlist(db, edgar):
    edgar.add("feed", fixture("current_form4.atom"))
    edgar.add_filing("444444", "0000444444-26-000009", wrap_txt(form4_xml(
        issuer_cik="444444", symbol="OTHR", owner="SMALL BUYER", shares=100, price=10.0, after=1100)))
    svc = service(db, edgar)
    svc.poll()
    notes = db.notifications()
    assert [n["kind"] for n in notes] == ["insider_buy_market"]   # the $1,000 buy is below the minimum
    assert notes[0]["title"] == "ACME: CEO bought $1.0M" and "not on your watchlist" in notes[0]["body"]
    market = svc.market_buys()
    assert {m["symbol"] for m in market} == {"ACME", "OTHR"}
    acme = next(m for m in market if m["symbol"] == "ACME")
    assert acme["shares_after"] == 70000 and round(acme["stake_change_pct"]) == 40
    assert market[0]["owner_display"]
    # Next poll stops at the accession numbers it has already seen.
    before = len(edgar.requests)
    svc.poll()
    assert len(edgar.requests) - before <= 2 and len(db.notifications()) == 1


def test_market_alerts_can_be_switched_off_or_raised(db, edgar):
    edgar.add("feed", fixture("current_form4.atom"))
    db.update_settings({"insider_market_alerts": False})
    service(db, edgar).poll()
    assert db.notifications() == [] and not any("browse-edgar" in r.full_url for r in edgar.requests)
    db.update_settings({"insider_market_alerts": True, "insider_market_min_value": 5_000_000})
    service(db, edgar).poll()
    assert db.notifications() == []


def test_cluster_buying_alert(db, edgar):
    accs = []
    for i, name in enumerate(["DOE JANE", "ROE RICHARD", "POE EDGAR"]):
        acc = f"0000950170-26-00900{i}"
        edgar.add_filing("111111", acc, wrap_txt(form4_xml(owner_cik=str(7000000 + i), owner=name,
                                                           day=f"2026-11-1{i}")))
        edgar.add_submissions(str(7000000 + i), [])
        accs.append({"accession": acc, "filed": f"2026-11-1{i + 2}", "report": f"2026-11-1{i}"})
    edgar.add_submissions("111111", accs)
    db.add_symbol("ACME")
    service(db, edgar).poll()
    kinds = [n["kind"] for n in db.notifications()]
    assert kinds.count("insider_buy") == 3 and kinds.count("insider_cluster") == 1
    cluster = next(n for n in db.notifications() if n["kind"] == "insider_cluster")
    assert "3 different insiders bought $150.0K" in cluster["body"]


def test_engine_uses_sec_trades_once_synced(db, edgar):
    db.add_symbol("ACME")
    svc = service(db, edgar)
    provider = CachedProvider(DemoProvider(today=TODAY))
    engine = Engine(db, provider, today_fn=lambda: TODAY, insiders=svc)
    before = engine.analyze("ACME")
    assert before["insiders"]["source"] == "yahoo"
    svc.poll()
    after = engine.analyze("ACME")
    assert after["insiders"]["source"] == "sec"
    trades = after["insiders"]["trades"]
    assert {t["code"] for t in trades} == {"P", "S", "F"}
    sale = next(t for t in trades if t["code"] == "S")
    assert sale["plan_10b5_1"] and sale["kind"] == "sell" and sale["url"]
    summary = after["insiders"]["summary"]
    assert summary["buyers"] == ["RIVERA ANA M"] and summary["sellers"] == ["CHEN DAVID"]
    signal = next(s for s in after["signals"] if s["key"] == "insiders")
    assert signal["score"] > 0
    # The engine leaves SEC-sourced insider alerts to the watcher: no duplicates.
    db.clear_notifications()
    engine.refresh_symbol("ACME")
    assert not [n for n in db.notifications() if n["kind"].startswith("insider")]


def test_planned_and_routine_buys_count_for_less():
    from stockanalysis.strategies import insider_signal
    def buy(name, **extra):
        return {"date": "2026-11-10", "kind": "buy", "insider": name, "value": 1e5, **extra}
    fresh = insider_signal([buy("A")], TODAY).score
    planned = insider_signal([buy("A", plan_10b5_1=True)], TODAY).score
    routine = insider_signal([buy("A", routine="routine")], TODAY).score
    assert planned == 0 and 0 < routine < fresh


def test_summarize_filing_ignores_derivatives():
    rows = [
        {"code": "P", "derivative": 0, "shares": 100, "value": 1000.0, "shares_after": 600, "plan_10b5_1": 0,
         "trade_date": "2026-11-18", "symbol": "X", "issuer_cik": "1", "issuer_name": "X", "owner_cik": "2",
         "owner_name": "A", "role": "Director", "is_officer": 0, "is_director": 1, "is_ten_pct": 0,
         "filed": "2026-11-19", "accepted": None, "accession": "a", "url": None},
        {"code": "P", "derivative": 1, "shares": 999, "value": 9e9, "shares_after": 1, "plan_10b5_1": 0,
         "trade_date": "2026-11-18"},
    ]
    t = summarize_filing(rows, "P")
    assert t["shares"] == 100 and t["value"] == 1000.0 and t["stake_change_pct"] == 20.0
    assert summarize_filing(rows, "S") is None


def test_sync_refreshes_the_stock_analysis(db, edgar):
    db.add_symbol("ACME")
    svc = service(db, edgar)
    updated = []
    svc.on_update = updated.append
    svc.poll()
    svc.poll()
    assert updated == ["ACME"]   # once for the first sync; nothing new the second time


def test_small_market_clusters_are_skipped(db, edgar):
    accs = []
    for i, name in enumerate(["DOE JANE", "ROE RICHARD", "POE EDGAR"]):
        acc = f"0000950170-26-00900{i}"
        edgar.add_filing("111111", acc, wrap_txt(form4_xml(owner_cik=str(7000000 + i), owner=name, day=f"2026-11-1{i}")))
        edgar.add_submissions(str(7000000 + i), [])
        accs.append(acc)
    feed = "".join(
        f'<entry><title>4 - Acme Robotics, Inc. (0000111111) (Issuer)</title><updated>2026-11-20T10:00:00-05:00</updated>'
        f'<category term="4"/><id>urn:tag:sec.gov,2008:accession-number={a}</id></entry>' for a in accs)
    edgar.add("feed", f'<feed xmlns="http://www.w3.org/2005/Atom">{feed}</feed>')
    service(db, edgar).poll()   # three $50K buys at a company not on the watchlist
    assert db.notifications() == []
