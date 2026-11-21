"""Read-only viewer of studies and backtests: a stdlib HTTP server, a static page, and JSON whose display strings
all come from trader.fmt."""

import json
import re
import threading
import urllib.request
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from trader import fmt, store
from trader.profit import chained_returns, drawdown_curve

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
    return "、".join(changes) or "參數未變更"


def _diffs(runs: list[store.Run]) -> dict[int, str]:
    """Each backtest against the previous one in its study; runs are in id order."""
    last: dict[str, store.Run] = {}
    out = {}
    for r in runs:
        out[r.id] = _diff(r, last.get(r.study_key))
        last[r.study_key] = r
    return out


def info_payload(workspace: Path) -> dict:
    return {"workspace": str(workspace)}


def tree_payload(workspace: Path) -> list[dict]:
    """Stocks, then studies, newest backtest first; backtests within a study oldest first."""
    studies = store.list_studies(workspace)
    by_study: dict[str, list[store.Run]] = {}
    for r in store.list_runs(workspace):
        by_study.setdefault(r.study_key, []).append(r)
    stocks: dict[str, dict] = {}
    for key, runs in sorted(by_study.items(), key=lambda kv: -kv[1][-1].id):
        first, final = runs[0], studies[key].final_run_id
        stock = stocks.setdefault(
            first.symbol, {"symbol": first.symbol, "label": first.label, "studies": []}
        )
        stock["studies"].append(
            {
                "key": key,
                "strategy": first.strategy,
                "dev": fmt.span(first.dev_start, first.dev_end),
                "exec": fmt.span(first.exec_start, first.exec_end),
                "question": first.hypothesis,
                "final_run_id": final,
                "updated_at": runs[-1].created_at,
                "runs": [
                    {
                        "id": r.id,
                        "n": r.n,
                        "hypothesis": r.hypothesis,
                        "dev_ret": fmt.pct(r.report.dev.strategy.ret),
                        "exec_ret": fmt.pct(r.report.exec.strategy.ret),
                        "overfit": r.report.overfit,
                        "final": r.id == final,
                        "created_at": r.created_at,
                    }
                    for r in runs
                ],
            }
        )
    return list(stocks.values())


def study_payload(workspace: Path, key: str) -> dict | None:
    study = store.get_study(workspace, key)
    runs = store.list_runs(workspace, study=key)
    if study is None or not runs:
        return None
    diffs = _diffs(runs)
    iterations = []
    for r in runs:
        rep = r.report
        ex = rep.exec
        iterations.append(
            {
                "id": r.id,
                "n": r.n,
                "hypothesis": r.hypothesis,
                "params": fmt.params_text(r.params),
                "diff": diffs[r.id],
                "dev_ret": fmt.pct(rep.dev.strategy.ret),
                "dev_ann": fmt.pct(rep.dev.strategy.annualized),
                "exec_ret": fmt.pct(ex.strategy.ret),
                "exec_ann": fmt.pct(ex.strategy.annualized),
                "bh_exec_ret": fmt.pct(ex.bh.ret),
                "exec_mdd": fmt.pct(ex.strategy.mdd),
                "exec_sharpe": fmt.ratio(ex.strategy.sharpe),
                "exec_trades": fmt.shares(ex.trades.count),
                "overfit": rep.overfit,
                "final": r.id == study.final_run_id,
            }
        )
    return {
        "key": key,
        "symbol": study.symbol,
        "label": runs[0].label,
        "strategy": study.strategy,
        "dev": fmt.span(study.dev_start, study.dev_end),
        "exec": fmt.span(study.exec_start, study.exec_end),
        "question": runs[0].hypothesis,
        "conclusion": json.loads(study.conclusion) if study.conclusion else None,
        "finalized_at": study.finalized_at,
        "final_run_id": study.final_run_id,
        "iterations": iterations,
    }


def _pct(values: list[float]) -> list[float]:
    return [round(x * 100, 2) for x in values]


def _dd(equity: list[float], cash: float) -> list[float]:
    return [round(d * 100, 2) for d in drawdown_curve(cash, equity)]


def run_payload(workspace: Path, run_id: int) -> dict | None:
    run = store.get(workspace, run_id)
    if run is None:
        return None
    runs = store.list_runs(workspace, study=run.study_key)
    p, rep, cash = run.payload, run.report, run.cash
    bars, dev, exe = p["bars"], p["dev"], p["exec"]
    return {
        "id": run.id,
        "n": run.n,
        "study_key": run.study_key,
        "symbol": run.symbol,
        "label": run.label,
        "strategy": run.strategy,
        "hypothesis": run.hypothesis,
        "params": fmt.params_text(run.params),
        "diff": _diffs(runs)[run.id],
        "created_at": run.created_at,
        "dev": fmt.span(run.dev_start, run.dev_end),
        "exec": fmt.span(run.exec_start, run.exec_end),
        "metrics": fmt.metric_rows(rep),
        "trade_metrics": fmt.trade_rows(rep),
        "overfit": rep.overfit,
        "overfit_note": fmt.OVERFIT_NOTE if rep.overfit else None,
        "drawdowns": {
            "dev": fmt.drawdown_rows(rep.dev.drawdowns),
            "exec": fmt.drawdown_rows(rep.exec.drawdowns),
        },
        "regimes": fmt.regime_rows(run.regimes),
        "regime_rules": fmt.REGIME_RULES,
        "chart": {
            "dates": bars["date"],
            **{c: bars[c] for c in ("open", "high", "low", "close", "volume")},
            "dev_dates": dev["dates"],
            "exec_dates": exe["dates"],
            "cum": _pct(chained_returns(cash, dev["equity"], exe["equity"])),
            "cum_bh": _pct(chained_returns(cash, p["bh_dev"], p["bh_exec"])),
            "dd_dev": _dd(dev["equity"], cash),
            "dd_exec": _dd(exe["equity"], cash),
            "markers": [
                {"date": f["date"], "side": f["side"]} for f in dev["fills"] + exe["fills"]
            ],
            "regimes": [{"start": g.start, "end": g.end, "kind": g.kind} for g in run.regimes],
        },
        "fills": [
            {k: f[k] for k in ("period", "date", "side", "buy", "price", "shares", "gross", "fees")}
            for f in fmt.fill_rows(run)
        ],
        "trips": fmt.trip_rows(run),
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
            return self._json(info_payload(self.workspace))
        if path == "/api/tree":
            return self._json(tree_payload(self.workspace))
        if m := re.fullmatch(r"/api/studies/([0-9a-f]{12})", path):
            p = study_payload(self.workspace, m.group(1))
            return self._json(p) if p else self._json({"error": "not found"}, 404)
        if m := re.fullmatch(r"/api/runs/(\d+)", path):
            p = run_payload(self.workspace, int(m.group(1)))
            return self._json(p) if p else self._json({"error": "not found"}, 404)
        if m := re.fullmatch(r"/static/([\w.-]+)", path):
            name = m.group(1)
            if name in FILES:
                return self._send(200, (STATIC / name).read_bytes(), FILES[name])
        if path == "/" or re.fullmatch(r"/runs/\d+|/studies/[0-9a-f]{12}", path):
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
