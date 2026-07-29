from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import validation_summary
from scripts.validation_summary import validate_summary


def _summary(tier: str) -> dict:
    package = tier in {"H", "C"}
    return {
        "schema_version": "validation-summary.v1",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "tier": tier,
        "package_gate_required": package,
        "reason": ["protected-control"] if package else ["exact-evidence"],
        "jobs": {
            "classifier": "required",
            "preflight": "required",
            "supply_chain": "required",
            "release_windows": "required" if package else "skipped",
            "release_linux": "required" if package else "skipped",
        },
        "platform_junit": {"windows": 4, "linux": 4} if package else {},
        "artifacts": [
            {"path": "classifier.json", "sha256": "c" * 64, "present": True},
            *(
                [
                    {"path": "release-windows/junit.xml", "sha256": "e" * 64, "present": True},
                    {"path": "release-linux/junit.xml", "sha256": "f" * 64, "present": True},
                ]
                if package
                else []
            ),
        ],
        "job_results": {
            "classifier": "success",
            "preflight": "success",
            "supply_chain": "success",
            "release": "success" if package else "skipped",
        },
        "identities": {key: "d" * 64 for key in ("environment", "source", "dependency", "product_tree", "policy")},
        "controls": {
            "guards_passed": True,
            "freshness_passed": True,
            "evidence_reuse_authorized": tier == "E",
            "automation_authority": "read-only",
            "apply_authority": False,
        },
    }


def test_e_and_h_terminal_summary_fixtures() -> None:
    assert validate_summary(_summary("E")) == []
    assert validate_summary(_summary("H")) == []


def test_terminal_summary_rejects_missing_and_forged_artifacts() -> None:
    missing = _summary("H")
    missing["platform_junit"].pop("windows")
    assert "terminal summary platform JUnit counts are required" in validate_summary(missing)
    forged = copy.deepcopy(_summary("E"))
    forged["artifacts"][0]["sha256"] = "forged"
    assert "terminal summary artifact presence/hashes are incomplete" in validate_summary(forged)
    absent_results = _summary("E")
    absent_results.pop("job_results")
    assert "terminal summary job results are inconsistent" in validate_summary(absent_results)


def test_terminal_collection_preserves_platform_artifact_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = tmp_path / "validation-evidence"
    classifier = artifacts / "validation-classifier-head" / "classifier.json"
    classifier.parent.mkdir(parents=True)
    classifier.write_text(
        json.dumps(
            {
                "tier": "H",
                "package_gate_required": True,
                "reasons": ["protected-control"],
                "evidence_reuse": {"authorized": False},
            }
        ),
        encoding="utf-8",
    )
    for platform in ("linux", "windows"):
        junit = artifacts / f"release-gate-head-{platform}" / "junit-full.xml"
        junit.parent.mkdir(parents=True)
        junit.write_text('<testsuite tests="3" />\n', encoding="utf-8")
    monkeypatch.setattr(validation_summary, "_tree_identity", lambda *_args: "d" * 64)

    report = validation_summary.collect_summary(
        tmp_path,
        artifacts,
        base="a" * 40,
        head="b" * 40,
        job_results={
            "classifier": "success",
            "preflight": "success",
            "supply_chain": "success",
            "release": "success",
        },
    )

    assert report["platform_junit"] == {"windows": 3, "linux": 3}
    assert validate_summary(report) == []


def test_workflow_keeps_artifact_names_and_writes_failed_terminal_evidence() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-gate.yml"
    ).read_text(encoding="utf-8")

    assert "merge-multiple: true" not in workflow
    build_step = workflow.index("- name: Build and validate authoritative terminal evidence")
    assert "if: always()" in workflow[build_step : build_step + 120]
