from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-gate.yml"

STEPS_AFTER_PROFILE = [
    "Verify protected environment",
    "Run lint and typing gates",
    "Run protected release gate",
    "Publish failure digest",
    "Upload release evidence",
]


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _names(job: dict[str, Any]) -> list[str]:
    return [step["name"] for step in job["steps"]]


def test_install_runs_before_isolated_profile_and_profile_keeps_pip_cache_dir() -> None:
    job = _jobs()["release-gate"]
    names = _names(job)
    install = names.index("Install pinned release environment")
    profile = names.index("Configure isolated user profile")
    assert install < profile
    assert "PIP_CACHE_DIR=" in job["steps"][profile]["run"]


def test_release_gate_needs_only_classifier() -> None:
    assert _jobs()["release-gate"]["needs"] == ["classifier"]


def test_validation_summary_still_requires_all_evidence_jobs() -> None:
    needs = _jobs()["validation-summary"]["needs"]
    for job in ("classifier", "preflight", "supply-chain", "release-gate"):
        assert job in needs


def test_release_gate_steps_after_profile_are_unchanged() -> None:
    names = _names(_jobs()["release-gate"])
    assert names[names.index("Configure isolated user profile") + 1 :] == STEPS_AFTER_PROFILE
