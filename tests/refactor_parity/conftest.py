"""Session fixtures: the sample pipeline is built once per pytest session in a clock-frozen subprocess."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from refactor_parity._harness import build_capture_root, remove_capture_root, run_capture


def _capture(now_offset_days: int) -> Iterator[dict[str, object]]:
    # The root holds junctions/symlinks back into the checkout, so it lives in the REAL system temp (captured by
    # tests/conftest.py before it redirects TEMP into the checkout), never inside the checkout.
    base = Path(os.environ.get("ETF_COCKPIT_TEST_SYSTEM_TEMP") or tempfile.gettempdir()) / "etf_ai_cockpit_parity"
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run_", dir=base))
    root = work / "root"
    try:
        build_capture_root(root)
        yield run_capture(root, work / "capture.json", now_offset_days=now_offset_days)
    finally:
        remove_capture_root(root)  # unlinks the junctions first: never follows a link into the checkout
        shutil.rmtree(work, ignore_errors=True)


@pytest.fixture(scope="session")
def pipeline_capture() -> Iterator[dict[str, object]]:
    """Sections captured with the frozen clock (today 2026-09-30, now 2026-09-30T12:00Z)."""

    yield from _capture(0)


@pytest.fixture(scope="session")
def shifted_pipeline_capture() -> Iterator[dict[str, object]]:
    """Same pipeline with the frozen ``now`` moved +400 days and +7 hours (wall-clock independence check)."""

    yield from _capture(400)
