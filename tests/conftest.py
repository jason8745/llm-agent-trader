import textwrap
from pathlib import Path

import pytest
from bars import random_bars

SYMBOL, START, END = "TEST.TW", "2024-01-01", "2024-12-31"

MA_CROSS = textwrap.dedent(
    '''
    """ma_cross：均線黃金交叉，僅做多。"""
    from trader import ta

    PARAMS = {"fast": 5, "slow": 20}


    def on_bar(hist, pos, p):
        fast = ta.sma(hist.close, p["fast"]).iloc[-1]
        slow = ta.sma(hist.close, p["slow"]).iloc[-1]
        return 1.0 if fast > slow else 0.0
    '''
)


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    """A workspace with one strategy and cached bars for TEST.TW, so nothing hits the network."""
    cache = tmp_path / "cache"
    (cache / "ohlcv").mkdir(parents=True)
    random_bars(n=120).to_csv(cache / "ohlcv" / f"{SYMBOL}_{START}_{END}.csv", index_label="date")
    work = tmp_path / "work"
    (work / "strategies").mkdir(parents=True)
    (work / "strategies" / "ma_cross.py").write_text(MA_CROSS, encoding="utf-8")
    monkeypatch.setenv("TRADER_CACHE", str(cache))
    monkeypatch.setenv("TRADER_WORKSPACE", str(work))
    return work
