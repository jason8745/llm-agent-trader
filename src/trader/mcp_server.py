"""MCP tools over stdio. Every number in a tool result comes from trader.profit via trader.fmt."""

import ast
import datetime as dt
import json
import os
import re
import webbrowser
from typing import TypedDict

from mcp.server import MCPServer

from trader import data, fmt, runner, store, viewer, workspace

VIEWER_PORT = int(os.environ.get("TRADER_VIEWER_PORT", "8765"))

INSTRUCTIONS = """Taiwan stock backtesting harness. You discuss strategies with the user, write them,
and backtest them on a deterministic engine. The user may not be an engineer.

At the start of every conversation, before any other trader tool, call get_research_guide and
follow it exactly: it covers the research folder (ask before creating it), getting started,
the four research conditions to confirm before the first backtest, writing strategies with
save_strategy, the backtest period, number rules, formal written Chinese, and the
verdict-plus-findings conclusion stored with finalize_study."""

server = MCPServer("llm-agent-trader", instructions=INSTRUCTIONS)


def _ws():
    return workspace.path()


STRATEGY_NAME = re.compile(r"[a-z][a-z0-9_]{0,40}")


def _needs_workspace() -> str | None:
    return workspace.missing()


def check_strategy(code: str) -> str | None:
    """Why the code is not a valid strategy, or None. Static checks only; nothing is executed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"第 {e.lineno} 行語法錯誤：{e.msg}"
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "on_bar" not in funcs:
        return "缺少 on_bar(hist, pos, p) 函式。"
    if len(funcs["on_bar"].args.args) != 3:
        return "on_bar 必須接受三個參數：hist、pos、p。"
    params = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "PARAMS" for t in n.targets)
    ]
    if not params or not isinstance(params[-1].value, ast.Dict):
        return '缺少 PARAMS 字典，例如 PARAMS = {"fast": 20, "slow": 60}。'
    return None


@server.tool()
def get_research_guide() -> str:
    """The research guide: workflow, rules and conclusion format. Call this first in every
    conversation, before any other trader tool, and follow it."""
    return workspace.guide()


@server.tool()
def setup_workspace() -> str:
    """Create the research folder that holds strategies and backtest records.

    Only call this after the user has agreed to the folder being created at the path shown
    by get_research_guide."""
    return workspace.setup()


@server.tool()
def save_strategy(name: str, code: str) -> str:
    """Save a strategy as strategies/<name>.py in the research folder; use this instead of any
    other file tool. name: lowercase letters, digits and underscores, e.g. ma_trend. The code
    must define PARAMS (a dict) and on_bar(hist, pos, p). Saving the same name overwrites it.
    If you have not called get_research_guide in this conversation, call it first.
    """
    if msg := _needs_workspace():
        return msg
    if not STRATEGY_NAME.fullmatch(name or ""):
        return "策略名稱須以小寫英文字母開頭，只能包含小寫英文字母、數字與底線，例如 ma_trend。"
    if problem := check_strategy(code):
        return f"策略未儲存：{problem}"
    path = _ws() / "strategies" / f"{name}.py"
    existed = path.exists()
    path.write_text(code if code.endswith("\n") else code + "\n", encoding="utf-8")
    return f"{'已更新' if existed else '已儲存'}策略 {name}：{path}"


def _port() -> int:
    """Start (or reuse) this workspace's viewer so every link the agent hands out opens."""
    try:
        return viewer.ensure_running(_ws(), VIEWER_PORT)
    except OSError:
        return VIEWER_PORT


@server.tool()
def search_stock(query: str) -> str:
    """Find Taiwan stocks and ETFs by code or Chinese name, e.g. "台積電" or "2330".
    If you have not called get_research_guide in this conversation, call it first."""
    hits = data.search_stock(query)
    if not hits:
        return f"查無符合「{query}」的上市櫃股票或 ETF。"
    lines = ["| 代號 | 名稱 | 市場 | 類別 |", "|---|---|---|---|"]
    kind = {"stock": "股票", "etf": "ETF"}
    market = {"TWSE": "上市", "TPEx": "上櫃"}
    lines += [
        f"| {h['symbol']} | {h['name']} | {market[h['market']]} | {kind[h['kind']]} |" for h in hits
    ]
    return "\n".join(lines)


@server.tool()
def get_ohlcv(symbol: str, start: str, end: str, limit: int = 60) -> str:
    """Daily bars (YYYY-MM-DD dates, inclusive). Shows the last `limit` rows."""
    try:
        bars = data.load_bars(symbol.strip().upper(), start, end)
    except data.DataError as e:
        return f"錯誤：{e}"
    tail = bars.tail(max(limit, 1))
    lines = [
        f"{fmt.symbol_label(symbol.strip().upper())} · {bars.index[0].date()} 至 {bars.index[-1].date()} · 共 {len(bars)} 個交易日"
        f"（顯示最後 {len(tail)} 筆）",
        "",
        "| 日期 | 開盤 | 最高 | 最低 | 收盤 | 成交量 | 現金股利 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for d, r in tail.iterrows():
        div = fmt.price(r["dividend"]) if r["dividend"] else ""
        lines.append(
            f"| {d.date()} | {fmt.price(r['open'])} | {fmt.price(r['high'])} | {fmt.price(r['low'])} "
            f"| {fmt.price(r['close'])} | {fmt.shares(r['volume'])} | {div} |"
        )
    return "\n".join(lines)


@server.tool()
def run_backtest(
    strategy: str,
    symbol: str,
    start: str,
    end: str,
    hypothesis: str,
    params: dict | None = None,
    cash: float = runner.DEFAULT_CASH,
    fee: dict | None = None,
) -> str:
    """Backtest a saved strategy on one symbol over one period.
    If you have not called get_research_guide in this conversation, call it first. Before the
    first backtest of a study, confirm the four research conditions in the guide with the user.

    Dates are YYYY-MM-DD, inclusive, start <= end. The 60 trading days before start are loaded
    as indicator history automatically.
    hypothesis (required): one sentence stating what this run tests, in formal written
    language. params overrides keys in the strategy's PARAMS. fee overrides the default
    fee schedule (commission_rate, min_commission, sell_tax_rate, floor_to_unit).
    """
    if msg := _needs_workspace():
        return msg
    try:
        run = runner.run_backtest(
            _ws(),
            strategy,
            symbol,
            start,
            end,
            hypothesis,
            params=params,
            cash=cash,
            fee=fee,
        )
    except runner.RunError as e:
        return f"回測失敗：{e}"
    return fmt.run_text(run, _port())


@server.tool()
def get_run(run_id: int) -> str:
    """Full detail of one backtest: metrics against buy-and-hold, deepest drawdowns, market regimes,
    fills, round trips, data fingerprint and source snapshot."""
    if msg := _needs_workspace():
        return msg
    run = store.get(_ws(), run_id)
    if run is None:
        return f"查無回測 #{run_id}。"
    source = f"策略原始碼（回測當下快照）\n```python\n{run.source}\n```"
    return fmt.run_detail(run, _port()) + "\n\n" + source


@server.tool()
def list_runs(strategy: str | None = None, symbol: str | None = None) -> str:
    """All backtests in this workspace grouped by study, oldest first, optionally filtered."""
    if msg := _needs_workspace():
        return msg
    ws = _ws()
    return fmt.runs_markdown(store.list_runs(ws, strategy, symbol), store.list_studies(ws))


MIN_FINDINGS, MAX_FINDINGS = 3, 6


class Finding(TypedDict):
    finding: str
    insight: str


def finalize(ws, run_id: int, verdict: str, findings: list, port: int) -> str:
    run = store.get(ws, run_id)
    if run is None:
        return f"查無回測 #{run_id}。"
    verdict = (verdict or "").strip()
    if not verdict:
        return "結論未寫入：總結不得為空白。"
    if not isinstance(findings, list) or not MIN_FINDINGS <= len(findings) <= MAX_FINDINGS:
        return f"結論未寫入：發現與洞察須為 {MIN_FINDINGS} 至 {MAX_FINDINGS} 組。"
    items = []
    for i, f in enumerate(findings, 1):
        finding = str((f or {}).get("finding", "")).strip() if isinstance(f, dict) else ""
        insight = str((f or {}).get("insight", "")).strip() if isinstance(f, dict) else ""
        if not finding or not insight:
            return f"結論未寫入：第 {i} 組須同時包含發現（finding）與洞察（insight）。"
        items.append({"finding": finding, "insight": insight})
    text = "\n".join([verdict] + [f"{x['finding']}\n{x['insight']}" for x in items])
    corpus = "\n\n".join(fmt.run_detail(r, port) for r in store.list_runs(ws, study=run.study_key))
    missing = list(dict.fromkeys(fmt.unverified_numbers(text, corpus)))
    if missing:
        return (
            f"結論未寫入：下列數字未出現在研究 {run.study_key} 任何一次回測的工具輸出中，"
            "請依工具輸出原文引用後重新送出。\n" + "\n".join(f"- {n}" for n in missing)
        )
    at = dt.datetime.now(data.TAIPEI).strftime("%Y-%m-%d %H:%M")
    conclusion = json.dumps({"verdict": verdict, "findings": items}, ensure_ascii=False)
    store.finalize(ws, run.study_key, run.id, conclusion, at)
    return (
        f"已將回測 #{run.id} 標記為研究 {run.study_key} 的定稿，並寫入結論分析。\n"
        f"檢視器：{fmt.study_url(run.study_key, port)}"
    )


@server.tool()
def finalize_study(run_id: int, verdict: str, findings: list[Finding]) -> str:
    """Mark one backtest as the final one of its study and store the conclusion.

    verdict: one sentence stating whether the strategy is worth using and when.
    findings: 3 to 6 items; each pairs a finding (a factual observation quoting tool numbers)
    with an insight (what it means, why it happened, or what to do next).
    Every number must appear verbatim in the tool output of some backtest in the same study;
    otherwise nothing is stored and the missing numbers are listed. Finalizing again
    overwrites the previous choice and conclusion.
    """
    if msg := _needs_workspace():
        return msg
    return finalize(_ws(), run_id, verdict, findings, _port())


@server.tool()
def open_dashboard(run_id: int | None = None) -> str:
    """Start this workspace's dashboard if needed, open it in the default browser, and return its URL.

    The dashboard lists every study and backtest in the workspace and shows new backtests
    without a reload. Pass run_id to open one backtest.
    """
    if msg := _needs_workspace():
        return msg
    port = _port()
    url = fmt.viewer_url(run_id, port) if run_id else f"http://127.0.0.1:{port}/"
    if run_id and store.get(_ws(), run_id) is None:
        return f"查無回測 #{run_id}。檢視器：http://127.0.0.1:{port}/"
    opened = webbrowser.open(url)
    note = "已在預設瀏覽器開啟。" if opened else "無法自動開啟瀏覽器，請手動開啟此連結。"
    return f"檢視器：{url}\n{note}新的回測完成後，頁面會自動顯示，不需要重新整理。"


def main() -> None:
    server.run("stdio")
