"""The only place numbers become display strings. The MCP tools, the CLI, and the viewer
all render through these functions, so a backtest reads identically everywhere."""

import re
from decimal import ROUND_HALF_UP, Decimal

from trader.data import stock_name
from trader.profit import Drawdown, Metrics, Period, RegimeRow, RegimeSummary, regime_summary
from trader.regime import RANGE_BAND, RANGE_MIN_BARS, REVERSAL, TREND

DASH = "—"
UNRECOVERED = "尚未回復"
PERIOD = "回測期間"
SIDE = {"BUY": "買進", "SELL": "賣出"}
REGIME_LABEL = {"up": "上漲段", "down": "下跌段", "range": "盤整段"}
REGIME_RULES = (
    f"盤勢分段依固定規則：價格在 {round(RANGE_BAND * 100)}% 區間內來回達 {RANGE_MIN_BARS} "
    f"個交易日以上為盤整段；其餘期間以反轉 {round(REVERSAL * 100)}% 判斷轉折，"
    f"漲幅達 {round(TREND * 100)}% 為上漲段、跌幅達 {round(TREND * 100)}% 為下跌段，其餘為盤整段。"
)


def _q(x: float, places: str) -> Decimal:
    return Decimal(repr(float(x))).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return DASH
    v = _q(x * 100, "0.01")
    if v == 0:
        return "0.00%"
    return f"{'+' if signed and v > 0 else ''}{v}%"


def money(x: float | None, signed: bool = False) -> str:
    if x is None:
        return DASH
    v = _q(x, "1")
    if v == 0:
        return "0"
    return f"{'+' if signed and v > 0 else ''}{int(v):,}"


def ratio(x: float | None) -> str:
    if x is None:
        return DASH
    v = _q(x, "0.01")
    return f"{v:,}" if v != 0 else "0.00"


def price(x: float) -> str:
    return f"{_q(x, '0.01'):,}"


def shares(n: int | None) -> str:
    return DASH if n is None else f"{int(n):,}"


def span(a: str | None, b: str | None) -> str:
    return f"{a} 至 {b}" if a and b else DASH


def _recovery_bars(m: Metrics) -> str:
    if m.mdd_peak is None:
        return DASH
    return UNRECOVERED if m.mdd_recovery_bars is None else shares(m.mdd_recovery_bars)


METRICS = [
    ("總報酬率", lambda m: pct(m.ret)),
    ("年化報酬率", lambda m: pct(m.annualized)),
    ("期末權益", lambda m: money(m.final_equity)),
    ("最大回撤", lambda m: pct(m.mdd)),
    ("最大回撤期間", lambda m: span(m.mdd_peak, m.mdd_trough)),
    ("回撤回復交易日", _recovery_bars),
    ("年化波動率", lambda m: pct(m.volatility, signed=False)),
    ("Sharpe 比率（無風險利率 0）", lambda m: ratio(m.sharpe)),
    ("Calmar 比率", lambda m: ratio(m.calmar)),
]
TRADES = [
    ("交易次數", lambda t: shares(t.count)),
    ("勝率", lambda t: pct(t.win_rate, signed=False)),
    ("平均獲利／平均虧損", lambda t: ratio(t.payoff)),
    ("獲利因子", lambda t: ratio(t.profit_factor)),
    ("單筆最大獲利", lambda t: money(t.best, signed=True)),
    ("單筆最大虧損", lambda t: money(t.worst, signed=True)),
    ("平均持有交易日", lambda t: ratio(t.avg_holding_bars)),
    ("持倉時間比例", lambda t: pct(t.exposure, signed=False)),
]


def metric_rows(p: Period) -> list[dict]:
    return [{"label": label, "strategy": f(p.strategy), "bh": f(p.bh)} for label, f in METRICS]


def trade_rows(p: Period) -> list[dict]:
    return [{"label": label, "value": f(p.trades)} for label, f in TRADES]


def regime_rows(rows: list[RegimeRow]) -> list[dict]:
    return [
        {
            "start": g.start,
            "end": g.end,
            "kind": g.kind,
            "label": REGIME_LABEL[g.kind],
            "bars": shares(g.bars),
            "price_change": pct(g.price_change),
            "strategy": pct(g.strategy),
            "exposure": pct(g.exposure, signed=False),
        }
        for g in rows
    ]


def regime_summary_rows(rows: list[RegimeSummary]) -> list[dict]:
    return [
        {
            "kind": g.kind,
            "label": REGIME_LABEL[g.kind],
            "segments": shares(g.segments),
            "bars": shares(g.bars),
            "price_change": pct(g.price_change),
            "strategy": pct(g.strategy),
            "exposure": pct(g.exposure, signed=False),
        }
        for g in rows
    ]


def drawdown_rows(drawdowns: list[Drawdown]) -> list[dict]:
    return [
        {
            "peak": d.peak,
            "trough": d.trough,
            "depth": pct(d.depth),
            "recovery": d.recovery or UNRECOVERED,
            "bars": shares(d.bars),
        }
        for d in drawdowns
    ]


def fill_rows(run) -> list[dict]:
    return [
        {
            "date": f["date"],
            "side": SIDE[f["side"]],
            "buy": f["side"] == "BUY",
            "price": price(f["price"]),
            "shares": shares(f["shares"]),
            "gross": money(f["gross"]),
            "commission": money(f["commission"]),
            "tax": money(f["tax"]),
            "fees": money(f["commission"] + f["tax"]),
        }
        for f in run.payload["ledger"]["fills"]
    ]


def trip_rows(run) -> list[dict]:
    return [
        {
            "entry": t["entry_date"],
            "exit": t["exit_date"],
            "held": shares(t["exit_bar"] - t["entry_bar"]),
            "pnl": money(t["pnl"], signed=True),
            "win": t["pnl"] > 0,
        }
        for t in run.payload["ledger"]["round_trips"]
    ]


def symbol_label(symbol: str) -> str:
    """'2330.TW 台積電' for listed Taiwan symbols, the bare symbol otherwise."""
    name = stock_name(symbol)
    return f"{symbol} {name}" if name else symbol


def params_text(params: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items()) or DASH


def viewer_url(run_id: int, port: int) -> str:
    return f"http://127.0.0.1:{port}/runs/{run_id}"


def study_url(key: str, port: int) -> str:
    return f"http://127.0.0.1:{port}/studies/{key}"


def _table(header: list[str], align: str, rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])


def regimes_markdown(run) -> str:
    summary = _table(
        ["盤勢", "段數", "交易日", "股價漲跌幅", "策略報酬率", "持倉時間比例"],
        ["---", "---:", "---:", "---:", "---:", "---:"],
        [
            [g["label"], g["segments"], g["bars"], g["price_change"], g["strategy"], g["exposure"]]
            for g in regime_summary_rows(regime_summary(run.regimes))
        ],
    )
    segments = _table(
        ["盤勢", "期間", "交易日", "股價漲跌幅", "策略報酬率", "持倉時間比例"],
        ["---", "---", "---:", "---:", "---:", "---:"],
        [
            [g["label"], span(g["start"], g["end"]), g["bars"], g["price_change"]]
            + [g["strategy"], g["exposure"]]
            for g in regime_rows(run.regimes)
        ],
    )
    return f"盤勢彙總（同類各段連乘）\n{summary}\n\n盤勢分段\n{segments}\n{REGIME_RULES}"


def run_text(run, port: int) -> str:
    r = run.report
    head = [
        f"回測 #{run.id} · 研究 {run.study_key} 第 {run.n} 次迭代 · {run.strategy} · {run.label}",
        f"{PERIOD}：{span(run.start, run.end)}（{shares(r.strategy.bars)} 個交易日）",
        f"假設：{run.hypothesis}",
        f"參數：{params_text(run.params)}",
    ]
    metrics = _table(
        ["指標", "策略", "買進並持有"],
        ["---", "---:", "---:"],
        [[m["label"], m["strategy"], m["bh"]] for m in metric_rows(r)],
    )
    trades = _table(
        ["交易統計", "策略"],
        ["---", "---:"],
        [[t["label"], t["value"]] for t in trade_rows(r)],
    )
    return "\n\n".join(
        [
            "\n".join(head),
            metrics,
            trades,
            regimes_markdown(run),
            f"檢視器：{viewer_url(run.id, port)}",
        ]
    )


def drawdowns_markdown(drawdowns: list[Drawdown]) -> str:
    if not drawdowns:
        return "（無回撤）"
    return _table(
        ["高點", "低點", "回撤幅度", "回復日", "交易日"],
        ["---", "---", "---:", "---", "---:"],
        [
            [d["peak"], d["trough"], d["depth"], d["recovery"], d["bars"]]
            for d in drawdown_rows(drawdowns)
        ],
    )


def fills_markdown(run) -> str:
    rows = fill_rows(run)
    if not rows:
        return "（無成交）"
    return _table(
        ["日期", "方向", "價格", "股數", "成交金額", "手續費", "證交稅"],
        ["---", "---", "---:", "---:", "---:", "---:", "---:"],
        [
            [f["date"], f["side"], f["price"], f["shares"], f["gross"]]
            + [f["commission"], f["tax"]]
            for f in rows
        ],
    )


def round_trips_markdown(run) -> str:
    rows = trip_rows(run)
    if not rows:
        return "（無已平倉交易）"
    return _table(
        ["進場", "出場", "持有交易日", "已實現損益"],
        ["---", "---", "---:", "---:"],
        [[t["entry"], t["exit"], t["held"], t["pnl"]] for t in rows],
    )


def run_detail(run, port: int) -> str:
    """get_run without the source snapshot; also the corpus finalize_study checks against."""
    r = run.report
    return "\n\n".join(
        [
            run_text(run, port),
            "最深回撤\n" + drawdowns_markdown(r.drawdowns),
            "成交明細\n" + fills_markdown(run),
            "已平倉交易\n" + round_trips_markdown(run),
            f"資料指紋：{run.data_sha}\n策略原始碼 sha256：{run.source_sha}",
        ]
    )


def runs_markdown(runs, studies: dict) -> str:
    """Backtests grouped by study, studies in order of their first backtest."""
    if not runs:
        return "（尚無回測紀錄）"
    groups: dict[str, list] = {}
    for run in runs:
        groups.setdefault(run.study_key, []).append(run)
    out = []
    for key, rs in groups.items():
        first, study = rs[0], studies.get(key)
        final = study.final_run_id if study else None
        title = f"研究 {key} · {first.label} · {first.strategy} · {PERIOD} {span(first.start, first.end)}"
        if final:
            title += f" · 定稿：回測 #{final}"
        rows = []
        for r in rs:
            rep = r.report
            rows.append(
                [
                    str(r.id),
                    str(r.n),
                    r.created_at,
                    pct(rep.strategy.ret),
                    pct(rep.bh.ret),
                    pct(rep.strategy.mdd),
                    r.hypothesis + (" （定稿）" if r.id == final else ""),
                ]
            )
        out.append(
            title
            + "\n"
            + _table(
                [
                    "#",
                    "迭代",
                    "時間",
                    "報酬率",
                    "買進並持有",
                    "最大回撤",
                    "假設",
                ],
                ["---:", "---:", "---", "---:", "---:", "---:", "---"],
                rows,
            )
        )
    return "\n\n".join(out)


# Numbers in prose: signed, thousands separators, decimals, optional percent.
NUMBER = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%?")
# A calendar year in prose ("2022 年") names a period, not a computed result.
YEAR = re.compile(r"(?<![\d.,+-])\d{4}(?=\s*年)")


def unverified_numbers(text: str, corpus: str) -> list[str]:
    """Numbers in text found nowhere in corpus, verbatim or without a leading +.

    Single-digit bare numbers and calendar years followed by 年 are ignored."""
    out = []
    for n in NUMBER.findall(YEAR.sub("", text)):
        bare = n.lstrip("+")
        if n not in corpus and bare not in corpus and len(bare.strip("%")) > 1:
            out.append(n)
    return out
