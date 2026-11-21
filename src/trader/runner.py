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
from trader.profit import daily_returns, regime_table, study_report

DEFAULT_CASH = 1_000_000
TIMEOUT_SECONDS = 60


class RunError(Exception):
    pass


def workspace() -> Path:
    return Path(os.environ.get("TRADER_WORKSPACE") or os.getcwd()).resolve()


def resolve_strategy(ws: Path, strategy: str) -> Path:
    p = Path(strategy)
    candidates = [p] if p.is_absolute() else [ws / p, ws / "strategies" / p]
    for c in candidates:
        for path in (c, c.with_suffix(".py")):
            if path.is_file() and path.suffix == ".py":
                return path.resolve()
    raise RunError(f"strategy file not found: {strategy} (looked in {ws} and {ws / 'strategies'})")


def _fees(symbol: str, override: dict | None) -> Fees:
    base = fees_for(symbol)
    if not override:
        return base
    known = {f.name for f in fields(Fees)}
    unknown = set(override) - known
    if unknown:
        raise RunError(f"unknown fee fields {sorted(unknown)}; allowed: {sorted(known)}")
    return replace(base, **override)


def _date(value: str, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise RunError(f"{name}須為 YYYY-MM-DD 格式的日期，收到 {value!r}。") from e


def _periods(dev_start: str, dev_end: str, exec_start: str, exec_end: str) -> None:
    ds, de = _date(dev_start, "策略開發期間起日"), _date(dev_end, "策略開發期間迄日")
    es, ee = _date(exec_start, "策略執行期間起日"), _date(exec_end, "策略執行期間迄日")
    if ds > de:
        raise RunError(f"策略開發期間起日 {dev_start} 晚於迄日 {dev_end}。")
    if es > ee:
        raise RunError(f"策略執行期間起日 {exec_start} 晚於迄日 {exec_end}。")
    if de >= es:
        raise RunError(f"策略執行期間起日 {exec_start} 須晚於策略開發期間迄日 {dev_end}。")


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
    dev_start: str,
    dev_end: str,
    exec_start: str,
    exec_end: str,
    hypothesis: str,
    params: dict | None = None,
    cash: float = DEFAULT_CASH,
    fee: dict | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> store.Run:
    """Development: the strategy on the development bars only. Execution: the strategy on all
    loaded bars from exec_start on, starting flat with the initial cash; earlier bars (the
    development period and any gap before exec_start) are indicator history only."""
    if not hypothesis or not hypothesis.strip():
        raise RunError("hypothesis is required: state what this run is testing")
    if cash <= 0:
        raise RunError(f"cash must be positive, got {cash}")
    _periods(dev_start, dev_end, exec_start, exec_end)
    path = resolve_strategy(ws, strategy)
    symbol = symbol.strip().upper()
    fees = _fees(symbol, fee)
    try:
        bars = data.load_bars(symbol, dev_start, exec_end)
    except data.DataError as e:
        raise RunError(str(e)) from e
    dates = [d.strftime("%Y-%m-%d") for d in bars.index]
    dev_n = sum(dev_start <= d <= dev_end for d in dates)
    k = next((i for i, d in enumerate(dates) if d >= exec_start), len(dates))
    for name, n in (("策略開發期間", dev_n), ("策略執行期間", len(dates) - k)):
        if n < 2:
            raise RunError(f"{name}僅有 {n} 個交易日，至少需要 2 個交易日。")

    source = path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        job = {
            "strategy_path": str(path),
            "params": params or {},
            "fees": asdict(fees),
            "cash": cash,
            "dev_bars": dev_n,
            "exec_start": k,
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
            )
        except subprocess.TimeoutExpired as e:
            raise RunError(f"strategy did not finish within {timeout:g} seconds") from e
        result_file = Path(job["result_path"])
        if not result_file.exists():
            raise RunError(
                f"strategy process exited with code {proc.returncode}: {proc.stderr[-2000:]}"
            )
        result = json.loads(result_file.read_text())
    if "error" in result:
        raise RunError(result["error"])
    data_sha = data.fingerprint(bars)
    if result["data_sha"] != data_sha:
        raise RunError("the strategy process read different bars than were fetched")

    dev, exe = _ledger(result["dev"]), _ledger(result["exec"])
    bh_dev = buy_and_hold(bars.iloc[:dev_n], fees, cash)
    bh_exec = buy_and_hold(bars, fees, cash, start=k)
    gap = k - dev_n  # bars after dev_end and before exec_start: history for execution only
    close = bars["close"].tolist()
    regimes = regime_table(
        dates,
        close,
        regime.segment(close),
        daily_returns(dev) + [0.0] * gap + daily_returns(exe),
        [s > 0 for s in dev.shares] + [False] * gap + [s > 0 for s in exe.shares],
    )
    payload = {
        "bars": {"date": dates, **{c: bars[c].tolist() for c in BAR_COLUMNS}},
        "dev": result["dev"],
        "exec": result["exec"],
        "bh_dev": bh_dev.equity,
        "bh_exec": bh_exec.equity,
        "report": asdict(study_report(dev, bh_dev, exe, bh_exec)),
        "regimes": [asdict(r) for r in regimes],
    }
    return store.insert(
        ws,
        created_at=dt.datetime.now(data.TAIPEI).strftime("%Y-%m-%d %H:%M"),
        strategy=path.stem,
        symbol=symbol,
        dev_start=dev_start,
        dev_end=dev_end,
        exec_start=exec_start,
        exec_end=exec_end,
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
            return {"error": f"unknown params {sorted(unknown)}; PARAMS defines {sorted(base)}"}
        p = {**base, **job["params"]}
        bars = pd.read_csv(job["bars_csv"], index_col="date", parse_dates=["date"])
        fees = Fees(**job["fees"])
        decide = lambda h, pos: mod.on_bar(h, pos, p)  # noqa: E731
        dev = simulate(bars.iloc[: job["dev_bars"]], decide, fees, job["cash"])
        exe = simulate(bars, decide, fees, job["cash"], start=job["exec_start"])
    except Exception as e:
        return {"error": _strategy_error(e, path)}
    return {
        "dev": asdict(dev),
        "exec": asdict(exe),
        "params": p,
        "data_sha": data.fingerprint(bars),
    }


if __name__ == "__main__":
    job = json.loads(sys.stdin.read())
    Path(job["result_path"]).write_text(json.dumps(_child(job)))
