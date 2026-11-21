import time

from stockanalysis import sentiment as s


def test_scores_tone_and_handles_negation():
    assert s.score_text("Acme beats estimates and raises guidance") == 1.0
    assert s.score_text("Acme shares plunge after downgrade") == -1.0
    assert s.score_text("Acme to present at conference") is None
    assert s.score_text("Acme does not miss a beat on record sales") > 0
    assert s.label(0.6) == "positive" and s.label(-0.6) == "negative" and s.label(None) == "neutral"


def test_relevance_filter():
    assert s.is_about("Apple unveils new iPhone", "AAPL", "Apple Inc.")
    assert s.is_about("Why AAPL stock dropped", "AAPL", "Apple Inc.")
    assert not s.is_about("3 ETFs to buy for retirement", "AAPL", "Apple Inc.")
    assert not s.is_about("SNAPPLE launches new flavour", "AAPL", "Apple Inc.")


def test_aggregate_weights_recent_headlines_more_and_drops_old_ones():
    now = time.time()
    items = [
        {"sentiment": 1.0, "published": now - 3600},
        {"sentiment": -1.0, "published": now - 5 * 86400},
        {"sentiment": -1.0, "published": now - 30 * 86400},  # too old
        {"sentiment": None, "published": now},                # no signal words
    ]
    out = s.aggregate(items, now=now)
    assert out["count"] == 2 and out["positive"] == 1 and out["negative"] == 1
    assert out["score"] > 0.5
