"""store.py — SQLite access layer (jobs, strategies, results, runs).

Schema and migrations for: strategies, variants, jobs, results_ticker,
results_variant, runs, kv.  WAL mode enabled.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def _db_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "lab.db"


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def _get_conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema (migrations by version)
# ---------------------------------------------------------------------------

_DDL = [
    # Version 1
    """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

    CREATE TABLE IF NOT EXISTS strategies (
        strategy_id   TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        family        TEXT,
        spec_json     TEXT,
        source        TEXT,
        status        TEXT DEFAULT 'active',
        created_at    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS variants (
        variant_id    TEXT PRIMARY KEY,
        strategy_id   TEXT NOT NULL REFERENCES strategies(strategy_id),
        params_json   TEXT,
        spec_json     TEXT,
        created_at    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS jobs (
        job_id        TEXT PRIMARY KEY,
        variant_id    TEXT NOT NULL REFERENCES variants(variant_id),
        ticker        TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'pending',
        attempts      INTEGER NOT NULL DEFAULT 0,
        started_at    TEXT,
        finished_at   TEXT,
        error         TEXT,
        result_path   TEXT,
        UNIQUE(variant_id, ticker)
    );

    CREATE TABLE IF NOT EXISTS results_ticker (
        variant_id    TEXT NOT NULL,
        ticker        TEXT NOT NULL,
        sector        TEXT,
        metrics_json  TEXT,
        PRIMARY KEY (variant_id, ticker)
    );

    CREATE TABLE IF NOT EXISTS results_variant (
        variant_id    TEXT PRIMARY KEY,
        metrics_json  TEXT,
        verdict       TEXT,
        flags_json    TEXT,
        computed_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS runs (
        run_id        TEXT PRIMARY KEY,
        started_at    TEXT NOT NULL,
        ended_at      TEXT,
        reason_stopped TEXT,
        jobs_done     INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS kv (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """,
]


def init_db(data_dir: str | Path) -> None:
    """Create or migrate the SQLite database."""
    db_path = _db_path(data_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _get_conn(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        current_version = row["version"] if row else 0

        for version, ddl in enumerate(_DDL, start=1):
            if version > current_version:
                for stmt in ddl.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version(version) VALUES(?)", (version,)
                )
        conn.commit()
    logger.info("Database initialised at %s (schema v%d).", db_path, _SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Strategy / Variant management
# ---------------------------------------------------------------------------

class Store:
    """Central data access object for strategy-lab."""

    def __init__(self, data_dir: str | Path):
        self.db_path = _db_path(data_dir)
        if not self.db_path.exists():
            init_db(data_dir)

    @contextmanager
    def conn(self) -> Generator[sqlite3.Connection, None, None]:
        yield from _get_conn(self.db_path)

    # --- Strategies ---

    def upsert_strategy(
        self,
        strategy_id: str,
        name: str,
        family: str,
        spec_json: str,
        source: str = "seed",
    ) -> None:
        with _get_conn(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategies(strategy_id, name, family, spec_json, source, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name=excluded.name, family=excluded.family,
                    spec_json=excluded.spec_json, source=excluded.source
                """,
                (strategy_id, name, family, spec_json, source, _now()),
            )
            conn.commit()

    def list_strategies(self) -> list[dict]:
        with _get_conn(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM strategies").fetchall()
        return [dict(r) for r in rows]

    # --- Variants ---

    def upsert_variant(
        self,
        variant_id: str,
        strategy_id: str,
        params_json: str,
        spec_json: str,
    ) -> None:
        with _get_conn(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO variants(variant_id, strategy_id, params_json, spec_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (variant_id, strategy_id, params_json, spec_json, _now()),
            )
            conn.commit()

    def list_variants(self, strategy_id: str | None = None) -> list[dict]:
        with _get_conn(self.db_path) as conn:
            if strategy_id:
                rows = conn.execute(
                    "SELECT * FROM variants WHERE strategy_id=?", (strategy_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM variants").fetchall()
        return [dict(r) for r in rows]

    # --- Jobs ---

    def create_jobs(self, variant_id: str, tickers: list[str]) -> int:
        """Create jobs for each ticker. Idempotent (INSERT OR IGNORE). Returns new jobs count."""
        created = 0
        with _get_conn(self.db_path) as conn:
            for ticker in tickers:
                job_id = str(uuid.uuid4())
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs(job_id, variant_id, ticker, status, attempts)
                    VALUES(?, ?, ?, 'pending', 0)
                    """,
                    (job_id, variant_id, ticker),
                )
                created += cursor.rowcount
            conn.commit()
        return created

    def reset_stale_running(self) -> int:
        """Reset jobs stuck in 'running' (crash/kill) to 'pending'. Returns count."""
        with _get_conn(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE jobs SET status='pending', attempts=attempts+1, started_at=NULL
                WHERE status='running'
                """
            )
            conn.commit()
        n = cursor.rowcount
        if n:
            logger.info("Reset %d stale running jobs to pending.", n)
        return n

    def claim_next_job(self) -> Optional[dict]:
        """Atomically claim the next pending job. Returns job dict or None."""
        with _get_conn(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT j.job_id, j.variant_id, j.ticker, j.attempts,
                       v.spec_json, v.strategy_id
                FROM jobs j
                JOIN variants v ON j.variant_id = v.variant_id
                WHERE j.status='pending' AND j.attempts < 3
                ORDER BY j.variant_id, j.ticker
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            job_id = row["job_id"]
            conn.execute(
                "UPDATE jobs SET status='running', started_at=? WHERE job_id=?",
                (_now(), job_id),
            )
            conn.commit()
        return dict(row)

    def complete_job(
        self,
        job_id: str,
        result_path: str,
        ticker: str,
        variant_id: str,
        sector: str,
        metrics_json: str,
    ) -> None:
        """Mark job done and write ticker-level results in one transaction."""
        with _get_conn(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs SET status='done', finished_at=?, result_path=?
                WHERE job_id=?
                """,
                (_now(), result_path, job_id),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO results_ticker(variant_id, ticker, sector, metrics_json)
                VALUES(?, ?, ?, ?)
                """,
                (variant_id, ticker, sector, metrics_json),
            )
            conn.commit()

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark job failed; if attempts >= 3, status becomes 'failed'."""
        with _get_conn(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET attempts=attempts+1,
                    status=CASE WHEN attempts+1 >= 3 THEN 'failed' ELSE 'pending' END,
                    finished_at=?,
                    error=?
                WHERE job_id=?
                """,
                (_now(), error[:2000], job_id),
            )
            conn.commit()

    def count_jobs(self, variant_id: str | None = None) -> dict[str, int]:
        """Return counts of jobs by status."""
        with _get_conn(self.db_path) as conn:
            if variant_id:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as n FROM jobs WHERE variant_id=? GROUP BY status",
                    (variant_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as n FROM jobs GROUP BY status"
                ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def variants_needing_evaluation(self) -> list[str]:
        """Return variant_ids where all jobs are done/failed and no variant result yet."""
        with _get_conn(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT j.variant_id
                FROM jobs j
                LEFT JOIN results_variant rv ON j.variant_id = rv.variant_id
                WHERE rv.variant_id IS NULL
                GROUP BY j.variant_id
                HAVING SUM(j.status IN ('pending','running')) = 0
                """
            ).fetchall()
        return [r["variant_id"] for r in rows]

    def save_variant_result(
        self,
        variant_id: str,
        metrics_json: str,
        verdict: str,
        flags_json: str,
    ) -> None:
        with _get_conn(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO results_variant(variant_id, metrics_json, verdict, flags_json, computed_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (variant_id, metrics_json, verdict, flags_json, _now()),
            )
            conn.commit()

    def get_ticker_results(self, variant_id: str) -> list[dict]:
        with _get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM results_ticker WHERE variant_id=?", (variant_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_variant_result(self, variant_id: str) -> Optional[dict]:
        with _get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM results_variant WHERE variant_id=?", (variant_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_all_results(self) -> list[dict]:
        with _get_conn(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT rv.*, v.strategy_id, s.name
                FROM results_variant rv
                JOIN variants v ON rv.variant_id = v.variant_id
                JOIN strategies s ON v.strategy_id = s.strategy_id
                ORDER BY rv.computed_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Runs ---

    def start_run(self) -> str:
        run_id = str(uuid.uuid4())
        with _get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, started_at) VALUES(?, ?)",
                (run_id, _now()),
            )
            conn.commit()
        return run_id

    def end_run(self, run_id: str, reason: str, jobs_done: int) -> None:
        with _get_conn(self.db_path) as conn:
            conn.execute(
                "UPDATE runs SET ended_at=?, reason_stopped=?, jobs_done=? WHERE run_id=?",
                (_now(), reason, jobs_done, run_id),
            )
            conn.commit()

    # --- KV store ---

    def kv_set(self, key: str, value: Any) -> None:
        with _get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)",
                (key, json.dumps(value, default=str)),
            )
            conn.commit()

    def kv_get(self, key: str, default: Any = None) -> Any:
        with _get_conn(self.db_path) as conn:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    # --- Status ---

    def integrity_check(self) -> bool:
        with _get_conn(self.db_path) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        ok = result[0] == "ok"
        if not ok:
            logger.error("DB integrity check FAILED: %s", result[0])
        return ok


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
