"""metrics.py — Per-ticker, per-sector, overall metrics + verdict tiers.

Implements all metrics from backtest_rules.md §3, §4, §5.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------

def _safe_div(a: float, b: float) -> Optional[float]:
    return a / b if b and not math.isnan(b) else None


def compute_trade_stats(trades: pd.DataFrame) -> dict[str, Any]:
    """Compute per-trade statistics from a trades DataFrame."""
    if trades is None or trades.empty:
        return {"n_trades": 0}

    rets = trades["net_return_pct"]
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    n = len(rets)

    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0

    payoff = _safe_div(avg_win, abs(avg_loss)) if avg_loss < 0 else None
    pf_num = float(wins.sum())
    pf_den = abs(float(losses.sum()))
    profit_factor = _safe_div(pf_num, pf_den)
    win_rate = len(wins) / n if n > 0 else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss if n > 0 else 0.0

    std_ret = float(rets.std(ddof=1)) if n > 1 else None
    t_stat = (
        float(rets.mean()) / (std_ret / math.sqrt(n))
        if std_ret and n >= 30
        else None
    )

    # Max consecutive losses
    streak = 0
    max_streak = 0
    for r in rets:
        if r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "n_trades": n,
        "win_rate": round(win_rate, 4),
        "avg_return": round(float(rets.mean()), 4),
        "median_return": round(float(rets.median()), 4),
        "std_return": round(std_ret, 4) if std_ret else None,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "payoff_ratio": round(payoff, 4) if payoff else None,
        "profit_factor": round(profit_factor, 4) if profit_factor else None,
        "expectancy": round(expectancy, 4),
        "t_stat": round(t_stat, 4) if t_stat else None,
        "avg_bars_held": round(float(trades["bars_held"].mean()), 2) if "bars_held" in trades else None,
        "max_consecutive_losses": max_streak,
    }


# ---------------------------------------------------------------------------
# Equity curve metrics
# ---------------------------------------------------------------------------

def compute_equity_curve_stats(trades: pd.DataFrame) -> dict[str, Any]:
    """Compute equity-curve statistics using cumulative percent returns (non-compounding)."""
    if trades is None or trades.empty:
        return {}

    trades_sorted = trades.sort_values("exit_date").copy()
    cumret = trades_sorted["net_return_pct"].cumsum()

    total_return = float(cumret.iloc[-1])

    # Max drawdown
    peak = cumret.cummax()
    dd = cumret - peak
    max_drawdown = float(dd.min())

    n_days = (trades_sorted["exit_date"].max() - trades_sorted["entry_date"].min()).days
    years = n_days / 365.25
    ann_return = total_return / years if years > 0 else 0.0
    calmar = _safe_div(ann_return, abs(max_drawdown)) if max_drawdown < 0 else None

    # Exposure
    # Rough estimate: count unique open-trade dates
    all_dates: set = set()
    for _, row in trades_sorted.iterrows():
        d = pd.date_range(row["entry_date"], row["exit_date"], freq="B")
        all_dates.update(d.tolist())
    total_bdays = pd.bdate_range(
        trades_sorted["entry_date"].min(),
        trades_sorted["exit_date"].max(),
    )
    exposure_pct = len(all_dates) / len(total_bdays) if len(total_bdays) > 0 else 0.0

    return {
        "total_return": round(total_return, 4),
        "max_drawdown": round(max_drawdown, 4),
        "calmar": round(calmar, 4) if calmar else None,
        "ann_return": round(ann_return, 4),
        "exposure_pct": round(exposure_pct, 4),
    }


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------

def compute_event_study(
    df: pd.DataFrame,
    signal_dates: pd.DatetimeIndex,
    horizons: list[int] = None,
) -> dict[str, Any]:
    """Forward close-to-close returns from entry open for each signal."""
    horizons = horizons or [1, 3, 5, 10, 20]
    result: dict[str, Any] = {}
    closes = df["Close"]

    # Unconditional baseline — all bars
    all_forward: dict[int, list[float]] = {h: [] for h in horizons}
    for i in range(len(df)):
        for h in horizons:
            if i + h < len(df):
                all_forward[h].append(
                    (closes.iloc[i + h] / closes.iloc[i] - 1) * 100
                )

    signal_forward: dict[int, list[float]] = {h: [] for h in horizons}
    for sd in signal_dates:
        if sd not in df.index:
            continue
        loc = df.index.get_loc(sd)
        for h in horizons:
            if loc + h < len(df):
                signal_forward[h].append(
                    (closes.iloc[loc + h] / closes.iloc[loc] - 1) * 100
                )

    for h in horizons:
        s_arr = np.array(signal_forward[h]) if signal_forward[h] else np.array([np.nan])
        a_arr = np.array(all_forward[h]) if all_forward[h] else np.array([np.nan])
        result[f"h{h}_signal_mean"] = round(float(np.nanmean(s_arr)), 4)
        result[f"h{h}_signal_median"] = round(float(np.nanmedian(s_arr)), 4)
        result[f"h{h}_pct_positive"] = round(float((s_arr > 0).mean()), 4) if len(s_arr) > 0 else None
        result[f"h{h}_baseline_mean"] = round(float(np.nanmean(a_arr)), 4)
        result[f"h{h}_excess_return"] = round(result[f"h{h}_signal_mean"] - result[f"h{h}_baseline_mean"], 4)

    return result


# ---------------------------------------------------------------------------
# Volume/flow stats at signal vs baseline
# ---------------------------------------------------------------------------

def compute_flow_stats(df: pd.DataFrame, signal_dates: pd.DatetimeIndex) -> dict[str, Any]:
    """Compare volume/flow indicators at signal bars vs unconditional average."""
    from lab.indicators import rel_volume as compute_rv, cmf as compute_cmf, mfi as compute_mfi, obv as compute_obv

    rv = compute_rv(df)
    cmf_s = compute_cmf(df)
    mfi_s = compute_mfi(df)
    obv_s = compute_obv(df)
    obv_slope = obv_s.diff(10)

    def _at_signals(series: pd.Series) -> list[float]:
        vals = []
        for sd in signal_dates:
            if sd in series.index:
                v = series[sd]
                if not np.isnan(v):
                    vals.append(float(v))
        return vals

    def _stats(vals_signal: list, baseline: pd.Series) -> dict:
        s_arr = np.array(vals_signal) if vals_signal else np.array([np.nan])
        b_arr = baseline.dropna().values
        return {
            "signal_mean": round(float(np.nanmean(s_arr)), 4),
            "baseline_mean": round(float(np.nanmean(b_arr)), 4),
        }

    return {
        "rel_volume": _stats(_at_signals(rv), rv),
        "cmf": _stats(_at_signals(cmf_s), cmf_s),
        "mfi": _stats(_at_signals(mfi_s), mfi_s),
        "obv_slope": _stats(_at_signals(obv_slope), obv_slope),
    }


# ---------------------------------------------------------------------------
# IS / OOS split
# ---------------------------------------------------------------------------

def is_oos_split(
    trades: pd.DataFrame,
    oos_fraction: float = 0.30,
    all_start: pd.Timestamp = None,
    all_end: pd.Timestamp = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split trades into in-sample and out-of-sample by entry date."""
    if trades.empty:
        return trades, trades

    start = all_start or trades["entry_date"].min()
    end = all_end or trades["entry_date"].max()
    split_date = start + (end - start) * (1 - oos_fraction)

    is_trades = trades[trades["entry_date"] < split_date].copy()
    oos_trades = trades[trades["entry_date"] >= split_date].copy()
    return is_trades, oos_trades


# ---------------------------------------------------------------------------
# Buy-and-hold baseline
# ---------------------------------------------------------------------------

def buy_and_hold_return(df: pd.DataFrame) -> float:
    """Return percent return if held from first to last close."""
    if df.empty or len(df) < 2:
        return 0.0
    return float((df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100)


# ---------------------------------------------------------------------------
# Random-entry baseline
# ---------------------------------------------------------------------------

def random_entry_baseline(
    df: pd.DataFrame,
    n_trades: int,
    spec_exit_hold_bars: int,
    variant_id: str,
    n_sims: int = 200,
) -> dict[str, Any]:
    """Run 200 random-entry simulations with matched trade count and time exit.

    Returns percentile of strategy mean return among simulations.
    Seeded from variant_id for reproducibility.
    """
    seed = int(variant_id[:8], 16) if len(variant_id) >= 8 else 42
    rng = np.random.default_rng(seed)

    closes = df["Close"].values
    n_bars = len(closes)
    sim_means: list[float] = []

    hold = spec_exit_hold_bars or 10
    max_entry = n_bars - hold - 1

    if max_entry < n_trades:
        return {"random_baseline_percentile": None, "n_sims": 0}

    for _ in range(n_sims):
        entry_idxs = rng.choice(max_entry, size=min(n_trades, max_entry), replace=False)
        rets: list[float] = []
        for ei in entry_idxs:
            exit_idx = min(ei + hold, n_bars - 1)
            ret = (closes[exit_idx] / closes[ei] - 1) * 100
            rets.append(ret)
        sim_means.append(float(np.mean(rets)))

    return {
        "random_baseline_mean": round(float(np.mean(sim_means)), 4),
        "random_baseline_std": round(float(np.std(sim_means)), 4),
        "n_sims": n_sims,
    }


def random_entry_percentile(strategy_mean: float, baseline: dict) -> Optional[float]:
    """Given strategy mean return and baseline stats, return approximate percentile."""
    bm = baseline.get("random_baseline_mean")
    bs = baseline.get("random_baseline_std")
    if bm is None or bs is None or bs == 0:
        return None
    z = (strategy_mean - bm) / bs
    # Approximate normal percentile
    from math import erf
    pct = 0.5 * (1 + erf(z / math.sqrt(2))) * 100
    return round(pct, 2)


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR
# ---------------------------------------------------------------------------

def benjamini_hochberg(p_values: list[float], alpha: float = 0.10) -> list[bool]:
    """Return list of booleans: True if variant passes BH FDR at level alpha."""
    m = len(p_values)
    if m == 0:
        return []
    idx = sorted(range(m), key=lambda i: p_values[i])
    reject = [False] * m
    for rank, i in enumerate(idx, start=1):
        if p_values[i] <= (rank / m) * alpha:
            reject[i] = True
    # Fill in all ranks up to the max rejected rank
    last_rejected = -1
    for rank, i in enumerate(idx, start=1):
        if reject[i]:
            last_rejected = rank
    for rank, i in enumerate(idx, start=1):
        if rank <= last_rejected:
            reject[i] = True
    return reject


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def compute_verdict(
    is_stats: dict,
    oos_stats: dict,
    verdict_config: Any,
    random_pct: Optional[float] = None,
    sector_positive_fraction: float = 0.0,
    passes_fdr: bool = True,
) -> tuple[str, list[str]]:
    """Compute verdict tier and flags.

    Returns (verdict, flags_list).
    """
    flags: list[str] = []
    oos_n = oos_stats.get("n_trades", 0)
    oos_exp = oos_stats.get("expectancy", None)
    oos_t = oos_stats.get("t_stat", None)
    oos_pf = oos_stats.get("profit_factor", None)
    is_exp = is_stats.get("expectancy", None)

    if oos_n < verdict_config.min_oos_trades:
        flags.append("few_trades")
    if is_exp is not None and oos_exp is not None and is_exp > 0 and oos_exp < 0.5 * is_exp:
        flags.append("is_oos_gap")
    if not passes_fdr:
        flags.append("fails_fdr")
    if sector_positive_fraction < verdict_config.min_sector_agreement:
        flags.append("sector_concentrated")
    if random_pct is not None and random_pct < 95 and oos_exp is not None and oos_exp > 0:
        flags.append("beats_buyhold_only_by_exposure")

    promising = (
        oos_n >= verdict_config.min_oos_trades
        and oos_exp is not None and oos_exp > 0
        and oos_t is not None and oos_t >= verdict_config.min_t_stat
        and passes_fdr
        and is_exp is not None and is_exp > 0
        and sector_positive_fraction >= verdict_config.min_sector_agreement
        and (random_pct is None or random_pct >= 95)
        and oos_pf is not None and oos_pf > 1.1
    )
    watch = (
        oos_n >= verdict_config.min_oos_trades
        and oos_exp is not None and oos_exp > 0
        and (
            (oos_t is not None and oos_t >= 1.5)
            or (random_pct is not None and random_pct >= 90)
        )
        and not promising
    )

    if promising:
        verdict = "promising"
    elif watch:
        verdict = "watch"
    else:
        verdict = "reject"

    return verdict, flags


# ---------------------------------------------------------------------------
# Aggregate metrics across tickers
# ---------------------------------------------------------------------------

def aggregate_metrics(
    all_trades: pd.DataFrame,
    oos_fraction: float = 0.30,
    horizons: list[int] = None,
) -> dict[str, Any]:
    """Aggregate metrics overall and by sector from a combined trades DataFrame."""
    horizons = horizons or [1, 3, 5, 10, 20]
    result: dict[str, Any] = {}

    if all_trades.empty:
        return result

    is_trades, oos_trades = is_oos_split(all_trades, oos_fraction)

    result["overall"] = {
        "is": compute_trade_stats(is_trades),
        "oos": compute_trade_stats(oos_trades),
        "all": compute_trade_stats(all_trades),
        "equity": compute_equity_curve_stats(all_trades),
    }

    # By sector
    if "sector" in all_trades.columns:
        sectors: dict[str, Any] = {}
        for sector, grp in all_trades.groupby("sector"):
            is_g, oos_g = is_oos_split(grp, oos_fraction)
            sectors[sector] = {
                "is": compute_trade_stats(is_g),
                "oos": compute_trade_stats(oos_g),
            }
        result["sectors"] = sectors

    return result
