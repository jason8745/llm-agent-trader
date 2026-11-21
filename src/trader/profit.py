"""Performance metrics. Every number the harness reports is computed here.

A backtest has a development period and an execution period, each its own ledger that
starts flat with the initial cash; returns are measured against that cash.
"""

import datetime as dt
import math
import statistics
from dataclasses import dataclass

from trader.engine import Ledger
from trader.regime import Regime

OVERFIT_GAP = 0.15
DAYS_PER_YEAR = 365.25
TRADING_DAYS_PER_YEAR = 252
TOP_DRAWDOWNS = 5


def annualize(ret: float, start: str, end: str) -> float | None:
    days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    if days <= 0 or ret <= -1:
        return None
    return (1 + ret) ** (DAYS_PER_YEAR / days) - 1


@dataclass(frozen=True)
class Drawdown:
    peak: str
    trough: str
    depth: float
    recovery: str | None
    bars: int


@dataclass(frozen=True)
class Metrics:
    start: str
    end: str
    bars: int
    ret: float
    annualized: float | None
    final_equity: float
    mdd: float
    mdd_peak: str | None
    mdd_trough: str | None
    mdd_recovery_bars: int | None
    volatility: float | None
    sharpe: float | None
    calmar: float | None


@dataclass(frozen=True)
class Trades:
    count: int
    win_rate: float | None
    payoff: float | None
    profit_factor: float | None
    best: float | None
    worst: float | None
    avg_holding_bars: float | None
    exposure: float


@dataclass(frozen=True)
class Period:
    strategy: Metrics
    trades: Trades
    bh: Metrics
    drawdowns: list[Drawdown]


@dataclass(frozen=True)
class StudyReport:
    dev: Period
    exec: Period

    @property
    def overfit(self) -> bool:
        a, b = self.dev.strategy.annualized, self.exec.strategy.annualized
        return a is not None and b is not None and a - b > OVERFIT_GAP


def daily_returns(led: Ledger) -> list[float]:
    """r_0 = E[0] / initial cash - 1, r_t = E[t] / E[t-1] - 1."""
    e = [led.initial_cash, *led.equity]
    return [e[t] / e[t - 1] - 1 for t in range(1, len(e))]


def drawdowns(led: Ledger) -> list[Drawdown]:
    """Every drawdown episode, chronological.

    The running peak starts at the initial cash at index -1, dated as the period's first
    date, and moves to any bar with equity >= peak (ties move it to the later bar). An
    episode starts at the first bar below the peak and ends at the first bar with equity
    >= that peak (recovery) or, unrecovered, at the last bar. bars counts trading days
    from max(peak index, 0) to the recovery index, or to the last bar if unrecovered.
    """
    e, d = led.equity, led.dates
    out: list[Drawdown] = []
    peak, peak_i, trough_i = led.initial_cash, -1, None
    for t, v in enumerate(e):
        if v >= peak:
            if trough_i is not None:
                out.append(_episode(d, peak, peak_i, e[trough_i], trough_i, t))
                trough_i = None
            peak, peak_i = v, t
        elif trough_i is None or v < e[trough_i]:
            trough_i = t
    if trough_i is not None:
        out.append(_episode(d, peak, peak_i, e[trough_i], trough_i, None))
    return out


def _episode(d, peak, peak_i, low, trough_i, recovery_i) -> Drawdown:
    end = recovery_i if recovery_i is not None else len(d) - 1
    return Drawdown(
        peak=d[max(peak_i, 0)],
        trough=d[trough_i],
        depth=low / peak - 1,
        recovery=d[recovery_i] if recovery_i is not None else None,
        bars=end - max(peak_i, 0),
    )


def drawdown_curve(initial_cash: float, equity: list[float]) -> list[float]:
    """Per-bar drawdown from the running peak, which starts at the initial cash."""
    peak, out = initial_cash, []
    for v in equity:
        peak = max(peak, v)
        out.append(v / peak - 1)
    return out


def chained_returns(initial_cash: float, dev: list[float], exe: list[float]) -> list[float]:
    """Cumulative return from the development start, one value per development and execution bar.

    The execution period restarts from the initial cash, so its curve is chained to the
    development end point: (1 + R_dev) * (E_t / initial cash) - 1. Inside the execution period
    the change relative to its start therefore equals the execution return exactly.
    """
    base = dev[-1] / initial_cash
    return [e / initial_cash - 1 for e in dev] + [base * e / initial_cash - 1 for e in exe]


def metrics(led: Ledger) -> Metrics:
    e, d = led.equity, led.dates
    ret = e[-1] / led.initial_cash - 1
    ann = annualize(ret, d[0], d[-1])
    worst = min(drawdowns(led), key=lambda x: x.depth, default=None)
    mdd = worst.depth if worst else 0.0
    r = daily_returns(led)
    sd = statistics.stdev(r) if len(r) >= 2 else None
    scale = math.sqrt(TRADING_DAYS_PER_YEAR)
    return Metrics(
        start=d[0],
        end=d[-1],
        bars=len(e),
        ret=ret,
        annualized=ann,
        final_equity=e[-1],
        mdd=mdd,
        mdd_peak=worst.peak if worst else None,
        mdd_trough=worst.trough if worst else None,
        mdd_recovery_bars=worst.bars if worst and worst.recovery else None,
        volatility=sd * scale if sd is not None else None,
        sharpe=statistics.fmean(r) / sd * scale if sd else None,
        calmar=ann / abs(mdd) if mdd and ann is not None else None,
    )


def trades(led: Ledger) -> Trades:
    """Round trips closed inside the ledger; a position still open at the end is not one."""
    pnl = [t.pnl for t in led.round_trips]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]  # a zero-pnl trade is neither a win nor a loss
    n = len(pnl)
    return Trades(
        count=n,
        win_rate=len(wins) / n if n else None,
        payoff=statistics.fmean(wins) / abs(statistics.fmean(losses)) if wins and losses else None,
        profit_factor=sum(wins) / abs(sum(losses)) if losses else None,
        best=max(pnl, default=None),
        worst=min(pnl, default=None),
        avg_holding_bars=(statistics.fmean(t.holding_bars for t in led.round_trips) if n else None),
        exposure=sum(s > 0 for s in led.shares) / len(led.shares),
    )


def period(led: Ledger, bh: Ledger) -> Period:
    deepest = sorted(drawdowns(led), key=lambda x: x.depth)[:TOP_DRAWDOWNS]
    return Period(strategy=metrics(led), trades=trades(led), bh=metrics(bh), drawdowns=deepest)


def study_report(dev: Ledger, dev_bh: Ledger, exe: Ledger, exe_bh: Ledger) -> StudyReport:
    return StudyReport(dev=period(dev, dev_bh), exec=period(exe, exe_bh))


@dataclass(frozen=True)
class RegimeRow:
    start: str
    end: str
    kind: str
    bars: int
    price_change: float
    strategy: float
    exposure: float


def regime_table(
    dates: list[str],
    close: list[float],
    regimes: list[Regime],
    strat_returns: list[float],
    in_position: list[bool],
) -> list[RegimeRow]:
    """Per-regime price change and strategy result over bars start+1..end.

    strat_returns and in_position are per-bar and aligned with dates.
    """
    rows = []
    for g in regimes:
        i, j = g.start, g.end
        rows.append(
            RegimeRow(
                start=dates[i],
                end=dates[j],
                kind=g.kind,
                bars=j - i,
                price_change=close[j] / close[i] - 1,
                strategy=math.prod(1 + r for r in strat_returns[i + 1 : j + 1]) - 1,
                exposure=sum(in_position[i + 1 : j + 1]) / (j - i),
            )
        )
    return rows
