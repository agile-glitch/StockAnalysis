import numpy as np
import pandas as pd

from stockanalysis import indicators as ind

from .conftest import make_history


def test_sma_matches_manual_mean():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0 and out.iloc[4] == 4.0


def test_rsi_is_100_when_price_only_rises_and_bounded_otherwise():
    rising = pd.Series(np.arange(1.0, 40.0))
    assert ind.rsi(rising, 14).iloc[-1] == 100.0
    noisy = make_history(300)["close"]
    values = ind.rsi(noisy, 14).dropna()
    assert ((values >= 0) & (values <= 100)).all()


def test_rsi_low_after_steady_decline():
    falling = pd.Series(np.linspace(100, 60, 40))
    assert ind.rsi(falling, 14).iloc[-1] < 5


def test_atr_reflects_daily_range():
    df = make_history(100, wiggle=0.0, daily=0.0)  # flat close, high/low +-1%
    atr = ind.atr(df, 14).iloc[-1]
    assert abs(atr - 2.0) < 0.05  # range is 2% of a ~100 price


def test_build_frame_has_every_strategy_input():
    frame = ind.build_frame(make_history(520))
    last = frame.iloc[-1]
    for column in ("sma50", "sma200", "rsi2", "rsi14", "macd_hist", "atr14", "high252",
                   "mom_12_1", "chandelier", "hv30", "vol_avg50"):
        assert not np.isnan(last[column]), column
    # 12-1 momentum skips the last month
    expected = frame["close"].iloc[-22] / frame["close"].iloc[-253] - 1
    assert abs(last["mom_12_1"] - expected) < 1e-9
