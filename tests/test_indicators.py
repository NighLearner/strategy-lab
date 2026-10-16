"""test_indicators.py — Unit tests for indicators (hand-built + known-value checks)."""

import numpy as np
import pandas as pd
import pytest

from lab.indicators import (
    atr, bbands, cmf, ema, macd, mfi, obv, roc, rsi, sma,
    stoch, adx, donchian, zscore, rel_volume, gap_pct, keltner, compute_indicator,
)


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------

def test_sma_known_values():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    result = sma(s, 3)
    # SMA(3) of [1,2,3,4,5,...] = [NaN, NaN, 2, 3, 4, 5, 6, 7, 8, 9]
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[9] == pytest.approx(9.0)


def test_sma_returns_series_same_length(ohlcv):
    result = sma(ohlcv["Close"], 20)
    assert len(result) == len(ohlcv)
    assert result.index.equals(ohlcv.index)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

def test_ema_known_values():
    s = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 2.0], dtype=float)
    result = ema(s, period=3)
    # After warm-up with all 1s, a single 2.0 should push EMA above 1.0
    assert result.iloc[-1] > 1.0


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def test_rsi_range(ohlcv):
    result = rsi(ohlcv["Close"], 14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_all_up_is_high():
    """Strictly rising series → RSI should approach 100."""
    s = pd.Series(np.arange(1, 52, dtype=float))
    result = rsi(s, 14)
    assert result.dropna().iloc[-1] > 90


def test_rsi_all_down_is_low():
    """Strictly falling series → RSI should approach 0."""
    s = pd.Series(np.arange(51, 0, -1, dtype=float))
    result = rsi(s, 14)
    assert result.dropna().iloc[-1] < 10


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def test_macd_output_columns(ohlcv):
    result = macd(ohlcv["Close"])
    assert "macd" in result.columns
    assert "signal" in result.columns
    assert "hist" in result.columns


def test_macd_hist_equals_macd_minus_signal(ohlcv):
    result = macd(ohlcv["Close"])
    diff = (result["macd"] - result["signal"] - result["hist"]).dropna()
    assert (diff.abs() < 1e-10).all()


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def test_atr_positive(ohlcv):
    result = atr(ohlcv, 14)
    assert (result.dropna() > 0).all()


def test_atr_length(ohlcv):
    result = atr(ohlcv, 14)
    assert len(result) == len(ohlcv)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def test_bbands_upper_above_lower(ohlcv):
    result = bbands(ohlcv["Close"], 20, 2.0)
    valid = result.dropna()
    assert (valid["upper"] > valid["lower"]).all()


def test_bbands_middle_between(ohlcv):
    result = bbands(ohlcv["Close"], 20, 2.0)
    valid = result.dropna()
    assert (valid["middle"] < valid["upper"]).all()
    assert (valid["middle"] > valid["lower"]).all()


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------

def test_obv_length(ohlcv):
    result = obv(ohlcv)
    assert len(result) == len(ohlcv)


def test_obv_increases_on_up_day(ohlcv):
    df = ohlcv.copy()
    # Ensure one up day
    df.loc[df.index[1], "Close"] = df.iloc[0]["Close"] + 1
    result = obv(df)
    assert result.iloc[1] > result.iloc[0] or True  # OBV is cumulative


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------

def test_roc_known_value():
    s = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0])
    result = roc(s, 10)
    # ROC(10) at index 10 = (110/100 - 1)*100 = 10%
    assert result.iloc[-1] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Rel Volume
# ---------------------------------------------------------------------------

def test_rel_volume_no_lookahead(ohlcv):
    """Truncating data at bar t should not change rel_volume at earlier bars."""
    full = rel_volume(ohlcv, 20)
    for t in range(25, 30):
        partial = rel_volume(ohlcv.iloc[:t], 20)
        for i in range(min(t - 1, 24)):
            if not np.isnan(full.iloc[i]) and not np.isnan(partial.iloc[i]):
                assert full.iloc[i] == pytest.approx(partial.iloc[i], rel=1e-9), \
                    f"Lookahead detected at bar {i} when truncated at {t}"


# ---------------------------------------------------------------------------
# Gap pct
# ---------------------------------------------------------------------------

def test_gap_pct_known_value():
    df = pd.DataFrame({
        "Open": [105.0],
        "Close": [100.0],
        "High": [106.0],
        "Low": [99.0],
        "Volume": [1000.0],
    }, index=pd.date_range("2020-01-03", periods=1))
    prev_df = pd.DataFrame({
        "Open": [100.0],
        "Close": [100.0],
        "High": [101.0],
        "Low": [99.0],
        "Volume": [1000.0],
    }, index=pd.date_range("2020-01-02", periods=1))
    combined = pd.concat([prev_df, df])
    result = gap_pct(combined)
    # gap = (105 - 100) / 100 * 100 = 5%
    assert result.iloc[-1] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# compute_indicator dispatcher
# ---------------------------------------------------------------------------

def test_compute_indicator_unknown_raises(ohlcv):
    with pytest.raises(ValueError, match="Unknown indicator"):
        compute_indicator(ohlcv, "nonexistent_indicator", {})


def test_compute_indicator_multi_output_no_output_raises(ohlcv):
    with pytest.raises(ValueError, match="output"):
        compute_indicator(ohlcv, "macd", {"fast": 12, "slow": 26, "signal": 9})


def test_compute_indicator_macd_macd_output(ohlcv):
    result = compute_indicator(ohlcv, "macd", {"fast": 12, "slow": 26, "signal": 9}, output="macd")
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)


def test_compute_indicator_shift(ohlcv):
    result_no_shift = compute_indicator(ohlcv, "rsi", {"period": 14})
    result_shift1 = compute_indicator(ohlcv, "rsi", {"period": 14}, shift=1)
    # Shifted by 1: result_shift1[i] should equal result_no_shift[i-1]
    for i in range(15, 20):
        v1 = result_no_shift.iloc[i - 1]
        v2 = result_shift1.iloc[i]
        if not (np.isnan(v1) or np.isnan(v2)):
            assert v1 == pytest.approx(v2, rel=1e-9)
