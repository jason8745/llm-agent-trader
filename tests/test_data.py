import datetime as dt
import os

import pandas as pd
import pytest
from bars import random_bars

from trader import data
from trader.engine import TW_ETF_FEES, TW_STOCK_FEES, fees_for


def test_search_by_name_and_code():
    assert data.search_stock("台積電")[0]["symbol"] == "2330.TW"
    assert data.search_stock("2330")[0]["name"] == "台積電"
    assert data.search_stock("2330.TW")[0]["code"] == "2330"
    assert data.search_stock("6488")[0]["symbol"] == "6488.TWO"
    assert data.search_stock("  ") == []


def test_exact_code_ranks_before_prefix_and_name_matches():
    codes = [s["code"] for s in data.search_stock("0050")]
    assert codes[0] == "0050"
    assert all(c.startswith("0050") for c in codes)


def test_stock_list_agrees_with_fee_schedule():
    stocks = data.stock_list()
    assert len(stocks) > 2000
    for s in stocks:
        assert s["symbol"].endswith(".TW" if s["market"] == "TWSE" else ".TWO")
        expected = TW_ETF_FEES if s["kind"] == "etf" else TW_STOCK_FEES
        assert fees_for(s["symbol"]) is expected, s


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_CACHE", str(tmp_path))
    calls = []

    def fake_download(symbol, start, end):
        calls.append((symbol, start, end))
        return random_bars(n=20)

    monkeypatch.setattr(data, "_download", fake_download)
    return calls


def test_past_ranges_are_cached_exactly(offline, tmp_path):
    first = data.load_bars("2330.TW", "2025-01-01", "2025-02-01")
    second = data.load_bars("2330.TW", "2025-01-01", "2025-02-01")
    assert len(offline) == 1
    pd.testing.assert_frame_equal(first, second, check_freq=False, check_exact=True)
    assert data.fingerprint(first) == data.fingerprint(second)


def test_ranges_touching_today_are_not_cached(offline):
    today = dt.datetime.now(data.TAIPEI).date().isoformat()
    data.load_bars("2330.TW", "2025-01-01", today)
    data.load_bars("2330.TW", "2025-01-01", today)
    assert len(offline) == 2


@pytest.mark.parametrize("start,end", [("2025-13-01", "2025-12-31"), ("2025-03-01", "2025-02-01")])
def test_bad_ranges_raise(offline, start, end):
    with pytest.raises(data.DataError):
        data.load_bars("2330.TW", start, end)


def test_fingerprint_changes_with_data():
    bars = random_bars(n=20)
    changed = bars.copy()
    changed.iloc[5, changed.columns.get_loc("close")] += 0.01
    assert data.fingerprint(bars) != data.fingerprint(changed)


@pytest.mark.skipif(not os.environ.get("TRADER_LIVE"), reason="set TRADER_LIVE=1 to hit yfinance")
def test_live_2330_dividend(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_CACHE", str(tmp_path))
    bars = data.load_bars("2330.TW", "2025-06-01", "2025-06-30")
    assert list(bars.columns) == ["open", "high", "low", "close", "volume", "dividend"]
    ex = bars.loc["2025-06-12"]
    assert ex["dividend"] == pytest.approx(4.5, abs=1e-3)
    assert (ex["open"], ex["close"]) == (1055.0, 1045.0)
    assert (bars["dividend"] > 0).sum() == 1
