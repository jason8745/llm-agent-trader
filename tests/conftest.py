import datetime as dt
import textwrap
from pathlib import Path

import pandas as pd
import pytest
from bars import random_bars

SYMBOL = "TEST.TW"
START, END = "2024-06-03", "2024-12-31"
PERIODS = (START, END)
# Keyword arguments for the run_backtest tool and runner.
BT = dict(start=START, end=END)
# The runner loads WARMUP_CALENDAR_DAYS before START so the strategy has indicator history.
LOAD_START = (dt.date.fromisoformat(START) - dt.timedelta(days=130)).isoformat()

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
    random_bars(n=len(pd.bdate_range(LOAD_START, END)), start=LOAD_START).to_csv(
        cache / "ohlcv" / f"{SYMBOL}_{LOAD_START}_{END}.csv", index_label="date"
    )
    work = tmp_path / "work"
    (work / "strategies").mkdir(parents=True)
    (work / "strategies" / "ma_cross.py").write_text(MA_CROSS, encoding="utf-8")
    monkeypatch.setenv("TRADER_CACHE", str(cache))
    monkeypatch.setenv("TRADER_WORKSPACE", str(work))
    return work
