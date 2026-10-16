"""librarian.py — Seed import (no LLM) + LLM proposals of new strategy cards."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from lab.store import Store

logger = logging.getLogger(__name__)

_LIBRARY_FILE = "library/strategies.md"


# ---------------------------------------------------------------------------
# Strategy card dataclass
# ---------------------------------------------------------------------------

class StrategyCard:
    def __init__(
        self,
        name: str,
        family: str,
        idea: str,
        entry: str,
        exit_rule: str,
        why_it_might_work: str = "",
        known_failure_modes: str = "",
        source: str = "seed",
        direction: str = "long",
    ) -> None:
        self.name = name
        self.family = family
        self.idea = idea
        self.entry = entry
        self.exit_rule = exit_rule
        self.why_it_might_work = why_it_might_work
        self.known_failure_modes = known_failure_modes
        self.source = source
        self.direction = direction

    def card_id(self) -> str:
        return hashlib.md5(self.name.lower().strip().encode()).hexdigest()[:12]

    def to_md(self) -> str:
        return (
            f"## {self.name}\n\n"
            f"**Family:** {self.family} | **Direction:** {self.direction}\n\n"
            f"**Idea:** {self.idea}\n\n"
            f"**Entry:** {self.entry}\n\n"
            f"**Exit:** {self.exit_rule}\n\n"
            f"**Why it might work:** {self.why_it_might_work}\n\n"
            f"**Known failure modes:** {self.known_failure_modes}\n\n"
            f"**Source:** {self.source}\n\n---\n"
        )


def _normalise_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


# ---------------------------------------------------------------------------
# Load the library markdown and extract existing strategy names
# ---------------------------------------------------------------------------

def load_library_names(library_dir: str | Path) -> set[str]:
    """Return normalised names of all strategies in the library."""
    md_path = Path(library_dir) / "strategies.md"
    if not md_path.exists():
        return set()
    names: set[str] = set()
    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            names.add(_normalise_name(m.group(1)))
    return names


def append_cards_to_library(cards: list[StrategyCard], library_dir: str | Path) -> int:
    """Append new cards to strategies.md, deduplicating by name. Returns count added."""
    md_path = Path(library_dir) / "strategies.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_library_names(library_dir)
    added = 0
    with md_path.open("a", encoding="utf-8") as f:
        if not md_path.stat().st_size:
            f.write("# Strategy Library\n\n")
        for card in cards:
            if _normalise_name(card.name) not in existing:
                f.write(card.to_md())
                existing.add(_normalise_name(card.name))
                added += 1
    return added


# ---------------------------------------------------------------------------
# Phase A: import seed strategies as cards (no LLM)
# ---------------------------------------------------------------------------

SEED_CARDS: list[StrategyCard] = [
    StrategyCard("Three White Soldiers", "candlestick_reversal",
                 "Three consecutive bullish bars with strong bodies and rising closes.",
                 "Three bull bars: each close > previous close, each open inside previous body, body >= 0.5*range.",
                 "Hold 10 bars or stop -8%.", direction="long", source="seed"),
    StrategyCard("Three Black Crows", "candlestick_reversal",
                 "Three consecutive bearish bars with strong bodies and falling closes.",
                 "Three bear bars: each close < previous close, body >= 0.5*range.",
                 "Hold 10 bars or stop -8%.", direction="short", source="seed"),
    StrategyCard("Bullish Engulfing", "candlestick_reversal",
                 "A bullish bar completely engulfs the previous bearish bar.",
                 "Bear bar followed by a bull bar where O <= prev C and C >= prev O.",
                 "Hold 10 bars or stop -8%.", direction="long", source="seed"),
    StrategyCard("Bearish Engulfing", "candlestick_reversal",
                 "A bearish bar completely engulfs the previous bullish bar.",
                 "Bull bar followed by a bear bar where O >= prev C and C <= prev O.",
                 "Hold 10 bars or stop -8%.", direction="short", source="seed"),
    StrategyCard("Hammer", "candlestick_reversal",
                 "Small body in upper portion of range, long lower shadow, after downtrend.",
                 "Lower shadow >= 2x body, upper shadow <= 10% range, prior 5-bar decline.",
                 "Hold 10 bars or stop -8%.", direction="long", source="seed"),
    StrategyCard("Shooting Star", "candlestick_reversal",
                 "Small body near lows, long upper shadow, after uptrend.",
                 "Upper shadow >= 2x body, lower shadow <= 10% range, prior 5-bar advance.",
                 "Hold 10 bars or stop -8%.", direction="short", source="seed"),
    StrategyCard("Golden Cross", "trend",
                 "SMA(50) crosses above SMA(200) — bullish trend confirmation.",
                 "SMA(50) cross_above SMA(200).",
                 "Death cross or hold 20 bars.", direction="long", source="seed"),
    StrategyCard("RSI Oversold Bounce", "mean_reversion",
                 "Buy when RSI is oversold in an uptrend.",
                 "RSI(14) < 30 and Close > SMA(200).",
                 "RSI > 50 or hold 10 bars or stop -8%.", direction="long", source="seed"),
    StrategyCard("Bollinger Lower Band Bounce", "mean_reversion",
                 "Price touches lower Bollinger Band in uptrend.",
                 "Close < lower BB(20,2), next bar closes back inside band.",
                 "Middle band touch or hold 10 bars.", direction="long", source="seed"),
    StrategyCard("Donchian Breakout", "breakout",
                 "Close above the highest high of the prior 20 bars.",
                 "Close > donchian upper (prior 20 bars).",
                 "Close < donchian lower (10 bars) or hold 20 bars.", direction="long", source="seed"),
    StrategyCard("ADX Trend Follow", "trend",
                 "Strong trend with positive directional movement.",
                 "ADX(14) > 25 and +DI > -DI and Close > SMA(50).",
                 "Close < SMA(50) or hold 20 bars.", direction="long", source="seed"),
    StrategyCard("MACD Signal Cross", "momentum",
                 "MACD crosses its signal line from below zero.",
                 "MACD line cross_above signal line while MACD < 0.",
                 "MACD cross_below signal or hold 15 bars.", direction="long", source="seed"),
    StrategyCard("Volume Spike Breakout", "volume_flow",
                 "Price breaks to new highs on exceptional volume.",
                 "rel_volume > 2 and Close > highest high of prior 20 bars.",
                 "Hold 10 bars or stop -8%.", direction="long", source="seed"),
    StrategyCard("CMF Accumulation", "volume_flow",
                 "Positive money flow with uptrend.",
                 "CMF(20) > 0.15 and Close > SMA(50).",
                 "CMF(20) < 0 or hold 15 bars.", direction="long", source="seed"),
    StrategyCard("Bollinger Squeeze Breakout", "volatility",
                 "Low volatility squeeze resolves with a breakout.",
                 "Bandwidth in lowest 10% of last 120 bars, then Close > upper band.",
                 "Close < middle band or hold 15 bars.", direction="long", source="seed"),
]


def import_seed_cards(library_dir: str | Path) -> int:
    """Import seed strategy cards to library. Returns count added."""
    return append_cards_to_library(SEED_CARDS, library_dir)


# ---------------------------------------------------------------------------
# Phase B: LLM proposals
# ---------------------------------------------------------------------------

def propose_new_cards(
    llm_client,
    library_dir: str | Path,
    n: int = 3,
) -> list[StrategyCard]:
    """Use LLM to propose new strategy cards not in the existing library."""
    existing = load_library_names(library_dir)

    prompt_path = Path(__file__).parent / "prompts" / "librarian_propose.txt"
    prompt = prompt_path.read_text(encoding="utf-8")
    prompt = prompt.replace("{existing_names}", "\n".join(sorted(existing)))
    prompt = prompt.replace("{n}", str(n))

    response = llm_client.chat(
        messages=[{"role": "user", "content": prompt}]
    )
    if not response:
        return []

    content = response.get("content", "")
    try:
        # Extract JSON array
        start = content.find("[")
        end = content.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        data = json.loads(content[start:end])
    except Exception as exc:
        logger.warning("Librarian: failed to parse LLM response: %s", exc)
        return []

    cards: list[StrategyCard] = []
    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            continue
        card = StrategyCard(
            name=item.get("name", "Unnamed"),
            family=item.get("family", "trend"),
            idea=item.get("idea", ""),
            entry=item.get("entry", ""),
            exit_rule=item.get("exit", "Hold 10 bars or stop -8%."),
            why_it_might_work=item.get("why_it_might_work", ""),
            known_failure_modes=item.get("known_failure_modes", ""),
            source=item.get("source", "llm"),
            direction=item.get("direction", "long"),
        )
        if _normalise_name(card.name) not in existing:
            cards.append(card)

    return cards
