"""runs.db: one row per backtest, self-contained enough to re-render without refetching."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from trader.profit import Report, Segment

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    params TEXT NOT NULL,
    source TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    data_sha TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class Run:
    id: int
    created_at: str
    strategy: str
    symbol: str
    start: str
    end: str
    hypothesis: str
    params: dict
    source: str
    source_sha: str
    data_sha: str
    payload: dict

    @property
    def report(self) -> Report:
        r = dict(self.payload["report"])
        for k, v in r.items():
            if isinstance(v, dict):
                r[k] = Segment(**v)
        return Report(**r)

    @property
    def dates(self) -> list[str]:
        return self.payload["bars"]["date"]


def db_path(workspace: Path) -> Path:
    return workspace / ".trader" / "runs.db"


def connect(workspace: Path) -> sqlite3.Connection:
    path = db_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def _run(row: sqlite3.Row) -> Run:
    d = dict(row)
    d["params"] = json.loads(d["params"])
    d["payload"] = json.loads(d["payload"])
    return Run(**d)


def insert(workspace: Path, **fields) -> Run:
    fields = {
        **fields,
        "params": json.dumps(fields["params"]),
        "payload": json.dumps(fields["payload"]),
    }
    cols = ", ".join(fields)
    with connect(workspace) as con:
        cur = con.execute(
            f"INSERT INTO runs ({cols}) VALUES ({', '.join('?' for _ in fields)})",
            list(fields.values()),
        )
    return get(workspace, cur.lastrowid)


def get(workspace: Path, run_id: int) -> Run | None:
    with connect(workspace) as con:
        row = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _run(row) if row else None


def list_runs(workspace: Path, strategy: str | None = None, symbol: str | None = None) -> list[Run]:
    q, args = "SELECT * FROM runs WHERE 1=1", []
    if strategy:
        q, args = q + " AND strategy = ?", [*args, strategy]
    if symbol:
        q, args = q + " AND symbol = ?", [*args, symbol.upper()]
    with connect(workspace) as con:
        return [_run(r) for r in con.execute(q + " ORDER BY id", args)]
