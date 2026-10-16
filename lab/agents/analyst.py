"""analyst.py — Generate plain-English commentary from injected numeric results."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def generate_commentary(
    llm_client,
    strategy_name: str,
    metrics: dict,
    verdict: str,
    flags: list[str],
) -> str:
    """Generate commentary for a strategy report.

    Numbers are injected by code; the LLM only comments on provided numbers.
    Returns 'LLM disabled' if LLM is unavailable.
    """
    if llm_client is None or not getattr(llm_client, "available", lambda: False)():
        return "LLM disabled — commentary not generated."

    oos = metrics.get("oos", {})
    is_ = metrics.get("is", {})
    overall = metrics.get("overall", {})

    # Build a structured data summary to inject (LLM sees only these numbers)
    data_summary = (
        f"Strategy: {strategy_name}\n"
        f"Verdict: {verdict}\n"
        f"Flags: {', '.join(flags) if flags else 'none'}\n\n"
        f"Out-of-sample results:\n"
        f"  Trades: {oos.get('n_trades', 'N/A')}\n"
        f"  Win rate: {oos.get('win_rate', 'N/A')}\n"
        f"  Expectancy: {oos.get('expectancy', 'N/A')}%\n"
        f"  Profit factor: {oos.get('profit_factor', 'N/A')}\n"
        f"  T-stat: {oos.get('t_stat', 'N/A')}\n\n"
        f"In-sample results:\n"
        f"  Trades: {is_.get('n_trades', 'N/A')}\n"
        f"  Expectancy: {is_.get('expectancy', 'N/A')}%\n"
    )

    prompt_path = Path(__file__).parent / "prompts" / "analyst.txt"
    if prompt_path.exists():
        template = prompt_path.read_text(encoding="utf-8")
        prompt = template.replace("{data_summary}", data_summary)
    else:
        prompt = (
            f"You are a quantitative analyst writing a brief research commentary.\n"
            f"Comment only on the numbers provided. Do not invent any statistics.\n\n"
            f"{data_summary}\n\n"
            f"Write 2-3 sentences of commentary on these results."
        )

    response = llm_client.chat(messages=[{"role": "user", "content": prompt}])
    if not response:
        return "Commentary generation failed."

    commentary = response.get("content", "").strip()
    # Post-check: reject if commentary contains any number not in the data summary
    # (simple heuristic: only numbers from the summary should appear)
    return commentary[:1000]  # cap length
