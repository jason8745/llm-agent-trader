import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from conftest import BT, PERIODS, SYMBOL
from mcp import Client, StdioServerParameters

from trader import fmt, mcp_server, profit, runner, store, viewer

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


def bt(ws, **kw):
    return runner.run_backtest(ws, "ma_cross", SYMBOL, *PERIODS, HYP, **kw)


@pytest.fixture
def served(ws):
    srv = viewer.make_server(ws, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def api(url):
    return json.loads(get(url)[2])


def test_viewer_serves_pages_and_assets(served):
    for path in ["/", "/runs/1", "/studies/0123456789ab"]:
        status, ctype, body = get(served + path)
        assert status == 200 and ctype.startswith("text/html") and b"app.js" in body
    for name in ["app.js", "app.css", "lightweight-charts.js"]:
        assert get(f"{served}/static/{name}")[0] == 200
    for bad in [
        "/static/../store.py",
        "/static/index.html",
        "/api/runs/999",
        "/api/runs",
        "/api/studies/0123456789ab",
        "/studies/xyz",
        "/nope",
    ]:
        with pytest.raises(urllib.error.HTTPError) as e:
            get(served + bad)
        assert e.value.code == 404


def test_three_surfaces_show_identical_strings(ws, served):
    run = bt(ws)
    detail = api(f"{served}/api/runs/{run.id}")
    cli = subprocess.run(
        [sys.executable, "-m", "trader.cli", "show", str(run.id)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    saved = store.get(ws, run.id)
    texts = {
        "cli show": cli,
        "run_backtest": fmt.run_text(saved, 8765),
        "get_run": fmt.run_detail(saved, 8765),
    }
    rep = saved.report
    assert detail["metrics"] == fmt.metric_rows(rep)
    assert detail["trade_metrics"] == fmt.trade_rows(rep)
    assert detail["regimes"] == fmt.regime_rows(saved.regimes)
    values = [v for row in detail["metrics"] + detail["trade_metrics"] for v in row.values()]
    values += [
        detail["regimes"][i][k]
        for i in range(len(detail["regimes"]))
        for k in ("label", "bars", "price_change", "strategy", "exposure", "start", "end")
    ]
    values.append(detail["regime_rules"])
    for name, text in texts.items():
        for v in values:
            assert v in text, (name, v)
    for period in ("dev", "exec"):
        for d in detail["drawdowns"][period]:
            assert all(v in texts["get_run"] for v in d.values())
    for f in detail["fills"]:
        assert (
            f"| {f['period']} | {f['date']} | {f['side']} | {f['price']} | {f['shares']} "
            in (texts["get_run"])
        )
    for t in detail["trips"]:
        assert (
            f"| {t['period']} | {t['entry']} | {t['exit']} | {t['held']} | {t['pnl']} |"
            in (texts["get_run"])
        )


def test_run_payload_shape_and_chart(ws, served):
    run = bt(ws)
    d = api(f"{served}/api/runs/{run.id}")
    assert set(d) == {
        "id", "n", "study_key", "symbol", "label", "strategy", "hypothesis", "params", "diff",
        "created_at", "dev", "exec", "metrics", "trade_metrics", "overfit", "overfit_note",
        "drawdowns", "regimes", "regime_rules", "chart", "fills", "trips", "source",
        "source_sha", "data_sha",
    }  # fmt: skip
    assert (d["dev"], d["exec"]) == (fmt.span(*PERIODS[:2]), fmt.span(*PERIODS[2:]))
    assert d["overfit_note"] == (fmt.OVERFIT_NOTE if d["overfit"] else None)
    c, p = d["chart"], run.payload
    assert c["dates"] == p["bars"]["date"] and c["close"] == p["bars"]["close"]
    assert c["dev_dates"] == p["dev"]["dates"] and c["exec_dates"] == p["exec"]["dates"]
    cash = run.cash
    cum = profit.chained_returns(cash, p["dev"]["equity"], p["exec"]["equity"])
    assert c["cum"] == [round(x * 100, 2) for x in cum]
    assert len(c["cum"]) == len(c["cum_bh"]) == len(c["dev_dates"]) + len(c["exec_dates"])
    peak, dd = run.cash, []
    for e in p["exec"]["equity"]:
        peak = max(peak, e)
        dd.append(round((e / peak - 1) * 100, 2))
    assert c["dd_exec"] == dd and len(c["dd_dev"]) == len(c["dev_dates"])
    assert min(c["dd_exec"]) == round(run.report.exec.strategy.mdd * 100, 2)
    fills = p["dev"]["fills"] + p["exec"]["fills"]
    assert c["markers"] == [{"date": f["date"], "side": f["side"]} for f in fills]
    assert [f["period"] for f in d["fills"]] == ["開發期間"] * len(p["dev"]["fills"]) + [
        "執行期間"
    ] * len(p["exec"]["fills"])
    assert set(d["fills"][0]) == {
        "period",
        "date",
        "side",
        "buy",
        "price",
        "shares",
        "gross",
        "fees",
    }
    assert c["regimes"][0] == {k: d["regimes"][0][k] for k in ("start", "end", "kind")}
    assert d["regimes"][0]["kind"] in {"up", "down", "range"}


def test_tree_and_study_payloads(ws, served):
    first = bt(ws)
    second = bt(ws, params={"fast": 8})
    third = bt(ws, params={"fast": 8})
    other = runner.run_backtest(
        ws, "ma_cross", SYMBOL, PERIODS[0], PERIODS[1], "2024-04-15", PERIODS[3], "另一研究"
    )
    mcp_server.finalize(
        ws, second.id, "以第二次迭代定稿。", [{"finding": "發現。", "insight": "洞察。"}] * 3, 8765
    )

    tree = api(f"{served}/api/tree")
    assert [s["symbol"] for s in tree] == [SYMBOL] and tree[0]["label"] == fmt.symbol_label(SYMBOL)
    studies = tree[0]["studies"]
    assert [s["key"] for s in studies] == [other.study_key, first.study_key]  # newest first
    s = studies[1]
    assert (s["question"], s["final_run_id"], s["dev"]) == (HYP, second.id, fmt.span(*PERIODS[:2]))
    assert [r["id"] for r in s["runs"]] == [first.id, second.id, third.id]
    assert [r["n"] for r in s["runs"]] == [1, 2, 3]
    assert [r["final"] for r in s["runs"]] == [False, True, False]
    assert s["runs"][0]["exec_ret"] == fmt.pct(first.report.exec.strategy.ret)
    assert set(s["runs"][0]) == {
        "id",
        "n",
        "hypothesis",
        "dev_ret",
        "exec_ret",
        "overfit",
        "final",
        "created_at",
    }

    st = api(f"{served}/api/studies/{first.study_key}")
    assert st["conclusion"]["verdict"] == "以第二次迭代定稿。" and st["finalized_at"]
    assert st["conclusion"]["findings"] == [{"finding": "發現。", "insight": "洞察。"}] * 3
    assert st["final_run_id"] == second.id and st["label"] == fmt.symbol_label(SYMBOL)
    assert [i["diff"] for i in st["iterations"]] == ["首次回測", "fast 5→8", "參數未變更"]
    it = st["iterations"][1]
    assert it["final"] and it["params"] == "fast=8, slow=20"
    ex = second.report.exec
    assert (it["exec_mdd"], it["exec_sharpe"], it["exec_trades"], it["bh_exec_ret"]) == (
        fmt.pct(ex.strategy.mdd),
        fmt.ratio(ex.strategy.sharpe),
        fmt.shares(ex.trades.count),
        fmt.pct(ex.bh.ret),
    )
    assert api(f"{served}/api/runs/{third.id}")["diff"] == "參數未變更"
    assert api(f"{served}/api/info") == {"workspace": str(ws)}


def test_frontend_never_formats_numbers():
    js = (Path(viewer.__file__).parent / "app.js").read_text()
    for banned in ["toFixed", "toLocaleString", "Intl.", "toPrecision"]:
        assert banned not in js, f"app.js must render strings from trader.fmt, found {banned}"


def test_ensure_running_reuses_own_viewer_and_skips_foreign_ones(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    port = 18765
    pa = viewer.ensure_running(a, port)
    assert viewer.ensure_running(a, port) == pa
    pb = viewer.ensure_running(b, port)
    assert pb != pa
    assert api(f"http://127.0.0.1:{pb}/api/info")["workspace"] == str(b)


def test_mcp_starts_viewer_for_its_links(ws, monkeypatch):
    monkeypatch.setenv("TRADER_VIEWER_PORT", "18865")
    launcher = Path(viewer.__file__).parents[1] / "mcp_launcher.py"
    child = json.dumps([sys.executable, "-m", "trader.cli", "mcp"])
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(launcher)],
        env=dict(os.environ, TRADER_MCP_CHILD=child),
    )
    args = {"strategy": "ma_cross", "symbol": SYMBOL, "hypothesis": HYP, **BT}

    async def go():
        async with Client(params) as client:
            res = await client.call_tool("run_backtest", args)
            text = "".join(c.text for c in res.content if hasattr(c, "text"))
            url = re.search(r"http://127\.0\.0\.1:(\d+)/runs/(\d+)", text)
            status, _, _ = await asyncio.to_thread(get, url.group(0))
            payload = await asyncio.to_thread(
                api, f"http://127.0.0.1:{url.group(1)}/api/runs/{url.group(2)}"
            )
            return status, payload, text

    status, payload, text = asyncio.run(go())
    assert status == 200
    assert payload["metrics"][0]["exec"] in text


def test_rejects_foreign_host_headers(served):
    port = served.rsplit(":", 1)[1]
    ok = urllib.request.Request(f"{served}/api/info", headers={"Host": f"localhost:{port}"})
    assert urllib.request.urlopen(ok, timeout=5).status == 200
    for host in ["evil.example", f"evil.example:{port}", "127.0.0.1:1"]:
        req = urllib.request.Request(f"{served}/api/tree", headers={"Host": host})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 403


def test_vendored_chart_library_is_pinned():
    import hashlib

    js = (Path(viewer.__file__).parent / "lightweight-charts.js").read_bytes()
    assert b"Lightweight Charts\xe2\x84\xa2 v5.2.1" in js[:200]
    assert hashlib.sha256(js).hexdigest() == (
        "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf"
    )


def test_open_dashboard_starts_the_viewer_before_any_backtest(ws, monkeypatch):
    monkeypatch.setenv("TRADER_VIEWER_PORT", "18965")
    monkeypatch.setenv("BROWSER", "true")
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "trader.cli", "mcp"], env=dict(os.environ)
    )

    async def go():
        async with Client(params) as client:
            res = await client.call_tool("open_dashboard", {})
            first = "".join(c.text for c in res.content if hasattr(c, "text"))
            url = re.search(r"http://127\.0\.0\.1:\d+/", first).group(0)
            listing = await asyncio.to_thread(api, url + "api/tree")
            res = await client.call_tool("open_dashboard", {"run_id": 7})
            missing = "".join(c.text for c in res.content if hasattr(c, "text"))
            return first, listing, missing

    first, listing, missing = asyncio.run(go())
    assert listing == [] and "已在預設瀏覽器開啟" in first and "自動顯示" in first
    assert "查無回測 #7" in missing
