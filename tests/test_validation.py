import numpy as np
import pandas as pd

from stockanalysis import strategies as st
from stockanalysis.validation.portfolio import Panel, Rules, benchmarks, curve_metrics, simulate, trade_metrics
from stockanalysis.validation.scores import earnings_points, score_history
from stockanalysis.validation.study import forward_returns, signal_events, summarize_events

from .conftest import make_history

CODES = {"strong_buy": 2, "buy": 1, "hold": 0, "sell": -1, "strong_sell": -2}


def test_vectorised_score_matches_live_rules():
    for seed, daily in [(1, 0.001), (2, -0.001), (3, 0.0)]:
        f = score_history(make_history(n=700, daily=daily, wiggle=0.02, seed=seed), use_earnings=False)
        for i in range(0, len(f), 5):
            row = f.iloc[i]
            signals = st.technical_signals(row)
            assert abs(sum(s.points for s in signals) - row["score"]) < 1e-9
            assert CODES[st.decide(signals)["action"]] == row["action"]


def test_earnings_only_count_from_the_next_day_and_fade():
    idx = pd.bdate_range("2024-01-01", periods=120)
    e = pd.DataFrame({"date": [pd.Timestamp("2024-01-10 16:00")], "surprise_pct": [20.0]})
    pts = earnings_points(idx, e)
    assert pts[pd.Timestamp("2024-01-10")] == 0                    # same day: not known yet
    day_after = pts[pd.Timestamp("2024-01-11")]
    assert 9 < day_after <= 10
    assert pts[pd.Timestamp("2024-02-20")] < day_after               # fades
    assert pts[pd.Timestamp("2024-05-01")] == 0                       # gone after ~85 days


def test_forward_returns_start_at_next_open():
    df = make_history(n=300, wiggle=0.0, daily=0.001)
    f = score_history(df, use_earnings=False)
    fwd = forward_returns(f, df, horizons=(5,))
    i = 100
    expected = df["close"].iloc[i + 5] / df["open"].iloc[i + 1] - 1
    assert abs(fwd["ret_5"].iloc[i] - expected) < 1e-12
    assert abs(fwd["exc_5"].iloc[i]) < 1e-12                          # same series as the "market"


def test_signal_events_and_summary():
    df = make_history(n=900, daily=0.0005, wiggle=0.02, seed=5)
    f = score_history(df, use_earnings=False)
    events = signal_events("X", f, make_history(n=900, daily=0.0, wiggle=0.0))
    assert set(events["kind"]) <= {"buy", "sell"} and len(events) > 0
    rows = summarize_events(events)
    assert all(0 <= r["win_rate"] <= 100 for r in rows)


def _panel(frames, spy):
    return Panel.build(frames, spy)


def test_portfolio_profits_in_a_steady_uptrend_and_costs_matter():
    spy = make_history(n=900, daily=0.0004, wiggle=0.008, seed=9)
    frames = {f"S{k}": score_history(make_history(n=900, daily=0.0012, wiggle=0.012, seed=k), use_earnings=False)
              for k in range(6)}
    panel = _panel(frames, spy)
    start = str(panel.dates[300].date())
    cheap = simulate(panel, Rules(cost_bps=0), start)
    dear = simulate(panel, Rules(cost_bps=50), start)
    assert curve_metrics(cheap["curve"])["total_return_pct"] > 0
    assert cheap["curve"].iloc[-1] > dear["curve"].iloc[-1]
    stats = trade_metrics(cheap)
    assert stats["trades"] > 0 and 0 < stats["invested_pct"] <= 100
    # Never more positions than allowed, never negative cash (equity stays positive).
    assert (cheap["curve"] > 0).all()


def test_portfolio_does_not_peek_ahead():
    spy = make_history(n=800, daily=0.0004, wiggle=0.008, seed=9)
    base = {f"S{k}": make_history(n=800, daily=0.001, wiggle=0.015, seed=k) for k in range(4)}
    frames = {k: score_history(v, use_earnings=False) for k, v in base.items()}
    changed = {}
    for k, v in base.items():
        v2 = v.copy()
        v2.iloc[600:, :4] *= 0.5            # crash the future
        changed[k] = score_history(v2, use_earnings=False)
    a = simulate(_panel(frames, spy), Rules(), str(spy.index[300].date()))
    b = simulate(_panel(changed, spy), Rules(), str(spy.index[300].date()))
    cut = spy.index[599]
    assert np.allclose(a["curve"].loc[:cut], b["curve"].loc[:cut])


def test_market_filter_blocks_buys_when_spy_is_falling():
    spy = make_history(n=800, daily=-0.002, wiggle=0.005, seed=2)   # bear market throughout
    frames = {f"S{k}": score_history(make_history(n=800, daily=0.0015, wiggle=0.01, seed=k), use_earnings=False)
              for k in range(3)}
    panel = _panel(frames, spy)
    res = simulate(panel, Rules(market_filter=True), str(spy.index[300].date()))
    assert res["trades"] == [] and res["open_trades"] == []
    bench = benchmarks(panel, str(spy.index[300].date()))
    assert bench["spy"].iloc[-1] < 1 and bench["equal_weight"].iloc[-1] > 1


def test_monthly_basket_matches_buy_and_hold_and_market_filter_earns_interest():
    from stockanalysis.validation.portfolio import MonthlyRules, simulate_monthly
    spy = make_history(n=900, daily=0.0004, wiggle=0.008, seed=9)
    frames = {f"S{k}": score_history(make_history(n=900, daily=0.0008, wiggle=0.015, seed=k), use_earnings=False)
              for k in range(5)}
    tbill = pd.Series(4.0, index=spy.index)  # 4% a year
    panel = Panel.build(frames, spy, tbill)
    start = str(spy.index[300].date())
    hold_all = simulate_monthly(panel, MonthlyRules(name="all", select="all", max_weight=1.0, cost_bps=0), start)
    ew = benchmarks(panel, start)["equal_weight"]
    a = curve_metrics(hold_all["curve"])["total_return_pct"]
    b = curve_metrics(ew)["total_return_pct"]
    assert abs(a - b) < 0.15 * abs(b) + 3     # monthly vs daily rebalancing, close but not identical
    bear = make_history(n=900, daily=-0.002, wiggle=0.005, seed=2)
    cash_panel = Panel.build(frames, bear, pd.Series(4.0, index=bear.index))
    res = simulate_monthly(cash_panel, MonthlyRules(name="f", select="all", market_filter=True), start)
    years = (res["curve"].index[-1] - res["curve"].index[0]).days / 365.25
    assert res["invested"] == 0 and abs(curve_metrics(res["curve"])["cagr_pct"] - 4.1) < 0.4 and years > 1
