import asyncio
import os
import re
import subprocess
import sys

from conftest import END, START, SYMBOL
from mcp import Client, StdioServerParameters

from trader import fmt, store

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


def call_tools(calls):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "trader.cli", "mcp"], env=dict(os.environ)
    )

    async def go():
        async with Client(params) as client:
            tools = sorted(t.name for t in (await client.list_tools()).tools)
            out = []
            for name, args in calls:
                res = await client.call_tool(name, args)
                out.append("".join(c.text for c in res.content if hasattr(c, "text")))
            return tools, out

    return asyncio.run(go())


def test_mcp_tools_over_stdio(ws):
    tools, (found, result, listing) = call_tools(
        [
            ("search_stock", {"query": "台積電"}),
            (
                "run_backtest",
                {
                    "strategy": "ma_cross",
                    "symbol": SYMBOL,
                    "start": START,
                    "end": END,
                    "hypothesis": HYP,
                },
            ),
            ("list_runs", {}),
        ]
    )
    assert tools == [
        "get_ohlcv",
        "get_run",
        "list_runs",
        "open_dashboard",
        "run_backtest",
        "search_stock",
    ]
    assert "2330.TW" in found and "台積電" in found
    run_id = int(re.search(r"回測 #(\d+)", result).group(1))
    run = store.get(ws, run_id)
    port = int(re.search(r"127\.0\.0\.1:(\d+)/runs/", result).group(1))
    assert result == fmt.run_text(run, port)
    assert HYP in listing


def test_mcp_and_cli_render_identical_numbers(ws, monkeypatch):
    monkeypatch.setenv("TRADER_VIEWER_PORT", "18965")
    _, (result,) = call_tools(
        [
            (
                "run_backtest",
                {
                    "strategy": "ma_cross",
                    "symbol": SYMBOL,
                    "start": START,
                    "end": END,
                    "hypothesis": HYP,
                },
            )
        ]
    )
    run_id = int(re.search(r"回測 #(\d+)", result).group(1))
    cli = subprocess.run(
        [sys.executable, "-m", "trader.cli", "show", str(run_id)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert cli == result
    s = fmt.summary(store.get(ws, run_id).report, store.get(ws, run_id).dates)
    for key, value in s.items():
        if key != "overfit":
            assert value in cli and value in result, key


def test_mcp_errors_are_messages_not_crashes(ws):
    (ws / "strategies" / "spin.py").write_text(
        "def on_bar(h, pos, p):\n    raise ValueError('bad')\n"
    )
    _, (err, ok) = call_tools(
        [
            (
                "run_backtest",
                {
                    "strategy": "spin",
                    "symbol": SYMBOL,
                    "start": START,
                    "end": END,
                    "hypothesis": HYP,
                },
            ),
            ("get_run", {"run_id": 999}),
        ]
    )
    assert err.startswith("回測失敗：") and "ValueError: bad" in err
    assert ok == "查無回測 #999。"
