from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality_programme import (
    SUITES,
    run_programme,
)


def test_quality_programme_writes_timed_json_and_markdown_with_bounded_scope(tmp_path: Path) -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "1 passed in 0.01s\n", "")

    run = run_programme(tmp_path, output_dir=tmp_path / "quality", suite_ids=("load",), runner=runner)

    assert run.exit_code == 0
    assert run.report.status == "passed"
    assert run.report.suites[0]["suite_id"] == "load"
    assert run.report.suites[0]["duration_ms"] >= 0
    assert json.loads(run.json_path.read_text(encoding="utf-8"))["schema_version"] == "quality-programme.v1"
    markdown = run.markdown_path.read_text(encoding="utf-8")
    assert "quality programme" in markdown
    assert "hardening_required" in markdown
    assert "Network calls: `false`" in markdown


def test_quality_programme_returns_nonzero_and_redacts_failure_output(tmp_path: Path) -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "api_key=super-secret\n", "failed")

    run = run_programme(tmp_path, output_dir=tmp_path / "quality", suite_ids=("fault_injection",), runner=runner)

    assert run.exit_code == 1
    assert run.report.status == "failed"
    assert run.report.failures == ["fault_injection: exit code 1"]
    report_text = run.json_path.read_text(encoding="utf-8")
    assert "super-secret" not in report_text
    assert "redacted" in report_text


def test_quality_programme_rejects_unknown_suite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown quality suite"):
        run_programme(tmp_path, output_dir=tmp_path / "quality", suite_ids=("unknown",))


def test_quality_suite_inventory_covers_the_initial_issue0143_programmes() -> None:
    assert {suite.suite_id for suite in SUITES} == {
        "visual_e2e",
        "load",
        "soak",
        "fault_injection",
        "chaos_sandbox",
    }
