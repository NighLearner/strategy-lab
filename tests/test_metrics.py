"""test_metrics.py — Unit tests for metrics, BH FDR, and verdict tiers."""

import math
import numpy as np
import pandas as pd
import pytest

from lab.config import VerdictConfig
from lab.metrics import (
    benjamini_hochberg,
    compute_equity_curve_stats,
    compute_trade_stats,
    compute_verdict,
    is_oos_split,
)


def _make_dummy_trades(returns: list[float]) -> pd.DataFrame:
    n = len(returns)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "net_return_pct": returns,
        "entry_date": dates,
        "exit_date": dates + pd.Timedelta(days=5),
        "bars_held": [5] * n,
        "ticker": ["AAPL"] * n,
        "sector": ["Technology"] * n,
    })


def test_compute_trade_stats_basics():
    # 3 wins (+10, +10, +10), 1 loss (-10)
    # Win rate: 75%
    # Avg win: 10, Avg loss: -10, Payoff ratio: 1.0
    # Profit factor: 30 / 10 = 3.0
    # Expectancy: 0.75 * 10 + 0.25 * (-10) = 7.5 - 2.5 = 5.0
    trades = _make_dummy_trades([10.0, 10.0, 10.0, -10.0])
    stats = compute_trade_stats(trades)
    assert stats["n_trades"] == 4
    assert stats["win_rate"] == 0.75
    assert stats["avg_win"] == 10.0
    assert stats["avg_loss"] == -10.0
    assert stats["payoff_ratio"] == 1.0
    assert stats["profit_factor"] == 3.0
    assert stats["expectancy"] == 5.0


def test_benjamini_hochberg_fdr():
    # Test FDR control with known p-values
    p_values = [0.001, 0.01, 0.04, 0.5]
    passed = benjamini_hochberg(p_values, alpha=0.05)
    # m = 4
    # rank 1: p=0.001 <= 1/4 * 0.05 = 0.0125 -> True
    # rank 2: p=0.01  <= 2/4 * 0.05 = 0.025  -> True
    # rank 3: p=0.04  <= 3/4 * 0.05 = 0.0375 -> False
    # rank 4: p=0.5   <= 4/4 * 0.05 = 0.05   -> False
    # Largest k is 2. So first 2 pass.
    assert passed == [True, True, False, False]


def test_determine_verdict_promising():
    cfg = VerdictConfig()
    is_stats = {"expectancy": 2.5, "n_trades": 100}
    oos_stats = {
        "n_trades": 60,
        "expectancy": 2.0,
        "t_stat": 2.5,
        "profit_factor": 1.4,
    }
    verdict, flags = compute_verdict(
        is_stats=is_stats,
        oos_stats=oos_stats,
        verdict_config=cfg,
        random_pct=98.0,
        sector_positive_fraction=0.8,
        passes_fdr=True,
    )
    assert verdict == "promising"
    assert "fails_fdr" not in flags
    assert "few_trades" not in flags


def test_determine_verdict_reject_due_to_few_trades():
    cfg = VerdictConfig(min_oos_trades=50)
    is_stats = {"expectancy": 2.5, "n_trades": 100}
    oos_stats = {
        "n_trades": 20,  # Below threshold
        "expectancy": 2.0,
        "t_stat": 2.5,
        "profit_factor": 1.4,
    }
    verdict, flags = compute_verdict(
        is_stats=is_stats,
        oos_stats=oos_stats,
        verdict_config=cfg,
        random_pct=98.0,
        sector_positive_fraction=0.8,
        passes_fdr=True,
    )
    assert verdict == "reject"
    assert "few_trades" in flags
