"""Session fixtures: the sample pipeline is built once per pytest run in a clock-frozen subprocess."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from refactor_parity._harness import CAPTURE_TIMEOUT_SECONDS, build_capture_root, remove_capture_root, run_capture


def _capture(now_offset_days: int) -> Iterator[dict[str, object]]:
    # The root holds junctions/symlinks back into the checkout, so it lives in the REAL system temp (captured by
    # tests/conftest.py before it redirects TEMP into the checkout), never inside the checkout.
    base = Path(os.environ.get("ETF_COCKPIT_TEST_SYSTEM_TEMP") or tempfile.gettempdir()) / "etf_ai_cockpit_parity"
    base.mkdir(parents=True, exist_ok=True)
    result = None
    run_uid = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if run_uid:
        # xdist gives every worker its own session fixtures. The workers of one run share one capture: the worker
        # that creates the claim file builds it, the others wait for the result file.
        for stale in base.glob("shared_*"):
            if time.time() - stale.stat().st_mtime > 86400:
                shutil.rmtree(stale, ignore_errors=True)
        shared = base / f"shared_{run_uid}"
        shared.mkdir(exist_ok=True)
        result = shared / f"capture_{now_offset_days}.json"
        try:
            os.close(os.open(shared / f"capture_{now_offset_days}.claim", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS + 300
            while not result.exists():
                if time.monotonic() > deadline:
                    raise AssertionError(f"shared capture {result} was not built in time") from None
                time.sleep(1)
            payload = json.loads(result.read_text(encoding="utf-8"))
            if "capture_error" in payload:
                raise AssertionError(f"shared capture failed in another worker: {payload['capture_error']}")
            yield payload
            return
    def publish(payload: dict[str, object]) -> None:
        if result is not None:
            partial = result.with_suffix(".partial")
            partial.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(partial, result)

    work = Path(tempfile.mkdtemp(prefix="run_", dir=base))
    root = work / "root"
    try:
        try:
            build_capture_root(root)
            payload = run_capture(root, work / "capture.json", now_offset_days=now_offset_days)
        except BaseException as exc:
            publish({"capture_error": f"{type(exc).__name__}: {exc}"})
            raise
        publish(payload)
        yield payload
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
