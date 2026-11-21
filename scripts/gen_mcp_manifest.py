"""Regenerate src/trader/mcp_manifest.json from the real MCP server.

    uv run python scripts/gen_mcp_manifest.py

The instant-start launcher serves this manifest before the real server is up;
tests/test_launcher.py fails if it drifts from what the real server reports.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "trader"))
from mcp_launcher import Child  # noqa: E402

OUT = ROOT / "src" / "trader" / "mcp_manifest.json"


def manifest():
    child = Child([sys.executable, "-m", "trader.cli", "mcp"], "2025-06-18")
    try:
        init = child.init
        tools = child.request("tools/list", {})["tools"]
    finally:
        child.proc.stdin.close()
        child.proc.wait()
    return {"serverInfo": init["serverInfo"], "instructions": init["instructions"], "tools": tools}


def render(m):
    return json.dumps(m, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(manifest()), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
