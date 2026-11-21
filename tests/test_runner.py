import time

import pytest
from conftest import BT, DEV_END, DEV_START, EXEC_END, EXEC_START, PERIODS, SYMBOL

from trader import data, runner, store
from trader.engine import buy_and_hold, fees_for, simulate
from trader.profit import study_report
from trader.ta import sma

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


def run(ws, strategy="ma_cross", periods=PERIODS, **kw):
    return runner.run_backtest(ws, strategy, SYMBOL, *periods, kw.pop("hypothesis", HYP), **kw)


def write(ws, name, body):
    (ws / "strategies" / f"{name}.py").write_text(body, encoding="utf-8")
    return name


def ma(hist, _pos):
    return 1.0 if sma(hist.close, 5).iloc[-1] > sma(hist.close, 20).iloc[-1] else 0.0


def test_run_matches_direct_engine_computation(ws):
    r = run(ws)
    bars = data.load_bars(SYMBOL, DEV_START, EXEC_END)
    dates = bars.index.strftime("%Y-%m-%d")
    dev_n = int((dates <= DEV_END).sum())
    k = int((dates < EXEC_START).sum())
    assert dev_n == k  # no gap between the periods
    fees, cash = fees_for(SYMBOL), runner.DEFAULT_CASH
    dev = simulate(bars.iloc[:dev_n], ma, fees, cash)
    exe = simulate(bars, ma, fees, cash, start=k)
    bh_dev = buy_and_hold(bars.iloc[:dev_n], fees, cash)
    expected = study_report(dev, bh_dev, exe, buy_and_hold(bars, fees, cash, start=k))
    assert r.report == expected
    assert r.payload["dev"]["equity"] == dev.equity
    assert r.payload["exec"]["equity"] == exe.equity
    assert r.params == {"fast": 5, "slow": 20}
    assert r.strategy == "ma_cross" and r.symbol == SYMBOL and r.hypothesis == HYP
    assert (r.dev_start, r.dev_end, r.exec_start, r.exec_end) == PERIODS
    assert len(r.payload["bars"]["date"]) == len(bars)
    assert r.regimes[0].start == DEV_START and r.regimes[-1].end == dates[-1]


def test_execution_starts_flat_at_exec_start_with_warm_up_history(ws):
    r = run(ws, write(ws, "hold", "def on_bar(hist, pos, p):\n    return 1.0\n"))
    exe, bars = r.payload["exec"], r.payload["bars"]
    k = bars["date"].index(exe["dates"][0])
    assert exe["dates"][0] >= EXEC_START and bars["date"][k - 1] < EXEC_START
    # The decision made on warm-up history before exec_start fills at exec_start's open.
    first = exe["fills"][0]
    assert (first["date"], first["side"], first["price"]) == (
        bars["date"][k],
        "BUY",
        bars["open"][k],
    )
    assert exe["initial_cash"] == runner.DEFAULT_CASH
    assert exe["equity"] == r.payload["bh_exec"]  # holding from the first bar is buy-and-hold
    assert r.payload["dev"]["dates"][-1] <= DEV_END  # development never sees later bars


def test_strategy_sees_earlier_bars_in_execution(ws):
    # 65 development bars; the last bar of a ledger makes no decision, so development never
    # sees 65 bars of history while execution does on its first decision.
    r = run(ws, write(ws, "late", "def on_bar(hist, pos, p):\n    return float(len(hist) >= 65)\n"))
    assert not r.payload["dev"]["fills"]
    assert r.payload["exec"]["fills"][0]["bar"] == 0


def test_gap_bars_are_history_for_execution_only(ws):
    r = run(ws, periods=(DEV_START, DEV_END, "2024-04-15", EXEC_END))
    dates, dev, exe = r.payload["bars"]["date"], r.payload["dev"], r.payload["exec"]
    gap = [d for d in dates if DEV_END < d < "2024-04-15"]
    assert gap
    assert len(dev["dates"]) + len(gap) + len(exe["dates"]) == len(dates)
    assert exe["dates"][0] == dates[len(dev["dates"]) + len(gap)]
    assert sum(g.bars for g in r.regimes) == len(dates) - 1  # regimes tile every loaded bar


@pytest.mark.parametrize(
    "periods,message",
    [
        (("2024/01/01", DEV_END, EXEC_START, EXEC_END), "策略開發期間起日須為 YYYY-MM-DD"),
        ((DEV_START, DEV_END, EXEC_START, "2024-13-01"), "策略執行期間迄日須為 YYYY-MM-DD"),
        (("2024-03-31", "2024-01-01", EXEC_START, EXEC_END), "策略開發期間起日 2024-03-31 晚於"),
        ((DEV_START, DEV_END, "2024-12-31", "2024-05-01"), "策略執行期間起日 2024-12-31 晚於"),
        ((DEV_START, DEV_END, DEV_END, EXEC_END), "須晚於策略開發期間迄日"),
        ((DEV_START, DEV_START, EXEC_START, EXEC_END), "策略開發期間僅有 1 個交易日"),
        ((DEV_START, DEV_END, "2024-11-01", EXEC_END), "策略執行期間僅有 0 個交易日"),
    ],
)
def test_period_validation(ws, periods, message):
    with pytest.raises(runner.RunError, match=message):
        run(ws, periods=periods)


def test_reruns_are_bit_identical_and_fingerprinted(ws):
    a, b = run(ws), run(ws)
    assert a.id != b.id and (a.n, b.n) == (1, 2) and a.study_key == b.study_key
    assert a.payload == b.payload
    assert a.data_sha == b.data_sha == data.fingerprint(data.load_bars(SYMBOL, DEV_START, EXEC_END))
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
    fills = r.payload["dev"]["fills"] + r.payload["exec"]["fills"]
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
    assert run(ws).report.exec.trades.count >= 0


def test_strategy_stdout_does_not_corrupt_results(ws):
    name = write(ws, "chatty", "def on_bar(hist, pos, p):\n    print('hello')\n    return 1.0\n")
    assert run(ws, name).payload["exec"]["fills"]


def test_list_runs_filters(ws):
    run(ws)
    write(ws, "hold", "def on_bar(hist, pos, p):\n    return 1.0\n")
    run(ws, "hold")
    assert [r.strategy for r in store.list_runs(ws)] == ["ma_cross", "hold"]
    assert [r.strategy for r in store.list_runs(ws, strategy="hold")] == ["hold"]
    assert runner.run_backtest(ws, "ma_cross", SYMBOL, hypothesis=HYP, **BT).n == 2
