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
        "get_research_guide",
        "setup_workspace",
        "save_strategy",
        "search_stock",
        "get_ohlcv",
        "run_backtest",
        "get_run",
        "list_runs",
        "finalize_study",
        "open_dashboard",
    ]
    assert waited > 2, "the first call waits for the real server"
    assert "回測 #1" in out and "回測期間" in out


def test_reports_a_server_that_cannot_start(ws):
    async def work(client):
        res = await client.call_tool("search_stock", {"query": "台積電"})
        return res.is_error, text(res)

    _, _, (is_error, out) = through_launcher([sys.executable, "-c", "raise SystemExit(3)"], work)
    assert is_error and "trader 伺服器無法啟動" in out and "code 3" in out


def test_launcher_and_workspace_use_only_the_standard_library():
    """They run before uv has installed pandas and the real server."""
    for path in [LAUNCHER, LAUNCHER.with_name("workspace.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods = {
            a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
        }
        mods |= {
            n.module.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module
        }
        assert mods <= set(sys.stdlib_module_names) | {"workspace"}, (path.name, mods)


def test_child_server_runs_with_the_same_uv_and_managed_python(monkeypatch):
    spec = importlib.util.spec_from_file_location("launcher", LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.delenv("TRADER_MCP_CHILD", raising=False)
    monkeypatch.setenv("UV", "/opt/claude/uv-runtime/uv")
    cmd = launcher.child_command()
    assert cmd[:3] == ["/opt/claude/uv-runtime/uv", "tool", "run"]
    assert "--managed-python" in cmd and cmd[-2:] == ["llm-agent-trader", "mcp"]
    assert cmd[cmd.index("--from") + 1] == str(ROOT)


def test_guide_and_setup_are_instant_and_identical_to_the_real_server(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_WORKSPACE", str(tmp_path / "research"))

    async def work(client):
        t0 = time.monotonic()
        guide = text(await client.call_tool("get_research_guide", {}))
        setup = text(await client.call_tool("setup_workspace", {}))
        return time.monotonic() - t0, guide, setup

    _, _, (took, guide, setup) = through_launcher(SLOW_REAL, work)
    assert took < 2, f"took {took:.1f}s; these must not wait for the real server"
    assert "尚未建立" in guide and setup.startswith("已建立研究資料夾")
    import shutil

    shutil.rmtree(tmp_path / "research")
    from trader import mcp_server

    assert guide == mcp_server.get_research_guide()
    assert setup == mcp_server.setup_workspace()
