import sqlite3

from conftest import DEV_END, DEV_START, EXEC_END, PERIODS, SYMBOL

from trader import fmt, runner, store

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


def bt(ws, periods=PERIODS, **kw):
    return runner.run_backtest(ws, "ma_cross", SYMBOL, *periods, HYP, **kw)


def test_legacy_runs_are_counted_not_shown(ws):
    assert store.legacy_count(ws) == 0
    path = store.db_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, payload TEXT)")
    con.executemany("INSERT INTO runs (payload) VALUES (?)", [("{}",), ("{}",)])
    con.commit()
    con.close()
    assert store.legacy_count(ws) == 2
    assert store.list_runs(ws) == [] and store.list_studies(ws) == {}
    assert bt(ws).id == 1


def test_study_grouping_and_iteration_numbers(ws):
    a, b = bt(ws), bt(ws, params={"fast": 8})
    other = bt(ws, periods=(DEV_START, DEV_END, "2024-04-15", EXEC_END))
    c = bt(ws)
    assert a.study_key == b.study_key == c.study_key != other.study_key
    assert [r.n for r in (a, b, other, c)] == [1, 2, 1, 3]
    assert a.study_key == store.study_key(SYMBOL, "ma_cross", *PERIODS)
    assert [r.id for r in store.list_runs(ws, study=a.study_key)] == [a.id, b.id, c.id]
    study = store.get_study(ws, a.study_key)
    assert (study.symbol, study.strategy, study.final_run_id) == (SYMBOL, "ma_cross", None)
    assert set(store.list_studies(ws)) == {a.study_key, other.study_key}
    assert a.label == fmt.symbol_label(SYMBOL)


def test_finalize_overwrites(ws):
    a, b = bt(ws), bt(ws)
    store.finalize(ws, a.study_key, a.id, "第一版", "2026-01-01 10:00")
    store.finalize(ws, a.study_key, b.id, "第二版", "2026-01-02 10:00")
    s = store.get_study(ws, a.study_key)
    assert (s.final_run_id, s.conclusion, s.finalized_at) == (b.id, "第二版", "2026-01-02 10:00")
