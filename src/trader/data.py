"""Market data: daily bars from yfinance with a local cache, and the Taiwan stock list."""

import datetime as dt
import hashlib
import json
import os
from functools import cache
from pathlib import Path

import pandas as pd

from trader.engine import BAR_COLUMNS

TAIPEI = dt.timezone(dt.timedelta(hours=8))
STOCKS_JSON = Path(__file__).with_name("taiwan_stocks.json")


class DataError(Exception):
    pass


def cache_dir() -> Path:
    return Path(os.environ.get("TRADER_CACHE", Path.home() / ".cache" / "llm-agent-trader"))


def _parse_date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError as e:
        raise DataError(f"dates must be YYYY-MM-DD, got {s!r}") from e


def _download(symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.Ticker(symbol).history(
        start=start.isoformat(),
        end=(end + dt.timedelta(days=1)).isoformat(),
        auto_adjust=False,
        actions=True,
    )
    if raw.empty:
        raise DataError(f"no data for {symbol} between {start} and {end}")
    bars = pd.DataFrame(
        {
            "open": raw["Open"],
            "high": raw["High"],
            "low": raw["Low"],
            "close": raw["Close"],
            "volume": raw["Volume"],
            "dividend": raw.get("Dividends", 0.0),
        }
    )
    bars.index = pd.DatetimeIndex(raw.index.tz_localize(None).normalize(), name="date")
    return bars.astype(float)


def load_bars(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Daily bars, split-adjusted but not dividend-adjusted, with cash dividends on ex-dates.

    Ranges that end before today (Taipei) are cached; a range touching today may still change.
    """
    s, e = _parse_date(start), _parse_date(end)
    if s > e:
        raise DataError(f"start {start} is after end {end}")
    path = cache_dir() / "ohlcv" / f"{symbol.upper()}_{s}_{e}.csv"
    if path.exists():
        return pd.read_csv(path, index_col="date", parse_dates=["date"])[list(BAR_COLUMNS)]
    bars = _download(symbol, s, e).rename_axis("date")
    if e < dt.datetime.now(TAIPEI).date():
        path.parent.mkdir(parents=True, exist_ok=True)
        bars.to_csv(path)
    return bars


def fingerprint(bars: pd.DataFrame) -> str:
    return hashlib.sha256(bars[list(BAR_COLUMNS)].to_csv().encode()).hexdigest()


@cache
def stock_list() -> list[dict]:
    return json.loads(STOCKS_JSON.read_text(encoding="utf-8"))


@cache
def _names() -> dict[str, str]:
    return {s["symbol"]: s["name"] for s in stock_list()}


def stock_name(symbol: str) -> str | None:
    """Chinese name of a listed Taiwan stock or ETF, or None for symbols outside the list."""
    return _names().get(symbol.strip().upper())


def search_stock(query: str, limit: int = 10) -> list[dict]:
    q = query.strip().upper().removesuffix(".TWO").removesuffix(".TW")
    if not q:
        return []
    stocks = stock_list()
    ranked = (
        [s for s in stocks if s["code"] == q]
        + [s for s in stocks if s["code"].startswith(q) and s["code"] != q]
        + [s for s in stocks if q in s["name"].upper() and not s["code"].startswith(q)]
    )
    return ranked[:limit]
