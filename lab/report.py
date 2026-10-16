"""report.py — Generate per-strategy Markdown reports and leaderboard."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from lab.store import Store

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "\n---\n\n"
    "*Research output only — not financial advice. "
    "Past performance does not predict future results. "
    "Results based on adjusted prices from yfinance (unofficial). "
    "Survivorship bias present (current S&P 500 constituents only).*\n"
)


def _fmt(v: Any, decimals: int = 2) -> str:
    if v is None or v != v:  # None or NaN
        return "N/A"
    if isinstance(v, float):
        return f"{v:.{decimals}f}"
    return str(v)


def _metrics_table(stats: dict, label: str) -> str:
    lines = [f"**{label}**\n"]
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    for key in [
        "n_trades", "win_rate", "avg_return", "median_return", "expectancy",
        "t_stat", "profit_factor", "payoff_ratio", "avg_bars_held",
        "max_consecutive_losses",
    ]:
        v = stats.get(key)
        lines.append(f"| {key} | {_fmt(v)} |")
    return "\n".join(lines)


def write_strategy_report(
    variant_id: str,
    store: Store,
    reports_dir: str | Path,
    commentary: str = "LLM disabled",
) -> Optional[str]:
    """Write per-strategy markdown report. Returns path or None on failure."""
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    result = store.get_variant_result(variant_id)
    if not result:
        logger.warning("No result for variant %s.", variant_id[:8])
        return None

    metrics = json.loads(result.get("metrics_json", "{}"))
    verdict = result.get("verdict", "unknown")
    flags_raw = result.get("flags_json", "[]")
    flags = json.loads(flags_raw) if flags_raw else []

    # Get strategy name from DB
    rows = store.get_ticker_results(variant_id)
    strategy_name = variant_id[:16]  # fallback

    # Gather variant info
    variants = store.list_variants()
    variant_row = next((v for v in variants if v["variant_id"] == variant_id), {})
    strategy_id = variant_row.get("strategy_id", "unknown")
    strategies = store.list_strategies()
    strat_row = next((s for s in strategies if s["strategy_id"] == strategy_id), {})
    strategy_name = strat_row.get("name", strategy_name)
    spec_json = variant_row.get("spec_json", "")

    overall = metrics.get("overall", {})
    is_stats = overall.get("is", {})
    oos_stats = overall.get("oos", {})
    equity = overall.get("equity", {})
    sectors = metrics.get("sectors", {})

    # Build report
    lines = [
        f"# Strategy Report: {strategy_name}",
        f"\n**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Variant ID:** `{variant_id[:20]}…`",
        f"**Verdict:** 🔴 {verdict.upper()}" if verdict == "reject" else
        (f"**Verdict:** 🟡 {verdict.upper()}" if verdict == "watch" else
         f"**Verdict:** 🟢 {verdict.upper()}"),
        f"**Flags:** {', '.join(flags) if flags else 'none'}",
        "\n---\n",
        "## 1. Strategy Spec\n",
        "```json",
        spec_json,
        "```\n",
        "## 2. Overall Results\n",
        _metrics_table(is_stats, "In-Sample"),
        "\n",
        _metrics_table(oos_stats, "Out-of-Sample"),
        "\n",
        "**Equity Curve Stats**",
        f"| Total Return | Max Drawdown | Ann. Return | Calmar | Exposure |",
        f"|---|---|---|---|---|",
        f"| {_fmt(equity.get('total_return'))}% | {_fmt(equity.get('max_drawdown'))}% | {_fmt(equity.get('ann_return'))}% | {_fmt(equity.get('calmar'))} | {_fmt(equity.get('exposure_pct'), 3)} |",
        "\n",
    ]

    # Sector table
    if sectors:
        lines.append("## 3. By-Sector Results\n")
        lines.append("| Sector | IS Trades | IS Exp. | OOS Trades | OOS Exp. |")
        lines.append("|--------|-----------|---------|------------|----------|")
        for sector, sec_metrics in sectors.items():
            is_s = sec_metrics.get("is", {})
            oos_s = sec_metrics.get("oos", {})
            lines.append(
                f"| {sector} | {_fmt(is_s.get('n_trades'), 0)} | "
                f"{_fmt(is_s.get('expectancy'))}% | "
                f"{_fmt(oos_s.get('n_trades'), 0)} | "
                f"{_fmt(oos_s.get('expectancy'))}% |"
            )
        lines.append("")

    # Analyst commentary
    lines.append("## 7. Analyst Commentary\n")
    lines.append(commentary)
    lines.append("")
    lines.append(_DISCLAIMER)

    report_content = "\n".join(lines)
    report_path = reports_path / f"{strategy_id}_{variant_id[:8]}.md"
    report_path.write_text(report_content, encoding="utf-8")
    logger.info("Report written: %s", report_path)
    return str(report_path)


def write_leaderboard(
    store: Store,
    reports_dir: str | Path,
) -> str:
    """Write leaderboard.md with all variant results ranked by OOS expectancy."""
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    all_results = store.list_all_results()
    if not all_results:
        content = "# Leaderboard\n\nNo results yet.\n"
    else:
        rows = []
        for r in all_results:
            metrics = json.loads(r.get("metrics_json", "{}"))
            oos = metrics.get("overall", {}).get("oos", {})
            rows.append({
                "name": r.get("name", "unknown"),
                "variant_id": r["variant_id"][:12],
                "verdict": r.get("verdict", "unknown"),
                "oos_trades": oos.get("n_trades", 0),
                "oos_expectancy": oos.get("expectancy", None),
                "oos_t_stat": oos.get("t_stat", None),
                "oos_win_rate": oos.get("win_rate", None),
            })

        # Sort: promising first by expectancy, then watch, then reject
        order = {"promising": 0, "watch": 1, "reject": 2}
        rows.sort(
            key=lambda x: (
                order.get(x["verdict"], 3),
                -(x["oos_expectancy"] or -999),
            )
        )

        promising = [r for r in rows if r["verdict"] == "promising"]
        watch = [r for r in rows if r["verdict"] == "watch"]
        reject = [r for r in rows if r["verdict"] == "reject"]

        lines = [
            "# Strategy Leaderboard",
            f"\n**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Total variants:** {len(rows)}\n",
            "## 🟢 Promising\n",
        ]
        if promising:
            lines.append("| Strategy | Variant | OOS Trades | OOS Exp. | OOS T-stat | Win Rate |")
            lines.append("|----------|---------|-----------|---------|-----------|---------|")
            for r in promising:
                lines.append(
                    f"| {r['name']} | `{r['variant_id']}` | "
                    f"{_fmt(r['oos_trades'], 0)} | {_fmt(r['oos_expectancy'])}% | "
                    f"{_fmt(r['oos_t_stat'])} | {_fmt(r['oos_win_rate'])} |"
                )
        else:
            lines.append("*None yet.*")

        lines.extend(["\n## 🟡 Watch\n"])
        if watch:
            lines.append("| Strategy | Variant | OOS Trades | OOS Exp. |")
            lines.append("|----------|---------|-----------|---------|")
            for r in watch:
                lines.append(
                    f"| {r['name']} | `{r['variant_id']}` | "
                    f"{_fmt(r['oos_trades'], 0)} | {_fmt(r['oos_expectancy'])}% |"
                )
        else:
            lines.append("*None yet.*")

        lines.extend(["\n## 🔴 Rejected\n"])
        if reject:
            lines.append("| Strategy | Variant | OOS Trades | OOS Exp. |")
            lines.append("|----------|---------|-----------|---------|")
            for r in reject:
                lines.append(
                    f"| {r['name']} | `{r['variant_id']}` | "
                    f"{_fmt(r['oos_trades'], 0)} | {_fmt(r['oos_expectancy'])}% |"
                )
        else:
            lines.append("*None.*")

        lines.append(_DISCLAIMER)
        content = "\n".join(lines)

    lb_path = reports_path / "leaderboard.md"
    lb_path.write_text(content, encoding="utf-8")
    logger.info("Leaderboard written: %s", lb_path)
    return str(lb_path)
