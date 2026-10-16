"""test_store_queue.py — Unit tests for store.py and queue.py."""

import json
from pathlib import Path
import pytest

from lab.store import Store, init_db
from lab.queue import enqueue_strategy, queue_status
from lab.spec import validate_spec


@pytest.fixture
def temp_store(tmp_path):
    init_db(tmp_path)
    return Store(tmp_path)


def test_db_init_and_idempotent(tmp_path):
    # Running init_db twice should be safe
    init_db(tmp_path)
    init_db(tmp_path)
    assert (tmp_path / "lab.db").exists()


def test_enqueue_and_claim_job(temp_store):
    spec_dict = {
        "id": "q_test_strat",
        "name": "Queue Test",
        "family": "trend",
        "direction": "long",
        "timeframe": "1d",
        "entry": {"all": [{"left": {"field": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 20}}}]},
        "exit": {"hold_bars": 5, "stop_loss_pct": 5, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
        "params_grid": {},
        "notes": "Queue test",
    }
    spec = validate_spec(spec_dict)
    tickers = ["AAPL", "MSFT"]
    
    n_jobs = enqueue_strategy(temp_store, spec, tickers)
    assert n_jobs == 2

    # Enqueueing again should be idempotent (no extra jobs)
    n_jobs_2 = enqueue_strategy(temp_store, spec, tickers)
    assert n_jobs_2 == 0

    status = queue_status(temp_store)
    assert status["total"] == 2
    assert status["pending"] == 2

    # Claim job
    job1 = temp_store.claim_next_job()
    assert job1 is not None
    assert job1["ticker"] in tickers
    assert "job_id" in job1
    assert "spec_json" in job1

    status = queue_status(temp_store)
    assert status["running"] == 1
    assert status["pending"] == 1

    # Mark done
    temp_store.complete_job(
        job1["job_id"],
        result_path="data/test_trades.parquet",
        ticker=job1["ticker"],
        variant_id=job1["variant_id"],
        sector="Technology",
        metrics_json="{}",
    )
    status = queue_status(temp_store)
    assert status["done"] == 1
    assert status["running"] == 0


def test_reset_stale_running(temp_store):
    spec_dict = {
        "id": "stale_test",
        "name": "Stale Test",
        "family": "trend",
        "direction": "long",
        "timeframe": "1d",
        "entry": {"all": [{"left": {"field": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 20}}}]},
        "exit": {"hold_bars": 5, "stop_loss_pct": 5, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
        "params_grid": {},
        "notes": "Stale test",
    }
    spec = validate_spec(spec_dict)
    enqueue_strategy(temp_store, spec, ["NVDA"])

    job = temp_store.claim_next_job()
    assert job is not None

    # Reset stale jobs
    reset_count = temp_store.reset_stale_running()
    assert reset_count == 1

    status = queue_status(temp_store)
    assert status["running"] == 0
    assert status["pending"] == 1
