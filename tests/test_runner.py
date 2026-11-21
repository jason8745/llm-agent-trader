import time

import pytest
from conftest import BT, END, LOAD_START, PERIODS, START, SYMBOL

from trader import data, runner, store
from trader.engine import buy_and_hold, fees_for, simulate
from trader.profit import period
from trader.ta import sma

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


def run(ws, strategy="ma_cross", periods=PERIODS, **kw):
    return runner.run_backtest(ws, strategy, SYMBOL, *periods, kw.pop("hypothesis", HYP), **kw)


def write(ws, name, body):
    (ws / "strategies" / f"{name}.py").write_text(body, encoding="utf-8")
    return name


def ma(hist, _pos):
    return 1.0 if sma(hist.close, 5).iloc[-1] > sma(hist.close, 20).iloc[-1] else 0.0


def loaded():
    """The bars the runner keeps: WARMUP_BARS of history before START, then the period."""
    bars = data.load_bars(SYMBOL, LOAD_START, END)
    k = int((bars.index.strftime("%Y-%m-%d") < START).sum())
    assert k > runner.WARMUP_BARS  # the fixture has more history than the runner keeps
    return bars.iloc[k - runner.WARMUP_BARS :], runner.WARMUP_BARS


def test_run_matches_direct_engine_computation(ws):
    r = run(ws)
    bars, k = loaded()
    fees, cash = fees_for(SYMBOL), runner.DEFAULT_CASH
    led = simulate(bars, ma, fees, cash, start=k)
    assert r.report == period(led, buy_and_hold(bars, fees, cash, start=k))
    assert r.payload["ledger"]["equity"] == led.equity
    assert r.params == {"fast": 5, "slow": 20}
    assert r.strategy == "ma_cross" and r.symbol == SYMBOL and r.hypothesis == HYP
    assert (r.start, r.end) == PERIODS
    assert r.payload["bars"]["date"] == list(bars.index.strftime("%Y-%m-%d"))
    assert r.regimes[0].start == led.dates[0] and r.regimes[-1].end == led.dates[-1]
    assert sum(g.bars for g in r.regimes) == len(led.dates) - 1  # regimes tile the period only


def test_backtest_starts_flat_at_start_after_warm_up_bars(ws):
    r = run(ws, write(ws, "hold", "def on_bar(hist, pos, p):\n    return 1.0\n"))
    led, bars = r.payload["ledger"], r.payload["bars"]
    k = bars["date"].index(led["dates"][0])
    assert k == runner.WARMUP_BARS
    assert led["dates"][0] >= START and bars["date"][k - 1] < START
    # The decision made on warm-up history before the start fills at the first bar's open.
    first = led["fills"][0]
    assert (first["date"], first["side"], first["price"]) == (
        bars["date"][k],
        "BUY",
        bars["open"][k],
    )
    assert led["initial_cash"] == runner.DEFAULT_CASH
    assert led["equity"] == r.payload["bh"]  # holding from the first bar is buy-and-hold


def test_strategy_sees_warm_up_history_on_its_first_decision(ws):
    body = f"def on_bar(hist, pos, p):\n    return float(len(hist) >= {runner.WARMUP_BARS})\n"
    assert run(ws, write(ws, "late", body)).payload["ledger"]["fills"][0]["bar"] == 0


@pytest.mark.parametrize(
    "periods,message",
    [
        (("2024/06/03", END), "回測期間起日須為 YYYY-MM-DD"),
        ((START, "2024-13-01"), "回測期間迄日須為 YYYY-MM-DD"),
        (("2024-12-31", "2024-06-03"), "回測期間起日 2024-12-31 晚於"),
    ],
)
def test_period_validation(ws, periods, message):
    with pytest.raises(runner.RunError, match=message):
        run(ws, periods=periods)


@pytest.mark.parametrize("periods,n", [((END, END), 1), (("2025-03-01", "2025-03-31"), 0)])
def test_period_needs_two_trading_days(ws, monkeypatch, periods, n):
    bars = data.load_bars(SYMBOL, LOAD_START, END)
    monkeypatch.setattr(runner.data, "load_bars", lambda *_: bars)
    with pytest.raises(runner.RunError, match=f"回測期間僅有 {n} 個交易日"):
        run(ws, periods=periods)


def test_reruns_are_bit_identical_and_fingerprinted(ws):
    a, b = run(ws), run(ws)
    assert a.id != b.id and (a.n, b.n) == (1, 2) and a.study_key == b.study_key
    assert a.payload == b.payload
    assert a.data_sha == b.data_sha == data.fingerprint(loaded()[0])
    assert a.source_sha == b.source_sha


def test_fingerprint_mismatch_is_rejected(ws, monkeypatch):
    monkeypatch.setattr(runner.data, "fingerprint", lambda _bars: "0" * 64)
    with pytest.raises(runner.RunError, match="價格資料與擷取的資料不一致"):
        run(ws)


def test_source_snapshot_survives_later_edits(ws):
    first = run(ws)
    path = ws / "strategies" / "ma_cross.py"
    path.write_text(path.read_text().replace('"fast": 5', '"fast": 8'))
    second = run(ws)
    assert '"fast": 5' in store.get(ws, first.id).source
    assert '"fast": 8' in second.source and first.source_sha != second.source_sha


def test_param_overrides(ws):
    r = run(ws, params={"fast": 10})
    assert r.params == {"fast": 10, "slow": 20}
    with pytest.raises(runner.RunError, match="未知的參數"):
        run(ws, params={"fsat": 10})


def test_fee_override(ws):
    r = run(ws, fee={"commission_rate": 0.0, "min_commission": 0})
    fills = r.payload["ledger"]["fills"]
    assert fills and all(f["commission"] == 0 for f in fills)
    with pytest.raises(runner.RunError, match="不支援的費用欄位"):
        run(ws, fee={"rate": 0})


@pytest.mark.parametrize("hyp", ["", "   "])
def test_hypothesis_is_required(ws, hyp):
    with pytest.raises(runner.RunError, match="必須填寫 hypothesis"):
        run(ws, hypothesis=hyp)


def test_strategy_exception_reports_its_line(ws):
    name = write(ws, "broken", "def on_bar(hist, pos, p):\n    return 1 / 0\n")
    with pytest.raises(runner.RunError) as e:
        run(ws, name)
    assert "ZeroDivisionError" in str(e.value) and "broken.py" in str(e.value)


def test_invalid_return_and_missing_on_bar(ws):
    with pytest.raises(runner.RunError, match="0 到 1 之間"):
        run(ws, write(ws, "big", "def on_bar(hist, pos, p):\n    return 2\n"))
    with pytest.raises(runner.RunError, match="must define on_bar"):
        run(ws, write(ws, "empty", "X = 1\n"))
    with pytest.raises(runner.RunError, match="找不到策略檔"):
        run(ws, "nope")


def test_infinite_loop_times_out_and_next_run_works(ws):
    name = write(ws, "spin", "def on_bar(hist, pos, p):\n    while True:\n        pass\n")
    t0 = time.monotonic()
    with pytest.raises(runner.RunError, match="未在 2 秒內完成"):
        run(ws, name, timeout=2)
    assert time.monotonic() - t0 < 10
    assert run(ws).report.trades.count >= 0


def test_strategy_stdout_does_not_corrupt_results(ws):
    name = write(ws, "chatty", "def on_bar(hist, pos, p):\n    print('hello')\n    return 1.0\n")
    assert run(ws, name).payload["ledger"]["fills"]


def test_list_runs_filters(ws):
    run(ws)
    write(ws, "hold", "def on_bar(hist, pos, p):\n    return 1.0\n")
    run(ws, "hold")
    assert [r.strategy for r in store.list_runs(ws)] == ["ma_cross", "hold"]
    assert [r.strategy for r in store.list_runs(ws, strategy="hold")] == ["hold"]
    assert runner.run_backtest(ws, "ma_cross", SYMBOL, hypothesis=HYP, **BT).n == 2


def test_backtest_leaves_no_pycache_in_strategies(ws):
    runner.run_backtest(ws, "ma_cross", SYMBOL, *PERIODS, "以 5 日與 20 日均線交叉作為基準策略。")
    assert not (ws / "strategies" / "__pycache__").exists()
