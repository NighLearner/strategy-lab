"""queue.py — Job generation, idempotent claiming, reset stale, retry cap."""

from __future__ import annotations

import json
import logging

from lab.signals import expand_variants
from lab.spec import StrategySpec
from lab.store import Store

logger = logging.getLogger(__name__)


def enqueue_strategy(
    store: Store,
    spec: StrategySpec,
    tickers: list[str],
    max_variants: int = 30,
    source: str = "seed",
) -> int:
    """Expand spec into variants and create jobs for each ticker.

    Idempotent: re-calling with the same spec + tickers is a no-op.
    Returns total new jobs created.
    """
    variants = expand_variants(spec, max_variants=max_variants)
    logger.info(
        "Strategy '%s' → %d variants × %d tickers = %d jobs",
        spec.id, len(variants), len(tickers), len(variants) * len(tickers),
    )

    # Upsert the base strategy
    store.upsert_strategy(
        strategy_id=spec.id,
        name=spec.name,
        family=spec.family,
        spec_json=spec.to_canonical_json(),
        source=source,
    )

    total_new = 0
    for variant in variants:
        vid = variant.spec_hash()
        store.upsert_variant(
            variant_id=vid,
            strategy_id=spec.id,
            params_json=json.dumps(variant.params_grid, default=str),
            spec_json=variant.to_canonical_json(),
        )
        new = store.create_jobs(vid, tickers)
        total_new += new

    logger.info("Enqueued %d new jobs for strategy '%s'.", total_new, spec.id)
    return total_new


def queue_status(store: Store) -> dict:
    """Return overall job queue counts."""
    counts = store.count_jobs()
    total = sum(counts.values())
    done = counts.get("done", 0)
    pending = counts.get("pending", 0)
    running = counts.get("running", 0)
    failed = counts.get("failed", 0)
    pct = round(done / total * 100, 1) if total > 0 else 0.0
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "running": running,
        "failed": failed,
        "pct_done": pct,
    }


def is_queue_empty(store: Store) -> bool:
    """True if no pending or running jobs remain."""
    counts = store.count_jobs()
    return counts.get("pending", 0) == 0 and counts.get("running", 0) == 0
