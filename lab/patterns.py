"""patterns.py — Vectorised candlestick pattern detectors.

Each function takes an OHLCV DataFrame and returns a boolean Series.
True on the bar where the pattern *completes* (the last candle of the pattern).

Conventions (from strategies_seed.md):
    body = |C - O|
    range = H - L  (treat range==0 as "no pattern")
    upper = H - max(O, C)
    lower = min(O, C) - L
    bull = C > O
    bear = C < O
    avg_body = SMA of body over 14 bars, shifted by 1 (no lookahead)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lab.indicators import sma


# ---------------------------------------------------------------------------
# Bar-level helpers (all vectorised)
# ---------------------------------------------------------------------------

def _body(df: pd.DataFrame) -> pd.Series:
    return (df["Close"] - df["Open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return df["High"] - df["Low"]


def _upper(df: pd.DataFrame) -> pd.Series:
    return df["High"] - df[["Open", "Close"]].max(axis=1)


def _lower(df: pd.DataFrame) -> pd.Series:
    return df[["Open", "Close"]].min(axis=1) - df["Low"]


def _bull(df: pd.DataFrame) -> pd.Series:
    return df["Close"] > df["Open"]


def _bear(df: pd.DataFrame) -> pd.Series:
    return df["Close"] < df["Open"]


def _avg_body(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """SMA of body over `period` bars, shifted by 1 (excludes current bar)."""
    return sma(_body(df), period).shift(1)


def _no_range(df: pd.DataFrame) -> pd.Series:
    return _range(df) == 0


# ---------------------------------------------------------------------------
# A. Candlestick Patterns
# ---------------------------------------------------------------------------

def three_white_soldiers(
    df: pd.DataFrame,
    body_ratio: float = 0.5,
    upper_ratio: float = 0.3,
) -> pd.Series:
    """A1. Three White Soldiers — bullish reversal/continuation."""
    O, H, L, C = df["Open"], df["High"], df["Low"], df["Close"]
    body = _body(df)
    rng = _range(df).replace(0, np.nan)
    upper = _upper(df)
    bull = _bull(df)
    avg_b = _avg_body(df)

    def row_ok(i: int) -> pd.Series:
        b = body.shift(i)
        r = rng.shift(i)
        u = upper.shift(i)
        bl = bull.shift(i)
        ab = avg_b.shift(i)
        return bl & (b >= body_ratio * r) & (u <= upper_ratio * r) & (b >= 0.5 * ab)

    cond_i2 = row_ok(2)
    cond_i1 = row_ok(1)
    cond_i0 = row_ok(0)

    closes_ascending = (C.shift(1) < C) & (C.shift(2) < C.shift(1))
    open_inside_i2_i1 = (O.shift(1) > O.shift(2)) & (O.shift(1) < C.shift(2))
    open_inside_i1_i0 = (O > O.shift(1)) & (O < C.shift(1))

    return (
        cond_i2 & cond_i1 & cond_i0
        & closes_ascending
        & open_inside_i2_i1
        & open_inside_i1_i0
        & ~_no_range(df)
    ).fillna(False)


def three_black_crows(
    df: pd.DataFrame,
    body_ratio: float = 0.5,
    lower_ratio: float = 0.3,
) -> pd.Series:
    """A2. Three Black Crows — bearish."""
    O, H, L, C = df["Open"], df["High"], df["Low"], df["Close"]
    body = _body(df)
    rng = _range(df).replace(0, np.nan)
    lower = _lower(df)
    bear = _bear(df)
    avg_b = _avg_body(df)

    def row_ok(i: int) -> pd.Series:
        b = body.shift(i)
        r = rng.shift(i)
        lo = lower.shift(i)
        be = bear.shift(i)
        ab = avg_b.shift(i)
        return be & (b >= body_ratio * r) & (lo <= lower_ratio * r) & (b >= 0.5 * ab)

    cond_i2 = row_ok(2)
    cond_i1 = row_ok(1)
    cond_i0 = row_ok(0)

    closes_descending = (C.shift(1) > C) & (C.shift(2) > C.shift(1))
    open_inside_i2_i1 = (O.shift(1) < O.shift(2)) & (O.shift(1) > C.shift(2))
    open_inside_i1_i0 = (O < O.shift(1)) & (O > C.shift(1))

    return (
        cond_i2 & cond_i1 & cond_i0
        & closes_descending
        & open_inside_i2_i1
        & open_inside_i1_i0
        & ~_no_range(df)
    ).fillna(False)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """A3. Bullish Engulfing."""
    O, C = df["Open"], df["Close"]
    return (
        _bear(df).shift(1)
        & _bull(df)
        & (O <= C.shift(1))
        & (C >= O.shift(1))
        & (_body(df) > _body(df).shift(1))
    ).fillna(False)


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """A4. Bearish Engulfing."""
    O, C = df["Open"], df["Close"]
    return (
        _bull(df).shift(1)
        & _bear(df)
        & (O >= C.shift(1))
        & (C <= O.shift(1))
        & (_body(df) > _body(df).shift(1))
    ).fillna(False)


def hammer(df: pd.DataFrame) -> pd.Series:
    """A5. Hammer — bullish reversal after downtrend."""
    body = _body(df)
    rng = _range(df).replace(0, np.nan)
    lower = _lower(df)
    upper = _upper(df)
    low_close = df[["Open", "Close"]].min(axis=1)

    body_in_top_third = low_close > (df["Low"] + 2 / 3 * rng)
    prior_decline = df["Close"].shift(1) < df["Close"].shift(6)

    return (
        (lower >= 2 * body.replace(0, np.nan))
        & (upper <= 0.1 * rng)
        & body_in_top_third
        & prior_decline
        & ~_no_range(df)
    ).fillna(False)


def shooting_star(df: pd.DataFrame) -> pd.Series:
    """A6. Shooting Star — bearish reversal after uptrend."""
    body = _body(df)
    rng = _range(df).replace(0, np.nan)
    upper = _upper(df)
    lower = _lower(df)
    high_close = df[["Open", "Close"]].max(axis=1)

    body_in_bottom_third = high_close < (df["Low"] + 1 / 3 * rng)
    prior_advance = df["Close"].shift(1) > df["Close"].shift(6)

    return (
        (upper >= 2 * body.replace(0, np.nan))
        & (lower <= 0.1 * rng)
        & body_in_bottom_third
        & prior_advance
        & ~_no_range(df)
    ).fillna(False)


def morning_star(df: pd.DataFrame) -> pd.Series:
    """A7. Morning Star — bullish reversal (3-bar pattern)."""
    body = _body(df)
    avg_b = _avg_body(df)
    O, C = df["Open"], df["Close"]

    # i-2: long bear
    long_bear = _bear(df).shift(2) & (body.shift(2) >= avg_b.shift(2))
    # i-1: small body, closes/gaps below C[i-2]
    small_body = body.shift(1) <= 0.3 * avg_b.shift(1)
    below_prev = C.shift(1) < C.shift(2)
    # i: bull, closes above midpoint of i-2 body
    midpoint_i2 = (O.shift(2) + C.shift(2)) / 2
    bull_closes_above_mid = _bull(df) & (C > midpoint_i2)

    return (long_bear & small_body & below_prev & bull_closes_above_mid).fillna(False)


def evening_star(df: pd.DataFrame) -> pd.Series:
    """A8. Evening Star — bearish reversal (3-bar)."""
    body = _body(df)
    avg_b = _avg_body(df)
    O, C = df["Open"], df["Close"]

    long_bull = _bull(df).shift(2) & (body.shift(2) >= avg_b.shift(2))
    small_body = body.shift(1) <= 0.3 * avg_b.shift(1)
    above_prev = C.shift(1) > C.shift(2)
    midpoint_i2 = (O.shift(2) + C.shift(2)) / 2
    bear_closes_below_mid = _bear(df) & (C < midpoint_i2)

    return (long_bull & small_body & above_prev & bear_closes_below_mid).fillna(False)


def bullish_harami(df: pd.DataFrame) -> pd.Series:
    """A9. Bullish Harami."""
    O, C = df["Open"], df["Close"]
    avg_b = _avg_body(df)
    # i-1: large bear
    large_bear = _bear(df).shift(1) & (_body(df).shift(1) >= avg_b.shift(1))
    # i: bull, body inside [C[i-1], O[i-1]]
    body_inside = (
        (O > C.shift(1)) & (O < O.shift(1))
        & (C > C.shift(1)) & (C < O.shift(1))
    )
    return (large_bear & _bull(df) & body_inside).fillna(False)


def bearish_harami(df: pd.DataFrame) -> pd.Series:
    """A10. Bearish Harami."""
    O, C = df["Open"], df["Close"]
    avg_b = _avg_body(df)
    large_bull = _bull(df).shift(1) & (_body(df).shift(1) >= avg_b.shift(1))
    body_inside = (
        (O < C.shift(1)) & (O > O.shift(1))
        & (C < C.shift(1)) & (C > O.shift(1))
    )
    return (large_bull & _bear(df) & body_inside).fillna(False)


def piercing_line(df: pd.DataFrame) -> pd.Series:
    """A11. Piercing Line — bullish."""
    O, C = df["Open"], df["Close"]
    midpoint_prev = (O.shift(1) + C.shift(1)) / 2
    return (
        _bear(df).shift(1)
        & _bull(df)
        & (O < C.shift(1))
        & (C > midpoint_prev)
        & (C < O.shift(1))
    ).fillna(False)


def dark_cloud_cover(df: pd.DataFrame) -> pd.Series:
    """A12. Dark Cloud Cover — bearish."""
    O, C = df["Open"], df["Close"]
    midpoint_prev = (O.shift(1) + C.shift(1)) / 2
    return (
        _bull(df).shift(1)
        & _bear(df)
        & (O > C.shift(1))
        & (C < midpoint_prev)
        & (C > O.shift(1))
    ).fillna(False)


def doji(df: pd.DataFrame, body_ratio: float = 0.1) -> pd.Series:
    """A13. Doji — body <= body_ratio * range."""
    rng = _range(df).replace(0, np.nan)
    return (_body(df) <= body_ratio * rng).fillna(False)


def inside_bar_breakout_up(df: pd.DataFrame) -> pd.Series:
    """A14. Inside Bar breakout — long (closes above i-2 high)."""
    H, L, C = df["High"], df["Low"], df["Close"]
    inside = (H.shift(1) < H.shift(2)) & (L.shift(1) > L.shift(2))
    return (inside & (C > H.shift(2))).fillna(False)


def inside_bar_breakout_down(df: pd.DataFrame) -> pd.Series:
    """A14. Inside Bar breakout — short (closes below i-2 low)."""
    H, L, C = df["High"], df["Low"], df["Close"]
    inside = (H.shift(1) < H.shift(2)) & (L.shift(1) > L.shift(2))
    return (inside & (C < L.shift(2))).fillna(False)


def tweezer_bottom(df: pd.DataFrame, tol_pct: float = 0.001) -> pd.Series:
    """A15. Tweezer Bottom — lows within tol_pct, after 5-bar decline, bar i is bull."""
    L, C = df["Low"], df["Close"]
    lows_match = (L - L.shift(1)).abs() / L.shift(1).replace(0, np.nan) <= tol_pct
    prior_decline = C.shift(1) < C.shift(6)
    return (lows_match & prior_decline & _bull(df)).fillna(False)


def tweezer_top(df: pd.DataFrame, tol_pct: float = 0.001) -> pd.Series:
    """A15. Tweezer Top — highs within tol_pct, after 5-bar advance, bar i is bear."""
    H, C = df["High"], df["Close"]
    highs_match = (H - H.shift(1)).abs() / H.shift(1).replace(0, np.nan) <= tol_pct
    prior_advance = C.shift(1) > C.shift(6)
    return (highs_match & prior_advance & _bear(df)).fillna(False)


def nr7_breakout_up(df: pd.DataFrame) -> pd.Series:
    """D2/A-extra. NR7 breakout — bar i-1 is the narrowest range of last 7; bar i close > H[i-1]."""
    rng = _range(df)
    min_range_7 = rng.shift(1).rolling(7, min_periods=7).min()
    nr7 = rng.shift(1) == min_range_7
    return (nr7 & (df["Close"] > df["High"].shift(1))).fillna(False)


# ---------------------------------------------------------------------------
# Pattern dispatcher — used by signals.py
# ---------------------------------------------------------------------------

PATTERN_MAP = {
    "three_white_soldiers": three_white_soldiers,
    "three_black_crows": three_black_crows,
    "bullish_engulfing": bullish_engulfing,
    "bearish_engulfing": bearish_engulfing,
    "hammer": hammer,
    "shooting_star": shooting_star,
    "morning_star": morning_star,
    "evening_star": evening_star,
    "bullish_harami": bullish_harami,
    "bearish_harami": bearish_harami,
    "piercing_line": piercing_line,
    "dark_cloud_cover": dark_cloud_cover,
    "doji": doji,
    "inside_bar_breakout_up": inside_bar_breakout_up,
    "inside_bar_breakout_down": inside_bar_breakout_down,
    "tweezer_bottom": tweezer_bottom,
    "tweezer_top": tweezer_top,
    "nr7_breakout_up": nr7_breakout_up,
}


def compute_pattern(df: pd.DataFrame, name: str, params: dict | None = None) -> pd.Series:
    """Evaluate a named pattern with optional params."""
    if name not in PATTERN_MAP:
        raise ValueError(f"Unknown pattern: '{name}'")
    fn = PATTERN_MAP[name]
    return fn(df, **(params or {}))
