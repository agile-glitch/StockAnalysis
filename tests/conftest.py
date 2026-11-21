from datetime import date

import numpy as np
import pandas as pd
import pytest

from stockanalysis.db import Database
from stockanalysis.engine import Engine
from stockanalysis.providers import CachedProvider
from stockanalysis.providers.demo import DemoProvider

TODAY = date(2026, 11, 19)


def make_history(n: int = 520, start: float = 100.0, daily: float = 0.001, wiggle: float = 0.01,
                 seed: int = 1) -> pd.DataFrame:
    """A smooth trending OHLCV series with a little noise."""
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(np.full(n, daily) + rng.normal(0, wiggle, n)))
    idx = pd.bdate_range(end=pd.Timestamp(TODAY), periods=n)
    return pd.DataFrame({
        "open": close * 0.998, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1_000_000.0),
    }, index=idx)


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def provider():
    return CachedProvider(DemoProvider(today=TODAY))


@pytest.fixture
def engine(db, provider):
    return Engine(db, provider, today_fn=lambda: TODAY)
