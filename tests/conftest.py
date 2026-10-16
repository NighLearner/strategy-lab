"""conftest.py — Shared fixtures for all tests."""

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    opens = closes * (1 + rng.normal(0, 0.005, n))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.01, n))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.01, n))
    volumes = rng.integers(100_000, 1_000_000, n).astype(float)
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=dates,
    )


@pytest.fixture
def ohlcv():
    return _make_ohlcv(200)


@pytest.fixture
def ohlcv_trending_up():
    """A clearly uptrending series — useful for trend signals."""
    n = 300
    dates = pd.date_range("2015-01-02", periods=n, freq="B")
    closes = 100.0 + np.arange(n) * 0.5  # strictly rising
    opens = closes - 0.2
    highs = closes + 0.5
    lows = opens - 0.3
    volumes = np.full(n, 500_000.0)
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=dates,
    )
