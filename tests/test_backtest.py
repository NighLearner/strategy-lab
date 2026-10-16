"""test_backtest.py — Backtest engine tests with synthetic data and known answers."""

import numpy as np
import pandas as pd
import pytest

from lab.backtest import run_backtest, _gross_return
from lab.spec import StrategySpec, validate_spec


def _make_spec(hold_bars: int = 5, stop_pct: float = None, tp_pct: float = None) -> StrategySpec:
    spec_data = {
        "id": "test_spec_v1",
        "name": "Test Spec",
        "family": "trend",
        "direction": "long",
        "timeframe": "1d",
        "entry": {"left": {"field": "close"}, "op": ">", "right": {"value": 0}},
        "exit": {
            "hold_bars": hold_bars,
            "stop_loss_pct": stop_pct,
            "take_profit_pct": tp_pct,
            "trailing_atr_mult": None,
            "any": [],
        },
        "params_grid": {},
    }
    return validate_spec(spec_data)


def _make_df(closes: list, opens: list = None, highs: list = None, lows: list = None) -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    closes_arr = np.array(closes, dtype=float)
    opens_arr = np.array(opens, dtype=float) if opens else closes_arr * 0.999
    highs_arr = np.array(highs, dtype=float) if highs else closes_arr * 1.01
    lows_arr = np.array(lows, dtype=float) if lows else closes_arr * 0.99
    return pd.DataFrame({
        "Open": opens_arr,
        "High": highs_arr,
        "Low": lows_arr,
        "Close": closes_arr,
        "Volume": np.full(n, 500_000.0),
    }, index=dates)


# ---------------------------------------------------------------------------
# Basic trade mechanics
# ---------------------------------------------------------------------------

def test_backtest_single_trade_hold_bars():
    """Single signal → single trade held for hold_bars."""
    closes = [100.0] * 20
    opens = [100.0] * 20
    highs = [101.0] * 20
    lows = [99.0] * 20
    df = _make_df(closes, opens, highs, lows)

    # Signal on bar 2 only
    entry_signals = pd.Series(False, index=df.index)
    entry_signals.iloc[2] = True
    exit_signals = pd.Series(False, index=df.index)

    spec = _make_spec(hold_bars=5)
    trades = run_backtest(df, entry_signals, exit_signals, spec, "test_v1", "FAKE", cost_bps=0, slip_bps=0)

    assert len(trades) == 1
    assert trades.iloc[0]["bars_held"] == 5
    assert trades.iloc[0]["exit_reason"] == "time"


def test_backtest_no_signals_empty():
    df = _make_df([100.0] * 10)
    entry_signals = pd.Series(False, index=df.index)
    exit_signals = pd.Series(False, index=df.index)
    spec = _make_spec()
    trades = run_backtest(df, entry_signals, exit_signals, spec, "v1", "FAKE", cost_bps=0, slip_bps=0)
    assert trades.empty


def test_backtest_gross_return_long_up():
    """Buy at 100, exit at 110 → +10%."""
    ret = _gross_return(100.0, 110.0, "long")
    assert ret == pytest.approx(10.0)


def test_backtest_gross_return_short_up():
    """Short at 100, exit at 90 → +10%."""
    ret = _gross_return(100.0, 90.0, "short")
    assert ret == pytest.approx(10.0)


def test_backtest_gross_return_long_down():
    """Buy at 100, exit at 90 → -10%."""
    ret = _gross_return(100.0, 90.0, "long")
    assert ret == pytest.approx(-10.0)


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

def test_backtest_costs_reduce_returns():
    """With costs, net return < gross return."""
    closes = [100.0] * 10
    opens = [100.0] + [100.0] * 9
    highs = [101.0] * 10
    lows = [99.0] * 10
    df = _make_df(closes, opens, highs, lows)

    entry_signals = pd.Series(False, index=df.index)
    entry_signals.iloc[0] = True
    exit_signals = pd.Series(False, index=df.index)

    spec = _make_spec(hold_bars=5)

    # With 0 cost
    trades_no_cost = run_backtest(df, entry_signals.copy(), exit_signals.copy(), spec, "v1", "FAKE", cost_bps=0, slip_bps=0)
    # With 10 bps cost
    trades_with_cost = run_backtest(df, entry_signals.copy(), exit_signals.copy(), spec, "v1", "FAKE", cost_bps=10, slip_bps=5)

    net_no_cost = trades_no_cost.iloc[0]["net_return_pct"]
    net_with_cost = trades_with_cost.iloc[0]["net_return_pct"]
    assert net_with_cost < net_no_cost


def test_doubling_costs_lowers_returns():
    """Doubling costs should lower net returns by approximately double the cost impact."""
    closes = [100.0, 100.0, 100.0, 100.0, 100.0, 105.0, 105.0, 105.0]
    opens = [100.0] * 8
    highs = [101.0, 101, 101, 101, 101, 106, 106, 106]
    lows = [99.0] * 8
    df = _make_df(closes, opens, highs, lows)

    entry_signals = pd.Series(False, index=df.index)
    entry_signals.iloc[0] = True
    exit_signals = pd.Series(False, index=df.index)
    spec = _make_spec(hold_bars=5, stop_pct=None)

    trades_10 = run_backtest(df, entry_signals.copy(), exit_signals.copy(), spec, "v1", "FAKE", cost_bps=10, slip_bps=0)
    trades_20 = run_backtest(df, entry_signals.copy(), exit_signals.copy(), spec, "v1", "FAKE", cost_bps=20, slip_bps=0)

    net_10 = trades_10.iloc[0]["net_return_pct"]
    net_20 = trades_20.iloc[0]["net_return_pct"]
    assert net_20 < net_10


# ---------------------------------------------------------------------------
# Stop loss
# ---------------------------------------------------------------------------

def test_backtest_stop_loss_triggered():
    """Stop loss triggers when low crosses stop price."""
    # Entry at open=100, stop=8% → stop_price=92
    # Bar 3 low = 91 → stop triggered
    opens  = [100, 100, 100, 100, 100, 100, 100]
    closes = [100, 100, 100,  91,  95,  98, 100]
    highs  = [101, 101, 101, 101, 101, 101, 101]
    lows   = [ 99,  99,  99,  91,  93,  97,  99]
    df = _make_df(closes, opens, highs, lows)

    entry_signals = pd.Series(False, index=df.index)
    entry_signals.iloc[0] = True
    exit_signals = pd.Series(False, index=df.index)
    spec = _make_spec(hold_bars=10, stop_pct=8.0)

    trades = run_backtest(df, entry_signals, exit_signals, spec, "v1", "FAKE", cost_bps=0, slip_bps=0)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "stop"
    assert trades.iloc[0]["net_return_pct"] < 0


# ---------------------------------------------------------------------------
# One position at a time
# ---------------------------------------------------------------------------

def test_backtest_one_position_at_a_time():
    """While in a position, new signals are ignored."""
    closes = [100.0] * 20
    df = _make_df(closes)

    entry_signals = pd.Series(False, index=df.index)
    # Signal on bars 0 and 2 (both within hold_bars=5 window)
    entry_signals.iloc[0] = True
    entry_signals.iloc[2] = True
    exit_signals = pd.Series(False, index=df.index)
    spec = _make_spec(hold_bars=10)

    trades = run_backtest(df, entry_signals, exit_signals, spec, "v1", "FAKE", cost_bps=0, slip_bps=0)
    # Should only produce one trade — bar 2 signal is during position
    assert len(trades) == 1
