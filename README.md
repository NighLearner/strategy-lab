# Strategy Lab

An idle-time algorithmic trading strategy research lab that continuously tests price-action, momentum, and mean-reversion trading rules across the S&P 500 universe with anti-overfitting controls and an optional local LLM agent loop.

---

## Features

- **Backtesting Engine**: Daily bar execution at next-day open, per-side transaction costs and slippage, exact exit precedence (stop loss, take profit, trailing ATR stop, rule exits, time exits).
- **Comprehensive Indicator Suite**: Pure-Python/NumPy/Pandas technical indicators and 12 classic candlestick patterns with lookahead-free guarantees.
- **Strict Anti-Overfitting**:
  - In-sample (70%) vs. Out-of-sample (30%) chronological split.
  - Benjamini–Hochberg False Discovery Rate (FDR) control across variants.
  - Sector agreement gates and random-entry Monte Carlo baselines.
  - Three-tier verdicts: `promising`, `watch`, and `reject`.
- **Safe & Idempotent Architecture**:
  - SQLite with Write-Ahead Logging (WAL) and atomic transactions.
  - Resumes seamlessly after interrupts or system crashes without duplicate work.
- **Resource Governor (Throttle)**:
  - Background CPU cap governor, thread throttling, thermal safeguards, and battery checks.
- **Autonomous Multi-Agent Loop (Ollama)**:
  - **Librarian**: Proposes new strategy cards and manages the strategy repository.
  - **SpecWriter**: Converts textual cards into schema-validated JSON specifications.
  - **Analyst**: Generates evidence-grounded commentary strictly from backtest metrics.
  - **Critic**: Analyzes verdicts and proposes targeted parameter mutations.

---

## Installation

Ensure Python 3.10+ is installed:

```bash
git clone <repo-url>
cd strategy-lab
pip install -r requirements.txt
```

---

## CLI Usage

### 1. Initialize Universe & Download Data
Build the S&P 500 universe, download 12 years of daily OHLCV data into local Parquet caches, and populate the database with seed strategies:

```bash
python -m lab init
```

### 2. Run the Research Engine
Start the backtester and agent cycle:

```bash
python -m lab run
```

To run with a simulated/dry LLM:
```bash
python -m lab run --dry-llm
```

### 3. Check Status
View real-time job queue counts, completion percentage, and system resource metrics:

```bash
python -m lab status
```

### 4. Soft Pause & Resume
Pause execution after the current job completes:

```bash
python -m lab pause
python -m lab resume
```

### 5. Stop Gracefully
Signal the engine to cleanly finish the active job, flush database transactions, and exit:

```bash
python -m lab stop
```

### 6. Generate Reports
Compile markdown summary reports and the leaderboard:

```bash
python -m lab report
```

### 7. Reset Failed Jobs
Reset failed jobs back to `pending`:

```bash
python -m lab reset-failed
```

---

## Configuration (`config.yaml`)

Edit `config.yaml` to adjust backtest parameters, resource caps, and LLM settings:

```yaml
paths:
  data_dir: data
  library_dir: library
  reports_dir: reports
  logs_dir: logs

universe:
  source: sp500
  max_tickers: 500
  extra_tickers: []
  include_forex: false

data:
  years: 12
  interval: 1d
  min_bars: 500
  batch_size: 25
  batch_sleep_s: 5
  refresh_hours: 20

backtest:
  entry_price: next_open
  cost_bps_per_side: 5
  slippage_bps_per_side: 5
  stop_before_target_if_both_hit: true
  oos_fraction: 0.30
  horizons: [1, 3, 5, 10, 20]
  min_trades_total: 100
  max_variants_per_strategy: 30

verdict:
  min_oos_trades: 60
  min_t_stat: 2.0
  fdr_alpha: 0.10
  min_sector_agreement: 0.60

throttle:
  worker_threads: 2
  max_cpu_percent: 50
  duty_sleep_seconds: 0.5
  active_hours: null
  min_battery_percent: 30
  max_temp_c: 82

llm:
  host: "http://localhost:11434"
  model: "qwen2.5:3b"
  temperature: 0.2
  keep_alive: "30s"
  timeout_s: 120
  max_retries: 3
  enabled: true

orchestrator:
  heartbeat_s: 60
  idle_poll_seconds: 300
  max_new_strategies_per_cycle: 3
```

---

## Running the Test Suite

Run the full pytest suite:

```bash
python -m pytest
```

---

## Known Limitations & Disclaimers

1. **Survivorship Bias**: The default universe uses current S&P 500 constituents. Historical survivorship bias is present as delisted or bankrupted companies are excluded.
2. **Adjusted Price Data**: Price history is sourced via Yahoo Finance (`auto_adjust=True`). Corporate action adjustments and split accounting may occasionally contain anomalies.
3. **Execution Assumptions**: Fills occur at next-day open with fixed transaction cost and slippage models. Real-world market impact, spread widening, and intraday liquidity constraints are not modeled.
4. **Not Financial Advice**: All outputs, reports, and agent commentaries produced by this tool are strictly for educational and empirical research purposes. Past performance is no guarantee of future returns.
