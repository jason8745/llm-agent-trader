"""Runs one backtest. Data is fetched here; the strategy runs in a child process with a timeout,
so an infinite loop or a crash in agent-written code never takes the MCP server down."""

import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import traceback
from dataclasses import asdict, fields, replace
from pathlib import Path

import pandas as pd

from trader import data, regime, store
from trader.engine import (
    BAR_COLUMNS,
    Fees,
    Fill,
    Ledger,
    RoundTrip,
    buy_and_hold,
    fees_for,
    simulate,
)
from trader.profit import daily_returns, period, regime_table

DEFAULT_CASH = 1_000_000
TIMEOUT_SECONDS = 60
WARMUP_BARS = 60  # history before the start date, for indicators; not part of the results
WARMUP_CALENDAR_DAYS = 130  # enough calendar days to cover WARMUP_BARS across holidays


class RunError(Exception):
    pass


def resolve_strategy(ws: Path, strategy: str) -> Path:
    p = Path(strategy)
    candidates = [p] if p.is_absolute() else [ws / p, ws / "strategies" / p]
    for c in candidates:
        for path in (c, c.with_suffix(".py")):
            if path.is_file() and path.suffix == ".py":
                return path.resolve()
    raise RunError(f"找不到策略檔 {strategy}（已搜尋 {ws} 與 {ws / 'strategies'}）。")


def _fees(symbol: str, override: dict | None) -> Fees:
    base = fees_for(symbol)
    if not override:
        return base
    known = {f.name for f in fields(Fees)}
    unknown = set(override) - known
    if unknown:
        raise RunError(f"不支援的費用欄位 {sorted(unknown)}；可用欄位為 {sorted(known)}。")
    return replace(base, **override)


def _date(value: str, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise RunError(f"{name}須為 YYYY-MM-DD 格式的日期，收到 {value!r}。") from e


def _period(start: str, end: str) -> dt.date:
    s, e = _date(start, "回測期間起日"), _date(end, "回測期間迄日")
    if s > e:
        raise RunError(f"回測期間起日 {start} 晚於迄日 {end}。")
    return s


def _ledger(d: dict) -> Ledger:
    return Ledger(
        **{
            **d,
            "fills": [Fill(**f) for f in d["fills"]],
            "round_trips": [RoundTrip(**t) for t in d["round_trips"]],
        }
    )


def run_backtest(
    ws: Path,
    strategy: str,
    symbol: str,
    start: str,
    end: str,
    hypothesis: str,
    params: dict | None = None,
    cash: float = DEFAULT_CASH,
    fee: dict | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> store.Run:
    """The strategy from the first bar on or after start, flat with the initial cash. Up to
    WARMUP_BARS earlier bars are loaded as indicator history; they are charted but not traded
    or measured."""
    if not hypothesis or not hypothesis.strip():
        raise RunError("必須填寫 hypothesis，說明本次回測驗證的假設。")
    if cash <= 0:
        raise RunError(f"初始資金須為正數，收到 {cash}。")
    first = _period(start, end)
    path = resolve_strategy(ws, strategy)
    symbol = symbol.strip().upper()
    fees = _fees(symbol, fee)
    try:
        loaded = (first - dt.timedelta(days=WARMUP_CALENDAR_DAYS)).isoformat()
        bars = data.load_bars(symbol, loaded, end)
    except data.DataError as e:
        raise RunError(str(e)) from e
    k = next((i for i, d in enumerate(bars.index) if d.strftime("%Y-%m-%d") >= start), len(bars))
    bars = bars.iloc[max(0, k - WARMUP_BARS) :]
    k = min(k, WARMUP_BARS)
    dates = [d.strftime("%Y-%m-%d") for d in bars.index]
    if len(dates) - k < 2:
        raise RunError(f"回測期間僅有 {len(dates) - k} 個交易日，至少需要 2 個交易日。")

    source = path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        job = {
            "strategy_path": str(path),
            "params": params or {},
            "fees": asdict(fees),
            "cash": cash,
            "start": k,
            "bars_csv": str(Path(tmp) / "bars.csv"),
            "result_path": str(Path(tmp) / "result.json"),
        }
        bars.to_csv(job["bars_csv"])
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "trader.runner"],
                input=json.dumps(job),
                capture_output=True,
                text=True,
                timeout=timeout,
                # keep the user's strategies folder free of __pycache__
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            )
        except subprocess.TimeoutExpired as e:
            raise RunError(f"策略未在 {timeout:g} 秒內完成。") from e
        result_file = Path(job["result_path"])
        if not result_file.exists():
            raise RunError(f"策略程序異常結束（代碼 {proc.returncode}）：{proc.stderr[-2000:]}")
        result = json.loads(result_file.read_text())
    if "error" in result:
        raise RunError(result["error"])
    data_sha = data.fingerprint(bars)
    if result["data_sha"] != data_sha:
        raise RunError("策略程序讀取的價格資料與擷取的資料不一致。")

    led = _ledger(result["ledger"])
    bh = buy_and_hold(bars, fees, cash, start=k)
    close = bars["close"].tolist()[k:]
    regimes = regime_table(
        dates[k:],
        close,
        regime.segment(close),
        daily_returns(led),
        [s > 0 for s in led.shares],
    )
    payload = {
        "bars": {"date": dates, **{c: bars[c].tolist() for c in BAR_COLUMNS}},
        "ledger": result["ledger"],
        "bh": bh.equity,
        "report": asdict(period(led, bh)),
        "regimes": [asdict(r) for r in regimes],
    }
    return store.insert(
        ws,
        created_at=dt.datetime.now(data.TAIPEI).strftime("%Y-%m-%d %H:%M"),
        strategy=path.stem,
        symbol=symbol,
        start=start,
        end=end,
        hypothesis=hypothesis.strip(),
        params=result["params"],
        cash=cash,
        fee=asdict(fees),
        source=source,
        source_sha=hashlib.sha256(source.encode()).hexdigest(),
        data_sha=data_sha,
        payload=payload,
    )


def _strategy_error(e: BaseException, path: str) -> str:
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == path]
    where = "".join(traceback.format_list(frames))
    return f"{where}{type(e).__name__}: {e}".strip()


def _child(job: dict) -> dict:
    path = job["strategy_path"]
    try:
        spec = importlib.util.spec_from_file_location("strategy", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "on_bar", None)):
            return {"error": f"{path} must define on_bar(hist, pos, p)"}
        base = dict(getattr(mod, "PARAMS", {}))
        unknown = set(job["params"]) - set(base)
        if unknown:
            return {"error": f"未知的參數 {sorted(unknown)}；PARAMS 定義的參數為 {sorted(base)}。"}
        p = {**base, **job["params"]}
        bars = pd.read_csv(job["bars_csv"], index_col="date", parse_dates=["date"])
        fees = Fees(**job["fees"])
        decide = lambda h, pos: mod.on_bar(h, pos, p)  # noqa: E731
        led = simulate(bars, decide, fees, job["cash"], start=job["start"])
    except Exception as e:
        return {"error": _strategy_error(e, path)}
    return {
        "ledger": asdict(led),
        "params": p,
        "data_sha": data.fingerprint(bars),
    }


if __name__ == "__main__":
    job = json.loads(sys.stdin.read())
    Path(job["result_path"]).write_text(json.dumps(_child(job)))
