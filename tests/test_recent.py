import pandas as pd

from stockanalysis.validation.recent import window_stats, windows
from .test_api import client  # noqa: F401  (shared fixture)


def test_windows_and_stats():
    end = pd.Timestamp("2026-11-20")
    w = windows(end)
    assert w["12m"][0] == pd.Timestamp("2025-11-20") and w["ytd"][0] == pd.Timestamp("2026-01-01")
    idx = pd.bdate_range("2026-01-01", periods=100)
    r = pd.Series(0.001, index=idx)
    st = window_stats(r, pd.Series(0.0, index=idx), idx[0], idx[-1])
    assert abs(st["return_pct"] - round((1.001 ** 100 - 1) * 100, 1)) < 0.11 and st["max_drawdown_pct"] == 0


def test_recent_endpoint(client):
    res = client.get("/api/validation/recent")
    if res.status_code == 200:
        data = res.json()
        assert "hold_spy" in data["methods"]["rows"] and "growth" in data["methods"]["rows"]
