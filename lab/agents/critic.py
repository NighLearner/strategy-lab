"""critic.py — LLM explains verdict and suggests mutations as JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def review_variant(
    llm_client,
    variant_id: str,
    strategy_name: str,
    verdict: str,
    flags: list[str],
    metrics: dict,
    max_suggestions: int = 3,
) -> list[dict]:
    """Get LLM critique and mutation suggestions.

    Returns a list of suggestion dicts (may be empty).
    """
    if llm_client is None or not getattr(llm_client, "available", lambda: False)():
        return []

    oos = metrics.get("oos", {})
    data_str = (
        f"Strategy: {strategy_name}\n"
        f"Verdict: {verdict}\n"
        f"Flags: {', '.join(flags) if flags else 'none'}\n"
        f"OOS n_trades: {oos.get('n_trades')}\n"
        f"OOS expectancy: {oos.get('expectancy')}%\n"
        f"OOS t-stat: {oos.get('t_stat')}\n"
        f"OOS win_rate: {oos.get('win_rate')}\n"
    )

    prompt = (
        f"You are a quantitative strategy critic.\n\n"
        f"Results for strategy '{strategy_name}':\n{data_str}\n\n"
        f"1. Briefly explain the verdict in 1-2 sentences.\n"
        f"2. Suggest up to {max_suggestions} mutations as a JSON array. Each mutation:\n"
        f"   {{\"description\": \"...\", \"change\": \"e.g. different holding period, add volume filter, sector-specific\"}}\n\n"
        f"Respond with JSON:\n"
        f"{{\"explanation\": \"...\", \"suggestions\": [...]}}"
    )

    response = llm_client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    if not response:
        return []

    content = response.get("content", "")
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start == -1:
            return []
        data = json.loads(content[start:end])
        return data.get("suggestions", [])
    except Exception as exc:
        logger.warning("Critic: parse error for '%s': %s", strategy_name, exc)
        return []
