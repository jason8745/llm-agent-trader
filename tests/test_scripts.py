import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script, *args, stdin=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


def stream(tmp_path, prose, tool_result):
    events = [
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": tool_result}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": prose}]}},
    ]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events))
    return p


def test_transcript_check_accepts_quoted_numbers(tmp_path):
    s = stream(tmp_path, "報酬率為 +50.72%，優於基準。", "| 報酬率 | +50.72% |")
    assert run("check_transcript.py", str(s), str(tmp_path / "t.md")).returncode == 0


def test_transcript_check_rejects_invented_numbers_and_slang(tmp_path):
    s = stream(tmp_path, "方向對了，年化約 +31.00%。", "| 報酬率 | +50.72% |")
    out = run("check_transcript.py", str(s), str(tmp_path / "t.md"))
    assert out.returncode == 1
    assert "+31.00%" in out.stdout and "方向對了" in out.stdout


def test_transcript_check_allows_calendar_years_but_not_other_numbers(tmp_path):
    s = stream(tmp_path, "可另以 2022 年驗證，報酬率為 +50.72%。", "| 報酬率 | +50.72% |")
    assert run("check_transcript.py", str(s), str(tmp_path / "t.md")).returncode == 0
    s = stream(tmp_path, "報酬率追不上基準，期末權益 2022。", "| 報酬率 | +50.72% |")
    out = run("check_transcript.py", str(s), str(tmp_path / "t.md"))
    assert "2022" in out.stdout and "追不上" in out.stdout


def test_sanitize_strips_local_paths():
    home = str(Path.home())
    text = f"{ROOT}/src/x.py {home}/notes /private/tmp/claude-502/-a-b/c/scratchpad/e2e/y.py"
    out = run("sanitize_evidence.py", "-", stdin=text).stdout
    assert out == "<repo>/src/x.py ~/notes <scratch>/e2e/y.py"


def test_desktop_extension_bundle(tmp_path, monkeypatch):
    import importlib.util
    import zipfile

    spec = importlib.util.spec_from_file_location("build_mcpb", ROOT / "scripts" / "build_mcpb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DIST", tmp_path)
    with zipfile.ZipFile(mod.build()) as z:
        names = set(z.namelist())
        m = json.loads(z.read("manifest.json"))
    assert {"manifest.json", "icon.png", "pyproject.toml", "uv.lock", "README.md"} <= names
    assert {"src/trader/guide.md", "src/trader/workspace.py", "src/trader/mcp_launcher.py"} <= names
    assert not any(n.startswith(("tests/", "docs/")) or "__pycache__" in n for n in names)
    assert m["manifest_version"] == "0.4" and m["server"]["type"] == "uv"
    assert "--managed-python" in m["server"]["mcp_config"]["args"]
    # No settings dialog at install time: Claude Desktop shows defaults like ${DOCUMENTS}
    # unexpanded and keeps Save disabled, so the server's own default folder is used instead.
    assert "user_config" not in m and "env" not in m["server"]["mcp_config"]
    assert {t["name"] for t in m["tools"]} >= {
        "get_research_guide",
        "setup_workspace",
        "save_strategy",
    }
