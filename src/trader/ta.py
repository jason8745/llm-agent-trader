"""Technical indicators. Each takes pandas Series and returns Series aligned to the input.

Conventions follow TA-Lib: values are NaN until the lookback is filled, EMA is seeded
with the SMA of its first n values, and RSI and ATR use Wilder smoothing.
Indicators compose: pass one indicator's output as another's input.
"""

import numpy as np
import pandas as pd


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def _seeded_smooth(x: pd.Series, n: int, alpha: float) -> pd.Series:
    vals = x.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    valid = np.flatnonzero(~np.isnan(vals))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    start = valid[0]
    seed_end = start + n - 1
    out[seed_end] = vals[start : seed_end + 1].mean()
    for i in range(seed_end + 1, len(vals)):
        out[i] = out[i - 1] + alpha * (vals[i] - out[i - 1])
    return pd.Series(out, index=x.index)


def ema(x: pd.Series, n: int) -> pd.Series:
    return _seeded_smooth(x, n, 2 / (n + 1))


def wilder(x: pd.Series, n: int) -> pd.Series:
    return _seeded_smooth(x, n, 1 / n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), n)
    loss = wilder(-delta.clip(upper=0), n)
    out = 100 - 100 / (1 + gain / loss)
    out[(loss == 0) & (gain > 0)] = 100.0
    out[(loss == 0) & (gain == 0)] = 50.0
    return out


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    # TA-Lib seeds the fast EMA so that both seeds end on the same bar.
    valid = np.flatnonzero(~np.isnan(close.to_numpy(dtype=float)))
    aligned = close.copy()
    if len(valid):
        aligned.iloc[: valid[0] + max(slow - fast, 0)] = np.nan
    line = ema(aligned, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bbands(close: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return wilder(true_range(high, low, close), n)
