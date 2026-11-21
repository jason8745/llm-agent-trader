import json
import math
from pathlib import Path

import pandas as pd
import pytest

from trader import ta

REF = json.loads((Path(__file__).parent / "fixtures" / "talib_reference.json").read_text())
H, L, C = (pd.Series(REF[k]) for k in ("high", "low", "close"))
MACD = ta.macd(C, 12, 26, 9)
BB = ta.bbands(C, 20, 2.0)

CASES = {
    "sma_10": ta.sma(C, 10),
    "ema_10": ta.ema(C, 10),
    "rsi_14": ta.rsi(C, 14),
    "macd_line": MACD[0],
    "macd_signal": MACD[1],
    "macd_hist": MACD[2],
    "bb_upper": BB[0],
    "bb_mid": BB[1],
    "bb_lower": BB[2],
    "atr_14": ta.atr(H, L, C, 14),
}
# TA-Lib withholds the MACD line until the signal line starts; ours starts at bar slow-1.
EARLY_OK = {"macd_line"}


@pytest.mark.parametrize("name", CASES)
def test_matches_talib(name):
    ours, ref = CASES[name], REF[name]
    for i, expected in enumerate(ref):
        got = ours.iloc[i]
        if expected is None:
            if name not in EARLY_OK:
                assert math.isnan(got), f"{name}[{i}] should be NaN, got {got}"
            continue
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-9), f"{name}[{i}]"


def test_every_public_indicator_has_a_reference_case():
    public = {n for n in dir(ta) if not n.startswith("_") and callable(getattr(ta, n))}
    public -= {"np", "pd", "wilder", "true_range"}
    covered = {name.split("_")[0].replace("bb", "bbands") for name in CASES}
    assert public <= covered, f"indicators without a TA-Lib reference case: {public - covered}"


def test_hand_computed_values():
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert ta.sma(x, 2).tolist()[1:] == [1.5, 2.5, 3.5, 4.5]
    # seed = mean(1,2,3) = 2; alpha = 0.5: 2 + 0.5*(4-2) = 3; 3 + 0.5*(5-3) = 4
    assert ta.ema(x, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert ta.rsi(x, 3).iloc[-1] == 100.0
    assert ta.rsi(pd.Series([5.0] * 6), 3).iloc[-1] == 50.0


def test_indicators_compose():
    smoothed = ta.ema(ta.rsi(C, 14), 5)
    assert smoothed.first_valid_index() == 14 + 5 - 1
    assert smoothed.dropna().between(0, 100).all()
