"""config.py — Load and validate config.yaml using pydantic v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class PathsConfig(BaseModel):
    data_dir: str = "data"
    library_dir: str = "library"
    reports_dir: str = "reports"
    logs_dir: str = "logs"


class UniverseConfig(BaseModel):
    source: str = "sp500"
    max_tickers: int = Field(500, ge=1)
    extra_tickers: list[str] = []
    include_forex: bool = False


class DataConfig(BaseModel):
    years: int = Field(12, ge=1, le=50)
    interval: str = "1d"
    min_bars: int = Field(500, ge=50)
    batch_size: int = Field(25, ge=1, le=200)
    batch_sleep_s: float = Field(5.0, ge=0)
    refresh_hours: int = Field(20, ge=1)


class BacktestConfig(BaseModel):
    entry_price: str = "next_open"
    cost_bps_per_side: float = Field(5.0, ge=0)
    slippage_bps_per_side: float = Field(5.0, ge=0)
    stop_before_target_if_both_hit: bool = True
    oos_fraction: float = Field(0.30, ge=0.05, le=0.5)
    horizons: list[int] = [1, 3, 5, 10, 20]
    min_trades_total: int = Field(100, ge=1)
    max_variants_per_strategy: int = Field(30, ge=1)


class VerdictConfig(BaseModel):
    min_oos_trades: int = Field(60, ge=1)
    min_t_stat: float = Field(2.0, ge=0)
    fdr_alpha: float = Field(0.10, ge=0.01, le=0.5)
    min_sector_agreement: float = Field(0.6, ge=0, le=1.0)


class ThrottleConfig(BaseModel):
    worker_threads: int = Field(2, ge=1)
    max_cpu_percent: float = Field(50.0, ge=5, le=95)
    duty_sleep_seconds: float = Field(0.5, ge=0)
    active_hours: Optional[str] = None  # e.g. "22:00-10:00"
    pause_if_user_active: bool = False
    pause_if_processes: list[str] = []
    min_battery_percent: float = Field(30.0, ge=0, le=100)
    require_ac_power: bool = False
    max_temp_c: float = Field(82.0, ge=40, le=110)

    @field_validator("active_hours")
    @classmethod
    def validate_active_hours(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        parts = v.split("-")
        if len(parts) != 2:
            raise ValueError("active_hours must be 'HH:MM-HH:MM'")
        for p in parts:
            h, m = p.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError(f"Invalid time: {p}")
        return v


class LLMConfig(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    temperature: float = Field(0.2, ge=0, le=2.0)
    keep_alive: str = "30s"
    timeout_s: int = Field(120, ge=5)
    max_retries: int = Field(3, ge=1)
    enabled: bool = True


class OrchestratorConfig(BaseModel):
    heartbeat_s: int = Field(60, ge=5)
    idle_poll_seconds: int = Field(300, ge=10)
    max_new_strategies_per_cycle: int = Field(3, ge=1)


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class LabConfig(BaseModel):
    paths: PathsConfig = PathsConfig()
    universe: UniverseConfig = UniverseConfig()
    data: DataConfig = DataConfig()
    backtest: BacktestConfig = BacktestConfig()
    verdict: VerdictConfig = VerdictConfig()
    throttle: ThrottleConfig = ThrottleConfig()
    llm: LLMConfig = LLMConfig()
    orchestrator: OrchestratorConfig = OrchestratorConfig()

    def config_hash(self) -> str:
        """SHA-256 of the canonical JSON representation."""
        canonical = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config(path: Path | str | None = None) -> LabConfig:
    """Load and validate config.yaml.  Raises ValueError on bad config."""
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if config_path.exists():
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        raw = {}
    try:
        return LabConfig(**raw)
    except Exception as exc:
        raise ValueError(f"Config validation failed ({config_path}): {exc}") from exc
