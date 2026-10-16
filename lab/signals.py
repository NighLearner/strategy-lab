"""signals.py — Evaluate strategy spec entry/exit condition trees into boolean Series."""

from __future__ import annotations

import logging
from typing import Union

import numpy as np
import pandas as pd

from lab.indicators import compute_indicator
from lab.patterns import compute_pattern
from lab.spec import (
    AllGroup,
    AnyGroup,
    BetweenOperand,
    ComparisonLeaf,
    ConditionType,
    ExitCondition,
    FieldOperand,
    IndicatorOperand,
    PatternLeaf,
    StrategySpec,
    ValueOperand,
)

logger = logging.getLogger(__name__)

FIELD_COL_MAP = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}


# ---------------------------------------------------------------------------
# Operand evaluation
# ---------------------------------------------------------------------------

def _eval_operand(
    df: pd.DataFrame,
    operand: Union[FieldOperand, IndicatorOperand, ValueOperand, BetweenOperand],
) -> pd.Series:
    if isinstance(operand, FieldOperand):
        col = FIELD_COL_MAP[operand.field]
        return df[col].astype(float)
    elif isinstance(operand, IndicatorOperand):
        return compute_indicator(df, operand.indicator, operand.params, operand.output, operand.shift)
    elif isinstance(operand, ValueOperand):
        return pd.Series(operand.value, index=df.index, dtype=float)
    else:
        raise TypeError(f"Unexpected operand type: {type(operand)}")


# ---------------------------------------------------------------------------
# Condition evaluation (recursive)
# ---------------------------------------------------------------------------

def _eval_condition(df: pd.DataFrame, cond: ConditionType) -> pd.Series:
    if isinstance(cond, AllGroup):
        result = pd.Series(True, index=df.index)
        for sub in cond.all:
            result = result & _eval_condition(df, sub)
        return result.fillna(False)

    elif isinstance(cond, AnyGroup):
        result = pd.Series(False, index=df.index)
        for sub in cond.any:
            result = result | _eval_condition(df, sub)
        return result.fillna(False)

    elif isinstance(cond, PatternLeaf):
        return compute_pattern(df, cond.pattern, cond.params)

    elif isinstance(cond, ComparisonLeaf):
        left_series = _eval_operand(df, cond.left)

        if isinstance(cond.right, BetweenOperand):
            return (
                (left_series >= cond.right.low) & (left_series <= cond.right.high)
            ).fillna(False)

        right_series = _eval_operand(df, cond.right)

        op = cond.op
        if op == "<":
            result = left_series < right_series
        elif op == "<=":
            result = left_series <= right_series
        elif op == ">":
            result = left_series > right_series
        elif op == ">=":
            result = left_series >= right_series
        elif op == "cross_above":
            # True when left[t-1] <= right[t-1] AND left[t] > right[t]
            result = (left_series.shift(1) <= right_series.shift(1)) & (left_series > right_series)
        elif op == "cross_below":
            result = (left_series.shift(1) >= right_series.shift(1)) & (left_series < right_series)
        else:
            raise ValueError(f"Unknown operator: '{op}'")

        return result.fillna(False)
    else:
        raise TypeError(f"Unknown condition type: {type(cond)}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_entry_signals(df: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """Evaluate the entry condition tree, return boolean Series indexed like df."""
    return _eval_condition(df, spec.entry)


def compute_exit_conditions(df: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """Evaluate the rule-based exit conditions (exit.any), return boolean Series."""
    if not spec.exit.any:
        return pd.Series(False, index=df.index)
    exit_any = AnyGroup(any=spec.exit.any)
    return _eval_condition(df, exit_any)


# ---------------------------------------------------------------------------
# Variant expansion
# ---------------------------------------------------------------------------

def _set_nested(d: dict, dot_path: str, value) -> dict:
    """Set a value in a nested dict using a dot-path key (mutates d)."""
    keys = dot_path.split(".")
    current = d
    for key in keys[:-1]:
        if key.isdigit():
            key = int(key)  # type: ignore[assignment]
        current = current[key]  # type: ignore[index]
    last = keys[-1]
    if last.isdigit():
        last = int(last)  # type: ignore[assignment]
    current[last] = value  # type: ignore[index]
    return d


def expand_variants(spec: StrategySpec, max_variants: int = 30) -> list[StrategySpec]:
    """Expand params_grid into a list of variant StrategySpecs with stable variant IDs.

    The base spec (no grid overrides) is always included.
    """
    import itertools
    import copy

    if not spec.params_grid:
        return [spec]

    keys = list(spec.params_grid.keys())
    value_lists = [spec.params_grid[k] for k in keys]

    variants: list[StrategySpec] = []
    base_dict = spec.model_dump(mode="json")

    for combo in itertools.product(*value_lists):
        d = copy.deepcopy(base_dict)
        try:
            for k, v in zip(keys, combo):
                _set_nested(d, k, v)
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Skipping variant (bad grid path '%s'): %s", k, exc)
            continue

        try:
            variant = StrategySpec.model_validate(d)
        except Exception as exc:
            logger.warning("Skipping invalid variant: %s", exc)
            continue

        variants.append(variant)
        if len(variants) >= max_variants:
            break

    return variants if variants else [spec]
