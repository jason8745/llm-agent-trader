"""Read-only run viewer: a stdlib HTTP server, a static page, and JSON whose display strings
all come from trader.fmt."""

import json
import re
import threading
import urllib.request
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from trader import fmt, store

STATIC = Path(__file__).parent
FILES = {
    "app.js": "text/javascript",
    "app.css": "text/css",
    "lightweight-charts.js": "text/javascript",
}
PORT_RANGE = 10


def _diff(run: store.Run, prev: store.Run | None) -> str:
    if prev is None:
        return "首次回測"
    changes = [
        f"{k} {prev.params.get(k, fmt.DASH)}→{v}"
        for k, v in run.params.items()
        if prev.params.get(k) != v
    ]
    if run.source_sha != prev.source_sha:
        changes.append("原始碼變更")
    return "、".join(changes) or "參數與原始碼皆未變更"


def _previous(runs: list[store.Run], run: store.Run) -> store.Run | None:
    same = [
        r for r in runs if r.strategy == run.strategy and r.symbol == run.symbol and r.id < run.id
    ]
    return same[-1] if same else None


def runs_payload(workspace: Path) -> list[dict]:
    runs = store.list_runs(workspace)
    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "strategy": r.strategy,
            "symbol": r.symbol,
            "hypothesis": r.hypothesis,
            "s": fmt.summary(r.report, r.dates),
        }
        for r in runs
    ]


def run_payload(workspace: Path, run_id: int) -> dict | None:
    runs = store.list_runs(workspace)
    run = next((r for r in runs if r.id == run_id), None)
    if run is None:
        return None
    led, bars = run.payload["ledger"], run.payload["bars"]
    side = {"BUY": "買進", "SELL": "賣出"}
    return {
        "id": run.id,
        "title": fmt.run_title(run),
        "created_at": run.created_at,
        "strategy": run.strategy,
        "symbol": run.symbol,
        "hypothesis": run.hypothesis,
        "params": ", ".join(f"{k}={v}" for k, v in run.params.items()) or fmt.DASH,
        "diff": _diff(run, _previous(runs, run)),
        "s": fmt.summary(run.report, run.dates),
        "overfit_note": fmt.OVERFIT_NOTE if run.report.overfit else "",
        "split": run.report.split,
        "bars": bars,
        "equity": led["equity"],
        "bh_equity": run.payload["bh_equity"],
        "markers": [{"date": f["date"], "side": f["side"]} for f in led["fills"]],
        "fills": [
            {
                "date": f["date"],
                "side": side[f["side"]],
                "buy": f["side"] == "BUY",
                "oos": f["bar"] >= run.report.split,
                "price": fmt.price(f["price"]),
                "shares": fmt.shares(f["shares"]),
                "gross": fmt.money(f["gross"]),
                "fees": fmt.money(f["commission"] + f["tax"]),
            }
            for f in led["fills"]
        ],
        "trips": [
            {
                "entry": t["entry_date"],
                "exit": t["exit_date"],
                "held": t["exit_bar"] - t["entry_bar"],
                "pnl": fmt.money(t["pnl"]),
                "win": t["pnl"] > 0,
            }
            for t in led["round_trips"]
        ],
        "source": run.source,
        "source_sha": run.source_sha,
        "data_sha": run.data_sha,
    }


class Handler(BaseHTTPRequestHandler):
    workspace: Path

    def __init__(self, *args, workspace: Path, **kw):
        self.workspace = workspace
        super().__init__(*args, **kw)

    def log_message(self, *_):
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(
            status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8"
        )

    def do_GET(self):
        port = self.server.server_address[1]
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            # Blocks DNS rebinding: a foreign page must not read strategy source or paths.
            return self._send(403, b"forbidden host", "text/plain")
        path = self.path.split("?", 1)[0]
        if path == "/api/info":
            return self._json({"workspace": str(self.workspace)})
        if path == "/api/runs":
            return self._json(runs_payload(self.workspace))
        if m := re.fullmatch(r"/api/runs/(\d+)", path):
            p = run_payload(self.workspace, int(m.group(1)))
            return self._json(p) if p else self._json({"error": "not found"}, 404)
        if m := re.fullmatch(r"/static/([\w.-]+)", path):
            name = m.group(1)
            if name in FILES:
                return self._send(200, (STATIC / name).read_bytes(), FILES[name])
        if path == "/" or re.fullmatch(r"/runs/\d+", path):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        self._send(404, b"not found", "text/plain")


def make_server(workspace: Path, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, workspace=workspace))


def _serves(port: int, workspace: Path) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=1) as r:
            return json.load(r).get("workspace") == str(workspace)
    except Exception:
        return False


def ensure_running(workspace: Path, port: int) -> int:
    """Start a background viewer for this workspace, or reuse one already serving it.
    A port held by another workspace's viewer is skipped so links never show foreign runs."""
    for p in range(port, port + PORT_RANGE):
        if _serves(p, workspace):
            return p
        try:
            srv = make_server(workspace, p)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return p
    raise OSError(f"no free port in {port}-{port + PORT_RANGE - 1} for the viewer")


def serve(workspace: Path, port: int) -> None:
    srv = make_server(workspace, port)
    print(f"llm-agent-trader viewer: http://127.0.0.1:{port}/  (workspace {workspace})", flush=True)
    srv.serve_forever()
