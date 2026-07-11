from __future__ import annotations

import sys
import os
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PYTEST_TEMP = ROOT / "logs" / "pytest_system_tmp"
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
