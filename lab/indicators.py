"""indicators.py — Pure-function technical indicators implemented with pandas/numpy.

All functions take a DataFrame (OHLCV) or Series and return a Series aligned to the same index.
No lookahead bias: computations use only data available at each bar's close.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(df: pd.DataFrame, *cols: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing columns: {missing}")


# ---------------------------------------------------------------------------
# Trend indicators
# ---------------------------------------------------------------------------

def sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD indicator.

    Returns DataFrame with columns: macd, signal, hist.
    """
    fast_ema = series.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = series.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


# ---------------------------------------------------------------------------
# Momentum indicators
# ---------------------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothed)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    res = 100.0 - (100.0 / (1.0 + rs))
    zero_loss = (avg_loss == 0) & avg_gain.notna()
    res = res.mask(zero_loss & (avg_gain > 0), 100.0)
    res = res.mask(zero_loss & (avg_gain == 0), 50.0)
    return res


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    """Rate of Change (percent)."""
    return (series / series.shift(period) - 1) * 100


def stoch(
    df: pd.DataFrame,
    k: int = 14,
    d: int = 3,
) -> pd.DataFrame:
    """Stochastic Oscillator.

    Returns DataFrame with columns: k, d.
    """
    _require(df, "High", "Low", "Close")
    lowest_low = df["Low"].rolling(k, min_periods=k).min()
    highest_high = df["High"].rolling(k, min_periods=k).max()
    k_line = 100 * (df["Close"] - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d_line = k_line.rolling(d, min_periods=d).mean()
    return pd.DataFrame({"k": k_line, "d": d_line})


# ---------------------------------------------------------------------------
# Volatility indicators
# ---------------------------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing)."""
    _require(df, "High", "Low", "Close")
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bbands(
    series: pd.Series,
    period: int = 20,
    std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands.

    Returns DataFrame with columns: upper, middle, lower, bandwidth.
    """
    middle = sma(series, period)
    sigma = series.rolling(period, min_periods=period).std(ddof=0)
    upper = middle + std * sigma
    lower = middle - std * sigma
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower, "bandwidth": bandwidth})


def keltner(
    df: pd.DataFrame,
    period: int = 20,
    mult: float = 2.0,
) -> pd.DataFrame:
    """Keltner Channels.

    Returns DataFrame with columns: upper, middle, lower.
    """
    _require(df, "High", "Low", "Close")
    middle = ema(df["Close"], period)
    _atr = atr(df, period)
    upper = middle + mult * _atr
    lower = middle - mult * _atr
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower})


# ---------------------------------------------------------------------------
# Trend strength
# ---------------------------------------------------------------------------

def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index.

    Returns DataFrame with columns: adx, plus_di, minus_di.
    """
    _require(df, "High", "Low", "Close")
    prev_high = df["High"].shift(1)
    prev_low = df["Low"].shift(1)
    prev_close = df["Close"].shift(1)

    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    dm_plus = (df["High"] - prev_high).clip(lower=0)
    dm_minus = (prev_low - df["Low"]).clip(lower=0)
    # When dm_plus >= dm_minus, dm_minus is zero and vice versa
    mask = dm_plus >= dm_minus
    dm_plus = dm_plus.where(mask, 0)
    dm_minus = dm_minus.where(~mask, 0)

    smooth = lambda s: s.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()  # noqa: E731
    atr_s = smooth(tr)
    di_plus = 100 * smooth(dm_plus) / atr_s.replace(0, np.nan)
    di_minus = 100 * smooth(dm_minus) / atr_s.replace(0, np.nan)

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx_series = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    return pd.DataFrame({"adx": adx_series, "plus_di": di_plus, "minus_di": di_minus})


# ---------------------------------------------------------------------------
# Channel / range indicators
# ---------------------------------------------------------------------------

def donchian(
    df: pd.DataFrame,
    period: int = 20,
) -> pd.DataFrame:
    """Donchian Channels (prior bars only — excludes current bar).

    Returns DataFrame with columns: upper, lower.
    """
    _require(df, "High", "Low")
    upper = df["High"].shift(1).rolling(period, min_periods=period).max()
    lower = df["Low"].shift(1).rolling(period, min_periods=period).min()
    return pd.DataFrame({"upper": upper, "lower": lower})


def highest(df: pd.DataFrame, period: int = 20, field: str = "High") -> pd.Series:
    """Highest value of `field` over prior `period` bars (current bar excluded)."""
    _require(df, field)
    return df[field].shift(1).rolling(period, min_periods=period).max()


def lowest(df: pd.DataFrame, period: int = 20, field: str = "Low") -> pd.Series:
    """Lowest value of `field` over prior `period` bars (current bar excluded)."""
    _require(df, field)
    return df[field].shift(1).rolling(period, min_periods=period).min()


# ---------------------------------------------------------------------------
# Statistical indicators
# ---------------------------------------------------------------------------

def zscore(series: pd.Series, period: int = 20) -> pd.Series:
    """Rolling Z-score of the series."""
    mu = series.rolling(period, min_periods=period).mean()
    sigma = series.rolling(period, min_periods=period).std(ddof=0)
    return (series - mu) / sigma.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Volume-based indicators
# ---------------------------------------------------------------------------

def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume."""
    _require(df, "Close", "Volume")
    direction = np.sign(df["Close"].diff().fillna(0))
    return (direction * df["Volume"]).cumsum()


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index."""
    _require(df, "High", "Low", "Close", "Volume")
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    raw_money = typical * df["Volume"]
    pos_flow = raw_money.where(typical > typical.shift(1), 0)
    neg_flow = raw_money.where(typical < typical.shift(1), 0)
    pos_sum = pos_flow.rolling(period, min_periods=period).sum()
    neg_sum = neg_flow.rolling(period, min_periods=period).sum()
    mfr = pos_sum / neg_sum.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Chaikin Money Flow."""
    _require(df, "High", "Low", "Close", "Volume")
    hl_range = (df["High"] - df["Low"]).replace(0, np.nan)
    clv = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / hl_range
    money_flow = clv * df["Volume"]
    return (
        money_flow.rolling(period, min_periods=period).sum()
        / df["Volume"].rolling(period, min_periods=period).sum().replace(0, np.nan)
    )


def vol_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume Simple Moving Average."""
    _require(df, "Volume")
    return sma(df["Volume"], period)


def rel_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Relative Volume: current bar's volume / SMA of prior `period` bars' volume.

    Current bar is excluded from the average (no lookahead).
    """
    _require(df, "Volume")
    prior_avg = df["Volume"].shift(1).rolling(period, min_periods=period).mean()
    return df["Volume"] / prior_avg.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Price-based derived indicators
# ---------------------------------------------------------------------------

def gap_pct(df: pd.DataFrame) -> pd.Series:
    """Gap percent: (Open - prev_Close) / prev_Close * 100."""
    _require(df, "Open", "Close")
    return (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1).replace(0, np.nan) * 100


def range_pct(df: pd.DataFrame) -> pd.Series:
    """Range percent: (High - Low) / Close * 100."""
    _require(df, "High", "Low", "Close")
    return (df["High"] - df["Low"]) / df["Close"].replace(0, np.nan) * 100


# ---------------------------------------------------------------------------
# Dispatcher — used by signals.py to evaluate indicator nodes from specs
# ---------------------------------------------------------------------------

INDICATOR_MAP = {
    "sma": lambda df, p: sma(df["Close"], **p),
    "ema": lambda df, p: ema(df["Close"], **p),
    "rsi": lambda df, p: rsi(df["Close"], **p),
    "macd": lambda df, p: macd(df["Close"], **p),
    "bbands": lambda df, p: bbands(df["Close"], **p),
    "atr": lambda df, p: atr(df, **p),
    "adx": lambda df, p: adx(df, **p),
    "stoch": lambda df, p: stoch(df, **p),
    "roc": lambda df, p: roc(df["Close"], **p),
    "donchian": lambda df, p: donchian(df, **p),
    "zscore": lambda df, p: zscore(df["Close"], **p),
    "obv": lambda df, p: obv(df),
    "mfi": lambda df, p: mfi(df, **p),
    "cmf": lambda df, p: cmf(df, **p),
    "vol_sma": lambda df, p: vol_sma(df, **p),
    "rel_volume": lambda df, p: rel_volume(df, **p),
    "keltner": lambda df, p: keltner(df, **p),
    "gap_pct": lambda df, p: gap_pct(df),
    "range_pct": lambda df, p: range_pct(df),
    "highest": lambda df, p: highest(df, **p),
    "lowest": lambda df, p: lowest(df, **p),
}


def compute_indicator(df: pd.DataFrame, name: str, params: dict, output: str | None = None, shift: int = 0) -> pd.Series:
    """Compute a named indicator and optionally select a sub-series.

    Args:
        df: OHLCV DataFrame.
        name: Indicator name (must be in INDICATOR_MAP).
        params: Parameters dict.
        output: Sub-series name for multi-output indicators (e.g. 'macd', 'signal').
        shift: Number of bars to shift back (≥ 0).
    """
    if name not in INDICATOR_MAP:
        raise ValueError(f"Unknown indicator: '{name}'")
    result = INDICATOR_MAP[name](df, params)
    if isinstance(result, pd.DataFrame):
        if output is None:
            raise ValueError(f"Indicator '{name}' returns multiple outputs; specify 'output' field. Available: {list(result.columns)}")
        if output not in result.columns:
            raise ValueError(f"Indicator '{name}' has no output '{output}'. Available: {list(result.columns)}")
        result = result[output]
    if shift > 0:
        result = result.shift(shift)
    return result
