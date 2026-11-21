"""Build mock-data.js for the dashboard design options from real backtests.

    uv run python docs/v2/mockups/v3/gen_mock.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from trader import data, profit, regime, ta
from trader.engine import buy_and_hold, fees_for, simulate

OUT = Path(__file__).with_name("mock-data.js")
CASH = 1_000_000


def pct(x, signed=True):
    return "—" if x is None else (f"{x * 100:+,.2f}%" if signed else f"{x * 100:,.2f}%")


def num(x, d=2):
    return "—" if x is None else f"{x:,.{d}f}"


def money(x, signed=False):
    return "—" if x is None else (f"{x:+,.0f}" if signed else f"{x:,.0f}")


def ma(fast, slow):
    return lambda h, _p: 1.0 if ta.sma(h.close, fast).iloc[-1] > ta.sma(h.close, slow).iloc[-1] else 0.0


def backtest(symbol, fast, slow, dev=("2023-01-01", "2024-12-31"), exe=("2025-01-01", "2025-12-31")):
    bars = data.load_bars(symbol, dev[0], exe[1])
    k = int(np.searchsorted(bars.index, pd.Timestamp(exe[0])))
    f = fees_for(symbol)
    d, dbh = simulate(bars.iloc[:k], ma(fast, slow), f, CASH), buy_and_hold(bars.iloc[:k], f, CASH)
    e, ebh = simulate(bars, ma(fast, slow), f, CASH, start=k), buy_and_hold(bars, f, CASH, start=k)
    rep = profit.study_report(d, dbh, e, ebh)
    close = bars.close.tolist()
    dates = [x.strftime("%Y-%m-%d") for x in bars.index]
    regs = regime.segment(close)
    rets = profit.daily_returns(d) + profit.daily_returns(e)
    pos = [s > 0 for s in d.shares] + [s > 0 for s in e.shares]
    rows = profit.regime_table(dates, close, regs, rets, pos)
    return bars, dates, k, d, dbh, e, ebh, rep, regs, rows


def metric_rows(rep):
    def per(m):
        return {
            "總報酬率": pct(m.ret), "年化報酬率": pct(m.annualized), "期末權益": money(m.final_equity),
            "最大回撤": pct(m.mdd), "最大回撤期間": f"{m.mdd_peak} 至 {m.mdd_trough}" if m.mdd_peak else "—",
            "回撤回復交易日": "尚未回復" if m.mdd and m.mdd_recovery_bars is None else num(m.mdd_recovery_bars, 0),
            "年化波動率": pct(m.volatility, False), "Sharpe 比率（無風險利率 0）": num(m.sharpe), "Calmar 比率": num(m.calmar),
        }
    a, b, c, d = per(rep.dev.strategy), per(rep.exec.strategy), per(rep.dev.bh), per(rep.exec.bh)
    return [{"label": k, "dev": a[k], "exec": b[k], "bh_dev": c[k], "bh_exec": d[k]} for k in a]


def trade_rows(rep):
    def per(t):
        return {
            "交易次數": num(t.count, 0), "勝率": pct(t.win_rate, False), "平均獲利／平均虧損": num(t.payoff),
            "獲利因子": num(t.profit_factor), "單筆最大獲利": money(t.best, True), "單筆最大虧損": money(t.worst, True),
            "平均持有交易日": num(t.avg_holding_bars, 1), "持倉時間比例": pct(t.exposure, False),
        }
    a, b = per(rep.dev.trades), per(rep.exec.trades)
    return [{"label": k, "dev": a[k], "exec": b[k]} for k in a]


LABEL = {"up": "上漲段", "down": "下跌段", "range": "盤整段"}
runs, iterations = [], []
for n, (fast, slow, hyp) in enumerate([
    (20, 60, "本次回測驗證 20 日與 60 日均線之多頭排列能否捕捉台積電之中期趨勢，預期最大回撤低於買進並持有基準。"),
    (10, 30, "第一次回測之策略開發期間報酬率落後於買進並持有基準，本次縮短均線期間至 10 日與 30 日，旨在提前進場時點。"),
    (20, 120, "第二次回測顯示縮短均線期間未能改善績效，本次將長期均線延長為 120 日，旨在減少回檔期間的出場次數。"),
], start=1):
    out = backtest("2330.TW", fast, slow)
    rep = out[7]
    runs.append(out)
    iterations.append({
        "id": n, "n": n, "hypothesis": hyp, "params": f"fast={fast}, slow={slow}",
        "diff": "首次回測" if n == 1 else f"fast 20→{fast}、slow 60→{slow}" if n == 2 else f"fast 10→{fast}、slow 30→{slow}",
        "dev_ret": pct(rep.dev.strategy.ret), "dev_ann": pct(rep.dev.strategy.annualized),
        "exec_ret": pct(rep.exec.strategy.ret), "exec_ann": pct(rep.exec.strategy.annualized),
        "bh_exec_ret": pct(rep.exec.bh.ret), "exec_mdd": pct(rep.exec.strategy.mdd),
        "exec_sharpe": num(rep.exec.strategy.sharpe), "exec_trades": num(rep.exec.trades.count, 0),
        "overfit": rep.overfit, "final": n == 1,
    })

bars, dates, k, d, dbh, e, ebh, rep, regs, rows = runs[0]
it = iterations[0]
dd = lambda led: (lambda eq: [round((v / m - 1) * 100, 2) for v, m in zip(eq, np.maximum.accumulate([led.initial_cash] + eq)[1:])])(led.equity)
regime_rows = [{"start": r.start, "end": r.end, "kind": r.kind, "label": LABEL[r.kind], "bars": num(r.bars, 0),
                "price_change": pct(r.price_change), "strategy": pct(r.strategy), "exposure": pct(r.exposure, False)} for r in rows]
mr = {m["label"]: m for m in metric_rows(rep)}
tr = {m["label"]: m for m in trade_rows(rep)}
up = [x for x in regime_rows if x["kind"] == "up"]
down = [x for x in regime_rows if x["kind"] == "down"]
conclusion = f"""**策略邏輯與定稿參數**：20 日均線高於 60 日均線時全額持有，否則空手，僅做多。參數為 fast=20、slow=60。

**兩段期間的績效**：策略開發期間的報酬率為 {it['dev_ret']}，年化報酬率 {it['dev_ann']}；策略執行期間的報酬率為 {it['exec_ret']}，年化報酬率 {it['exec_ann']}。策略執行期間的最大回撤為 {mr['最大回撤']['exec']}，Sharpe 比率為 {mr['Sharpe 比率（無風險利率 0）']['exec']}。兩段期間的年化報酬率差距未達過度擬合警示門檻。

**與買進並持有基準比較**：策略開發期間落後於基準的 {mr['總報酬率']['bh_dev']}；策略執行期間的報酬率高於基準的 {mr['總報酬率']['bh_exec']}，最大回撤 {mr['最大回撤']['exec']} 亦低於基準的 {mr['最大回撤']['bh_exec']}。

**盤勢分析**：在 {down[-1]['start']} 至 {down[-1]['end']} 的下跌段，股價下跌 {down[-1]['price_change']}，策略報酬率為 {down[-1]['strategy']}，持倉時間比例 {down[-1]['exposure']}，顯示均線條件有效降低下跌段的損失。在 {up[0]['start']} 至 {up[0]['end']} 的上漲段，股價上漲 {up[0]['price_change']}，策略報酬率為 {up[0]['strategy']}，未能完整參與上漲。

**結論與適用情境**：本策略的主要作用是降低下跌段的回撤，適用於重視風險控制的投資人。策略執行期間僅有 {tr['交易次數']['exec']} 筆已平倉交易，統計可信度有限。"""

mock = {
    "tree": [
        {"symbol": "2330.TW", "label": "2330.TW 台積電", "studies": [
            {"key": "a1", "strategy": "ma_trend", "dev": "2023-01-01 至 2024-12-31", "exec": "2025-01-01 至 2025-12-31",
             "final_run_id": 1, "runs": [{"id": x["id"], "n": x["n"], "hypothesis": x["hypothesis"], "dev_ret": x["dev_ret"], "exec_ret": x["exec_ret"], "overfit": x["overfit"], "final": x["final"]} for x in iterations]},
            {"key": "a2", "strategy": "rsi_reversal", "dev": "2022-01-01 至 2024-06-30", "exec": "2024-07-01 至 2025-12-31",
             "final_run_id": None, "runs": [{"id": 9, "n": 1, "hypothesis": "本次回測驗證 RSI 低於 30 進場、高於 70 出場之反轉策略。", "dev_ret": "+12.41%", "exec_ret": "-3.27%", "overfit": True, "final": False}]},
        ]},
        {"symbol": "0050.TW", "label": "0050.TW 元大台灣50", "studies": [
            {"key": "b1", "strategy": "ma_trend", "dev": "2023-01-01 至 2024-12-31", "exec": "2025-01-01 至 2025-12-31",
             "final_run_id": None, "runs": [{"id": 12, "n": 1, "hypothesis": "本次回測將台積電定稿參數套用至 0050，驗證策略於大盤型 ETF 之適用性。", "dev_ret": "+38.20%", "exec_ret": "+21.05%", "overfit": False, "final": False}]},
        ]},
    ],
    "study": {"key": "a1", "label": "2330.TW 台積電", "strategy": "ma_trend", "dev": "2023-01-01 至 2024-12-31", "exec": "2025-01-01 至 2025-12-31",
              "question": iterations[0]["hypothesis"], "conclusion": conclusion, "finalized_at": "2026-11-21 16:20", "final_run_id": 1, "iterations": iterations},
    "run": {
        "id": 1, "n": 1, "hypothesis": it["hypothesis"], "params": it["params"], "diff": it["diff"], "created_at": "2026-11-21 16:02",
        "metrics": metric_rows(rep), "trade_metrics": trade_rows(rep), "overfit": rep.overfit,
        "drawdowns": {p: [{"peak": x.peak, "trough": x.trough, "depth": pct(x.depth), "recovery": x.recovery or "尚未回復", "bars": num(x.bars, 0)} for x in getattr(rep, p).drawdowns] for p in ("dev", "exec")},
        "regimes": regime_rows,
        "regime_rules": "盤勢分段依固定規則：價格在 12% 區間內來回達 60 個交易日以上為盤整段；其餘期間以反轉 10% 判斷轉折，漲幅達 15% 為上漲段、跌幅達 15% 為下跌段，其餘為盤整段。",
        "chart": {
            "dates": dates, **{c: [round(v, 2) for v in bars[c].tolist()] for c in ("open", "high", "low", "close")}, "volume": [int(v) for v in bars.volume.tolist()],
            "dev_dates": d.dates, "exec_dates": e.dates,
            "pnl_dev": [round(v - CASH) for v in d.equity], "pnl_exec": [round(v - CASH) for v in e.equity],
            "bh_pnl_dev": [round(v - CASH) for v in dbh.equity], "bh_pnl_exec": [round(v - CASH) for v in ebh.equity],
            "dd_dev": dd(d), "dd_exec": dd(e),
            "markers": [{"date": f.date, "side": f.side} for f in d.fills + e.fills],
            "regimes": [{"start": dates[g.start], "end": dates[g.end], "kind": g.kind} for g in regs],
        },
    },
}
OUT.write_text("window.MOCK = " + json.dumps(mock, ensure_ascii=False) + ";\n", encoding="utf-8")
print("wrote", OUT, "iterations:", [(x["dev_ret"], x["exec_ret"]) for x in iterations])
print(conclusion)
