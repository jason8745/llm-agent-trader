"""The only place numbers become display strings. The MCP tools, the CLI, and the viewer
all render through these functions, so a run reads identically everywhere."""

from decimal import ROUND_HALF_UP, Decimal

from trader.data import stock_name
from trader.profit import Report

DASH = "—"


def _q(x: float, places: str) -> Decimal:
    return Decimal(repr(float(x))).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return DASH
    v = _q(x * 100, "0.01")
    if v == 0:
        return "0.00%"
    return f"{'+' if signed and v > 0 else ''}{v}%"


def money(x: float) -> str:
    v = _q(x, "1")
    return f"{int(v):,}" if v != 0 else "0"


def price(x: float) -> str:
    return f"{_q(x, '0.01'):,}"


def shares(n: int) -> str:
    return f"{int(n):,}"


def summary(report: Report, dates: list[str]) -> dict[str, str]:
    r = report
    return {
        "total": pct(r.total.ret),
        "in_sample": pct(r.in_sample.ret),
        "out_of_sample": pct(r.out_of_sample.ret),
        "mdd": pct(r.total.mdd),
        "bh_total": pct(r.bh_total.ret),
        "bh_in_sample": pct(r.bh_in_sample.ret),
        "bh_out_of_sample": pct(r.bh_out_of_sample.ret),
        "bh_mdd": pct(r.bh_total.mdd),
        "trades": shares(r.trades),
        "win_rate": pct(r.win_rate, signed=False),
        "final_equity": money(r.final_equity),
        "realized_pnl": money(r.realized_pnl),
        "unrealized_pnl": money(r.unrealized_pnl),
        "in_sample_annualized": pct(r.in_sample_annualized),
        "out_of_sample_annualized": pct(r.out_of_sample_annualized),
        "oos_start": dates[r.split - 1],
        "overfit": "yes" if r.overfit else "no",
    }


ROW_LABELS = [
    ("總報酬率", "total", "bh_total"),
    ("樣本內報酬率", "in_sample", "bh_in_sample"),
    ("樣本外報酬率", "out_of_sample", "bh_out_of_sample"),
    ("最大回撤", "mdd", "bh_mdd"),
]
OVERFIT_NOTE = "⚑ 樣本內年化報酬率較樣本外年化報酬率高出逾 15 個百分點，可能過度擬合。"


def summary_markdown(s: dict[str, str]) -> str:
    lines = ["| 指標 | 策略 | 買進並持有基準 |", "|---|---:|---:|"]
    lines += [f"| {label} | {s[a]} | {s[b]} |" for label, a, b in ROW_LABELS]
    lines.append("")
    lines.append(
        f"交易次數 {s['trades']} · 勝率 {s['win_rate']} · 期末權益 {s['final_equity']}"
        f"（已實現損益 {s['realized_pnl']}，未實現損益 {s['unrealized_pnl']}）"
    )
    lines.append(
        f"年化報酬率：樣本內 {s['in_sample_annualized']} · 樣本外 {s['out_of_sample_annualized']}"
        f" · 樣本外區間起點：{s['oos_start']}"
    )
    if s["overfit"] == "yes":
        lines.append(OVERFIT_NOTE)
    return "\n".join(lines)


def symbol_label(symbol: str) -> str:
    """'2330.TW 台積電' for listed Taiwan symbols, the bare symbol otherwise."""
    name = stock_name(symbol)
    return f"{symbol} {name}" if name else symbol


def viewer_url(run_id: int, port: int) -> str:
    return f"http://127.0.0.1:{port}/runs/{run_id}"


def run_title(run) -> str:
    n = len(run.dates)
    return (
        f"回測 #{run.id} · {run.strategy} · {run.symbol} · "
        f"{run.dates[0]} 至 {run.dates[-1]}（{n} 個交易日）"
    )


def run_text(run, port: int) -> str:
    s = summary(run.report, run.dates)
    params = ", ".join(f"{k}={v}" for k, v in run.params.items()) or DASH
    return "\n".join(
        [
            run_title(run),
            f"假設：{run.hypothesis}",
            f"參數：{params}",
            "",
            summary_markdown(s),
            f"檢視器：{viewer_url(run.id, port)}",
        ]
    )


def fills_markdown(fills: list[dict]) -> str:
    if not fills:
        return "（無成交）"
    lines = [
        "| 日期 | 方向 | 價格 | 股數 | 成交金額 | 手續費 | 證交稅 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    side = {"BUY": "買進", "SELL": "賣出"}
    for f in fills:
        lines.append(
            f"| {f['date']} | {side[f['side']]} | {price(f['price'])} | {shares(f['shares'])} "
            f"| {money(f['gross'])} | {money(f['commission'])} | {money(f['tax'])} |"
        )
    return "\n".join(lines)


def round_trips_markdown(trips: list[dict]) -> str:
    if not trips:
        return "（無已平倉交易）"
    lines = ["| 進場 | 出場 | 持有交易日 | 已實現損益 |", "|---|---|---:|---:|"]
    for t in trips:
        held = t["exit_bar"] - t["entry_bar"]
        lines.append(f"| {t['entry_date']} | {t['exit_date']} | {held} | {money(t['pnl'])} |")
    return "\n".join(lines)


def runs_markdown(runs) -> str:
    if not runs:
        return "（尚無回測紀錄）"
    lines = [
        "| # | 時間 | 策略 | 標的 | 樣本內 | 樣本外 | 買進並持有（樣本外） | 最大回撤 | 交易次數 | 假設 |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in runs:
        s = summary(r.report, r.dates)
        flag = " ⚑" if s["overfit"] == "yes" else ""
        lines.append(
            f"| {r.id} | {r.created_at} | {r.strategy} | {r.symbol} | {s['in_sample']} "
            f"| {s['out_of_sample']}{flag} | {s['bh_out_of_sample']} | {s['mdd']} "
            f"| {s['trades']} | {r.hypothesis} |"
        )
    return "\n".join(lines)
