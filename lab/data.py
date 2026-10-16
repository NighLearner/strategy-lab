"""data.py — yfinance download, per-ticker Parquet cache, incremental refresh, validation."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_META_FILE = "prices_meta.json"
_REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _meta_path(data_dir: Path) -> Path:
    return data_dir / "prices" / _META_FILE


def _load_meta(data_dir: Path) -> dict:
    p = _meta_path(data_dir)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_meta(data_dir: Path, meta: dict) -> None:
    p = _meta_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def _parquet_path(data_dir: Path, ticker: str) -> Path:
    return data_dir / "prices" / f"{ticker}.parquet"


def _normalise_frame(raw: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Flatten MultiIndex columns, keep OHLCV, normalise index."""
    if raw is None or raw.empty:
        return None

    df = raw.copy()

    # Handle MultiIndex columns (multi-ticker download)
    if isinstance(df.columns, pd.MultiIndex):
        # Try to pull out this ticker's slice
        if ticker in df.columns.get_level_values(1):
            df = df.xs(ticker, axis=1, level=1)
        elif ticker in df.columns.get_level_values(0):
            df = df.xs(ticker, axis=1, level=0)
        else:
            # Flatten: take first level
            df.columns = df.columns.get_level_values(0)

    # Capitalise columns
    df.columns = [c.capitalize() if c.lower() in [x.lower() for x in _REQUIRED_COLS]
                  else c for c in df.columns]

    # Keep only OHLCV
    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        logger.warning("[%s] Missing columns after normalise: %s", ticker, missing)
        return None

    df = df[_REQUIRED_COLS].copy()

    # Normalise index to timezone-naive DatetimeIndex named "Date"
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
    df.index.name = "Date"
    df = df.sort_index()

    return df


def _validate(df: pd.DataFrame, ticker: str, min_bars: int = 500) -> tuple[bool, str]:
    """Return (ok, reason) for the DataFrame."""
    if df is None or df.empty:
        return False, "no_data"

    # Sorted unique index
    if not df.index.is_monotonic_increasing or df.index.duplicated().any():
        return False, "bad_index"

    # Non-positive prices
    for col in ["Open", "High", "Low", "Close"]:
        if (df[col] <= 0).any():
            return False, f"non_positive_{col.lower()}"

    # NaN OHLC
    if df[["Open", "High", "Low", "Close"]].isna().any().any():
        return False, "nan_ohlc"

    # OHLC consistency
    bad_high = df["High"] < df[["Open", "Close"]].max(axis=1)
    bad_low = df["Low"] > df[["Open", "Close"]].min(axis=1)
    if bad_high.any() or bad_low.any():
        # Drop bad bars and check what's left
        df_clean = df[~(bad_high | bad_low)]
        if len(df_clean) < min_bars:
            return False, "bad_ohlc_many"

    # Minimum history
    if len(df) < min_bars:
        return False, "too_short"

    # Very low-priced tickers (median < $1)
    if df["Close"].median() < 1.0:
        return False, "penny_stock"

    return True, "ok"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_batch(
    tickers: list[str],
    start: str,
    end: str,
    backoff: tuple[int, ...] = (10, 30, 90),
) -> dict[str, pd.DataFrame]:
    """Download a batch of tickers with exponential backoff. Returns {ticker: df}."""
    import yfinance as yf  # imported here to allow mocking in tests

    attempt = 0
    while True:
        try:
            raw = yf.download(
                tickers=tickers,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                threads=False,
                progress=False,
            )
            results: dict[str, pd.DataFrame] = {}
            for tk in tickers:
                norm = _normalise_frame(raw, tk)
                results[tk] = norm  # type: ignore[assignment]
            return results
        except Exception as exc:
            if attempt >= len(backoff):
                logger.error("Batch download failed after %d attempts: %s", attempt + 1, exc)
                return {tk: None for tk in tickers}  # type: ignore[dict-item]
            wait = backoff[attempt]
            logger.warning("Download error (attempt %d): %s. Retry in %ds.", attempt + 1, exc, wait)
            time.sleep(wait)
            attempt += 1


# ---------------------------------------------------------------------------
# Cache read/write
# ---------------------------------------------------------------------------

def _read_cache(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        return df
    except Exception as exc:
        logger.warning("Corrupt cache %s: %s", path, exc)
        return None


def _write_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_ticker(
    ticker: str,
    data_dir: Path,
    years: int = 12,
    min_bars: int = 500,
    refresh_hours: int = 20,
    force: bool = False,
) -> tuple[bool, str]:
    """Ensure ticker is cached and up to date. Returns (ok, reason).

    Skips if refreshed within ``refresh_hours``.
    """
    meta = _load_meta(data_dir)
    ticker_meta = meta.get(ticker, {})

    # Check if already excluded
    if ticker_meta.get("status") == "excluded":
        return False, ticker_meta.get("reason", "excluded")

    # Check refresh window
    last_refresh = ticker_meta.get("last_refresh")
    if last_refresh and not force:
        elapsed_h = (datetime.utcnow() - datetime.fromisoformat(last_refresh)).total_seconds() / 3600
        if elapsed_h < refresh_hours:
            return True, "cached"

    cache_path = _parquet_path(data_dir, ticker)
    cached = _read_cache(cache_path)

    end_date = date.today().isoformat()
    if cached is not None and len(cached) > 0:
        last_bar = cached.index[-1].date()
        # Incremental fetch: from 5 days before last bar
        start_date = (last_bar - timedelta(days=5)).isoformat()
    else:
        start_date = (date.today() - timedelta(days=years * 365)).isoformat()

    batch = _download_batch([ticker], start_date, end_date)
    new_df = batch.get(ticker)

    if new_df is not None and not new_df.empty:
        if cached is not None:
            # Check for split/dividend adjustment discrepancy
            overlap = new_df.index.intersection(cached.index)
            if len(overlap) >= 3:
                ratio = (new_df.loc[overlap, "Close"] / cached.loc[overlap, "Close"]).dropna()
                if ratio.empty is False and ((ratio - 1).abs() > 0.005).any():
                    logger.info("[%s] Price discrepancy detected — full re-download.", ticker)
                    start_date = (date.today() - timedelta(days=years * 365)).isoformat()
                    batch = _download_batch([ticker], start_date, end_date)
                    new_df = batch.get(ticker)
                    cached = None

        combined = pd.concat([cached, new_df] if cached is not None else [new_df])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    elif cached is not None:
        combined = cached
    else:
        combined = new_df  # type: ignore[assignment]

    ok, reason = _validate(combined, ticker, min_bars)
    if not ok:
        logger.warning("[%s] Excluded: %s", ticker, reason)
        meta[ticker] = {
            "status": "excluded",
            "reason": reason,
            "last_refresh": datetime.utcnow().isoformat(),
        }
        _save_meta(data_dir, meta)
        return False, reason

    # Drop zero-volume-only rows
    combined = combined[~((combined["Volume"] == 0) & combined["Volume"].notna())]

    if cached is None or len(combined) > len(cached):
        _write_cache(cache_path, combined)

    meta[ticker] = {
        "status": "ok",
        "last_bar": combined.index[-1].date().isoformat(),
        "n_bars": len(combined),
        "last_refresh": datetime.utcnow().isoformat(),
        "reason": "",
    }
    _save_meta(data_dir, meta)
    return True, "ok"


def download_universe(
    tickers: list[str],
    data_dir: Path,
    years: int = 12,
    min_bars: int = 500,
    batch_size: int = 25,
    batch_sleep_s: float = 5.0,
    refresh_hours: int = 20,
    force: bool = False,
) -> dict[str, str]:
    """Batch-download and cache all tickers. Returns {ticker: status_reason}."""
    results: dict[str, str] = {}
    batches = [tickers[i : i + batch_size] for i in range(0, len(tickers), batch_size)]

    for bi, batch in enumerate(batches):
        logger.info("Batch %d/%d (%d tickers) …", bi + 1, len(batches), len(batch))
        for ticker in batch:
            ok, reason = refresh_ticker(ticker, data_dir, years, min_bars, refresh_hours, force)
            results[ticker] = reason
            logger.debug("[%s] %s", ticker, reason)

        if bi < len(batches) - 1:
            time.sleep(batch_sleep_s)

    n_ok = sum(1 for v in results.values() if v in ("ok", "cached"))
    n_excl = len(results) - n_ok
    logger.info("Download complete: %d ok / cached, %d excluded/failed.", n_ok, n_excl)
    return results


def load_ticker(ticker: str, data_dir: Path) -> Optional[pd.DataFrame]:
    """Load a ticker's OHLCV DataFrame from cache.  Returns None if not cached."""
    return _read_cache(_parquet_path(data_dir, ticker))


def get_meta(data_dir: Path) -> dict:
    """Return the full prices metadata dict."""
    return _load_meta(data_dir)
