"""test_signals.py — Unit tests for signal generation and variant expansion."""

import numpy as np
import pandas as pd
import pytest

from lab.signals import compute_entry_signals, compute_exit_conditions, expand_variants
from lab.spec import StrategySpec, validate_spec


def test_evaluate_signals_pattern(ohlcv):
    # Test hammer reversal entry
    spec_dict = {
        "id": "hammer_test",
        "name": "Hammer Test",
        "family": "candlestick_reversal",
        "direction": "long",
        "timeframe": "1d",
        "entry": {"pattern": "hammer", "params": {}},
        "exit": {"hold_bars": 5, "stop_loss_pct": 5, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
        "params_grid": {},
        "notes": "Hammer test",
    }
    spec = validate_spec(spec_dict)
    entries = compute_entry_signals(ohlcv, spec)
    exits = compute_exit_conditions(ohlcv, spec)
    assert isinstance(entries, pd.Series)
    assert isinstance(exits, pd.Series)
    assert len(entries) == len(ohlcv)
    assert entries.dtype == bool
    assert exits.dtype == bool


def test_evaluate_signals_comparison(ohlcv):
    spec_dict = {
        "id": "rsi_comp_test",
        "name": "RSI Comp Test",
        "family": "momentum",
        "direction": "long",
        "timeframe": "1d",
        "entry": {
            "all": [
                {"left": {"indicator": "rsi", "params": {"period": 14}}, "op": "<", "right": {"value": 50.0}}
            ]
        },
        "exit": {
            "hold_bars": 5,
            "stop_loss_pct": 5,
            "take_profit_pct": None,
            "trailing_atr_mult": None,
            "any": [
                {"left": {"indicator": "rsi", "params": {"period": 14}}, "op": ">", "right": {"value": 70.0}}
            ],
        },
        "params_grid": {},
        "notes": "RSI comp test",
    }
    spec = validate_spec(spec_dict)
    entries = compute_entry_signals(ohlcv, spec)
    exits = compute_exit_conditions(ohlcv, spec)
    assert len(entries) == len(ohlcv)
    assert len(exits) == len(ohlcv)


def test_expand_variants_no_grid():
    spec_dict = {
        "id": "fixed_strat",
        "name": "Fixed Strat",
        "family": "trend",
        "direction": "long",
        "timeframe": "1d",
        "entry": {"all": [{"left": {"field": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 20}}}]},
        "exit": {"hold_bars": 5, "stop_loss_pct": 5, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
        "params_grid": {},
        "notes": "No grid",
    }
    spec = validate_spec(spec_dict)
    variants = expand_variants(spec)
    assert len(variants) == 1
    assert variants[0].id == "fixed_strat"


def test_expand_variants_grid():
    spec_dict = {
        "id": "grid_strat",
        "name": "Grid Strat",
        "family": "trend",
        "direction": "long",
        "timeframe": "1d",
        "entry": {"all": [{"left": {"field": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 20}}}]},
        "exit": {"hold_bars": 5, "stop_loss_pct": 5, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
        "params_grid": {
            "exit.hold_bars": [3, 5, 10],
            "exit.stop_loss_pct": [3.0, 5.0],
        },
        "notes": "Grid test",
    }
    spec = validate_spec(spec_dict)
    variants = expand_variants(spec)
    assert len(variants) == 6  # 3 * 2
    for vspec in variants:
        assert vspec.exit.hold_bars in [3, 5, 10]
        assert vspec.exit.stop_loss_pct in [3.0, 5.0]
