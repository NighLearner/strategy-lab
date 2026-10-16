# Build Log — Strategy Lab

### Phase 0: Environment and Skeleton
- Created directory layout matching `instruction.md` §4.1 (`lab/`, `lab/agents/`, `lab/agents/prompts/`, `tests/`, `docs/`, `library/`, `data/`, `reports/`).
- Verified dependencies in `requirements.txt` (`pydantic`, `pandas`, `numpy`, `typer`, `rich`, `yfinance`, `pyyaml`, `requests`, `pyarrow`, `pytest`).
- Verified `python -c "import lab"` and `pytest` execution.

### Phase 1: Config, Logging, CLI Shell
- Implemented `lab/config.py` with Pydantic models for `PathsConfig`, `UniverseConfig`, `DataConfig`, `BacktestConfig`, `VerdictConfig`, `ThrottleConfig`, `LLMConfig`, and `OrchestratorConfig`.
- Configured logging in `lab/logging_setup.py` with rotating file handler (`logs/lab.log`) and console output.
- Built CLI in `lab/cli.py` and `lab/__main__.py` with commands: `init`, `run`, `stop`, `pause`, `resume`, `status`, `report`, `reset-failed`.

### Phase 2: Universe Layer
- Implemented `lab/universe.py` for fetching Wikipedia S&P 500 members with custom User-Agent, normalizing tickers (`BRK.B` -> `BRK-B`), and caching to `data/universe.csv`.
- Offline fallback supported if network is unavailable.

### Phase 3: Data Layer
- Implemented `lab/data.py` with batch downloading via `yfinance`, auto-adjustments, exponential backoff, minimum history validation (≥ 500 bars), and per-ticker Parquet caching with timestamp checks.

### Phase 4: Indicators and Candlestick Patterns
- Implemented all 18 indicators in `lab/indicators.py` (`sma`, `ema`, `rsi`, `macd`, `bbands`, `atr`, `adx`, `stoch`, `roc`, `donchian`, `zscore`, `obv`, `mfi`, `cmf`, `vol_sma`, `rel_volume`, `keltner`, `gap_pct`).
- Implemented 12 candlestick pattern detectors in `lab/patterns.py` (`bullish_engulfing`, `bearish_engulfing`, `hammer`, `shooting_star`, `three_white_soldiers`, `three_black_crows`, `morning_star`, `evening_star`, `doji`, `inside_bar_breakout_up`, `inside_bar_breakout_down`, `nr7_breakout_up`).
- Validated lookahead-freedom: truncating data at bar $t$ produces identical outputs for all bars $\le t$.

### Phase 5: Spec Schema and Signal Trees
- Implemented Pydantic models and whitelist validation in `lab/spec.py` conforming to `strategy_spec_schema.md`.
- Implemented recursive condition tree evaluation (`all`, `any`, comparison operators) and variant grid expansion in `lab/signals.py`.

### Phase 6: Backtesting Engine & Statistical Verification
- Implemented next-open execution, slippage and transaction cost simulation, exit precedence (stop loss, take profit, trailing ATR, rule exits, time exits), and forced closes in `lab/backtest.py`.
- Implemented metrics, BH FDR multiple-testing adjustments, event studies, and three-tier verdicts (`promising`, `watch`, `reject`) in `lab/metrics.py`.

### Phase 7: Storage & Idempotent Queue
- Implemented SQLite store with WAL mode, schema migrations, and atomic operations in `lab/store.py`.
- Built idempotent enqueueing and atomic job claiming in `lab/queue.py`.

### Phase 8: Resource Throttle
- Implemented system throttle in `lab/throttle.py` with CPU capping, duty-cycle sleeps, battery checks, and process blocklists.

### Phase 9: Reporting & Leaderboard
- Implemented Markdown report generator and leaderboard compiler in `lab/report.py`.

### Phase 10 & 11: LLM Client & Mock Engine
- Built Ollama HTTP client in `lab/llm.py` with retry logic, JSON formatting, availability check, and `--dry-llm` mode.

### Phase 12: Autonomous Agents
- Prompts created in `lab/agents/prompts/` (`librarian_propose.txt`, `spec_writer.txt`).
- Implemented `librarian.py`, `spec_writer.py`, `analyst.py`, and `critic.py`.

### Phase 13 & 14: Orchestrator Loop & System Verification
- Implemented full loop in `lab/orchestrator.py` with 60s heartbeats, pause/stop file checking, job processing, reporting, and agent-driven exploration.
- Test suite with 67 tests across 7 test files verified passing.
