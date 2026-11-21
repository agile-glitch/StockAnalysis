import io
import zipfile

import numpy as np
import pandas as pd

from stockanalysis.validation.insider_history import (attach_prices, clean_symbol, event_stats, events,
                                                      market_relative, parse_zip, portfolio, quarters)

from .conftest import make_history


def tsv(rows, cols):
    return "\t".join(cols) + "\n" + "\n".join("\t".join(str(v) for v in r) for r in rows) + "\n"


def fake_zip():
    sub_cols = ["ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
                "ISSUERTRADINGSYMBOL"]
    own_cols = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]
    tr_cols = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
               "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", tsv([
            ["A1", "05-MAR-2024", "04-MAR-2024", "4", "111", "Acme Corp", "acme"],
            ["A2", "06-MAR-2024", "05-MAR-2024", "4", "111", "Acme Corp", "ACME"],
            ["A3", "06-MAR-2024", "05-MAR-2024", "3", "222", "Other Inc", "OTH"],
        ], sub_cols))
        z.writestr("REPORTINGOWNER.tsv", tsv([
            ["A1", "9001", "Doe Jane", "Officer", "Chief Executive Officer"],
            ["A2", "9002", "Roe Rick", "Director", ""],
            ["A3", "9003", "X", "Director", ""],
        ], own_cols))
        z.writestr("NONDERIV_TRANS.tsv", tsv([
            ["A1", "1", "04-MAR-2024", "P", "10000", "20.5", "A", "50000"],
            ["A1", "2", "04-MAR-2024", "S", "500", "21", "D", "49500"],      # a sale: dropped
            ["A2", "3", "05-MAR-2024", "P", "1000", "21", "A", "9000"],
            ["A2", "4", "05-MAR-2024", "M", "1000", "5", "A", "10000"],      # option exercise: dropped
            ["A3", "5", "05-MAR-2024", "P", "1000", "10", "A", "1000"],      # Form 3: dropped
        ], tr_cols))
    return buf.getvalue()


def test_parse_zip_keeps_form4_open_market_purchases():
    df = parse_zip(fake_zip())
    assert sorted(df["accession"]) == ["A1", "A2"]
    a1 = df[df["accession"] == "A1"].iloc[0]
    assert a1["value"] == 205000 and a1["filed"] == pd.Timestamp("2024-03-05")
    assert a1["title"] == "Chief Executive Officer" and a1["owner_cik"] == "9001"


def test_events_flags_cluster_officer_and_size():
    ev = events(parse_zip(fake_zip()))
    assert list(ev["symbol"]) == ["ACME", "ACME"]
    first, second = ev.iloc[0], ev.iloc[1]
    assert first["officer"] and first["big"] and not first["cluster"]
    assert second["cluster"] and not second["big"]                 # second insider within 30 days


def test_clean_symbol():
    assert clean_symbol("brk.b") == "BRK-B"
    assert clean_symbol(" NYSE:XOM ") == "XOM"
    assert clean_symbol("NONE ") == "NONE"     # looks like a ticker; Yahoo will simply have no prices
    assert clean_symbol("12345") is None and clean_symbol(None) is None


def test_quarters_stop_at_today():
    from datetime import date
    qs = list(quarters(date(2007, 5, 1)))
    assert qs[0] == (2006, 1) and qs[-1] == (2007, 2) and len(qs) == 6


def test_backtest_pipeline_on_fake_prices():
    df = make_history(n=700)
    spy = make_history(n=700, daily=0.0003, seed=5)
    ev = pd.DataFrame({"symbol": ["ACME"] * 3, "filed": [df.index[300], df.index[400], df.index[500]],
                       "price": [float(df["close"].iloc[300])] * 3, "value": [2e5] * 3})
    evp = market_relative(attach_prices(ev, {"ACME": df}), spy)
    assert len(evp) == 3 and (evp["entry"] == [df.index[301], df.index[401], df.index[501]]).all()
    assert np.isclose(evp["ret_21"].iloc[0], df["close"].iloc[321] / df["open"].iloc[301] - 1)
    stats = event_stats(pd.concat([evp] * 10, ignore_index=True))
    assert stats["events"] == 30 and "h21" in stats
    cash = pd.Series(0.0, index=spy.index)
    pf = portfolio(evp, {"ACME": df}, spy, cash, str(df.index[250].date()), None)
    assert pf["strategy"]["cagr_pct"] is not None and pf["avg_positions"] > 0
