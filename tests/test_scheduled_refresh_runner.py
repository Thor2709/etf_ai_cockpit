"""scripts/scheduled_refresh.ps1 runs the daily and weekly data jobs one at a time (Yahoo stays at 1 call/s)."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "scheduled_refresh.ps1"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell.exe") is None,
    reason="requires Windows PowerShell (scheduled job runner)",
)


def _start(scripts: Path, root: Path, job: str) -> subprocess.Popen:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(scripts / RUNNER.name),
    ]
    return subprocess.Popen(
        [*command, "-Job", job, "-Root", str(root), "-Python", sys.executable]
    )


def _log(root: Path, job: str) -> list[str]:
    (path,) = (root / "logs" / "scheduled").glob(f"{job}-*.log")
    return path.read_text(encoding="utf-8-sig").splitlines()


def test_second_job_waits_until_the_first_ends(tmp_path):
    scripts, root = tmp_path / "scripts", tmp_path / "root"
    scripts.mkdir()
    shutil.copy(RUNNER, scripts)
    running = root / "daily.running"
    (scripts / "run_daily_paper.py").write_text(
        f"import pathlib, time\npathlib.Path({str(running)!r}).touch()\ntime.sleep(3)\n",
        encoding="utf-8",
    )
    (scripts / "refresh_stock_fundamentals.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    daily = _start(scripts, root, "Daily")
    weekly = None
    try:
        deadline = time.monotonic() + 30
        while not running.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not running.exists():
            pytest.skip("a real scheduled data job holds the lock on this machine")
        weekly = _start(scripts, root, "Weekly")
        assert daily.wait(60) == 0
        assert weekly.wait(60) == 0
    finally:
        for process in (daily, weekly):
            if process is not None and process.poll() is None:
                process.kill()

    daily_end = next(line for line in _log(root, "Daily") if " end Daily " in line)
    weekly_log = _log(root, "Weekly")
    weekly_start = next(line for line in weekly_log if line.endswith(" start Weekly"))
    assert any(
        line.endswith(" waiting for the other data job to end") for line in weekly_log
    )
    assert weekly_start.split()[0] >= daily_end.split()[0]
