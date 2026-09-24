"""The standard packaged test collection must exercise the offline V2/AGY harness."""
from pathlib import Path
import subprocess
import sys


def test_packaged_collection_includes_offline_harness() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "docs/codex-config", "-p", "test_*.py", "-v"],
        cwd=root, capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
