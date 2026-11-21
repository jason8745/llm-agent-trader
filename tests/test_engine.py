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


def test_overfit_flag_compares_annualized_returns():
    from trader.profit import annualize

    # 2330.TW run: +63.64% over ~2 years in sample, +48.10% over ~10 months out of sample.
    is_ann = annualize(0.6364, "2023-01-03", "2025-02-14")
    oos_ann = annualize(0.4810, "2025-02-14", "2025-12-31")
    assert is_ann < oos_ann, "better annualized out of sample is not overfitting"
    assert annualize(0.21, "2024-01-01", "2025-01-01") == pytest.approx(0.21, abs=1e-3)
    assert annualize(0.1, "2025-01-01", "2025-01-01") is None


def test_overfit_flag_fires_when_out_of_sample_collapses():
    n = 300
    s = int(0.7 * n)
    closes = [100 * 1.002**t for t in range(s)] + [100 * 1.002 ** (s - 1)] * (n - s)
    bars = make_bars(closes, closes)
    r = report(simulate(bars, lambda _h, _p: 1.0, NO_FEES, 1e6), buy_and_hold(bars, NO_FEES, 1e6))
    assert r.out_of_sample.ret == pytest.approx(0, abs=0.01) and r.in_sample.ret > 0.3
    assert r.overfit


def test_peeking_strategy_cannot_profit():
    """The usual look-ahead bug, shift(-1), yields NaN on the engine's truncated history."""
    bars = random_bars(n=250, seed=4)

    def peek(hist, _pos):
        tomorrow = hist["close"].shift(-1).iloc[-1]
        return 1.0 if tomorrow > hist["close"].iloc[-1] else 0.0

    led = simulate(bars, peek, NO_FEES, 1e6)
    assert led.fills == [] and led.equity[-1] == 1e6

    closes = bars["close"].tolist()
    with_future = 1.0
    for t in range(len(closes) - 1):
        if closes[t + 1] > closes[t]:
            with_future *= closes[t + 1] / closes[t]
    assert with_future > 2, "the same rule with real future data would have been very profitable"


# start: bars before start are warm-up history. Bars from 2025-01-01 (Wed):
# 01-01, 01-02, 01-03, 01-06, 01-07; start=2 trades from 01-03.
START_OPENS = [10, 11, 12, 13, 15]
START_CLOSES = [10, 11, 12.5, 14, 16]


def test_start_skips_warmup_and_fills_at_start_open():
    bars = make_bars(START_OPENS, START_CLOSES)
    seen = []

    def decide(hist, pos):
        seen.append((len(hist), hist.index[-1].strftime("%Y-%m-%d"), pos))
        return {2: 1.0, 3: 1.0, 4: 0.0}[len(hist)]  # the first call needs both warm-up bars

    led = simulate(bars, decide, NO_FEES, 1200, start=2)
    # Decision at close of bar 1 sees bars 0..1 flat; later calls see the full history to t.
    assert seen == [(2, "2025-01-02", 0.0), (3, "2025-01-03", 1.0), (4, "2025-01-06", 1.0)]
    assert led.dates == ["2025-01-03", "2025-01-06", "2025-01-07"]
    assert len(led.cash) == len(led.shares) == len(led.equity) == len(led.dividends) == 3
    buy, sell = led.fills
    # 1200 / 12 = 100 shares at bar 2's open; sold at bar 4's open 15 -> cash 1500
    assert (buy.bar, buy.date, buy.price, buy.shares) == (0, "2025-01-03", 12.0, 100)
    assert (sell.bar, sell.date, sell.price) == (2, "2025-01-07", 15.0)
    assert led.equity == [1250, 1400, 1500]
    (trip,) = led.round_trips
    assert (trip.entry_bar, trip.exit_bar, trip.entry_date, trip.exit_date, trip.pnl) == (
        0,
        2,
        "2025-01-03",
        "2025-01-07",
        300,
    )


def test_start_never_shows_the_future():
    bars = random_bars(n=60)
    start, lens = 20, []

    def spy(hist, _pos):
        lens.append(len(hist))
        return 0.0

    simulate(bars, spy, NO_FEES, 1e5, start=start)
    # pre-loop call at close start-1, then t = start..n-2
    assert lens == list(range(start, len(bars)))


def test_start_zero_is_unchanged():
    bars = random_bars(seed=5)

    def run(**kw):
        rng = np.random.default_rng(3)
        return simulate(bars, lambda _h, _p: float(rng.choice([0, 1])), TW_STOCK_FEES, 1e6, **kw)

    a, b = run(), run(start=0)
    assert a.equity == b.equity and a.fills == b.fills and a.round_trips == b.round_trips


def test_start_ledger_replays():
    bars, start = random_bars(seed=2), 50
    rng = np.random.default_rng(2)
    led = simulate(
        bars, lambda _h, _p: float(rng.choice([0, 0.5, 1])), TW_STOCK_FEES, 1e6, start=start
    )
    cash, shares = replay(bars.iloc[start:], led)
    assert led.shares == shares and led.cash == pytest.approx(cash, abs=1e-6)
    assert all(led.dates[f.bar] == f.date for f in led.fills)


def test_buy_and_hold_with_start():
    bars = make_bars(START_OPENS, START_CLOSES)
    bh = buy_and_hold(bars, NO_FEES, 1200, start=2)
    assert (bh.fills[0].bar, bh.fills[0].date, bh.fills[0].shares) == (0, "2025-01-03", 100)
    assert bh.equity == [1250, 1400, 1600]


@pytest.mark.parametrize("start", [-1, 5])
def test_start_out_of_range(start):
    with pytest.raises(ValueError):
        simulate(make_bars(START_OPENS, START_CLOSES), lambda _h, _p: 0.0, NO_FEES, 1, start=start)
