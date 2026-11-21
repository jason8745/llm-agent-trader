import time

import pytest
from conftest import END, START, SYMBOL

from trader import data, fmt, runner, store
from trader.engine import buy_and_hold, fees_for, simulate
from trader.profit import report
from trader.ta import sma

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


def run(ws, strategy="ma_cross", **kw):
    return runner.run_backtest(ws, strategy, SYMBOL, START, END, kw.pop("hypothesis", HYP), **kw)


def test_run_matches_direct_engine_computation(ws):
    r = run(ws)
    bars = data.load_bars(SYMBOL, START, END)

    def ma(hist, _pos):
        return 1.0 if sma(hist.close, 5).iloc[-1] > sma(hist.close, 20).iloc[-1] else 0.0

    fees = fees_for(SYMBOL)
    led = simulate(bars, ma, fees, runner.DEFAULT_CASH)
    expected = report(led, buy_and_hold(bars, fees, runner.DEFAULT_CASH))
    assert r.report == expected
    assert r.payload["ledger"]["equity"] == led.equity
    assert r.params == {"fast": 5, "slow": 20}
    assert r.strategy == "ma_cross" and r.symbol == SYMBOL and r.hypothesis == HYP


def test_reruns_are_bit_identical_and_fingerprinted(ws):
    a, b = run(ws), run(ws)
    assert a.id != b.id
    assert a.payload == b.payload
    assert a.data_sha == b.data_sha == data.fingerprint(data.load_bars(SYMBOL, START, END))
    assert a.source_sha == b.source_sha


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
    with pytest.raises(runner.RunError, match="unknown params"):
        run(ws, params={"fsat": 10})


def test_fee_override(ws):
    r = run(ws, fee={"commission_rate": 0.0, "min_commission": 0})
    assert all(f["commission"] == 0 for f in r.payload["ledger"]["fills"])
    with pytest.raises(runner.RunError, match="unknown fee fields"):
        run(ws, fee={"rate": 0})


@pytest.mark.parametrize("hyp", ["", "   "])
def test_hypothesis_is_required(ws, hyp):
    with pytest.raises(runner.RunError, match="hypothesis is required"):
        run(ws, hypothesis=hyp)


def write(ws, name, body):
    (ws / "strategies" / f"{name}.py").write_text(body, encoding="utf-8")
    return name


def test_strategy_exception_reports_its_line(ws):
    name = write(ws, "broken", "def on_bar(hist, pos, p):\n    return 1 / 0\n")
    with pytest.raises(runner.RunError) as e:
        run(ws, name)
    assert "ZeroDivisionError" in str(e.value) and "broken.py" in str(e.value)


def test_invalid_return_and_missing_on_bar(ws):
    with pytest.raises(runner.RunError, match="between 0 and 1"):
        run(ws, write(ws, "big", "def on_bar(hist, pos, p):\n    return 2\n"))
    with pytest.raises(runner.RunError, match="must define on_bar"):
        run(ws, write(ws, "empty", "X = 1\n"))
    with pytest.raises(runner.RunError, match="not found"):
        run(ws, "nope")


def test_infinite_loop_times_out_and_next_run_works(ws):
    name = write(ws, "spin", "def on_bar(hist, pos, p):\n    while True:\n        pass\n")
    t0 = time.monotonic()
    with pytest.raises(runner.RunError, match="did not finish within 2 seconds"):
        run(ws, name, timeout=2)
    assert time.monotonic() - t0 < 10
    assert run(ws).report.trades >= 0


def test_strategy_stdout_does_not_corrupt_results(ws):
    name = write(ws, "chatty", "def on_bar(hist, pos, p):\n    print('hello')\n    return 1.0\n")
    assert run(ws, name).payload["ledger"]["fills"]


def test_list_runs_filters(ws):
    run(ws)
    write(ws, "hold", "def on_bar(hist, pos, p):\n    return 1.0\n")
    run(ws, "hold")
    assert [r.strategy for r in store.list_runs(ws)] == ["ma_cross", "hold"]
    assert [r.strategy for r in store.list_runs(ws, strategy="hold")] == ["hold"]


def test_run_text_contains_every_summary_value(ws):
    r = run(ws)
    text = fmt.run_text(r, 8765)
    for key, value in fmt.summary(r.report, r.dates).items():
        if key != "overfit":
            assert value in text, key
    assert "http://127.0.0.1:8765/runs/" in text
