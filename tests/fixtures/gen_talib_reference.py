"""Regenerate talib_reference.json. Needs TA-Lib, which is not a project dependency:

uv run --with ta-lib --with numpy python tests/fixtures/gen_talib_reference.py
"""

import json
from pathlib import Path

import numpy as np
import talib

rng = np.random.default_rng(20261121)
n = 120
close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
high = close * (1 + rng.uniform(0, 0.02, n))
low = close * (1 - rng.uniform(0, 0.02, n))


def clean(a):
    return [None if np.isnan(v) else float(v) for v in a]


line, sig, hist = talib.MACD(close, 12, 26, 9)
up, mid, lo = talib.BBANDS(close, 20, 2.0, 2.0, 0)
out = {
    "talib_version": talib.__version__,
    "high": high.tolist(),
    "low": low.tolist(),
    "close": close.tolist(),
    "sma_10": clean(talib.SMA(close, 10)),
    "ema_10": clean(talib.EMA(close, 10)),
    "rsi_14": clean(talib.RSI(close, 14)),
    "macd_line": clean(line),
    "macd_signal": clean(sig),
    "macd_hist": clean(hist),
    "bb_upper": clean(up),
    "bb_mid": clean(mid),
    "bb_lower": clean(lo),
    "atr_14": clean(talib.ATR(high, low, close, 14)),
}
Path(__file__).with_name("talib_reference.json").write_text(json.dumps(out))
