from __future__ import annotations

import copy

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
