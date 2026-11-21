import numpy as np
import pandas as pd
import pytest

from stockanalysis import lab_runner
from stockanalysis import tactics as T

from .conftest import make_history


def frame(**kw):
    df = make_history(**kw)
    return df, df[["close"]], df[["open"]]


def test_every_tactic_runs_and_describes_itself():
    _, close, _ = frame(n=700, wiggle=0.02, seed=3)
    for key, tactic in T.TACTICS.items():
        held = T.positions(key, {}, close)
        assert held.dtypes.iloc[0] == bool and held.shape == close.shape
        assert T.describe(key, {})
        assert len(tactic.params) >= 1


def test_params_are_clamped_and_kept_consistent():
    assert T.clean_params("price_ma", {"n": 99999})["n"] == 400
    assert T.clean_params("price_ma", {"n": "junk"})["n"] == 200
    cross = T.clean_params("ma_cross", {"fast": 300, "slow": 100})
    assert cross["fast"] < cross["slow"]
    rsi = T.clean_params("rsi_reversion", {"buy_below": 40, "sell_above": 40})
    assert rsi["sell_above"] > rsi["buy_below"]
    with pytest.raises(KeyError):
        T.clean_params("nope", {})


def test_trend_tactics_hold_uptrends_and_skip_downtrends():
    _, up, _ = frame(n=600, daily=0.002, wiggle=0.002, seed=1)
    _, down, _ = frame(n=600, daily=-0.002, wiggle=0.002, seed=1)
    # MACD's signal-line version keeps crossing in a perfectly steady trend; its zero-line version holds.
    for key, params in (("price_ma", {}), ("ma_cross", {}), ("momentum", {}), ("macd", {"zero_line": 1})):
        assert T.positions(key, params, up).iloc[-100:].to_numpy().mean() > 0.9, key
        assert T.positions(key, params, down).iloc[-100:].to_numpy().mean() < 0.1, key


def test_rsi_bounce_buys_dips_and_respects_trend_filter():
    df, close, _ = frame(n=600, daily=0.001, wiggle=0.0, seed=1)
    close = close.copy()
    close.iloc[500:504] = close.iloc[499].to_numpy() * np.array([[0.97], [0.94], [0.91], [0.88]])
    held = T.positions("rsi_reversion", {"period": 2, "buy_below": 10, "sell_above": 70, "trend_filter": 0}, close)
    assert held.iloc[501:505].to_numpy().any()
    falling = close.iloc[::-1].reset_index(drop=True).set_axis(close.index)
    filtered = T.positions("rsi_reversion", {"period": 2, "buy_below": 10, "trend_filter": 1}, falling)
    assert not filtered.iloc[250:].to_numpy().any() or filtered.iloc[250:].to_numpy().mean() < 0.05


def test_backtest_matches_buy_and_hold_and_charges_costs():
    df, close, open_ = frame(n=500, wiggle=0.02, seed=7)
    always = pd.DataFrame(True, index=close.index, columns=close.columns)
    r = T.backtest(open_, close, always, cost=0)
    assert abs((1 + r).prod().iloc[0] - close["close"].iloc[-1] / open_["open"].iloc[1]) < 1e-9
    flip = pd.DataFrame(np.arange(len(close)) % 10 < 5, index=close.index, columns=close.columns)
    cheap, dear = T.backtest(open_, close, flip, cost=0), T.backtest(open_, close, flip, cost=0.01)
    assert (1 + dear).prod().iloc[0] < (1 + cheap).prod().iloc[0]
    never = pd.DataFrame(False, index=close.index, columns=close.columns)
    cash = pd.Series(0.0001, index=close.index)
    assert abs((1 + T.backtest(open_, close, never, cash)).prod().iloc[0] - 1.0001 ** len(close)) < 1e-9


def test_pooled_returns_split_money_and_hold_cash_otherwise():
    idx = pd.bdate_range("2024-01-01", periods=6)
    rets = pd.DataFrame({"A": [0, .01, .01, .01, .01, .01], "B": [0, .03, .03, .03, .03, .03]}, index=idx)
    held = pd.DataFrame({"A": [True] * 6, "B": [False] * 6}, index=idx)
    pooled = T.pooled_returns(rets, held, pd.Series(0.0, index=idx), max_weight=0.10)
    assert abs(pooled.iloc[-1] - 0.001) < 1e-12        # 10% in A, 90% in cash at 0%
    both = T.pooled_returns(rets, held | True, None, max_weight=1.0)
    assert abs(both.iloc[-1] - 0.02) < 1e-12           # half in each


def test_lab_runner_on_one_stock():
    df, _, _ = frame(n=1200, daily=0.0006, wiggle=0.02, seed=4)
    r = lab_runner.run(df, "donchian", {"entry": 55, "exit": 20}, None)
    assert r["label"] == "55-day breakout, 20-day exit"
    assert set(r["strategy"]) >= {"cagr_pct", "max_drawdown_pct", "sharpe"}
    assert len(r["chart"]["dates"]) == len(r["chart"]["price"]) == len(r["chart"]["strategy"])
    assert all(p is None or isinstance(p, float) for p in r["chart"]["holding_price"])
    for t in r["trades"]:
        assert t["exit_date"] >= t["entry_date"]
    assert isinstance(r["holding_now"], bool)


def test_catalog_lists_every_tactic_with_settings():
    cat = lab_runner.tactic_catalog()
    assert {c["key"] for c in cat} == set(T.TACTICS)
    for c in cat:
        for p in c["params"]:
            assert p["min"] <= p["default"] <= p["max"]
