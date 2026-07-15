from __future__ import annotations

import sys
import os
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_repo_pytest_temp = ROOT / "logs" / "pytest_system_tmp"
if os.name == "nt" and len(str(_repo_pytest_temp)) > 90:
    # Linked worktrees can exceed Windows' legacy path limit before the test
    # payload is created. Keep the same deterministic case layout in the
    # system temp directory when the repository path itself is too long.
    PYTEST_TEMP = Path(tempfile.gettempdir()) / "etf_ai_cockpit_pytest"
else:
    PYTEST_TEMP = _repo_pytest_temp
PYTEST_TEMP.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(PYTEST_TEMP)
os.environ["TMP"] = str(PYTEST_TEMP)
os.environ["TMPDIR"] = str(PYTEST_TEMP)
tempfile.tempdir = str(PYTEST_TEMP)


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    path = PYTEST_TEMP / "cases" / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
