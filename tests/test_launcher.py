import ast
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from conftest import BT, SYMBOL
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "trader" / "mcp_launcher.py"
MANIFEST = ROOT / "src" / "trader" / "mcp_manifest.json"
SLOW_REAL = [
    sys.executable,
    "-c",
    "import runpy, sys, time; time.sleep(5); sys.argv = ['x', 'mcp']; "
    "runpy.run_module('trader.cli', run_name='__main__')",
]


def through_launcher(child, work):
    env = dict(os.environ, TRADER_MCP_CHILD=json.dumps(child))
    params = StdioServerParameters(command=sys.executable, args=[str(LAUNCHER)], env=env)

    async def go():
        t0 = time.monotonic()
        async with Client(params) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            ready = time.monotonic() - t0
            res = await work(client)
            return ready, tools, res

    return asyncio.run(go())


def text(res):
    return "".join(c.text for c in res.content if hasattr(c, "text"))


def test_manifest_matches_the_real_server():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "gen_mcp_manifest.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert MANIFEST.read_text(encoding="utf-8") == gen.render(gen.manifest()), (
        "run: uv run python scripts/gen_mcp_manifest.py"
    )


def test_handshake_is_instant_while_the_real_server_starts(ws):
    async def work(client):
        t0 = time.monotonic()
        res = await client.call_tool(
            "run_backtest",
            {
                "strategy": "ma_cross",
                "symbol": SYMBOL,
                **BT,
                "hypothesis": "以 5 日與 20 日均線交叉作為基準策略。",
            },
        )
        return time.monotonic() - t0, text(res)

    ready, tools, (waited, out) = through_launcher(SLOW_REAL, work)
    assert ready < 3, f"handshake took {ready:.1f}s; the real server must not block it"
    assert tools == [
        "search_stock",
        "get_ohlcv",
        "run_backtest",
        "get_run",
        "list_runs",
        "finalize_study",
        "open_dashboard",
    ]
    assert waited > 2, "the first call waits for the real server"
    assert "回測 #1" in out and "策略執行期間" in out


def test_reports_a_server_that_cannot_start(ws):
    async def work(client):
        res = await client.call_tool("search_stock", {"query": "台積電"})
        return res.is_error, text(res)

    _, _, (is_error, out) = through_launcher([sys.executable, "-c", "raise SystemExit(3)"], work)
    assert is_error and "trader 伺服器無法啟動" in out and "code 3" in out


def test_launcher_runs_on_python_39():
    ast.parse(LAUNCHER.read_text(encoding="utf-8"), feature_version=(3, 9))
