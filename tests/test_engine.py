import itertools

import numpy as np
import pytest
from bars import make_bars, random_bars

from trader.engine import (
    NO_FEES,
    TW_ETF_FEES,
    TW_STOCK_FEES,
    StrategyError,
    buy_and_hold,
    fees_for,
    simulate,
)
from trader.profit import report


def scripted(*targets):
    it = iter(targets)
    return lambda _hist, _pos: next(it)


# Hand-computed scenario. Decisions at closes t0..t4: 1, 1, 1, 0, 0. TW stock fees, 100,000 cash.
GOLDEN_OPENS = [100, 101, 103, 105, 102, 107]
GOLDEN_CLOSES = [100, 102, 104, 103, 106, 108]


def golden():
    bars = make_bars(GOLDEN_OPENS, GOLDEN_CLOSES)
    led = simulate(bars, scripted(1.0, 1.0, 1.0, 0.0, 0.0), TW_STOCK_FEES, 100_000)
    return bars, led


def test_golden_fills():
    _, led = golden()
    buy, sell = led.fills
    # t1 open 101: floor(100000 / (101 * 1.001425)) = 988; 989 * 101 + 142 = 100,031 > cash
    assert (buy.date, buy.side, buy.price, buy.shares) == ("2025-01-02", "BUY", 101.0, 988)
    assert buy.gross == 99_788 and buy.commission == 142  # floor(142.1979)
    # t4 open 102: gross 100,776; commission floor(143.6058) = 143; tax floor(302.328) = 302
    assert (sell.date, sell.side, sell.price, sell.shares) == ("2025-01-07", "SELL", 102.0, 988)
    assert sell.gross == 100_776 and sell.commission == 143 and sell.tax == 302


def test_golden_ledger():
    _, led = golden()
    assert led.cash == [100_000, 70, 70, 70, 100_401, 100_401]
    assert led.shares == [0, 988, 988, 988, 0, 0]
    # 70 + 988 * close
    assert led.equity == [100_000, 100_846, 102_822, 101_834, 100_401, 100_401]
    assert led.realized_pnl == 401  # 100,331 net proceeds - 99,930 cost
    assert len(led.round_trips) == 1 and led.round_trips[0].pnl == 401
    assert led.round_trips[0].holding_bars == 3


def test_golden_buy_and_hold():
    bars, _ = golden()
    bh = buy_and_hold(bars, TW_STOCK_FEES, 100_000)
    # t0 open 100: 998 shares, 99,800 + 142 commission, cash 58
    assert bh.fills[0].shares == 998 and bh.fills[0].commission == 142
    assert bh.equity == [99_858, 101_854, 103_850, 102_852, 105_846, 107_842]


def test_golden_report():
    bars, led = golden()
    r = report(led, buy_and_hold(bars, TW_STOCK_FEES, 100_000))
    assert r.split == 4  # floor(0.7 * 6)
    assert r.total.ret == pytest.approx(100_401 / 100_000 - 1, abs=1e-12)
    assert r.in_sample.ret == pytest.approx(101_834 / 100_000 - 1, abs=1e-12)
    assert r.out_of_sample.ret == pytest.approx(100_401 / 101_834 - 1, abs=1e-12)
    assert r.in_sample.mdd == pytest.approx(101_834 / 102_822 - 1, abs=1e-12)
    assert r.out_of_sample.mdd == pytest.approx(100_401 / 101_834 - 1, abs=1e-12)
    assert r.total.mdd == pytest.approx(100_401 / 102_822 - 1, abs=1e-12)
    assert r.bh_total.ret == pytest.approx(0.07842, abs=1e-12)
    assert r.bh_in_sample.ret == pytest.approx(0.02852, abs=1e-12)
    assert r.bh_out_of_sample.ret == pytest.approx(107_842 / 102_852 - 1, abs=1e-12)
    assert r.trades == 1 and r.win_rate == 1.0
    assert r.final_equity == 100_401 and r.unrealized_pnl == 0


@pytest.mark.parametrize(
    "fees,gross,commission,tax",
    [
        (TW_STOCK_FEES, 10_000, 20, 30),  # 14.25 -> minimum 20
        (TW_STOCK_FEES, 998_439.6, 1422, 2995),  # floor(1422.776), floor(2995.3188)
        (TW_ETF_FEES, 998_439.6, 1422, 998),  # ETF tax 0.1%
        (
            TW_STOCK_FEES,
            1_000_000 / 1.425 * 1.425,
            1425,
            3000,
        ),  # exact integers survive float noise
        (NO_FEES, 998_439.6, 0, 0),
    ],
)
def test_fee_rules(fees, gross, commission, tax):
    assert fees.commission(gross) == commission
    assert fees.tax(gross) == tax


def test_fee_schedule_by_symbol():
    assert fees_for("2330.TW") is TW_STOCK_FEES
    assert fees_for("6488.TWO") is TW_STOCK_FEES
    assert fees_for("0050.TW") is TW_ETF_FEES
    assert fees_for("00878.tw") is TW_ETF_FEES
    assert fees_for("AAPL") is NO_FEES


def replay(bars, led):
    """Rebuild cash and shares from fills and dividends alone."""
    cash, shares, fills = led.initial_cash, 0, iter(led.fills)
    nxt = next(fills, None)
    out_cash, out_shares = [], []
    for t, div in enumerate(bars["dividend"]):
        cash += shares * div
        while nxt is not None and nxt.bar == t:
            cash += nxt.cash_delta
            shares += nxt.shares if nxt.side == "BUY" else -nxt.shares
            nxt = next(fills, None)
        out_cash.append(cash)
        out_shares.append(shares)
    return out_cash, out_shares


WEIGHT_STRATEGIES = {
    "all-in/out": lambda rng: rng.choice([0.0, 1.0]),
    "fractional": lambda rng: rng.choice([0.0, 0.25, 0.5, 0.8, 1.0]),
    "sticky": lambda rng: rng.choice([0.6, 0.6, 0.6, 0.0]),
}


@pytest.mark.parametrize(
    "strategy,seed,fees",
    list(itertools.product(WEIGHT_STRATEGIES, [1, 2, 3], [TW_STOCK_FEES, NO_FEES])),
)
def test_ledger_invariants(strategy, seed, fees):
    bars = random_bars(seed=seed)
    rng = np.random.default_rng(seed)
    pick = WEIGHT_STRATEGIES[strategy]
    led = simulate(bars, lambda _h, _p: float(pick(rng)), fees, 1_000_000)

    cash, shares = replay(bars, led)
    assert led.shares == shares
    assert led.cash == pytest.approx(cash, abs=1e-6)
    for t, close in enumerate(bars["close"]):
        assert led.equity[t] == pytest.approx(cash[t] + shares[t] * close, abs=1e-6)
        assert led.cash[t] >= -1e-9, "cash never goes negative"
    assert led.equity[-1] - led.initial_cash == pytest.approx(
        led.realized_pnl + led.unrealized_pnl, abs=1e-6
    )
    r = report(led, buy_and_hold(bars, fees, 1_000_000))
    assert (1 + r.in_sample.ret) * (1 + r.out_of_sample.ret) == pytest.approx(
        1 + r.total.ret, rel=1e-12
    )
    for f in led.fills:
        assert f.commission == fees.commission(f.gross)
        assert f.tax == (fees.tax(f.gross) if f.side == "SELL" else 0)


def test_strategy_sees_only_the_past_and_fills_next_open():
    bars = random_bars(n=40)
    seen = []

    def spy(hist, _pos):
        seen.append((len(hist), hist.index[-1]))
        hist.loc[:, "close"] = 0.0  # mutation must not leak into the engine
        return 1.0 if len(hist) == 10 else 0.0

    led = simulate(bars, spy, NO_FEES, 100_000)
    assert seen == [(t + 1, bars.index[t]) for t in range(len(bars) - 1)]
    buy = led.fills[0]
    assert buy.bar == 10 and buy.price == bars["open"].iloc[10]
    assert led.equity[-1] > 0 and bars["close"].iloc[5] != 0


def test_peeking_is_impossible():
    """A strategy that wants tomorrow's close can only ever get today's."""
    bars = random_bars(n=60)
    asked = []

    def oracle(hist, _pos):
        asked.append(hist["close"].iloc[-1])
        return 0.0

    simulate(bars, oracle, NO_FEES, 100_000)
    assert asked == bars["close"].iloc[:-1].tolist()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1.5, -0.1, None, "1", True])
def test_invalid_targets_raise(bad):
    with pytest.raises(StrategyError):
        simulate(random_bars(n=20), lambda _h, _p: bad, NO_FEES, 100_000)


def test_dividend_is_not_a_loss():
    # Ex-dividend on t2: price drops 100 -> 95 and holders receive 5 per share.
    bars = make_bars([100, 100, 95, 95], [100, 100, 95, 95], [0, 0, 5, 0])
    bh = buy_and_hold(bars, NO_FEES, 100_000)
    assert bh.equity == [100_000, 100_000, 100_000, 100_000]
    assert bh.dividends == [0, 0, 5_000, 0]
    # Back-adjusted closes: factor (100 - 5) / 100 before the ex-date gives a flat 95 series.
    adjusted = [95, 95, 95, 95]
    assert bh.equity[-1] / bh.initial_cash - 1 == adjusted[-1] / adjusted[0] - 1


def test_deterministic():
    bars = random_bars()

    def run():
        rng = np.random.default_rng(9)
        return simulate(bars, lambda _h, _p: float(rng.choice([0, 1])), TW_STOCK_FEES, 1e6)

    a, b = run(), run()
    assert a.equity == b.equity and a.fills == b.fills


def test_buys_every_affordable_share():
    # 100 shares at 1000 cost 100,000 + floor(142.5) = 100,142: exactly affordable.
    bars = make_bars([1000] * 4, [1000] * 4)
    led = simulate(bars, lambda _h, _p: 1.0, TW_STOCK_FEES, 100_142, initial_target=1.0)
    assert led.fills[0].shares == 100 and led.cash[0] == 0


def test_fractional_target_survives_float_noise():
    # 0.29 * 100 / 1 is 28.999999999999996 in floating point; the target is 29 shares.
    bars = make_bars([1] * 4, [1] * 4)
    led = simulate(bars, lambda _h, _p: 0.29, NO_FEES, 100, initial_target=0.29)
    assert led.fills[0].shares == 29
