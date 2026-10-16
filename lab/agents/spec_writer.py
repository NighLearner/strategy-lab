"""spec_writer.py — Convert a strategy card to a validated JSON spec using LLM."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from lab.agents.librarian import StrategyCard
from lab.spec import StrategySpec, validate_spec

logger = logging.getLogger(__name__)


def card_to_spec(
    card: StrategyCard,
    llm_client,
) -> Optional[StrategySpec]:
    """Send a strategy card to the LLM and return a validated StrategySpec.

    Returns None if all retries fail or the LLM is unavailable.
    """
    prompt_path = Path(__file__).parent / "prompts" / "spec_writer.txt"
    template = prompt_path.read_text(encoding="utf-8")

    prompt = template.replace("{name}", card.name)
    prompt = prompt.replace("{family}", card.family)
    prompt = prompt.replace("{idea}", card.idea)
    prompt = prompt.replace("{entry}", card.entry)
    prompt = prompt.replace("{exit}", card.exit_rule)
    prompt = prompt.replace("{direction}", card.direction)

    response = llm_client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    if not response:
        logger.warning("SpecWriter: no LLM response for card '%s'.", card.name)
        return None

    content = response.get("content", "")

    # Try to extract JSON object from response
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning("SpecWriter: no JSON found in response for '%s'.", card.name)
            return None
        data = json.loads(content[start:end])
    except json.JSONDecodeError as exc:
        logger.warning("SpecWriter: JSON parse error for '%s': %s", card.name, exc)
        return None

    try:
        spec = validate_spec(data)
        logger.info("SpecWriter: valid spec generated for '%s' → %s.", card.name, spec.id)
        return spec
    except Exception as exc:
        logger.warning("SpecWriter: spec validation failed for '%s': %s", card.name, exc)
        return None
