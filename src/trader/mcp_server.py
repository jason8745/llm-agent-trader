"""MCP tools over stdio. Every number in a tool result comes from trader.profit via trader.fmt."""

import datetime as dt
import os
import webbrowser

from mcp.server import MCPServer

from trader import data, fmt, runner, store, viewer

VIEWER_PORT = int(os.environ.get("TRADER_VIEWER_PORT", "8765"))

INSTRUCTIONS = """Taiwan stock backtesting harness. You write strategies; the engine runs them.

A strategy is a Python file (usually strategies/<name>.py) defining
    PARAMS = {...}
    def on_bar(hist, pos, p) -> float
hist is a DataFrame of bars up to and including today (open, high, low, close, volume,
dividend); pos is the current position as a fraction of equity; p is PARAMS merged with
overrides. Return the target position, 0.0 to 1.0. It fills at the next day's open and only
changes when the returned target changes. Indicators: `from trader import ta`
(sma, ema, rsi, macd, bbands, atr; they compose).

Every backtest has two explicit periods, each compared with buy-and-hold:
策略開發期間 (development: design and tune the strategy here) and 策略執行期間 (execution:
a simulated live run that starts flat with the initial cash; indicators may use earlier
bars). Tune on the development period only. A study is one symbol, one strategy file and
both periods; finalize it with finalize_study. Quote numbers exactly as the tools return
them."""

server = MCPServer("llm-agent-trader", instructions=INSTRUCTIONS)


def _ws():
    return runner.workspace()


def _port() -> int:
    """Start (or reuse) this workspace's viewer so every link the agent hands out opens."""
    try:
        return viewer.ensure_running(_ws(), VIEWER_PORT)
    except OSError:
        return VIEWER_PORT


@server.tool()
def search_stock(query: str) -> str:
    """Find Taiwan stocks and ETFs by code or Chinese name, e.g. "台積電" or "2330"."""
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
    dev_start: str,
    dev_end: str,
    exec_start: str,
    exec_end: str,
    hypothesis: str,
    params: dict | None = None,
    cash: float = runner.DEFAULT_CASH,
    fee: dict | None = None,
) -> str:
    """Backtest a strategy file on one symbol over a development and an execution period.

    Dates are YYYY-MM-DD, inclusive, with dev_start <= dev_end < exec_start <= exec_end.
    hypothesis (required): one sentence stating what this run tests, in formal written
    language. params overrides keys in the strategy's PARAMS. fee overrides the default
    fee schedule (commission_rate, min_commission, sell_tax_rate, floor_to_unit).
    """
    try:
        run = runner.run_backtest(
            _ws(),
            strategy,
            symbol,
            dev_start,
            dev_end,
            exec_start,
            exec_end,
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
    """Full detail of one backtest: both periods' metrics, deepest drawdowns, market regimes,
    fills, round trips, data fingerprint and source snapshot."""
    run = store.get(_ws(), run_id)
    if run is None:
        return f"查無回測 #{run_id}。"
    source = f"策略原始碼（回測當下快照）\n```python\n{run.source}\n```"
    return fmt.run_detail(run, _port()) + "\n\n" + source


@server.tool()
def list_runs(strategy: str | None = None, symbol: str | None = None) -> str:
    """All backtests in this workspace grouped by study, oldest first, optionally filtered."""
    ws = _ws()
    return fmt.runs_markdown(store.list_runs(ws, strategy, symbol), store.list_studies(ws))


def finalize(ws, run_id: int, conclusion: str, port: int) -> str:
    run = store.get(ws, run_id)
    if run is None:
        return f"查無回測 #{run_id}。"
    if not conclusion or not conclusion.strip():
        return "結論未寫入：結論分析不得為空白。"
    corpus = "\n\n".join(fmt.run_detail(r, port) for r in store.list_runs(ws, study=run.study_key))
    missing = list(dict.fromkeys(fmt.unverified_numbers(conclusion, corpus)))
    if missing:
        return (
            f"結論未寫入：下列數字未出現在研究 {run.study_key} 任何一次回測的工具輸出中，"
            "請依工具輸出原文引用後重新送出。\n" + "\n".join(f"- {n}" for n in missing)
        )
    at = dt.datetime.now(data.TAIPEI).strftime("%Y-%m-%d %H:%M")
    store.finalize(ws, run.study_key, run.id, conclusion.strip(), at)
    return (
        f"已將回測 #{run.id} 標記為研究 {run.study_key} 的定稿，並寫入結論分析。\n"
        f"檢視器：{fmt.study_url(run.study_key, port)}"
    )


@server.tool()
def finalize_study(run_id: int, conclusion: str) -> str:
    """Mark one backtest as the final one of its study and store the conclusion (markdown).

    Every number in the conclusion must appear verbatim in the tool output of some backtest
    in the same study; otherwise nothing is stored and the missing numbers are listed.
    Finalizing again overwrites the previous choice and conclusion.
    """
    return finalize(_ws(), run_id, conclusion, _port())


@server.tool()
def open_dashboard(run_id: int | None = None) -> str:
    """Start this workspace's dashboard if needed, open it in the default browser, and return its URL.

    The dashboard lists every study and backtest in the workspace and shows new backtests
    without a reload. Pass run_id to open one backtest.
    """
    port = _port()
    url = fmt.viewer_url(run_id, port) if run_id else f"http://127.0.0.1:{port}/"
    if run_id and store.get(_ws(), run_id) is None:
        return f"查無回測 #{run_id}。檢視器：http://127.0.0.1:{port}/"
    opened = webbrowser.open(url)
    note = "已在預設瀏覽器開啟。" if opened else "無法自動開啟瀏覽器，請手動開啟此連結。"
    return f"檢視器：{url}\n{note}新的回測完成後，頁面會自動顯示，不需要重新整理。"


def main() -> None:
    server.run("stdio")
