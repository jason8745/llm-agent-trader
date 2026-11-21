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
    s = stream(tmp_path, "樣本外報酬率為 +50.72%，優於基準。", "| 樣本外報酬率 | +50.72% |")
    assert run("check_transcript.py", str(s), str(tmp_path / "t.md")).returncode == 0


def test_transcript_check_rejects_invented_numbers_and_slang(tmp_path):
    s = stream(tmp_path, "方向對了，年化約 +31.00%。", "| 樣本外報酬率 | +50.72% |")
    out = run("check_transcript.py", str(s), str(tmp_path / "t.md"))
    assert out.returncode == 1
    assert "+31.00%" in out.stdout and "方向對了" in out.stdout


def test_sanitize_strips_local_paths():
    home = str(Path.home())
    text = f"{ROOT}/src/x.py {home}/notes /private/tmp/claude-502/-a-b/c/scratchpad/e2e/y.py"
    out = run("sanitize_evidence.py", "-", stdin=text).stdout
    assert out == "<repo>/src/x.py ~/notes <scratch>/e2e/y.py"
