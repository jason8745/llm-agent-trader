import numpy as np
import pandas as pd


def make_bars(opens, closes, dividends=None, start="2025-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(opens))
    o, c = np.asarray(opens, float), np.asarray(closes, float)
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c),
            "low": np.minimum(o, c),
            "close": c,
            "volume": 1000.0,
            "dividend": np.asarray(dividends if dividends is not None else [0.0] * len(o), float),
        },
        index=idx,
    )


def random_bars(n=300, seed=7, dividend_every=60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    opens = closes * (1 + rng.normal(0, 0.005, n))
    divs = np.zeros(n)
    divs[dividend_every::dividend_every] = 2.5
    return make_bars(opens.round(2), closes.round(2), divs)
