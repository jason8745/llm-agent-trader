"""Build the Claude Desktop extension (dist/llm-agent-trader-<version>.mcpb).

    uv run python scripts/build_mcpb.py

The extension uses Claude Desktop's built-in uv runtime: Claude Desktop downloads uv itself,
uv downloads Python and the dependencies from pyproject.toml, so the user installs nothing.
"""

import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
INCLUDE = ["pyproject.toml", "uv.lock", "README.md", "LICENSE"]
SKIP = {"__pycache__"}


def manifest(version: str) -> dict:
    tools = json.loads((ROOT / "src/trader/mcp_manifest.json").read_text(encoding="utf-8"))["tools"]
    return {
        "manifest_version": "0.4",
        "name": "llm-agent-trader",
        "display_name": "台股回測 LLM Agent Trader",
        "version": version,
        "description": "與 Claude 討論台股策略，由 Claude 撰寫並回測，結果以 dashboard 呈現。",
        "long_description": (
            "安裝後，在對話中說「開始使用台股回測」。Claude 會徵求同意後建立研究資料夾、"
            "開啟 dashboard，並引導你完成第一個策略研究：確認研究條件、回測策略開發期間與"
            "策略執行期間、與買進並持有比較，最後寫入發現與洞察。所有數字由確定性的回測引擎計算。"
        ),
        "author": {"name": "jason8745", "url": "https://github.com/jason8745"},
        "repository": {"type": "git", "url": "https://github.com/jason8745/llm-agent-trader"},
        "homepage": "https://github.com/jason8745/llm-agent-trader",
        "documentation": "https://github.com/jason8745/llm-agent-trader#readme",
        "support": "https://github.com/jason8745/llm-agent-trader/issues",
        "icon": "icon.png",
        "license": "MIT",
        "keywords": ["台股", "回測", "backtesting", "taiwan-stock", "trading"],
        "server": {
            "type": "uv",
            "entry_point": "src/trader/mcp_launcher.py",
            "mcp_config": {
                "command": "uv",
                "args": [
                    "run",
                    "--no-project",
                    "--managed-python",
                    "--python",
                    "3.12",
                    "${__dirname}/src/trader/mcp_launcher.py",
                ],
            },
        },
        "tools": [
            {"name": t["name"], "description": t["description"].split("\n")[0]} for t in tools
        ],
        "compatibility": {"platforms": ["darwin", "win32"]},
    }


def files() -> list[tuple[Path, str]]:
    out = [(ROOT / f, f) for f in INCLUDE if (ROOT / f).exists()]
    out.append((ROOT / ".claude-plugin" / "icon.png", "icon.png"))
    for p in sorted((ROOT / "src" / "trader").rglob("*")):
        if p.is_file() and not SKIP & set(p.parts) and p.suffix != ".pyc":
            out.append((p, p.relative_to(ROOT).as_posix()))
    return out


def build() -> Path:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    DIST.mkdir(exist_ok=True)
    out = DIST / f"llm-agent-trader-{version}.mcpb"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest(version), ensure_ascii=False, indent=2))
        for src, name in files():
            z.write(src, name)
    return out


if __name__ == "__main__":
    path = build()
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
