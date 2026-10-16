"""test_spec.py — Unit tests for strategy spec schema and whitelist validation."""

import pytest
from lab.spec import (
    StrategySpec,
    validate_spec,
    WHITELISTED_INDICATORS,
    WHITELISTED_PATTERNS,
)


def _minimal_valid_spec_dict() -> dict:
    return {
        "id": "test_strat_v1",
        "name": "Test Strategy",
        "family": "momentum",
        "direction": "long",
        "timeframe": "1d",
        "entry": {
            "all": [
                {
                    "left": {"indicator": "rsi", "params": {"period": 14}},
                    "op": "<",
                    "right": {"value": 30.0},
                }
            ]
        },
        "exit": {
            "hold_bars": 10,
            "stop_loss_pct": 5.0,
            "take_profit_pct": 10.0,
            "trailing_atr_mult": None,
            "any": [],
        },
        "params_grid": {},
        "notes": "A minimal valid test strategy.",
    }


def test_valid_spec_loads():
    d = _minimal_valid_spec_dict()
    spec = validate_spec(d)
    assert isinstance(spec, StrategySpec)
    assert spec.id == "test_strat_v1"
    assert spec.direction == "long"


def test_unknown_indicator_rejected():
    d = _minimal_valid_spec_dict()
    d["entry"]["all"][0]["left"]["indicator"] = "super_unknown_indicator"
    with pytest.raises(Exception) as exc_info:
        validate_spec(d)
    assert "Unknown indicator" in str(exc_info.value) or "super_unknown_indicator" in str(exc_info.value)


def test_unknown_pattern_rejected():
    d = _minimal_valid_spec_dict()
    d["entry"] = {"pattern": "super_unknown_candle", "params": {}}
    with pytest.raises(Exception) as exc_info:
        validate_spec(d)
    assert "Unknown pattern" in str(exc_info.value) or "super_unknown_candle" in str(exc_info.value)


def test_negative_shift_rejected():
    d = _minimal_valid_spec_dict()
    d["entry"]["all"][0]["left"]["shift"] = -1
    with pytest.raises(Exception) as exc_info:
        validate_spec(d)
    assert "shift" in str(exc_info.value).lower() or "lookahead" in str(exc_info.value).lower()


def test_out_of_bounds_indicator_param_rejected():
    d = _minimal_valid_spec_dict()
    # RSI period bounds: (2, 50). Try 1000.
    d["entry"]["all"][0]["left"]["params"]["period"] = 1000
    with pytest.raises(Exception) as exc_info:
        validate_spec(d)
    assert "out of range" in str(exc_info.value).lower()


def test_spec_hash_deterministic():
    d1 = _minimal_valid_spec_dict()
    d2 = _minimal_valid_spec_dict()
    s1 = validate_spec(d1)
    s2 = validate_spec(d2)
    h1 = s1.spec_hash()
    h2 = s2.spec_hash()
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex length


def test_invalid_family_rejected():
    d = _minimal_valid_spec_dict()
    d["family"] = "magical_crystal_ball"
    with pytest.raises(Exception) as exc_info:
        validate_spec(d)
    assert "family" in str(exc_info.value).lower()
