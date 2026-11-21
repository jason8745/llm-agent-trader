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
from conftest import END, START, SYMBOL
from mcp import Client, StdioServerParameters

from trader import fmt, runner, store, viewer

HYP = "以 5 日與 20 日均線交叉作為基準策略。"


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
    for path in ["/", "/runs/1"]:
        status, ctype, body = get(served + path)
        assert status == 200 and ctype.startswith("text/html") and b"app.js" in body
    for name in ["app.js", "app.css", "lightweight-charts.js"]:
        assert get(f"{served}/static/{name}")[0] == 200
    for bad in ["/static/../store.py", "/static/index.html", "/api/runs/999", "/nope"]:
        with pytest.raises(urllib.error.HTTPError) as e:
            get(served + bad)
        assert e.value.code == 404


def test_three_surfaces_show_identical_strings(ws, served):
    run = runner.run_backtest(ws, "ma_cross", SYMBOL, START, END, HYP)
    expected = fmt.summary(run.report, run.dates)

    detail = api(f"{served}/api/runs/{run.id}")
    listing = api(f"{served}/api/runs")
    cli = subprocess.run(
        [sys.executable, "-m", "trader.cli", "show", str(run.id)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    mcp_text = fmt.run_text(store.get(ws, run.id), 8765)

    assert detail["s"] == expected and listing[0]["s"] == expected
    for key, value in expected.items():
        if key != "overfit":
            assert value in cli, key
            assert value in mcp_text, key


def test_viewer_payload_matches_ledger(ws, served):
    run = runner.run_backtest(ws, "ma_cross", SYMBOL, START, END, HYP)
    d = api(f"{served}/api/runs/{run.id}")
    led = run.payload["ledger"]
    assert d["equity"] == led["equity"] and d["bh_equity"] == run.payload["bh_equity"]
    assert len(d["fills"]) == len(led["fills"]) == len(d["markers"])
    assert [f["oos"] for f in d["fills"]] == [f["bar"] >= run.report.split for f in led["fills"]]
    assert d["diff"] == "首次回測"
    second = runner.run_backtest(ws, "ma_cross", SYMBOL, START, END, HYP, params={"fast": 8})
    assert api(f"{served}/api/runs/{second.id}")["diff"] == "fast 5→8"


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
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "trader.cli", "mcp"], env=dict(os.environ)
    )
    args = {"strategy": "ma_cross", "symbol": SYMBOL, "start": START, "end": END, "hypothesis": HYP}

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
    assert payload["s"]["out_of_sample"] in text


def test_rejects_foreign_host_headers(served):
    port = served.rsplit(":", 1)[1]
    ok = urllib.request.Request(f"{served}/api/info", headers={"Host": f"localhost:{port}"})
    assert urllib.request.urlopen(ok, timeout=5).status == 200
    for host in ["evil.example", f"evil.example:{port}", "127.0.0.1:1"]:
        req = urllib.request.Request(f"{served}/api/runs", headers={"Host": host})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 403
