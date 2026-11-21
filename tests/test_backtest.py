from stockanalysis.backtest import run_backtest

from .conftest import make_history


def test_backtest_reports_consistent_numbers():
    out = run_backtest(make_history(n=1260, daily=0.0006, wiggle=0.015, seed=7))
    assert out["available"]
    assert out["trades"] >= 1 and out["closed_trades"] <= out["trades"]
    assert -100 <= out["strategy_max_drawdown_pct"] <= 0
    assert 0 <= out["time_in_market_pct"] <= 100
    assert len(out["curve"]["dates"]) == len(out["curve"]["strategy"]) == len(out["curve"]["buy_hold"])
    assert out["curve"]["strategy"][0] == 100.0
    assert abs(out["curve"]["strategy"][-1] - (100 + out["strategy_return_pct"])) < 0.2


def test_backtest_stays_out_of_a_falling_stock():
    out = run_backtest(make_history(n=1260, daily=-0.0015, wiggle=0.01, seed=3))
    assert out["buy_hold_return_pct"] < -50
    assert out["strategy_return_pct"] > out["buy_hold_return_pct"]
    assert out["strategy_max_drawdown_pct"] > out["buy_hold_max_drawdown_pct"]
    assert out["time_in_market_pct"] < 30


def test_backtest_needs_enough_history():
    assert not run_backtest(make_history(n=200))["available"]
