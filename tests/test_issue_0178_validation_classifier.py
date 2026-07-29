from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import validate_app
from scripts import classify_validation
from scripts.classify_validation import build_report, validation_summary_failures


def test_classifier_tiers_and_stable_reason_report() -> None:
    evidence = build_report(["docs/product-completion/PROGRESS.md"])
    ordinary = build_report(["src/etf_cockpit/app/page.py"])
    high = build_report(["src/etf_cockpit/data/migrations/v2.py"])
    certification = build_report(["docs/product-completion/certification/final.json"])

    assert [report["tier"] for report in (evidence, ordinary, high, certification)] == [
        "E",
        "O",
        "H",
        "C",
    ]
    assert json.dumps(evidence, sort_keys=True) == json.dumps(
        build_report(["docs/product-completion/PROGRESS.md"]), sort_keys=True
    )


def test_classifier_fails_unknown_and_protected_tooling_upward() -> None:
    assert build_report(["unexpected.file"])["tier"] == "H"
    assert build_report(["scripts/update_programme_status.py"])["tier"] == "H"
    assert build_report([".github/workflows/release-gate.yml"])["tier"] == "H"


def test_ordinary_cadence_requires_central_gate_after_two_issues() -> None:
    first = build_report(["src/etf_cockpit/app/page.py"], ordinary_issues_since_full_gate=1)
    second = build_report(["src/etf_cockpit/app/page.py"], ordinary_issues_since_full_gate=2)

    assert first["package_gate_required"] is False
    assert second["package_gate_required"] is True
    assert second["ordinary_full_gate_cadence"]["threshold"] == 2


def test_high_risk_fixtures_require_platform_gate() -> None:
    fixtures = [
        "src/etf_cockpit/persistence/store.py",
        "src/etf_cockpit/data/migrations/v3.py",
        "tests/test_concurrency.py",
        "src/etf_cockpit/core/finance/returns.py",
        "configs/security_policy.yaml",
        "packaging/windows/build.ps1",
        "issues/programme_control_state.json",
        "src/etf_cockpit/broker/orders.py",
    ]
    assert all(build_report([path])["package_gate_required"] for path in fixtures)


def test_evidence_tier_skips_packages_only_with_exact_reusable_identities() -> None:
    hashes = {
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "source_sha256": "c" * 64,
        "dependency_sha256": "d" * 64,
        "product_tree_sha256": "e" * 64,
        "policy_sha256": "f" * 64,
        "artifact_manifest_sha256": "1" * 64,
        "environment_sha256": "2" * 64,
        "execution_allowed": False,
    }
    path = "docs/product-completion/PROGRESS.md"
    exact = build_report(
        [path], reusable_evidence=hashes, expected_evidence=hashes
    )
    missing = build_report([path])
    forged = build_report(
        [path],
        reusable_evidence={**hashes, "execution_allowed": True},
        expected_evidence=hashes,
    )

    assert exact["package_gate_required"] is False
    assert exact["evidence_reuse"]["authorized"] is True
    assert missing["package_gate_required"] is True
    assert forged["package_gate_required"] is True

    wrong_hash = {**hashes, "product_tree_sha256": "0" * 64}
    mismatch = build_report(
        [path], reusable_evidence=wrong_hash, expected_evidence=hashes
    )
    assert mismatch["package_gate_required"] is True


def test_evidence_tier_is_a_closed_projection_allowlist() -> None:
    assert build_report(["docs/product-completion/PROGRESS.md"])["tier"] == "E"
    assert build_report(
        [
            "issues/programme_control_state.json",
            "issues/issue_registry.json",
            ".github/status-transition-guard-manifest.json",
            "docs/product-completion/CURRENT_STATUS.json",
        ],
        reusable_evidence=None,
    )["tier"] == "E"
    assert build_report(["docs/architecture/SDD.md"])["tier"] == "H"
    assert build_report(["plans/BATCH.md"])["tier"] == "H"


def test_identical_forged_head_files_cannot_authorize_e_reuse(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    head = base
    forged = {"base_sha": base, "head_sha": head}
    (tmp_path / "reuse.json").write_text(json.dumps(forged), encoding="utf-8")
    (tmp_path / "expected.json").write_text(json.dumps(forged), encoding="utf-8")

    assert (
        classify_validation.derive_trusted_evidence(
            tmp_path,
            base=base,
            head=head,
            artifact_manifest="expected.json",
        )
        is None
    )


def test_store_modules_and_tests_require_platform_gate_without_substring_spillover() -> None:
    for path in (
        "src/etf_cockpit/data/universe_store.py",
        "tests/test_universe_store.py",
    ):
        report = build_report([path])
        assert report["tier"] == "H"
        assert report["package_gate_required"] is True

    boundary = build_report(["src/etf_cockpit/app/restore.py"])
    assert boundary["tier"] == "O"
    assert boundary["package_gate_required"] is False


def test_terminal_summary_accepts_every_valid_conditional_combination() -> None:
    common = {"classifier": "success", "preflight": "success", "supply_chain": "success"}

    assert not validation_summary_failures(
        package_gate_required=False, release_gate="skipped", **common
    )
    assert not validation_summary_failures(
        package_gate_required=True, release_gate="success", **common
    )
    assert validation_summary_failures(
        package_gate_required=True, release_gate="skipped", **common
    )
    assert validation_summary_failures(
        package_gate_required=False,
        release_gate="skipped",
        classifier="success",
        preflight="failure",
        supply_chain="success",
    )


def test_clean_checkout_uses_explicit_base_and_head_for_changed_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tests = tmp_path / "tests"
    tests.mkdir()
    changed_test = tests / "test_changed.py"
    changed_test.write_text("def test_before():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    changed_test.write_text("def test_after():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_BASE_SHA", base)
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_HEAD_SHA", head)

    assert validate_app._changed_test_paths(tmp_path) == ["tests/test_changed.py"]


def test_invalid_explicit_diff_refs_fail_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validate_app, "_git", lambda _root, *_args: "")
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_BASE_SHA", "invalid")
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_HEAD_SHA", "0" * 40)

    with pytest.raises(ValueError, match="explicit validation base/head"):
        validate_app._changed_test_paths(tmp_path)


def test_workflow_has_unconditional_bookends_and_single_source_scan() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
    supply_workflow = (root / ".github/workflows/supply-chain.yml").read_text(encoding="utf-8")

    assert "concurrency:" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "classifier:" in workflow
    assert "base_sha: ${{ steps.classify.outputs.base_sha }}" in workflow
    assert "ETF_COCKPIT_VALIDATION_BASE_SHA: ${{ needs.classifier.outputs.base_sha }}" in workflow
    assert "validation-summary:" in workflow
    assert "if: always()" in workflow
    assert "needs.classifier.outputs.package_gate_required == 'true'" in workflow
    assert "scripts/validate_app.py --root . --changed" in workflow
    assert workflow.count("scripts/generate_programme.py --root . --check") == 2
    assert ".github/issue-transitions/reuse-evidence.json" in workflow
    assert 'git diff --check "$ETF_COCKPIT_VALIDATION_BASE_SHA" "$ETF_COCKPIT_VALIDATION_HEAD_SHA" --' in workflow
    assert "tests/test_button_contracts.py tests/test_architecture_boundaries.py" in workflow
    assert "scripts/smoke_app.py --mode offline --timeout 30" in workflow
    assert workflow.count("scripts/supply_chain_scan.py") == 1
    assert "workflow_dispatch:" in supply_workflow
    assert "pull_request:" not in supply_workflow
    assert "push:" not in supply_workflow
