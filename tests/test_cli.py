import subprocess
import sys

from trader import __version__


def test_cli_reports_version():
    out = subprocess.run(
        [sys.executable, "-m", "trader.cli", "--version"], capture_output=True, text=True
    )
    assert out.returncode == 0
    assert out.stdout.strip() == __version__
