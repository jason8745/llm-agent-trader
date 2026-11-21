"""runs.db: one row per backtest, self-contained enough to re-render without refetching,
and one row per study (symbol, strategy and the two periods).

The `runs` table of earlier versions (one 70/30 split per run) is left untouched and only
counted."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from trader.profit import Drawdown, Metrics, Period, RegimeRow, StudyReport, Trades

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    study_key TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    dev_start TEXT NOT NULL,
    dev_end TEXT NOT NULL,
    exec_start TEXT NOT NULL,
    exec_end TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    params TEXT NOT NULL,
    cash REAL NOT NULL,
    fee TEXT NOT NULL,
    source TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    data_sha TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studies (
    key TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    dev_start TEXT NOT NULL,
    dev_end TEXT NOT NULL,
    exec_start TEXT NOT NULL,
    exec_end TEXT NOT NULL,
    final_run_id INTEGER,
    conclusion TEXT,
    finalized_at TEXT
);
"""
STUDY_FIELDS = ("symbol", "strategy", "dev_start", "dev_end", "exec_start", "exec_end")


def study_key(symbol, strategy, dev_start, dev_end, exec_start, exec_end) -> str:
    raw = "|".join([symbol, strategy, dev_start, dev_end, exec_start, exec_end])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _period(d: dict) -> Period:
    return Period(
        strategy=Metrics(**d["strategy"]),
        trades=Trades(**d["trades"]),
        bh=Metrics(**d["bh"]),
        drawdowns=[Drawdown(**x) for x in d["drawdowns"]],
    )


@dataclass(frozen=True)
class Run:
    id: int
    created_at: str
    study_key: str
    strategy: str
    symbol: str
    dev_start: str
    dev_end: str
    exec_start: str
    exec_end: str
    hypothesis: str
    params: dict
    cash: float
    fee: dict
    source: str
    source_sha: str
    data_sha: str
    payload: dict
    n: int  # 1-based iteration number within its study

    @property
    def report(self) -> StudyReport:
        r = self.payload["report"]
        return StudyReport(dev=_period(r["dev"]), exec=_period(r["exec"]))

    @property
    def regimes(self) -> list[RegimeRow]:
        return [RegimeRow(**x) for x in self.payload["regimes"]]

    @property
    def label(self) -> str:
        from trader.fmt import symbol_label

        return symbol_label(self.symbol)


@dataclass(frozen=True)
class Study:
    key: str
    symbol: str
    strategy: str
    dev_start: str
    dev_end: str
    exec_start: str
    exec_end: str
    final_run_id: int | None
    conclusion: str | None
    finalized_at: str | None


def db_path(workspace: Path) -> Path:
    return workspace / ".trader" / "runs.db"


def connect(workspace: Path) -> sqlite3.Connection:
    path = db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


SELECT = """SELECT b.*, (SELECT COUNT(*) FROM backtests p
    WHERE p.study_key = b.study_key AND p.id <= b.id) AS n FROM backtests b"""


def _run(row: sqlite3.Row) -> Run:
    d = dict(row)
    for k in ("params", "fee", "payload"):
        d[k] = json.loads(d[k])
    return Run(**d)


def insert(workspace: Path, **fields) -> Run:
    key = study_key(*(fields[k] for k in STUDY_FIELDS))
    row = {
        **fields,
        "study_key": key,
        "params": json.dumps(fields["params"]),
        "fee": json.dumps(fields["fee"]),
        "payload": json.dumps(fields["payload"]),
    }
    with connect(workspace) as con:
        con.execute(
            f"INSERT OR IGNORE INTO studies (key, {', '.join(STUDY_FIELDS)}) VALUES (?{', ?' * 6})",
            [key, *(fields[k] for k in STUDY_FIELDS)],
        )
        cur = con.execute(
            f"INSERT INTO backtests ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            list(row.values()),
        )
    return get(workspace, cur.lastrowid)


def get(workspace: Path, run_id: int) -> Run | None:
    with connect(workspace) as con:
        row = con.execute(SELECT + " WHERE b.id = ?", (run_id,)).fetchone()
    return _run(row) if row else None


def list_runs(
    workspace: Path,
    strategy: str | None = None,
    symbol: str | None = None,
    study: str | None = None,
) -> list[Run]:
    q, args = SELECT + " WHERE 1=1", []
    for col, val in (
        ("strategy", strategy),
        ("symbol", symbol and symbol.upper()),
        ("study_key", study),
    ):
        if val:
            q, args = q + f" AND b.{col} = ?", [*args, val]
    with connect(workspace) as con:
        return [_run(r) for r in con.execute(q + " ORDER BY b.id", args)]


def get_study(workspace: Path, key: str) -> Study | None:
    with connect(workspace) as con:
        row = con.execute("SELECT * FROM studies WHERE key = ?", (key,)).fetchone()
    return Study(**dict(row)) if row else None


def list_studies(workspace: Path) -> dict[str, Study]:
    with connect(workspace) as con:
        return {r["key"]: Study(**dict(r)) for r in con.execute("SELECT * FROM studies")}


def finalize(workspace: Path, key: str, run_id: int, conclusion: str, at: str) -> None:
    """Marks run_id as the study's final backtest; finalizing again overwrites."""
    with connect(workspace) as con:
        con.execute(
            "UPDATE studies SET final_run_id = ?, conclusion = ?, finalized_at = ? WHERE key = ?",
            (run_id, conclusion, at, key),
        )


def legacy_count(workspace: Path) -> int:
    """Backtests stored by earlier versions in the old `runs` table; not shown anywhere."""
    with connect(workspace) as con:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone():
            return 0
        return con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
