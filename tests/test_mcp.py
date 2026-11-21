import asyncio
import json
import os
import re
import subprocess
import sys

from conftest import BT, PERIODS, SYMBOL
from mcp import Client, StdioServerParameters

from trader import fmt, mcp_server, runner, store, workspace

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
        "get_research_guide",
        "get_run",
        "list_runs",
        "open_dashboard",
        "run_backtest",
        "save_strategy",
        "search_stock",
        "setup_workspace",
    ]
    assert "2330.TW" in found and "台積電" in found
    run_id = int(re.search(r"回測 #(\d+)", result).group(1))
    run = store.get(ws, run_id)
    port = int(re.search(r"127\.0\.0\.1:(\d+)/runs/", result).group(1))
    assert result == fmt.run_text(run, port)
    assert detail.startswith(fmt.run_detail(run, port)) and run.source in detail
    assert "成交明細" in detail and "最深回撤" in detail and "盤勢彙總" in result
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
    ret = fmt.pct(ra.strategy.ret)  # from the first iteration's output
    mdd = fmt.pct(rb.strategy.mdd)
    trips = fmt.shares(rb.trades.count)
    verdict = "本策略僅適用於重視風險控制的情境。"
    findings = [
        {
            "finding": f"第一次實驗的報酬率為 {ret}。",
            "insight": "此結果作為後續調整參數的基準。",
        },
        {
            "finding": f"最大回撤為 {mdd}。",
            "insight": "回撤須與買進並持有基準比較。",
        },
        {
            "finding": f"交易次數為 {trips} 次。",
            "insight": "本研究以 2025 年以前的資料為準，交易次數少時統計可信度有限。",
        },
    ]
    out = mcp_server.finalize(ws, b.id, verdict, findings, 8765)
    assert out.endswith(f"http://127.0.0.1:8765/studies/{b.study_key}"), out
    s = store.get_study(ws, b.study_key)
    assert s.final_run_id == b.id and s.finalized_at
    assert json.loads(s.conclusion) == {"verdict": verdict, "findings": findings}
    again = mcp_server.finalize(ws, a.id, "改以第一次迭代定稿。", findings, 8765)
    assert "已將回測" in again and store.get_study(ws, a.study_key).final_run_id == a.id


def test_finalize_rejects_invented_numbers_and_stores_nothing(ws):
    a, _ = first_study(ws)
    real = fmt.pct(a.report.strategy.ret)
    ok = {"finding": f"報酬率為 {real}。", "insight": "依工具輸出引用。"}
    bad = {"finding": "年化約 +31.07%。", "insight": "期末權益 1,234,567。"}
    out = mcp_server.finalize(ws, a.id, "總結。", [ok, bad, ok], 8765)
    assert out.startswith("結論未寫入")
    assert "- +31.07%" in out and "- 1,234,567" in out and real not in out
    s = store.get_study(ws, a.study_key)
    assert s.final_run_id is None and s.conclusion is None and s.finalized_at is None
    assert mcp_server.finalize(ws, 999, "x", [ok] * 3, 8765) == "查無回測 #999。"


def test_finalize_requires_paired_findings_and_insights(ws):
    a, _ = first_study(ws)
    pair = {"finding": "發現。", "insight": "洞察。"}
    assert "總結不得為空白" in mcp_server.finalize(ws, a.id, " ", [pair] * 3, 8765)
    assert "3 至 6 組" in mcp_server.finalize(ws, a.id, "總結。", [pair] * 2, 8765)
    assert "3 至 6 組" in mcp_server.finalize(ws, a.id, "總結。", [pair] * 7, 8765)
    missing = [pair, {"finding": "只有發現。", "insight": ""}, pair]
    assert "第 2 組須同時包含" in mcp_server.finalize(ws, a.id, "總結。", missing, 8765)
    assert store.get_study(ws, a.study_key).conclusion is None


def test_research_folder_is_created_only_by_setup_workspace(tmp_path, monkeypatch):
    target = tmp_path / "Documents" / "trader-research"
    monkeypatch.setenv("TRADER_WORKSPACE", str(target))
    guide = mcp_server.get_research_guide()
    assert "## 開始使用" in guide and str(target) in guide and "尚未建立" in guide
    code = 'PARAMS = {"fast": 5}\n\n\ndef on_bar(hist, pos, p):\n    return 0.0\n'
    for out in [
        mcp_server.save_strategy("ma_cross", code),
        mcp_server.list_runs(),
        mcp_server.get_run(1),
        mcp_server.open_dashboard(),
        mcp_server.finalize_study(1, "總結。", []),
    ]:
        assert out.startswith("研究資料夾尚未建立") and "setup_workspace" in out
    assert not target.exists(), "no tool may create the folder before setup_workspace"
    assert mcp_server.setup_workspace().startswith("已建立研究資料夾")
    assert (target / "strategies").is_dir() and "已建立" in mcp_server.get_research_guide()
    assert mcp_server.setup_workspace().startswith("研究資料夾已存在")


def test_default_research_folder_is_in_documents(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADER_WORKSPACE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert workspace.path() == tmp_path / "Documents" / "trader-research"


def test_save_strategy_validates_then_writes(ws):
    good = 'PARAMS = {"fast": 5}\n\n\ndef on_bar(hist, pos, p):\n    return 0.0'
    assert mcp_server.save_strategy("Bad-Name", good).startswith("策略名稱須以小寫英文字母開頭")
    bad = {
        "def on_bar(hist, pos, p):\n    return (": "語法錯誤",
        'PARAMS = {"fast": 5}\n': "缺少 on_bar",
        "PARAMS = {}\ndef on_bar(hist, pos):\n    return 0.0\n": "三個參數",
        "def on_bar(hist, pos, p):\n    return 0.0\n": "缺少 PARAMS",
    }
    for code, why in bad.items():
        out = mcp_server.save_strategy("trial", code)
        assert out.startswith("策略未儲存") and why in out, out
    assert not (ws / "strategies" / "trial.py").exists()
    assert mcp_server.save_strategy("trial", good).startswith("已儲存策略 trial")
    assert (ws / "strategies" / "trial.py").read_text(encoding="utf-8") == good + "\n"
    assert mcp_server.save_strategy("trial", good).startswith("已更新策略 trial")
    run = runner.run_backtest(ws, "trial", SYMBOL, *PERIODS, HYP)
    assert run.strategy == "trial"
