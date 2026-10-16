"""cli.py — Command-line interface for strategy-lab.

Commands: init, run, stop, pause, resume, status, report, reset-failed
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="lab",
    help="Idle-Time Strategy Research Lab",
    add_completion=False,
)
console = Console()


def _load_config(config_path: str):
    from lab.config import load_config
    try:
        return load_config(config_path)
    except ValueError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@app.command()
def init(
    config: str = typer.Option("config.yaml", "--config", "-c", help="Path to config.yaml"),
    force: bool = typer.Option(False, "--force", help="Force re-download of all data"),
):
    """Initialise: build universe, download price data, import seed strategies."""
    from lab.logging_setup import setup_logging
    from lab.data import download_universe
    from lab.store import init_db
    from lab.universe import build_universe, load_universe
    from lab.agents.librarian import import_seed_cards, SEED_CARDS
    from lab.spec import load_spec, save_spec
    from lab.queue import enqueue_strategy
    from lab.store import Store

    cfg = _load_config(config)
    setup_logging(cfg.paths.logs_dir)
    logger = logging.getLogger(__name__)

    data_dir = Path(cfg.paths.data_dir)
    library_dir = Path(cfg.paths.library_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    library_dir.mkdir(parents=True, exist_ok=True)
    (library_dir / "specs").mkdir(parents=True, exist_ok=True)

    # Init DB
    init_db(data_dir)
    console.print("[green]✓[/green] Database initialised.")

    # Build universe
    console.print("Building universe …")
    universe_df = build_universe(
        data_dir,
        extra_tickers=cfg.universe.extra_tickers,
        max_tickers=cfg.universe.max_tickers,
    )
    console.print(f"[green]✓[/green] Universe: {len(universe_df)} tickers, {universe_df['sector'].nunique()} sectors.")

    # Download prices
    tickers = universe_df["ticker"].tolist()
    console.print(f"Downloading price data for {len(tickers)} tickers (this may take a while) …")
    results = download_universe(
        tickers,
        data_dir,
        years=cfg.data.years,
        min_bars=cfg.data.min_bars,
        batch_size=cfg.data.batch_size,
        batch_sleep_s=cfg.data.batch_sleep_s,
        refresh_hours=cfg.data.refresh_hours,
        force=force,
    )
    ok = sum(1 for v in results.values() if v in ("ok", "cached"))
    excl = len(results) - ok
    console.print(f"[green]✓[/green] Data: {ok} cached, {excl} excluded.")

    # Import seed cards
    n = import_seed_cards(library_dir)
    console.print(f"[green]✓[/green] Seed library: {n} cards imported.")

    # Write seed JSON specs
    from lab.spec import StrategySpec, validate_spec
    _write_seed_specs(library_dir)

    # Enqueue seed specs
    store = Store(data_dir)
    specs_dir = library_dir / "specs"
    total_jobs = 0
    for spec_path in specs_dir.glob("*.json"):
        try:
            spec = load_spec(str(spec_path))
            n_jobs = enqueue_strategy(store, spec, tickers,
                                      max_variants=cfg.backtest.max_variants_per_strategy)
            total_jobs += n_jobs
        except Exception as exc:
            console.print(f"[yellow]Warning:[/yellow] Could not enqueue {spec_path.name}: {exc}")

    console.print(f"[green]✓[/green] Enqueued {total_jobs} jobs.")
    console.print("[bold green]Init complete. Run `python -m lab run` to start backtesting.[/bold green]")


def _write_seed_specs(library_dir: Path) -> None:
    """Write JSON spec files for all seed strategies."""
    import json as _json
    specs_dir = library_dir / "specs"
    specs_dir.mkdir(exist_ok=True)

    SEED_SPECS = _get_seed_specs()
    for spec_data in SEED_SPECS:
        path = specs_dir / f"{spec_data['id']}.json"
        if not path.exists():
            path.write_text(_json.dumps(spec_data, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _get_seed_specs() -> list[dict]:
    """Hand-crafted JSON specs for seed strategies."""
    return [
        {
            "id": "three_white_soldiers_v1",
            "name": "Three White Soldiers",
            "family": "candlestick_reversal",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"pattern": "three_white_soldiers", "params": {"body_ratio": 0.5, "upper_ratio": 0.3}},
            "exit": {"hold_bars": 10, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
            "params_grid": {"exit.hold_bars": [5, 10, 20]},
            "notes": "Three consecutive bull bars with strong bodies — bullish reversal.",
        },
        {
            "id": "three_black_crows_v1",
            "name": "Three Black Crows",
            "family": "candlestick_reversal",
            "direction": "short",
            "timeframe": "1d",
            "entry": {"pattern": "three_black_crows", "params": {"body_ratio": 0.5, "lower_ratio": 0.3}},
            "exit": {"hold_bars": 10, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
            "params_grid": {"exit.hold_bars": [5, 10, 20]},
            "notes": "Three consecutive bear bars — bearish reversal.",
        },
        {
            "id": "bullish_engulfing_v1",
            "name": "Bullish Engulfing",
            "family": "candlestick_reversal",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"pattern": "bullish_engulfing", "params": {}},
            "exit": {"hold_bars": 10, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
            "params_grid": {"exit.hold_bars": [5, 10, 20]},
            "notes": "Bullish bar engulfs previous bearish bar.",
        },
        {
            "id": "rsi_oversold_uptrend_v1",
            "name": "RSI Oversold in Uptrend",
            "family": "mean_reversion",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"all": [
                {"left": {"indicator": "rsi", "params": {"period": 14}}, "op": "<", "right": {"value": 30}},
                {"left": {"field": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 200}}},
            ]},
            "exit": {"hold_bars": 10, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None,
                     "any": [{"left": {"indicator": "rsi", "params": {"period": 14}}, "op": ">", "right": {"value": 50}}]},
            "params_grid": {"entry.all.0.right.value": [25, 30, 35]},
            "notes": "Buy oversold dips in uptrend.",
        },
        {
            "id": "golden_cross_v1",
            "name": "Golden Cross",
            "family": "trend",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"left": {"indicator": "sma", "params": {"period": 50}}, "op": "cross_above",
                      "right": {"indicator": "sma", "params": {"period": 200}}},
            "exit": {"hold_bars": 60, "stop_loss_pct": 15, "take_profit_pct": None, "trailing_atr_mult": None, "any": [
                {"left": {"indicator": "sma", "params": {"period": 50}}, "op": "cross_below",
                 "right": {"indicator": "sma", "params": {"period": 200}}}
            ]},
            "params_grid": {},
            "notes": "50-day SMA crosses above 200-day SMA — classic trend signal.",
        },
        {
            "id": "donchian_breakout_v1",
            "name": "Donchian Channel Breakout",
            "family": "breakout",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"left": {"field": "close"}, "op": ">", "right": {"indicator": "donchian", "params": {"period": 20}, "output": "upper"}},
            "exit": {"hold_bars": 20, "stop_loss_pct": 10, "take_profit_pct": None, "trailing_atr_mult": None,
                     "any": [{"left": {"field": "close"}, "op": "<", "right": {"indicator": "donchian", "params": {"period": 10}, "output": "lower"}}]},
            "params_grid": {"exit.hold_bars": [10, 20, 30]},
            "notes": "Breakout above Donchian upper channel (prior 20 bars).",
        },
        {
            "id": "macd_cross_v1",
            "name": "MACD Signal Cross Below Zero",
            "family": "momentum",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"all": [
                {"left": {"indicator": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}, "output": "macd"},
                 "op": "cross_above",
                 "right": {"indicator": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}, "output": "signal"}},
                {"left": {"indicator": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}, "output": "macd"},
                 "op": "<", "right": {"value": 0}},
            ]},
            "exit": {"hold_bars": 15, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None, "any": [
                {"left": {"indicator": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}, "output": "macd"},
                 "op": "cross_below",
                 "right": {"indicator": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}, "output": "signal"}},
            ]},
            "params_grid": {},
            "notes": "MACD crosses signal while negative — early momentum shift.",
        },
        {
            "id": "volume_spike_breakout_v1",
            "name": "Volume Spike Breakout",
            "family": "volume_flow",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"all": [
                {"left": {"indicator": "rel_volume", "params": {"period": 20}}, "op": ">", "right": {"value": 2.0}},
                {"left": {"field": "close"}, "op": ">", "right": {"indicator": "highest", "params": {"period": 20, "field": "High"}}},
            ]},
            "exit": {"hold_bars": 10, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
            "params_grid": {"exit.hold_bars": [5, 10, 15]},
            "notes": "High volume breakout to new highs.",
        },
        {
            "id": "cmf_accumulation_v1",
            "name": "CMF Accumulation",
            "family": "volume_flow",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"all": [
                {"left": {"indicator": "cmf", "params": {"period": 20}}, "op": ">", "right": {"value": 0.15}},
                {"left": {"field": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 50}}},
            ]},
            "exit": {"hold_bars": 15, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None,
                     "any": [{"left": {"indicator": "cmf", "params": {"period": 20}}, "op": "<", "right": {"value": 0}}]},
            "params_grid": {},
            "notes": "Positive money flow with uptrend context.",
        },
        {
            "id": "hammer_reversal_v1",
            "name": "Hammer Reversal",
            "family": "candlestick_reversal",
            "direction": "long",
            "timeframe": "1d",
            "entry": {"pattern": "hammer", "params": {}},
            "exit": {"hold_bars": 10, "stop_loss_pct": 8, "take_profit_pct": None, "trailing_atr_mult": None, "any": []},
            "params_grid": {"exit.hold_bars": [5, 10, 20]},
            "notes": "Hammer candle after decline — bullish reversal signal.",
        },
    ]


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@app.command()
def run(
    config: str = typer.Option("config.yaml", "--config", "-c"),
    dry_llm: bool = typer.Option(False, "--dry-llm", help="Use fake LLM for testing"),
):
    """Start the main backtesting loop (resumes from database)."""
    from lab.orchestrator import Orchestrator
    cfg = _load_config(config)
    orch = Orchestrator(cfg, dry_llm=dry_llm)
    orch.run()


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

@app.command()
def stop():
    """Signal the running lab to stop after the current job."""
    stop_path = Path("data/STOP")
    stop_path.parent.mkdir(exist_ok=True)
    stop_path.touch()
    console.print("[yellow]STOP file created.[/yellow] The lab will finish the current job and exit.")


# ---------------------------------------------------------------------------
# pause / resume
# ---------------------------------------------------------------------------

@app.command()
def pause():
    """Create a PAUSE file to soft-pause the loop."""
    Path("data/PAUSE").touch()
    console.print("[yellow]PAUSE file created.[/yellow]")


@app.command()
def resume():
    """Remove the PAUSE file to resume the loop."""
    p = Path("data/PAUSE")
    if p.exists():
        p.unlink()
        console.print("[green]PAUSE file removed — loop will resume.[/green]")
    else:
        console.print("No PAUSE file found.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command()
def status(
    config: str = typer.Option("config.yaml", "--config", "-c"),
):
    """Show current queue status and system metrics."""
    from lab.queue import queue_status
    from lab.store import Store
    from lab.throttle import Throttle

    cfg = _load_config(config)
    data_dir = Path(cfg.paths.data_dir)

    if not (data_dir / "lab.db").exists():
        console.print("[yellow]No database found. Run `lab init` first.[/yellow]")
        raise typer.Exit(0)

    store = Store(data_dir)
    q = queue_status(store)
    throttle = Throttle(cfg.throttle)
    sys_status = throttle.get_status()

    # Queue table
    table = Table(title="Job Queue")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Total", str(q["total"]))
    table.add_row("Done", f"[green]{q['done']}[/green]")
    table.add_row("Pending", str(q["pending"]))
    table.add_row("Running", str(q["running"]))
    table.add_row("Failed", f"[red]{q['failed']}[/red]")
    table.add_row("% Done", f"{q['pct_done']}%")
    console.print(table)

    # System status
    sys_table = Table(title="System Status")
    sys_table.add_column("Metric")
    sys_table.add_column("Value", justify="right")
    sys_table.add_row("CPU %", f"{sys_status['cpu_pct']:.1f}%")
    sys_table.add_row("Memory (MB)", str(sys_status["mem_used_mb"]))
    if sys_status["battery_pct"] is not None:
        plugged = "[Plugged]" if sys_status["plugged"] else "[Battery]"
        sys_table.add_row("Battery", f"{sys_status['battery_pct']:.0f}% {plugged}")
    if sys_status["gpu_temp_c"] is not None:
        sys_table.add_row("GPU Temp", f"{sys_status['gpu_temp_c']:.0f} C")
    if sys_status["gpu_vram_free_mb"] is not None:
        sys_table.add_row("GPU VRAM Free", f"{sys_status['gpu_vram_free_mb']} MB")
    sys_table.add_row("Throttle OK", "[green]Yes[/green]" if sys_status["throttle_ok"] else "[red]No[/red]")
    console.print(sys_table)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@app.command()
def report(
    config: str = typer.Option("config.yaml", "--config", "-c"),
):
    """Generate/refresh reports for all evaluated variants."""
    from lab.report import write_leaderboard, write_strategy_report
    from lab.store import Store

    cfg = _load_config(config)
    store = Store(Path(cfg.paths.data_dir))
    all_results = store.list_all_results()

    for r in all_results:
        write_strategy_report(r["variant_id"], store, cfg.paths.reports_dir)

    lb_path = write_leaderboard(store, cfg.paths.reports_dir)
    console.print(f"[green]Reports generated. Leaderboard:[/green] {lb_path}")


# ---------------------------------------------------------------------------
# reset-failed
# ---------------------------------------------------------------------------

@app.command(name="reset-failed")
def reset_failed(
    config: str = typer.Option("config.yaml", "--config", "-c"),
):
    """Reset all failed jobs back to pending."""
    from lab.store import Store
    import sqlite3

    cfg = _load_config(config)
    store = Store(Path(cfg.paths.data_dir))
    from lab.store import _get_conn
    db_path = Path(cfg.paths.data_dir) / "lab.db"
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status='pending', attempts=0, error=NULL WHERE status='failed'"
        )
        conn.commit()
    console.print(f"[green]Reset {cursor.rowcount} failed jobs to pending.[/green]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app()


if __name__ == "__main__":
    main()
