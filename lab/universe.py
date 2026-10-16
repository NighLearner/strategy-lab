"""universe.py — Build and refresh the S&P 500 ticker universe."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SECTOR_ETFS: dict[str, str] = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Industrials": "XLI",
}


def _normalise_ticker(sym: str) -> str:
    """Replace dots with hyphens for yfinance compatibility."""
    return sym.replace(".", "-").strip().upper()


def fetch_sp500(timeout: int = 30) -> pd.DataFrame:
    """Download S&P 500 constituents from Wikipedia.

    Returns a DataFrame with columns: ticker, name, sector, industry.
    Raises requests.RequestException on network failure.
    """
    logger.info("Fetching S&P 500 list from Wikipedia …")
    resp = requests.get(SP500_URL, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
    resp.raise_for_status()

    tables = pd.read_html(io.StringIO(resp.text))
    # The first table on that page is the constituents list.
    df = tables[0]

    # Normalise column names across Wikipedia edits
    col_map: dict[str, str] = {}
    for col in df.columns:
        low = col.lower()
        if "symbol" in low or "ticker" in low:
            col_map[col] = "ticker"
        elif "security" in low or "company" in low or "name" in low:
            col_map[col] = "name"
        elif "gics sector" in low or "sector" in low:
            col_map[col] = "sector"
        elif "sub-industry" in low or "industry" in low:
            col_map[col] = "industry"
    df = df.rename(columns=col_map)

    keep = [c for c in ["ticker", "name", "sector", "industry"] if c in df.columns]
    df = df[keep].dropna(subset=["ticker"]).copy()
    df["ticker"] = df["ticker"].apply(_normalise_ticker)
    df = df[df["ticker"].str.match(r"^[A-Z0-9\-]{1,10}$")]
    logger.info("Fetched %d tickers from Wikipedia.", len(df))
    return df.reset_index(drop=True)


def build_universe(
    data_dir: str | Path = "data",
    extra_tickers: list[str] | None = None,
    max_tickers: int = 500,
) -> pd.DataFrame:
    """Fetch S&P 500 (+ extras), save to universe.csv and return the DataFrame.

    Falls back to the existing CSV on network failure.
    """
    csv_path = Path(data_dir) / "universe.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        df = fetch_sp500()
    except Exception as exc:
        logger.warning("Network fetch failed (%s). Falling back to cached CSV.", exc)
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            logger.info("Loaded %d tickers from cache.", len(df))
            return df
        raise RuntimeError("No cached universe.csv and network fetch failed.") from exc

    # Append extra tickers (no sector info)
    if extra_tickers:
        extras = pd.DataFrame(
            {
                "ticker": [_normalise_ticker(t) for t in extra_tickers],
                "name": [""] * len(extra_tickers),
                "sector": ["Unknown"] * len(extra_tickers),
                "industry": [""] * len(extra_tickers),
            }
        )
        df = pd.concat([df, extras], ignore_index=True)

    df = df.drop_duplicates(subset="ticker").head(max_tickers)
    df.to_csv(csv_path, index=False)
    logger.info("Universe saved: %d tickers, %d sectors → %s", len(df), df["sector"].nunique(), csv_path)

    # Print sector counts
    if "sector" in df.columns:
        counts = df["sector"].value_counts()
        for sector, cnt in counts.items():
            logger.info("  %-35s %d", sector, cnt)

    return df


def load_universe(data_dir: str | Path = "data") -> pd.DataFrame:
    """Load the saved universe CSV; raises if it doesn't exist."""
    csv_path = Path(data_dir) / "universe.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Universe CSV not found: {csv_path}. Run `lab init` first.")
    return pd.read_csv(csv_path)
