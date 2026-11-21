import asyncio
import os
import re
import subprocess
import sys

from conftest import BT, PERIODS, SYMBOL
from mcp import Client, StdioServerParameters

from trader import fmt, mcp_server, runner, store

HYP = "以 5 日與 20 日均線交叉作為基準策略。"
BACKTEST = {"strategy": "ma_cross", "symbol": SYMBOL, "hypothesis": HYP, **BT}


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
    tools, (found, result, detail, listing) = call_tools(
        [
            ("search_stock", {"query": "台積電"}),
            ("run_backtest", BACKTEST),
            ("get_run", {"run_id": 1}),
            ("list_runs", {}),
        ]
    )
    assert tools == [
        "finalize_study",
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
    assert detail.startswith(fmt.run_detail(run, port)) and run.source in detail
    assert "成交明細" in detail and "最深回撤（策略執行期間）" in detail
    assert HYP in listing and f"研究 {run.study_key}" in listing
    for text in (result, detail, listing, mcp_server.INSTRUCTIONS):
        assert "樣本內" not in text and "樣本外" not in text


def test_mcp_and_cli_render_identical_numbers(ws, monkeypatch):
    monkeypatch.setenv("TRADER_VIEWER_PORT", "18965")
    _, (result,) = call_tools([("run_backtest", BACKTEST)])
    run_id = int(re.search(r"回測 #(\d+)", result).group(1))
    cli = subprocess.run(
        [sys.executable, "-m", "trader.cli", "show", str(run_id)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert cli == result


def test_cli_backtest_and_runs(ws):
    cli = [sys.executable, "-m", "trader.cli"]
    out = subprocess.run(
        [*cli, "backtest", "ma_cross", SYMBOL, *PERIODS, "--hypothesis", HYP],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.startswith("回測 #1 · 研究 ")
    runs = subprocess.run([*cli, "runs"], capture_output=True, text=True, check=True).stdout
    assert "| 1 | 1 |" in runs and HYP in runs


def test_mcp_errors_are_messages_not_crashes(ws):
    (ws / "strategies" / "spin.py").write_text(
        "def on_bar(h, pos, p):\n    raise ValueError('bad')\n"
    )
    _, (err, ok) = call_tools(
        [("run_backtest", {**BACKTEST, "strategy": "spin"}), ("get_run", {"run_id": 999})]
    )
    assert err.startswith("回測失敗：") and "ValueError: bad" in err
    assert ok == "查無回測 #999。"


def first_study(ws):
    a = runner.run_backtest(ws, "ma_cross", SYMBOL, *PERIODS, HYP)
    b = runner.run_backtest(ws, "ma_cross", SYMBOL, *PERIODS, HYP, params={"fast": 8})
    return a, b


def test_finalize_accepts_numbers_quoted_from_the_study(ws):
    a, b = first_study(ws)
    ra, rb = a.report, b.report
    dev_ret = fmt.pct(ra.dev.strategy.ret)  # from the first iteration's output
    exec_mdd = fmt.pct(rb.exec.strategy.mdd)
    trips = fmt.shares(rb.exec.trades.count)
    text = (
        f"**兩段期間的績效**：策略開發期間報酬率為 {dev_ret}，策略執行期間最大回撤為 "
        f"{exec_mdd}，交易次數 {trips} 次；本研究以 2025 年以前的資料為準。"
    )
    out = mcp_server.finalize(ws, b.id, text, 8765)
    assert out.endswith(f"http://127.0.0.1:8765/studies/{b.study_key}"), out
    s = store.get_study(ws, b.study_key)
    assert (s.final_run_id, s.conclusion) == (b.id, text) and s.finalized_at
    again = mcp_server.finalize(ws, a.id, "改以第一次迭代定稿。", 8765)
    assert "已將回測" in again and store.get_study(ws, a.study_key).final_run_id == a.id


def test_finalize_rejects_invented_numbers_and_stores_nothing(ws):
    a, _ = first_study(ws)
    real = fmt.pct(a.report.dev.strategy.ret)
    out = mcp_server.finalize(
        ws, a.id, f"報酬率為 {real}，年化約 +31.07%，期末權益 1,234,567。", 8765
    )
    assert out.startswith("結論未寫入")
    assert "- +31.07%" in out and "- 1,234,567" in out and real not in out
    s = store.get_study(ws, a.study_key)
    assert s.final_run_id is None and s.conclusion is None and s.finalized_at is None
    assert mcp_server.finalize(ws, 999, "x", 8765) == "查無回測 #999。"
