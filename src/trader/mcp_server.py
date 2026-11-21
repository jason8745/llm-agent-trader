"""MCP tools over stdio. Every number in a tool result comes from trader.profit via trader.fmt."""

import os

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

Every run reports in-sample (first 70%) and out-of-sample (last 30%) results next to
buy-and-hold. Tune on in-sample only. Quote numbers exactly as the tools return them."""

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
        f"{symbol.upper()} · {bars.index[0].date()} 至 {bars.index[-1].date()} · 共 {len(bars)} 個交易日"
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
    """Backtest a strategy file on one symbol over [start, end].

    hypothesis (required): one sentence stating what this run tests, in formal written
    language. params overrides keys in the strategy's PARAMS. fee overrides the default
    fee schedule (commission_rate, min_commission, sell_tax_rate, floor_to_unit).
    """
    try:
        run = runner.run_backtest(
            _ws(), strategy, symbol, start, end, hypothesis, params=params, cash=cash, fee=fee
        )
    except runner.RunError as e:
        return f"回測失敗：{e}"
    return fmt.run_text(run, _port())


@server.tool()
def get_run(run_id: int) -> str:
    """Full detail of one run: summary, fills, round trips, data fingerprint, source snapshot."""
    run = store.get(_ws(), run_id)
    if run is None:
        return f"查無回測 #{run_id}。"
    led = run.payload["ledger"]
    return "\n\n".join(
        [
            fmt.run_text(run, _port()),
            "成交明細\n" + fmt.fills_markdown(led["fills"]),
            "已平倉交易\n" + fmt.round_trips_markdown(led["round_trips"]),
            f"資料指紋：{run.data_sha}\n策略原始碼 sha256：{run.source_sha}",
            f"策略原始碼（回測當下快照）\n```python\n{run.source}\n```",
        ]
    )


@server.tool()
def list_runs(strategy: str | None = None, symbol: str | None = None) -> str:
    """All runs in this workspace, oldest first, optionally filtered."""
    return fmt.runs_markdown(store.list_runs(_ws(), strategy, symbol))


def main() -> None:
    server.run("stdio")
