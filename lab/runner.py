"""runner.py — Execute one job (strategy variant × ticker) end-to-end."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from lab.backtest import run_backtest
from lab.config import LabConfig
from lab.data import load_ticker
from lab.metrics import compute_trade_stats, is_oos_split
from lab.signals import compute_entry_signals, compute_exit_conditions
from lab.spec import StrategySpec, validate_spec
from lab.store import Store

logger = logging.getLogger(__name__)


def run_job(
    job: dict,
    store: Store,
    config: LabConfig,
    sector_map: dict[str, str] | None = None,
) -> bool:
    """Run one job: backtest a variant×ticker, write results, mark done.

    Returns True on success, False on failure (job is marked failed in store).
    """
    job_id = job["job_id"]
    variant_id = job["variant_id"]
    ticker = job["ticker"]
    spec_json = job["spec_json"]

    try:
        # Parse spec
        spec = validate_spec(json.loads(spec_json))
    except Exception as exc:
        logger.error("[%s|%s] Invalid spec: %s", variant_id[:8], ticker, exc)
        store.fail_job(job_id, f"bad_spec: {exc}")
        return False

    sector = sector_map.get(ticker, "") if sector_map else ""

    # Load data
    data_dir = Path(config.paths.data_dir)
    df = load_ticker(ticker, data_dir)
    if df is None or df.empty:
        logger.warning("[%s|%s] No data — skipping.", variant_id[:8], ticker)
        store.fail_job(job_id, "no_data")
        return False

    if len(df) < config.data.min_bars:
        logger.warning("[%s|%s] Too few bars (%d) — skipping.", variant_id[:8], ticker, len(df))
        store.fail_job(job_id, f"too_short:{len(df)}")
        return False

    try:
        # Compute signals
        entry_signals = compute_entry_signals(df, spec)
        exit_signals = compute_exit_conditions(df, spec)

        # Run backtest
        trades_df = run_backtest(
            df=df,
            entry_signals=entry_signals,
            exit_signals=exit_signals,
            spec=spec,
            variant_id=variant_id,
            ticker=ticker,
            sector=sector,
            cost_bps=config.backtest.cost_bps_per_side,
            slip_bps=config.backtest.slippage_bps_per_side,
            stop_before_target=config.backtest.stop_before_target_if_both_hit,
        )

        # Compute metrics
        is_trades, oos_trades = is_oos_split(trades_df, config.backtest.oos_fraction)
        metrics = {
            "is": compute_trade_stats(is_trades),
            "oos": compute_trade_stats(oos_trades),
            "all": compute_trade_stats(trades_df),
            "n_bars": len(df),
        }
        metrics_json = json.dumps(metrics, default=str)

        # Save trades to Parquet
        result_dir = data_dir / "results" / variant_id
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = str(result_dir / f"{ticker}.parquet")
        if not trades_df.empty:
            trades_df.to_parquet(result_path, index=False)
        else:
            result_path = ""

        # Commit to DB (atomically: mark done + save metrics)
        store.complete_job(
            job_id=job_id,
            result_path=result_path,
            ticker=ticker,
            variant_id=variant_id,
            sector=sector,
            metrics_json=metrics_json,
        )
        n_trades = len(trades_df)
        logger.info("[%s|%s] Done — %d trades.", variant_id[:8], ticker, n_trades)
        return True

    except Exception as exc:
        logger.error("[%s|%s] Job failed: %s", variant_id[:8], ticker, exc, exc_info=True)
        store.fail_job(job_id, str(exc)[:500])
        return False
