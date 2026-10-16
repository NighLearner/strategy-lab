"""spec.py — Pydantic v2 models for strategy specs + whitelist validation.

Schema defined in knowledge/strategy_spec_schema.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from lab.indicators import INDICATOR_MAP
from lab.patterns import PATTERN_MAP

# ---------------------------------------------------------------------------
# Whitelists (mirrors strategy_spec_schema.md)
# ---------------------------------------------------------------------------

WHITELISTED_INDICATORS = set(INDICATOR_MAP.keys())

WHITELISTED_PATTERNS = set(PATTERN_MAP.keys())

WHITELISTED_OPERATORS = {"<", "<=", ">", ">=", "cross_above", "cross_below", "between"}

WHITELISTED_FIELDS = {"open", "high", "low", "close", "volume"}

WHITELISTED_FAMILIES = {
    "candlestick_reversal",
    "candlestick_continuation",
    "trend",
    "momentum",
    "mean_reversion",
    "breakout",
    "volatility",
    "volume_flow",
    "combo",
}

# Param bounds for indicators
INDICATOR_PARAM_BOUNDS: dict[str, dict[str, tuple]] = {
    "sma":       {"period": (2, 300)},
    "ema":       {"period": (2, 300)},
    "rsi":       {"period": (2, 50)},
    "macd":      {"fast": (3, 30), "slow": (10, 60), "signal": (3, 20)},
    "bbands":    {"period": (5, 100), "std": (0.5, 4.0)},
    "atr":       {"period": (2, 50)},
    "adx":       {"period": (5, 50)},
    "stoch":     {"k": (5, 30), "d": (2, 10)},
    "roc":       {"period": (1, 252)},
    "donchian":  {"period": (5, 252)},
    "zscore":    {"period": (5, 100)},
    "obv":       {},
    "mfi":       {"period": (5, 30)},
    "cmf":       {"period": (5, 50)},
    "vol_sma":   {"period": (5, 100)},
    "rel_volume": {"period": (5, 100)},
    "keltner":   {"period": (5, 60), "mult": (0.5, 4.0)},
    "gap_pct":   {},
    "range_pct": {},
    "highest":   {"period": (2, 260)},
    "lowest":    {"period": (2, 260)},
}

MAX_SPEC_BYTES = 4096
MAX_CONDITION_DEPTH = 3
MAX_CONDITION_LEAVES = 8
MAX_PARAMS_GRID_KEYS = 3
MAX_PARAMS_GRID_VALUES = 5
MAX_VARIANTS_PER_GRID_KEY = 5


# ---------------------------------------------------------------------------
# Operand models
# ---------------------------------------------------------------------------

class FieldOperand(BaseModel):
    field: str

    @field_validator("field")
    @classmethod
    def check_field(cls, v: str) -> str:
        if v.lower() not in WHITELISTED_FIELDS:
            raise ValueError(f"Unknown field '{v}'. Allowed: {WHITELISTED_FIELDS}")
        return v.lower()


class IndicatorOperand(BaseModel):
    indicator: str
    params: dict[str, Any] = {}
    output: Optional[str] = None
    shift: int = Field(0, ge=0)

    @field_validator("indicator")
    @classmethod
    def check_indicator(cls, v: str) -> str:
        if v not in WHITELISTED_INDICATORS:
            raise ValueError(f"Unknown indicator '{v}'. Allowed: {sorted(WHITELISTED_INDICATORS)}")
        return v

    @field_validator("shift")
    @classmethod
    def check_shift(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Negative shift is forbidden (lookahead bias).")
        return v

    @model_validator(mode="after")
    def check_params(self) -> "IndicatorOperand":
        bounds = INDICATOR_PARAM_BOUNDS.get(self.indicator, {})
        for pname, pval in self.params.items():
            if pname not in bounds and bounds:
                raise ValueError(f"Unknown param '{pname}' for indicator '{self.indicator}'")
            if pname in bounds:
                lo, hi = bounds[pname]
                if not (lo <= pval <= hi):
                    raise ValueError(
                        f"Param '{pname}' = {pval} out of range [{lo}, {hi}] for '{self.indicator}'"
                    )
        return self


class ValueOperand(BaseModel):
    value: float


class BetweenOperand(BaseModel):
    low: float
    high: float


Operand = Union[FieldOperand, IndicatorOperand, ValueOperand]


# ---------------------------------------------------------------------------
# Condition models
# ---------------------------------------------------------------------------

class PatternLeaf(BaseModel):
    pattern: str
    params: dict[str, Any] = {}

    @field_validator("pattern")
    @classmethod
    def check_pattern(cls, v: str) -> str:
        if v not in WHITELISTED_PATTERNS:
            raise ValueError(f"Unknown pattern '{v}'. Allowed: {sorted(WHITELISTED_PATTERNS)}")
        return v


class ComparisonLeaf(BaseModel):
    left: Operand
    op: str
    right: Union[Operand, BetweenOperand]

    @field_validator("op")
    @classmethod
    def check_op(cls, v: str) -> str:
        if v not in WHITELISTED_OPERATORS:
            raise ValueError(f"Unknown operator '{v}'. Allowed: {WHITELISTED_OPERATORS}")
        return v


# Forward-reference-friendly condition
ConditionType = Union[
    "AllGroup",
    "AnyGroup",
    PatternLeaf,
    ComparisonLeaf,
]


class AllGroup(BaseModel):
    all: list[ConditionType]


class AnyGroup(BaseModel):
    any: list[ConditionType]


AllGroup.model_rebuild()
AnyGroup.model_rebuild()


# ---------------------------------------------------------------------------
# Exit model
# ---------------------------------------------------------------------------

class ExitCondition(BaseModel):
    hold_bars: Optional[int] = Field(None, ge=1, le=60)
    stop_loss_pct: Optional[float] = Field(None, gt=0, le=50)
    take_profit_pct: Optional[float] = Field(None, gt=0)
    trailing_atr_mult: Optional[float] = Field(None, gt=0)
    any: list[ConditionType] = []

    @model_validator(mode="after")
    def at_least_one_exit(self) -> "ExitCondition":
        if (
            self.hold_bars is None
            and self.stop_loss_pct is None
            and self.take_profit_pct is None
            and self.trailing_atr_mult is None
            and not self.any
        ):
            raise ValueError("Exit must specify at least one of: hold_bars, stop_loss_pct, take_profit_pct, trailing_atr_mult, or a non-empty 'any' list.")
        return self


# ---------------------------------------------------------------------------
# Top-level spec
# ---------------------------------------------------------------------------

class StrategySpec(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9_]{3,60}$")
    name: str = Field(..., max_length=80)
    family: str
    direction: Literal["long", "short"]
    timeframe: Literal["1d"] = "1d"
    entry: ConditionType
    exit: ExitCondition
    params_grid: dict[str, list[Any]] = {}
    notes: Optional[str] = Field(None, max_length=300)

    @field_validator("family")
    @classmethod
    def check_family(cls, v: str) -> str:
        if v not in WHITELISTED_FAMILIES:
            raise ValueError(f"Unknown family '{v}'. Allowed: {sorted(WHITELISTED_FAMILIES)}")
        return v

    @field_validator("params_grid")
    @classmethod
    def check_params_grid(cls, v: dict) -> dict:
        if len(v) > MAX_PARAMS_GRID_KEYS:
            raise ValueError(f"params_grid may have at most {MAX_PARAMS_GRID_KEYS} keys.")
        for key, vals in v.items():
            if not isinstance(vals, list) or len(vals) == 0:
                raise ValueError(f"params_grid['{key}'] must be a non-empty list.")
            if len(vals) > MAX_PARAMS_GRID_VALUES:
                raise ValueError(f"params_grid['{key}'] may have at most {MAX_PARAMS_GRID_VALUES} values.")
        return v

    def spec_hash(self) -> str:
        """SHA-256 of canonical JSON (sorted keys, no whitespace)."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_canonical_json(self) -> str:
        """Canonical JSON string for hashing and storage."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @model_validator(mode="after")
    def check_size(self) -> "StrategySpec":
        if len(self.to_canonical_json().encode()) > MAX_SPEC_BYTES:
            raise ValueError(f"Spec exceeds {MAX_SPEC_BYTES} bytes.")
        return self


# ---------------------------------------------------------------------------
# Load / validate from file or dict
# ---------------------------------------------------------------------------

def validate_spec(data: dict) -> StrategySpec:
    """Parse and validate a strategy spec dict. Raises ValueError on failure."""
    return StrategySpec.model_validate(data)


def load_spec(path: str) -> StrategySpec:
    """Load and validate a JSON spec file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return validate_spec(data)


def save_spec(spec: StrategySpec, directory: str) -> str:
    """Save spec to directory/<spec.id>.json and return the path."""
    import os
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{spec.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(spec.to_canonical_json())
    return path
