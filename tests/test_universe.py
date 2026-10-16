"""test_universe.py — Unit tests for universe.py."""

from unittest.mock import patch, MagicMock
from pathlib import Path
import pandas as pd
import pytest

from lab.universe import fetch_sp500, build_universe, load_universe


_SAMPLE_HTML = """
<html>
<body>
<table>
    <tr>
        <th>Symbol</th>
        <th>Security</th>
        <th>GICS Sector</th>
        <th>GICS Sub-Industry</th>
    </tr>
    <tr>
        <td>AAPL</td>
        <td>Apple Inc.</td>
        <td>Information Technology</td>
        <td>Technology Hardware, Storage & Peripherals</td>
    </tr>
    <tr>
        <td>BRK.B</td>
        <td>Berkshire Hathaway</td>
        <td>Financials</td>
        <td>Multi-Sector Holdings</td>
    </tr>
</table>
</body>
</html>
"""


def test_fetch_sp500_success():
    mock_resp = MagicMock()
    mock_resp.text = _SAMPLE_HTML
    mock_resp.status_code = 200

    with patch("requests.get", return_value=mock_resp):
        df = fetch_sp500()

    assert len(df) == 2
    assert list(df.columns) == ["ticker", "name", "sector", "industry"]
    # Check normalization: BRK.B -> BRK-B
    assert df.loc[df["ticker"] == "BRK-B", "sector"].iloc[0] == "Financials"
    assert df.loc[df["ticker"] == "AAPL", "name"].iloc[0] == "Apple Inc."


def test_build_universe_and_load(tmp_path):
    mock_resp = MagicMock()
    mock_resp.text = _SAMPLE_HTML
    mock_resp.status_code = 200

    with patch("requests.get", return_value=mock_resp):
        df = build_universe(data_dir=tmp_path, extra_tickers=["SPY"])

    assert len(df) == 3
    assert (tmp_path / "universe.csv").exists()

    loaded = load_universe(tmp_path)
    assert len(loaded) == 3
    assert "SPY" in loaded["ticker"].values
