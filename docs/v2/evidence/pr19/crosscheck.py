"""Recompute the new per-period metrics with pandas, independently of trader.profit.

    uv run python docs/v2/evidence/pr19/crosscheck.py
"""

import math

import numpy as np
import pandas as pd

from trader import data, profit, regime, ta
from trader.engine import buy_and_hold, fees_for, simulate

bars = data.load_bars("2330.TW", "2023-01-01", "2025-12-31")
k = int(np.searchsorted(bars.index, pd.Timestamp("2025-01-01")))


def decide(h, _p):
    return 1.0 if ta.sma(h.close, 20).iloc[-1] > ta.sma(h.close, 60).iloc[-1] else 0.0


fees, cash = fees_for("2330.TW"), 1_000_000
dev, dev_bh = simulate(bars.iloc[:k], decide, fees, cash), buy_and_hold(bars.iloc[:k], fees, cash)
exe, exe_bh = simulate(bars, decide, fees, cash, start=k), buy_and_hold(bars, fees, cash, start=k)
rep = profit.study_report(dev, dev_bh, exe, exe_bh)


def independent(led):
    e = pd.Series([led.initial_cash] + led.equity)
    r = e.pct_change().dropna()
    mdd = (e / e.cummax() - 1).min()
    ret = e.iloc[-1] / led.initial_cash - 1
    days = (pd.Timestamp(led.dates[-1]) - pd.Timestamp(led.dates[0])).days
    ann = (1 + ret) ** (365.25 / days) - 1
    sd = r.std(ddof=1)
    return {"ret": ret, "annualized": ann, "mdd": mdd, "volatility": sd * math.sqrt(252),
            "sharpe": r.mean() / sd * math.sqrt(252), "calmar": ann / abs(mdd)}


worst = 0.0
for name, led, m in [("開發期間 策略", dev, rep.dev.strategy), ("開發期間 買進並持有", dev_bh, rep.dev.bh),
                     ("執行期間 策略", exe, rep.exec.strategy), ("執行期間 買進並持有", exe_bh, rep.exec.bh)]:
    ind = independent(led)
    diff = max(abs(ind[key] - getattr(m, key)) for key in ind)
    worst = max(worst, diff)
    print(f"{name}: {m.start}~{m.end} {m.bars} bars ret={m.ret:+.4%} ann={m.annualized:+.4%} "
          f"mdd={m.mdd:.4%} vol={m.volatility:.4%} sharpe={m.sharpe:.4f} calmar={m.calmar:.4f} max|diff|={diff:.1e}")
print(f"執行期間第一筆成交 {exe.fills[0].date}，紀錄起點 {exe.dates[0]}，長度 {len(exe.dates)} = {len(bars) - k}")
print(f"執行期間買進並持有於 {exe_bh.fills[0].date} 以開盤價 {exe_bh.fills[0].price} 買進（當日開盤 {bars.open.iloc[k]}）")
print("盤勢分段：" + "、".join(f"{bars.index[g.start].date()} {g.kind}" for g in regime.segment(bars.close.tolist())))
assert worst < 1e-12, worst
print("ALL METRICS MATCH")
