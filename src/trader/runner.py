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

from trader import data, store
from trader.engine import BAR_COLUMNS, Fees, buy_and_hold, fees_for, simulate
from trader.profit import MIN_BARS, report

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
    if not hypothesis or not hypothesis.strip():
        raise RunError("hypothesis is required: state what this run is testing")
    if cash <= 0:
        raise RunError(f"cash must be positive, got {cash}")
    path = resolve_strategy(ws, strategy)
    symbol = symbol.strip().upper()
    fees = _fees(symbol, fee)
    try:
        bars = data.load_bars(symbol, start, end)
    except data.DataError as e:
        raise RunError(str(e)) from e
    if len(bars) < MIN_BARS:
        raise RunError(f"need at least {MIN_BARS} trading days, got {len(bars)}")

    source = path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        job = {
            "strategy_path": str(path),
            "params": params or {},
            "fees": asdict(fees),
            "cash": cash,
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

    payload = {
        "bars": {"date": result["ledger"]["dates"], **{c: bars[c].tolist() for c in BAR_COLUMNS}},
        "ledger": result["ledger"],
        "bh_equity": result["bh_equity"],
        "report": result["report"],
        "fees": asdict(fees),
        "cash": cash,
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
        source=source,
        source_sha=hashlib.sha256(source.encode()).hexdigest(),
        data_sha=data.fingerprint(bars),
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
        led = simulate(bars, lambda h, pos: mod.on_bar(h, pos, p), fees, job["cash"])
        bh = buy_and_hold(bars, fees, job["cash"])
        rep = report(led, bh)
    except Exception as e:
        return {"error": _strategy_error(e, path)}
    ledger = asdict(led)
    ledger["unrealized_pnl"] = led.unrealized_pnl
    return {"ledger": ledger, "bh_equity": bh.equity, "report": asdict(rep), "params": p}


if __name__ == "__main__":
    job = json.loads(sys.stdin.read())
    Path(job["result_path"]).write_text(json.dumps(_child(job)))
