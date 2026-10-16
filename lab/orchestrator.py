"""orchestrator.py — Main loop implementing instruction.md §7."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Optional

from lab.agents.analyst import generate_commentary
from lab.agents.critic import review_variant
from lab.agents.librarian import import_seed_cards, propose_new_cards
from lab.agents.spec_writer import card_to_spec
from lab.config import LabConfig
from lab.data import download_universe
from lab.logging_setup import setup_logging
from lab.metrics import aggregate_metrics, compute_verdict, is_oos_split
from lab.queue import enqueue_strategy, is_queue_empty, queue_status
from lab.report import write_leaderboard, write_strategy_report
from lab.runner import run_job
from lab.spec import save_spec
from lab.store import Store, init_db
from lab.throttle import Throttle
from lab.universe import build_universe, load_universe

logger = logging.getLogger(__name__)

_STOP_FILE = "data/STOP"


class Orchestrator:
    """Main orchestrator loop."""

    def __init__(self, config: LabConfig, dry_llm: bool = False) -> None:
        self.config = config
        self.dry_llm = dry_llm
        self._stop_requested = False
        self._pause_requested = False

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Init subsystems
        data_dir = Path(config.paths.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        init_db(data_dir)

        self.store = Store(data_dir)
        self.throttle = Throttle(config.throttle)

        # Build LLM client
        from lab.llm import build_llm_client
        self.llm = build_llm_client(config.llm, dry_run=dry_llm)

        self.data_dir = data_dir
        self.library_dir = Path(config.paths.library_dir)
        self.reports_dir = Path(config.paths.reports_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)

        self.run_id: Optional[str] = None
        self.jobs_done = 0

    def _handle_signal(self, signum, frame) -> None:
        logger.info("Signal %d received — stopping after current job.", signum)
        self._stop_requested = True

    def _check_stop_file(self) -> bool:
        stop_path = Path(_STOP_FILE)
        if stop_path.exists():
            logger.info("STOP file found — stopping.")
            stop_path.unlink(missing_ok=True)
            return True
        return False

    def stop_requested(self) -> bool:
        return self._stop_requested or self._check_stop_file()

    def _startup(self) -> None:
        """Startup: reset stale jobs, ensure universe + seeds."""
        stale = self.store.reset_stale_running()
        if stale:
            logger.info("Reset %d stale jobs.", stale)

        # Universe
        csv_path = self.data_dir / "universe.csv"
        if not csv_path.exists():
            logger.info("Building universe …")
            build_universe(
                self.data_dir,
                extra_tickers=self.config.universe.extra_tickers,
                max_tickers=self.config.universe.max_tickers,
            )
        else:
            logger.info("Universe CSV exists (%s rows).", sum(1 for _ in open(csv_path)) - 1)

        # Import seed cards to library
        n = import_seed_cards(self.library_dir)
        if n:
            logger.info("Imported %d seed strategy cards.", n)

        # Enqueue seed specs if they exist
        specs_dir = self.library_dir / "specs"
        if specs_dir.exists():
            self._enqueue_all_specs(specs_dir)

    def _enqueue_all_specs(self, specs_dir: Path) -> None:
        """Enqueue all JSON specs in library/specs/."""
        from lab.spec import load_spec
        universe = load_universe(self.data_dir)
        tickers = universe["ticker"].tolist()

        for spec_path in specs_dir.glob("*.json"):
            try:
                spec = load_spec(str(spec_path))
                enqueue_strategy(
                    self.store, spec, tickers,
                    max_variants=self.config.backtest.max_variants_per_strategy,
                )
            except Exception as exc:
                logger.warning("Failed to enqueue spec %s: %s", spec_path.name, exc)

    def _evaluate_finished_variants(self) -> None:
        """Compute aggregate metrics and verdict for completed variants."""
        finished = self.store.variants_needing_evaluation()
        for vid in finished:
            if self.stop_requested():
                return
            try:
                self._evaluate_variant(vid)
            except Exception as exc:
                logger.error("Evaluation failed for %s: %s", vid[:12], exc)

    def _evaluate_variant(self, variant_id: str) -> None:
        """Aggregate metrics, compute verdict, write report for a variant."""
        import pandas as pd
        results_dir = self.data_dir / "results" / variant_id
        if not results_dir.exists():
            return

        dfs = []
        for parquet_path in results_dir.glob("*.parquet"):
            try:
                df = pd.read_parquet(parquet_path)
                if not df.empty:
                    dfs.append(df)
            except Exception:
                pass

        all_trades = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        metrics = aggregate_metrics(
            all_trades,
            self.config.backtest.oos_fraction,
            self.config.backtest.horizons,
        )
        overall = metrics.get("overall", {})
        is_stats = overall.get("is", {})
        oos_stats = overall.get("oos", {})
        sectors = metrics.get("sectors", {})

        # Count sectors with positive OOS expectancy
        pos_sectors = sum(
            1 for s in sectors.values()
            if (s.get("oos", {}).get("expectancy") or 0) > 0
            and (s.get("oos", {}).get("n_trades") or 0) >= 20
        )
        total_sectors_with_trades = sum(
            1 for s in sectors.values()
            if (s.get("oos", {}).get("n_trades") or 0) >= 20
        )
        sec_agreement = pos_sectors / total_sectors_with_trades if total_sectors_with_trades else 0.0

        verdict, flags = compute_verdict(
            is_stats=is_stats,
            oos_stats=oos_stats,
            verdict_config=self.config.verdict,
            sector_positive_fraction=sec_agreement,
        )

        metrics_json = json.dumps(metrics, default=str)
        self.store.save_variant_result(
            variant_id, metrics_json, verdict, json.dumps(flags)
        )
        logger.info("Variant %s: verdict=%s flags=%s", variant_id[:12], verdict, flags)

        # Commentary via LLM (optional)
        commentary = "LLM disabled"
        if self.config.llm.enabled:
            try:
                commentary = generate_commentary(
                    self.llm, variant_id, metrics, verdict, flags
                )
            except Exception:
                pass

        write_strategy_report(variant_id, self.store, self.reports_dir, commentary)

        # Critic review
        if self.config.llm.enabled and self.llm.available():
            try:
                review_variant(self.llm, variant_id, variant_id, verdict, flags, metrics)
            except Exception:
                pass

    def _heartbeat(self, last_hb: float) -> float:
        now = time.time()
        if now - last_hb >= self.config.orchestrator.heartbeat_s:
            status = self.throttle.get_status()
            q = queue_status(self.store)
            logger.info(
                "♥ HEARTBEAT — jobs: %d/%d (%.1f%%) | CPU: %.0f%% | throttle_ok: %s",
                q["done"], q["total"], q["pct_done"],
                status["cpu_pct"], status["throttle_ok"],
            )
            return now
        return last_hb

    def run(self) -> None:
        """Main orchestrator loop."""
        setup_logging(self.config.paths.logs_dir)
        logger.info("=== Strategy Lab starting (run ID will be assigned) ===")

        self.run_id = self.store.start_run()
        self._startup()

        last_hb = time.time()

        try:
            while not self.stop_requested():
                last_hb = self._heartbeat(last_hb)

                # Throttle
                self.throttle.wait_until_ok()
                if self.stop_requested():
                    break

                # Try to claim a job
                job = self.store.claim_next_job()
                if job:
                    universe = load_universe(self.data_dir)
                    sector_map = dict(zip(universe["ticker"], universe.get("sector", [""] * len(universe))))
                    run_job(job, self.store, self.config, sector_map)
                    self.jobs_done += 1
                    self.throttle.duty_sleep()
                    continue

                # No pending jobs: evaluate and generate reports
                self._evaluate_finished_variants()

                if is_queue_empty(self.store):
                    write_leaderboard(self.store, self.reports_dir)

                    if self.config.llm.enabled and self.llm.available():
                        logger.info("Queue empty — asking LLM for new strategy ideas.")
                        universe = load_universe(self.data_dir)
                        tickers = universe["ticker"].tolist()
                        new_cards = propose_new_cards(
                            self.llm,
                            self.library_dir,
                            n=self.config.orchestrator.max_new_strategies_per_cycle,
                        )
                        for card in new_cards:
                            spec = card_to_spec(card, self.llm)
                            if spec:
                                save_spec(spec, str(self.library_dir / "specs"))
                                enqueue_strategy(
                                    self.store, spec, tickers,
                                    max_variants=self.config.backtest.max_variants_per_strategy,
                                    source="llm",
                                )
                    else:
                        logger.info("Queue empty; LLM unavailable. Sleeping %ds.",
                                    self.config.orchestrator.idle_poll_seconds)
                        time.sleep(self.config.orchestrator.idle_poll_seconds)

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt caught.")
        finally:
            reason = "stop_requested" if self._stop_requested else "completed"
            if self.run_id:
                self.store.end_run(self.run_id, reason, self.jobs_done)
            logger.info("=== Strategy Lab stopped (%s). Jobs done this run: %d ===",
                        reason, self.jobs_done)
            self.store.integrity_check()
