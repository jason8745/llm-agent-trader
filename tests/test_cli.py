import os
import subprocess
import sys

from trader import __version__


def test_cli_reports_version():
    out = subprocess.run(
        [sys.executable, "-m", "trader.cli", "--version"], capture_output=True, text=True
    )
    assert out.returncode == 0
    assert out.stdout.strip() == __version__


def test_cli_never_creates_the_research_folder(tmp_path):
    target = tmp_path / "trader-research"
    env = dict(os.environ, TRADER_WORKSPACE=str(target))
    out = subprocess.run(
        [sys.executable, "-m", "trader.cli", "runs"], capture_output=True, text=True, env=env
    )
    assert out.returncode != 0 and "研究資料夾尚未建立" in out.stderr
    assert not target.exists()
