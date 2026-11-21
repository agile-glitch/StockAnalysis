from datetime import date, timedelta

import pandas as pd

from stockanalysis import strategies as st
from stockanalysis.indicators import build_frame

from .conftest import TODAY, make_history


def last_row(**kw):
    return build_frame(make_history(**kw)).iloc[-1]


def test_uptrend_scores_bullish_and_downtrend_bearish():
    up, down = last_row(daily=0.002), last_row(daily=-0.002)
    assert st.trend_signal(up).score == 1.0
    assert st.trend_signal(down).score == -1.0
    assert st.momentum_signal(up).score > 0.9
    assert st.momentum_signal(down).score < -0.9
    assert st.high52_signal(up).score > 0.5
    assert st.high52_signal(down).score < -0.9


def test_short_history_marks_signals_unavailable():
    row = build_frame(make_history(n=120)).iloc[-1]
    assert not st.trend_signal(row).available
    assert not st.momentum_signal(row).available
    assert st.trend_signal(row).points == 0


def test_strong_uptrend_is_a_buy_and_downtrend_a_sell():
    up = st.decide(st.technical_signals(last_row(daily=0.002)))
    down = st.decide(st.technical_signals(last_row(daily=-0.002)))
    assert up["action"] in ("buy", "strong_buy") and up["score"] >= st.BUY_THRESHOLD
    assert down["action"] in ("sell", "strong_sell")
    assert up["reasons"] and down["reasons"]


def test_trend_gate_blocks_buy_below_200_day_average():
    row = last_row(daily=-0.002)
    trend = st.trend_signal(row)
    assert trend.score < 0
    # Every other signal as bullish as it can be.
    others = [st.Signal(k, k, "event", 1.0, w, "good", "") for k, w in st.WEIGHTS.items() if k != "trend"]
    decision = st.decide([trend] + others)
    assert decision["score"] >= st.BUY_THRESHOLD
    assert decision["action"] == "hold"
    assert "200-day" in decision["gate_note"]


def test_buy_needs_a_confirmed_trend():
    row = build_frame(make_history(n=120)).iloc[-1]
    others = [st.Signal(k, k, "event", 1.0, w, "good", "") for k, w in st.WEIGHTS.items() if k != "trend"]
    decision = st.decide([st.trend_signal(row)] + others)
    assert decision["action"] == "hold" and decision["gate_note"]


def _trade(days_ago, kind, insider, value=100_000):
    return {"date": (TODAY - timedelta(days=days_ago)).isoformat(), "kind": kind,
            "insider": insider, "position": "Director", "shares": 1000, "value": value, "text": ""}


def test_insider_cluster_buying_is_the_strongest_signal():
    cluster = [_trade(5, "buy", "A"), _trade(20, "buy", "B"), _trade(40, "buy", "C")]
    single = [_trade(5, "buy", "A")]
    assert st.insider_signal(cluster, TODAY).score == 1.0
    assert 0 < st.insider_signal(single, TODAY).score < st.insider_signal(cluster, TODAY).score
    assert "Cluster" in st.insider_signal(cluster, TODAY).headline


def test_insider_sales_count_for_little_and_old_or_other_trades_for_nothing():
    sells = [_trade(5, "sell", n) for n in "ABCD"]
    assert -0.35 < st.insider_signal(sells, TODAY).score < 0
    stale = [_trade(200, "buy", "A"), _trade(5, "other", "B")]
    assert st.insider_signal(stale, TODAY).score == 0
    assert not st.insider_signal(None, TODAY).available


def test_earnings_surprise_decays_with_age():
    def report(days_ago, surprise):
        return [{"date": (TODAY - timedelta(days=days_ago)).isoformat(), "eps_estimate": 1.0,
                 "eps_actual": 1.1, "surprise_pct": surprise}]
    fresh, older = st.earnings_signal(report(2, 12), TODAY), st.earnings_signal(report(50, 12), TODAY)
    assert fresh.score > older.score > 0
    assert st.earnings_signal(report(120, 12), TODAY).score == 0
    assert st.earnings_signal(report(2, -12), TODAY).score < 0
    future = [{"date": (TODAY + timedelta(days=10)).isoformat(), "eps_estimate": 1.0, "eps_actual": None, "surprise_pct": None}]
    assert not st.earnings_signal(future, TODAY).available


def test_news_signal_needs_two_headlines():
    assert not st.news_signal({"score": 0.9, "count": 1, "positive": 1, "negative": 0}).available
    sig = st.news_signal({"score": -0.6, "count": 5, "positive": 1, "negative": 4})
    assert sig.available and sig.score < 0


def test_golden_cross_and_big_move_events():
    # Long decline then a sharp recovery forces the 50-day through the 200-day.
    down, up = make_history(n=300, daily=-0.002, wiggle=0.0), make_history(n=220, daily=0.006, wiggle=0.0)
    close = list(down["close"]) + list(down["close"].iloc[-1] * up["close"] / up["close"].iloc[0])
    idx = pd.bdate_range(end=pd.Timestamp(TODAY), periods=len(close))
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1e6}, index=idx)
    frame = build_frame(df)
    crossed = (frame["sma50"] > frame["sma200"]) & (frame["sma50"].shift(1) <= frame["sma200"].shift(1))
    cross_at = list(crossed).index(True)
    kinds = {e["kind"] for e in st.technical_events(frame.iloc[: cross_at + 1])}
    assert "golden_cross" in kinds

    jump = make_history(n=300, wiggle=0.0)
    jump.iloc[-1, jump.columns.get_loc("close")] *= 1.08
    events = st.technical_events(build_frame(jump))
    assert any(e["kind"] == "big_move" and e["direction"] == "bullish" for e in events)
