"""The research folder and the research guide.

Standard library only: the instant-start launcher serves get_research_guide and
setup_workspace from this module before pandas and the real server are installed.
"""

import os
from pathlib import Path

GUIDE = Path(__file__).with_name("guide.md")


def path() -> Path:
    """The single research folder. TRADER_WORKSPACE overrides it (extension settings, tests)."""
    override = os.environ.get("TRADER_WORKSPACE")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Documents" / "trader-research"


def missing() -> str | None:
    ws = path()
    if ws.is_dir():
        return None
    return (
        f"研究資料夾尚未建立：{ws}\n"
        "請先向使用者說明此資料夾用於存放策略檔與回測紀錄，取得同意後呼叫 setup_workspace。"
    )


def guide() -> str:
    ws = path()
    state = "已建立" if ws.is_dir() else "尚未建立，建立前須徵得使用者同意"
    return f"{GUIDE.read_text(encoding='utf-8')}\n\n目前的研究資料夾：{ws}（{state}）"


def setup() -> str:
    ws = path()
    existed = ws.is_dir()
    (ws / "strategies").mkdir(parents=True, exist_ok=True)
    head = "研究資料夾已存在" if existed else "已建立研究資料夾"
    return f"{head}：{ws}\n策略檔存放於 {ws / 'strategies'}，回測紀錄存放於 {ws / '.trader'}。"
