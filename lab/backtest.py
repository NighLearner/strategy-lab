"""backtest.py — Trade simulation per ticker following backtest_rules.md.

Execution model (exact):
1. Signal computed on bar t using data through close of t.
2. Entry at open of t+1.
3. One position per ticker at a time.
4. Costs: (cost_bps + slippage_bps) / 10000 per side.
5. Exit priority: stop → take-profit → trailing-ATR → rule exits → time exit.
6. If stop and target hit same bar: stop wins.
7. Time exit at CLOSE of hold_bars-th bar (entry bar = bar 0).
8. Gaps > 5 days inside trade → discard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from lab.indicators import atr as compute_atr, cmf as compute_cmf, mfi as compute_mfi, rsi as compute_rsi, rel_volume as compute_rel_volume
from lab.spec import StrategySpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-trade record
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    ticker: str
    sector: str
    variant_id: str
    direction: str  # "long" | "short"
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    exit_reason: str
    bars_held: int
    gross_return_pct: float
    net_return_pct: float
    mae_pct: float   # maximum adverse excursion
    mfe_pct: float   # maximum favourable excursion
    rel_volume_at_signal: float
    cmf_at_signal: float
    mfi_at_signal: float
    rsi_at_signal: float
    forced_close: bool = False


# ---------------------------------------------------------------------------
# Cost helpers
# ---------------------------------------------------------------------------

def _entry_cost_mult(cost_bps: float, slip_bps: float, direction: str) -> float:
    c = (cost_bps + slip_bps) / 10000
    return (1 + c) if direction == "long" else (1 - c)


def _exit_cost_mult(cost_bps: float, slip_bps: float, direction: str) -> float:
    c = (cost_bps + slip_bps) / 10000
    return (1 - c) if direction == "long" else (1 + c)


def _gross_return(entry_px: float, exit_px: float, direction: str) -> float:
    if direction == "long":
        return (exit_px / entry_px - 1) * 100
    else:
        return (1 - exit_px / entry_px) * 100


# ---------------------------------------------------------------------------
# Single trade simulation
# ---------------------------------------------------------------------------

def _simulate_trade(
    df: pd.DataFrame,
    entry_bar_idx: int,
    signal_bar_idx: int,
    direction: str,
    spec: StrategySpec,
    exit_signals: pd.Series,
    cost_bps: float,
    slip_bps: float,
    stop_before_target: bool,
    atr_series: pd.Series,
    ticker: str,
    sector: str,
    variant_id: str,
    context: dict,
) -> Optional[Trade]:
    """Simulate a single trade from entry_bar_idx onward."""
    if entry_bar_idx >= len(df):
        return None

    entry_row = df.iloc[entry_bar_idx]
    raw_entry_px = float(entry_row["Open"])
    if raw_entry_px <= 0 or np.isnan(raw_entry_px):
        return None

    entry_cost = _entry_cost_mult(cost_bps, slip_bps, direction)
    entry_price = raw_entry_px * entry_cost

    hold_bars = spec.exit.hold_bars or 60
    stop_pct = spec.exit.stop_loss_pct
    tp_pct = spec.exit.take_profit_pct
    trail_mult = spec.exit.trailing_atr_mult

    # Compute stop / take-profit prices
    if stop_pct is not None:
        if direction == "long":
            stop_price = raw_entry_px * (1 - stop_pct / 100)
        else:
            stop_price = raw_entry_px * (1 + stop_pct / 100)
    else:
        stop_price = None

    if tp_pct is not None:
        if direction == "long":
            tp_price = raw_entry_px * (1 + tp_pct / 100)
        else:
            tp_price = raw_entry_px * (1 - tp_pct / 100)
    else:
        tp_price = None

    trail_stop: Optional[float] = None
    highest_close_since_entry = raw_entry_px if direction == "long" else raw_entry_px

    exit_price_raw: Optional[float] = None
    exit_reason = "time"
    exit_bar = entry_bar_idx

    mae = 0.0
    mfe = 0.0

    for bi in range(entry_bar_idx, min(entry_bar_idx + hold_bars + 1, len(df))):
        row = df.iloc[bi]
        bar_o, bar_h, bar_l, bar_c = (
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
        )

        # Check for large gap (> 5 trading days) inside trade
        if bi > entry_bar_idx:
            prev_date = df.index[bi - 1]
            curr_date = df.index[bi]
            gap_days = (curr_date - prev_date).days
            if gap_days > 7:  # ~5 trading days
                exit_price_raw = bar_o
                exit_reason = "gap_discard"
                exit_bar = bi
                break

        # Update trail stop (active from next bar after entry)
        if trail_mult is not None and bi > entry_bar_idx:
            atr_val = atr_series.iloc[bi] if bi < len(atr_series) else np.nan
            if not np.isnan(atr_val):
                if direction == "long":
                    highest_close_since_entry = max(highest_close_since_entry, bar_c)
                    new_trail = highest_close_since_entry - trail_mult * atr_val
                    trail_stop = max(trail_stop or 0, new_trail)
                else:
                    highest_close_since_entry = min(highest_close_since_entry, bar_c)
                    new_trail = highest_close_since_entry + trail_mult * atr_val
                    trail_stop = min(trail_stop or float("inf"), new_trail)

        # --- Check exits for this bar ---
        stop_hit = False
        tp_hit = False

        if stop_price is not None:
            if direction == "long" and bar_l <= stop_price:
                stop_hit = True
            elif direction == "short" and bar_h >= stop_price:
                stop_hit = True

        if tp_price is not None:
            if direction == "long" and bar_h >= tp_price:
                tp_hit = True
            elif direction == "short" and bar_l <= tp_price:
                tp_hit = True

        # Trail stop
        trail_hit = False
        if trail_stop is not None and bi > entry_bar_idx:
            if direction == "long" and bar_l <= trail_stop:
                trail_hit = True
            elif direction == "short" and bar_h >= trail_stop:
                trail_hit = True

        # Determine exit
        if stop_hit and tp_hit:
            # Both hit: stop wins if stop_before_target
            if stop_before_target:
                exit_price_raw = min(bar_o, stop_price) if direction == "long" else max(bar_o, stop_price)
                exit_reason = "stop"
            else:
                exit_price_raw = max(bar_o, tp_price) if direction == "long" else min(bar_o, tp_price)
                exit_reason = "take_profit"
            exit_bar = bi
            break
        elif stop_hit:
            exit_price_raw = min(bar_o, stop_price) if direction == "long" else max(bar_o, stop_price)
            exit_reason = "stop"
            exit_bar = bi
            break
        elif tp_hit:
            exit_price_raw = max(bar_o, tp_price) if direction == "long" else min(bar_o, tp_price)
            exit_reason = "take_profit"
            exit_bar = bi
            break
        elif trail_hit:
            exit_price_raw = min(bar_o, trail_stop) if direction == "long" else max(bar_o, trail_stop)
            exit_reason = "trailing_stop"
            exit_bar = bi
            break
        elif bi > entry_bar_idx and exit_signals.iloc[bi]:
            # Rule exit: execute at NEXT bar's open
            next_bi = bi + 1
            if next_bi < len(df):
                exit_price_raw = float(df.iloc[next_bi]["Open"])
                exit_reason = "rule"
                exit_bar = next_bi
            else:
                exit_price_raw = bar_c
                exit_reason = "rule_last"
                exit_bar = bi
            break

        # Time exit: at CLOSE of hold_bars-th bar
        bars_so_far = bi - entry_bar_idx
        if bars_so_far >= hold_bars:
            exit_price_raw = bar_c
            exit_reason = "time"
            exit_bar = bi
            break

        # Track MAE/MFE
        if direction == "long":
            mae = min(mae, (bar_l / raw_entry_px - 1) * 100)
            mfe = max(mfe, (bar_h / raw_entry_px - 1) * 100)
        else:
            mae = min(mae, (1 - bar_h / raw_entry_px) * 100)
            mfe = max(mfe, (1 - bar_l / raw_entry_px) * 100)

    if exit_price_raw is None or np.isnan(exit_price_raw):
        # Force close at last bar
        exit_bar = len(df) - 1
        exit_price_raw = float(df.iloc[exit_bar]["Close"])
        exit_reason = "forced_close"

    # Apply exit costs
    exit_cost = _exit_cost_mult(cost_bps, slip_bps, direction)
    exit_price_net = exit_price_raw * exit_cost

    gross_ret = _gross_return(raw_entry_px, exit_price_raw, direction)
    net_ret = _gross_return(entry_price, exit_price_net, direction)

    forced = exit_reason in ("forced_close", "gap_discard")
    if exit_reason == "gap_discard":
        return None  # discard as per rules

    signal_row = df.iloc[signal_bar_idx]
    rv = float(context.get("rel_volume", pd.Series([np.nan])).iloc[signal_bar_idx]) if "rel_volume" in context else np.nan
    cmf_val = float(context.get("cmf", pd.Series([np.nan])).iloc[signal_bar_idx]) if "cmf" in context else np.nan
    mfi_val = float(context.get("mfi", pd.Series([np.nan])).iloc[signal_bar_idx]) if "mfi" in context else np.nan
    rsi_val = float(context.get("rsi", pd.Series([np.nan])).iloc[signal_bar_idx]) if "rsi" in context else np.nan

    return Trade(
        ticker=ticker,
        sector=sector,
        variant_id=variant_id,
        direction=direction,
        signal_date=df.index[signal_bar_idx],
        entry_date=df.index[entry_bar_idx],
        entry_price=raw_entry_px,
        exit_date=df.index[exit_bar],
        exit_price=exit_price_raw,
        exit_reason=exit_reason,
        bars_held=exit_bar - entry_bar_idx,
        gross_return_pct=gross_ret,
        net_return_pct=net_ret,
        mae_pct=mae,
        mfe_pct=mfe,
        rel_volume_at_signal=rv,
        cmf_at_signal=cmf_val,
        mfi_at_signal=mfi_val,
        rsi_at_signal=rsi_val,
        forced_close=forced,
    )


# ---------------------------------------------------------------------------
# Public backtest function
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame,
    entry_signals: pd.Series,
    exit_signals: pd.Series,
    spec: StrategySpec,
    variant_id: str,
    ticker: str,
    sector: str = "",
    cost_bps: float = 5.0,
    slip_bps: float = 5.0,
    stop_before_target: bool = True,
) -> pd.DataFrame:
    """Run backtest for one ticker.  Returns a DataFrame of trades."""
    if df.empty or not entry_signals.any():
        return pd.DataFrame()

    atr_series = compute_atr(df, 14)
    context = {
        "rel_volume": compute_rel_volume(df),
        "cmf": compute_cmf(df),
        "mfi": compute_mfi(df),
        "rsi": compute_rsi(df["Close"]),
    }

    trades: list[Trade] = []
    in_position = False
    position_end_bar: int = -1

    for i, signal_bar in enumerate(df.index):
        if i <= position_end_bar:
            continue

        if not entry_signals.iloc[i]:
            continue

        entry_bar_i = i + 1
        if entry_bar_i >= len(df):
            break

        in_position = True
        trade = _simulate_trade(
            df=df,
            entry_bar_idx=entry_bar_i,
            signal_bar_idx=i,
            direction=spec.direction,
            spec=spec,
            exit_signals=exit_signals,
            cost_bps=cost_bps,
            slip_bps=slip_bps,
            stop_before_target=stop_before_target,
            atr_series=atr_series,
            ticker=ticker,
            sector=sector,
            variant_id=variant_id,
            context=context,
        )

        if trade is not None:
            trades.append(trade)
            # Find exit bar in original index
            try:
                position_end_bar = df.index.get_loc(trade.exit_date)
            except KeyError:
                position_end_bar = i + 1

    if not trades:
        return pd.DataFrame()

    records = [t.__dict__ for t in trades]
    return pd.DataFrame(records)
