import math

import numpy as np
import pytest
from bars import random_bars

from trader.engine import NO_FEES, TW_STOCK_FEES, Ledger, RoundTrip, buy_and_hold, simulate
from trader.profit import (
    Drawdown,
    daily_returns,
    drawdown_curve,
    drawdowns,
    metrics,
    period,
    regime_table,
    study_report,
    trades,
)
from trader.regime import Regime


def ledger(equity, initial=100.0, dates=None, shares=None, trips=()):
    dates = dates or [f"2025-01-{i + 1:02d}" for i in range(len(equity))]
    return Ledger(
        initial_cash=initial,
        dates=list(dates),
        cash=list(equity),
        shares=list(shares or [0] * len(equity)),
        equity=list(equity),
        round_trips=list(trips),
    )


GOLDEN_DATES = ["2025-01-01", "2025-04-01", "2025-07-01", "2026-01-01"]  # 365 calendar days


def test_metrics_golden():
    # Daily returns vs 100 cash: 110/100, 99/110, 108.9/99, 130.68/108.9 -> 0.1, -0.1, 0.1, 0.2
    m = metrics(ledger([110, 99, 108.9, 130.68], dates=GOLDEN_DATES))
    assert (m.start, m.end, m.bars) == ("2025-01-01", "2026-01-01", 4)
    assert m.ret == pytest.approx(0.3068, abs=1e-12)
    assert m.final_equity == 130.68
    # (1.3068)^(365.25 / 365) - 1 = 0.306889...; catches 365 instead of 365.25
    assert m.annualized == pytest.approx(1.3068 ** (365.25 / 365) - 1, abs=1e-12)
    assert m.annualized - 0.3068 > 1e-4
    # Peak 110 on 01-01, trough 99 on 04-01 (108.9 is still below), recovered on 2026-01-01
    assert m.mdd == pytest.approx(-0.1, abs=1e-12)
    assert (m.mdd_peak, m.mdd_trough, m.mdd_recovery_bars) == ("2025-01-01", "2025-04-01", 3)
    # mean 0.075; squared deviations .000625 + .030625 + .000625 + .015625 = .0475
    # sample variance (ddof=1) = .0475 / 3; catches ddof=0 (/4) and 365 instead of 252
    sd = math.sqrt(0.0475 / 3)
    assert m.volatility == pytest.approx(sd * math.sqrt(252), abs=1e-12)
    assert m.sharpe == pytest.approx(0.075 / sd * math.sqrt(252), abs=1e-12)
    assert m.calmar == pytest.approx(m.annualized / 0.1, abs=1e-9)


def test_metrics_flat_equity():
    m = metrics(ledger([100, 100, 100]))
    assert m.ret == 0 and m.mdd == 0.0 and m.volatility == 0.0
    assert m.sharpe is None and m.calmar is None
    assert m.mdd_peak is None and m.mdd_trough is None and m.mdd_recovery_bars is None


def test_metrics_no_drawdown():
    m = metrics(ledger([101, 102]))
    assert m.mdd == 0.0 and m.calmar is None and m.sharpe is not None


def test_metrics_single_bar():
    m = metrics(ledger([105]))
    assert m.ret == pytest.approx(0.05) and m.bars == 1
    assert m.annualized is None and m.volatility is None and m.sharpe is None
    assert m.calmar is None


def test_drawdowns_from_initial_cash_and_unrecovered():
    d = [f"2025-01-0{i}" for i in range(1, 6)]
    eps = drawdowns(ledger([90, 95, 100, 80, 85], dates=d))
    assert eps == [
        # peak is the initial cash, dated at the first date; recovered at index 2 -> 2 - 0 bars
        Drawdown(peak=d[0], trough=d[0], depth=pytest.approx(-0.1), recovery=d[2], bars=2),
        # peak 100 at index 2, trough 80, never back -> 4 - 2 bars to the last bar
        Drawdown(peak=d[2], trough=d[3], depth=pytest.approx(-0.2), recovery=None, bars=2),
    ]
    m = metrics(ledger([90, 95, 100, 80, 85], dates=d))
    assert (m.mdd, m.mdd_peak, m.mdd_trough) == (pytest.approx(-0.2), d[2], d[3])
    assert m.mdd_recovery_bars is None  # deepest episode not recovered


def test_period_keeps_five_deepest():
    equity = [99, 100, 97, 100, 95, 100, 98, 100, 90, 100, 96, 100, 93]
    led = ledger(equity)
    assert [round(e.depth, 6) for e in drawdowns(led)] == [
        -0.01,
        -0.03,
        -0.05,
        -0.02,
        -0.1,
        -0.04,
        -0.07,
    ]
    p = period(led, ledger([100] * len(equity)))
    assert [round(e.depth, 6) for e in p.drawdowns] == [-0.1, -0.07, -0.05, -0.04, -0.03]
    assert p.drawdowns[1].recovery is None
    assert p.bh.ret == 0 and p.strategy.mdd == pytest.approx(-0.1)


def trip(a, b, pnl):
    return RoundTrip(a, b, "", "", pnl)


def test_trades_golden():
    trips = [
        trip(0, 3, 300),
        trip(4, 6, -100),
        trip(7, 8, 60),
        trip(9, 13, -200),
        trip(14, 15, 0),  # zero pnl: not a win, not a loss
        trip(16, 20, 30),
    ]
    t = trades(ledger([100] * 10, shares=[0, 5, 5, 0, 0, 0, 2, 2, 0, 0], trips=trips))
    assert t.count == 6
    assert t.win_rate == pytest.approx(3 / 6)
    # mean win (300 + 60 + 30) / 3 = 130, mean loss (-100 - 200) / 2 = -150 -> 130 / 150
    assert t.payoff == pytest.approx(130 / 150)
    # 390 / 300; differs from payoff, so swapping the two definitions fails
    assert t.profit_factor == pytest.approx(1.3)
    assert (t.best, t.worst) == (300, -200)
    assert t.avg_holding_bars == pytest.approx((3 + 2 + 1 + 4 + 1 + 4) / 6)
    assert t.exposure == pytest.approx(0.4)


def test_trades_none_cases():
    none = trades(ledger([100] * 4, shares=[0, 1, 1, 1]))
    assert none.count == 0 and none.exposure == 0.75
    assert none.win_rate is none.payoff is none.profit_factor is None
    assert none.best is none.worst is none.avg_holding_bars is None
    no_loss = trades(ledger([100], trips=[trip(0, 1, 10), trip(1, 2, 20)]))
    assert no_loss.win_rate == 1.0 and no_loss.payoff is None and no_loss.profit_factor is None
    no_win = trades(ledger([100], trips=[trip(0, 1, -10)]))
    assert no_win.win_rate == 0.0 and no_win.payoff is None and no_win.profit_factor == 0.0


def test_open_position_is_not_a_trade():
    bars = random_bars(n=30)
    t = trades(simulate(bars, lambda _h, _p: 1.0, NO_FEES, 1e5))
    assert t.count == 0 and t.exposure == pytest.approx(29 / 30)  # bought at bar 1's open


def year(ret):
    return ledger([100 * (1 + ret)], dates=["2025-01-01"]), ledger(
        [100, 100 * (1 + ret)], dates=["2025-01-01", "2026-01-01"]
    )


def test_overfit():
    _, dev = year(0.30)
    _, good = year(0.20)  # annualized gap ~0.10
    _, bad = year(0.10)  # gap ~0.20
    single, _ = year(0.10)  # annualized None
    assert not study_report(dev, dev, good, good).overfit
    assert study_report(dev, dev, bad, bad).overfit
    assert not study_report(dev, dev, single, single).overfit
    assert study_report(dev, dev, bad, bad).exec.strategy.ret == pytest.approx(0.10)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_metrics_invariants(seed):
    bars = random_bars(seed=seed)
    rng = np.random.default_rng(seed)
    led = simulate(bars, lambda _h, _p: float(rng.choice([0, 1])), TW_STOCK_FEES, 1e6)
    m = metrics(led)
    assert math.prod(1 + r for r in daily_returns(led)) - 1 == pytest.approx(m.ret, rel=1e-9)
    assert m.mdd == pytest.approx(
        min(0.0, *drawdown_curve(led.initial_cash, led.equity)), abs=1e-12
    )
    assert trades(led).count == len(led.round_trips)
    bh = metrics(buy_and_hold(bars, TW_STOCK_FEES, 1e6))
    assert bh.mdd <= 0 and bh.volatility > 0


def test_regime_table_golden():
    dates = ["d0", "d1", "d2", "d3", "d4"]
    close = [100, 110, 99, 120, 132]
    regimes = [Regime(0, 2, "range"), Regime(2, 4, "up")]
    # bar 0's return and position belong to no regime's start+1..end span
    returns = [0.5, 0.1, -0.2, 0.0, 0.2]
    held = [True, True, False, True, True]
    a, b = regime_table(dates, close, regimes, returns, held)
    assert (a.start, a.end, a.kind, a.bars) == ("d0", "d2", "range", 2)
    assert a.price_change == pytest.approx(-0.01)  # 99 / 100 - 1
    assert a.strategy == pytest.approx(1.1 * 0.8 - 1)  # -0.12 compounded, not the sum -0.1
    assert a.exposure == 0.5
    assert b.price_change == pytest.approx(132 / 99 - 1)
    assert b.strategy == pytest.approx(0.2) and b.exposure == 1.0


def test_drawdown_curve_starts_at_initial_cash():
    assert drawdown_curve(100, [90, 110, 99, 120]) == pytest.approx([-0.1, 0, -0.1, 0])
