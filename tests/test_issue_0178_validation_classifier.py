from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import validate_app
from scripts import classify_validation
from scripts.classify_validation import (
    build_report,
    derive_ordinary_gate_cadence,
    parallel_pilot_plan,
    validation_summary_failures,
)


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


def test_status_completion_candidate_remains_exact_evidence_tier() -> None:
    report = build_report(
        [".github/issue-transitions/post-merge-control-candidate.json"]
    )

    assert report["tier"] == "E"
    assert report["paths"] == [
        {
            "path": ".github/issue-transitions/post-merge-control-candidate.json",
            "tier": "E",
            "reason": "allowlisted-semantic-event-or-projection",
        }
    ]


def test_classifier_fails_unknown_and_protected_tooling_upward() -> None:
    assert build_report(["unexpected.file"])["tier"] == "H"
    assert build_report(["scripts/update_programme_status.py"])["tier"] == "H"
    assert build_report([".github/workflows/release-gate.yml"])["tier"] == "H"


def test_ordinary_cadence_requires_central_gate_after_two_issues() -> None:
    missing = build_report(["src/etf_cockpit/app/page.py"])
    first = build_report(["src/etf_cockpit/app/page.py"], ordinary_issues_since_full_gate=1)
    second = build_report(["src/etf_cockpit/app/page.py"], ordinary_issues_since_full_gate=2)

    assert missing["package_gate_required"] is True
    assert missing["ordinary_full_gate_cadence"]["known"] is False
    assert first["package_gate_required"] is False
    assert second["package_gate_required"] is True
    assert second["ordinary_full_gate_cadence"]["threshold"] == 2


def _cadence_commit(root: Path, relative: str, value: str, message: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _cadence_fixture(root: Path, ordinary_count: int, *, reset: bool = False) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    _cadence_commit(root, "scripts/protected.py", "H\n", "nearest H reset")
    if reset:
        _cadence_commit(root, "src/ordinary.py", "before-reset\n", "old O")
        _cadence_commit(root, "scripts/reset.py", "H again\n", "second H reset")
    _cadence_commit(root, "docs/product-completion/PROGRESS.md", "E\n", "ignored E")
    for index in range(ordinary_count):
        _cadence_commit(root, "src/ordinary.py", f"O {index}\n", f"ordinary {index}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    subprocess.run(["git", "branch", "main", head], cwd=root, check=True)
    return head


@pytest.mark.parametrize("ordinary_count", [0, 1, 2])
def test_first_parent_cadence_counts_zero_one_and_two_ordinary_commits(
    tmp_path: Path, ordinary_count: int
) -> None:
    head = _cadence_fixture(tmp_path, ordinary_count)
    cadence = derive_ordinary_gate_cadence(tmp_path, base=head, main_ref="main")

    assert cadence["known"] is True
    assert cadence["source"] == "exact-first-parent-origin-main"
    assert cadence["issues_since_last_full_gate"] == ordinary_count
    assert cadence["due"] is (ordinary_count >= 1)


def test_first_parent_cadence_resets_at_nearest_high_risk_commit(tmp_path: Path) -> None:
    head = _cadence_fixture(tmp_path, 1, reset=True)
    cadence = derive_ordinary_gate_cadence(tmp_path, base=head, main_ref="main")

    assert cadence["known"] is True
    assert cadence["issues_since_last_full_gate"] == 1
    assert cadence["due"] is True
    assert cadence["reason"] == "counted-first-parent-since-nearest-H-C"


def test_unknown_cadence_fails_upward_for_stale_and_malformed_inputs(tmp_path: Path) -> None:
    _cadence_fixture(tmp_path, 1)
    stale_base = subprocess.check_output(
        ["git", "rev-parse", "main~1"], cwd=tmp_path, text=True
    ).strip()
    stale = derive_ordinary_gate_cadence(tmp_path, base=stale_base, main_ref="main")
    malformed = derive_ordinary_gate_cadence(tmp_path, base="bad", main_ref="main")

    assert stale["known"] is False and stale["due"] is True
    assert stale["source"] == "exact-first-parent-origin-main"
    assert stale["reason"] == "stale-pr-base"
    assert malformed["known"] is False
    assert build_report(
        ["src/etf_cockpit/app/page.py"],
        cadence={"known": False, "issues_since_last_full_gate": None, "due": True},
    )["package_gate_required"] is True


def test_cadence_without_a_reset_boundary_is_unknown(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    head = _cadence_commit(tmp_path, "src/ordinary.py", "ordinary\n", "ordinary without reset")
    subprocess.run(["git", "branch", "main", head], cwd=tmp_path, check=True)

    cadence = derive_ordinary_gate_cadence(tmp_path, base=head, main_ref="main")

    assert cadence["known"] is False
    assert cadence["reason"] == "missing-reset-boundary"
    assert cadence["due"] is True


def test_negative_explicit_cadence_override_fails_upward(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _cadence_fixture(tmp_path, 0)

    assert classify_validation.main(
        [
            "--root",
            str(tmp_path),
            "--base",
            head,
            "--head",
            head,
            "--changed-file",
            "src/etf_cockpit/app/page.py",
            "--ordinary-issues-since-full-gate",
            "-1",
        ]
    ) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ordinary_full_gate_cadence"] == {
        "due": True,
        "issues_since_last_full_gate": -1,
        "known": False,
        "reason": "malformed-negative-cadence-override",
        "source": "explicit-cli-cadence",
        "threshold": 2,
    }
    assert report["package_gate_required"] is True


def test_parallel_pilot_selection_is_additive_and_report_only() -> None:
    unrelated = parallel_pilot_plan(["docs/product-completion/DELIVERY_WORKFLOW.md"], tier="H")
    mechanics = parallel_pilot_plan(["scripts/profile_parallel_pytest.py"], tier="H")
    workflow_mechanics = parallel_pilot_plan([".github/workflows/release-gate.yml"], tier="H")
    isolation = parallel_pilot_plan(["tests/test_concurrency.py"], tier="H")
    certification = parallel_pilot_plan(["docs/product-completion/certification/final.json"], tier="C")
    manual = parallel_pilot_plan(["docs/notes.md"], tier="H", trigger="manual")
    full = parallel_pilot_plan(["docs/notes.md"], tier="H", trigger="manual-full")
    manual_mechanics = parallel_pilot_plan(
        ["scripts/profile_parallel_pytest.py"], tier="H", trigger="manual"
    )
    manual_certification = parallel_pilot_plan(
        ["docs/product-completion/certification/final.json"], tier="C", trigger="manual"
    )

    assert unrelated["parallel_pilot_required"] is False
    assert unrelated["parallel_pilot_repetitions"] == 0
    assert mechanics["parallel_pilot_repetitions"] == 2
    assert workflow_mechanics["parallel_pilot_repetitions"] == 2
    assert isolation["parallel_pilot_repetitions"] == 2
    assert certification["parallel_pilot_repetitions"] == 2
    assert manual["parallel_pilot_required"] is True
    assert manual["parallel_pilot_repetitions"] == 1
    assert full["parallel_pilot_repetitions"] == 2
    assert manual_mechanics["parallel_pilot_repetitions"] == 2
    assert manual_mechanics["parallel_pilot_reason"] == "pilot-mechanics-or-ISSUE-0180-change"
    assert manual_certification["parallel_pilot_repetitions"] == 2
    drift = build_report([], pilot_trigger="scheduled")
    assert drift["parallel_pilot_required"] is True
    assert drift["package_gate_required"] is False


def test_parallel_pilot_reason_is_hash_seed_deterministic() -> None:
    root = Path(__file__).resolve().parents[1]
    code = (
        "import json; from scripts.classify_validation import parallel_pilot_plan; "
        "print(json.dumps(parallel_pilot_plan(["
        "'tests/test_concurrency.py','requirements-release.txt'], tier='H'), sort_keys=True))"
    )
    outputs = {
        subprocess.check_output(
            [sys.executable, "-c", code],
            cwd=root,
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            text=True,
        ).strip()
        for seed in range(1, 9)
    }

    assert len(outputs) == 1
    report = json.loads(outputs.pop())
    assert report["parallel_pilot_reason"] == "release-dependency-or-python-environment-change"


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
    assert build_report(
        ["docs/product-completion/programme/phases/phase-01-governance-scope.md"]
    )["tier"] == "E"
    assert build_report(["docs/product-completion/programme/roadmap.md"])["tier"] == "E"
    assert build_report(
        ["docs/product-completion/programme/phases/phase-02-data.md"]
    )["tier"] == "E"
    for generated_path in (
        "docs/product-completion/programme/git-workflow.md",
        "docs/product-completion/programme/implementation-order.md",
        "docs/product-completion/programme/prompt-2-handoff.md",
        "docs/product-completion/programme/test-and-performance-strategy.md",
        "README.md",
        "CHANGELOG.md",
        "issues/open.md",
    ):
        assert build_report([generated_path])["tier"] == "E"
    assert build_report(["docs/product-completion/programme/notes.md"])["tier"] == "H"
    assert build_report(["docs/product-completion/programme/roadmap.md.bak"])["tier"] == "H"
    assert build_report(["plans/ACTIVE_CODEX_GOAL.md"])["tier"] == "E"


def test_checkpoint_chronology_allowlist_is_narrow_and_content_independent() -> None:
    positive = [
        "plans/ACTIVE_CODEX_GOAL.md",
        "plans/BATCH-B04-ANALYSIS-SPINE.md",
        "plans/BATCH-B02-DATA-SPINE-CONTINUATION.md",
    ]
    negative = [
        "plans/BATCH.md",
        "plans/ATOMIC_FAST_PATH_METRICS.md",
        "plans/BATCH-DOCS-SDD-20260802.md",
        "plans/BATCH-B04-ANALYSIS-SPINE.txt",
        "plans/arbitrary-checkpoint.md",
    ]

    assert all(build_report([path])["tier"] == "E" for path in positive)
    assert all(build_report([path])["tier"] == "H" for path in negative)
    assert build_report(
        [positive[0], "scripts/classify_validation.py"]
    )["tier"] == "H"
    assert build_report(["AGENTS.md"])["tier"] == "H"
    assert build_report(["docs/product-completion/DELIVERY_WORKFLOW.md"])["tier"] == "H"


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
            reusable_evidence=forged,
        )
        is None
    )


def _commit(tmp_path: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=tmp_path, check=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()


def _evidence_repo(tmp_path: Path) -> tuple[str, str, str, str, dict[str, object]]:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    files = {
        "src/product.py": "VALUE = 1\n",
        "scripts/tool.py": "VALUE = 1\n",
        "configs/policy.json": "{}\n",
        "pyproject.toml": "[project]\nname = 'fixture'\nversion = '1'\n",
        "requirements-release.txt": "",
        "requirements-release-parsers.txt": "",
        "AGENTS.md": "execution_allowed=false\n",
        ".github/workflows/gate.yml": "name: gate\n",
        ".github/issue-transitions/protected-evidence-manifest.json": "{}\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    reviewed_base = _commit(tmp_path, "reviewed base")
    (tmp_path / "review.txt").write_text("H gate passed\n", encoding="utf-8")
    reviewed_head = _commit(tmp_path, "reviewed head")
    (tmp_path / "prior-evidence.txt").write_text("merged\n", encoding="utf-8")
    current_base = _commit(tmp_path, "current base")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "projection.md").write_text("complete\n", encoding="utf-8")
    current_head = _commit(tmp_path, "current E head")
    seed: dict[str, object] = {
        "base_sha": reviewed_base,
        "head_sha": reviewed_head,
        "source_sha256": "0" * 64,
        "dependency_sha256": "0" * 64,
        "product_tree_sha256": "0" * 64,
        "policy_sha256": "0" * 64,
        "artifact_manifest_sha256": "0" * 64,
        "environment_sha256": "0" * 64,
        "execution_allowed": False,
    }
    return reviewed_base, reviewed_head, current_base, current_head, seed


def test_prior_reviewed_head_authorizes_later_committed_e_head(tmp_path: Path) -> None:
    reviewed_base, reviewed_head, current_base, current_head, seed = _evidence_repo(
        tmp_path
    )

    expected = classify_validation.derive_trusted_evidence(
        tmp_path,
        base=current_base,
        head=current_head,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
        reusable_evidence=seed,
    )

    assert expected is not None
    assert expected["base_sha"] == reviewed_base
    assert expected["head_sha"] == reviewed_head
    report = build_report(
        ["docs/product-completion/PROGRESS.md"],
        reusable_evidence=expected,
        expected_evidence=expected,
    )
    assert report["evidence_reuse"]["authorized"] is True
    assert report["package_gate_required"] is False


def test_head_only_forged_sidecar_cannot_authorize_reuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, current_base, _, seed = _evidence_repo(tmp_path)
    expected = classify_validation.derive_trusted_evidence(
        tmp_path,
        base=current_base,
        head=current_base,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
        reusable_evidence=seed,
    )
    assert expected is not None
    subprocess.run(["git", "checkout", "-q", current_base], cwd=tmp_path, check=True)
    sidecar = tmp_path / ".github" / "issue-transitions" / "reuse-evidence.json"
    sidecar.write_text(json.dumps(expected), encoding="utf-8")
    injected_head = _commit(tmp_path, "inject forged sidecar")

    assert (
        classify_validation.main(
            [
                "--root",
                str(tmp_path),
                "--base",
                current_base,
                "--head",
                injected_head,
                "--reuse-evidence",
                str(sidecar),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["tier"] == "E"
    assert report["evidence_reuse"]["authorized"] is False
    assert report["package_gate_required"] is True


def test_base_anchored_prior_evidence_authorizes_cli_reuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, current_base, _, seed = _evidence_repo(tmp_path)
    expected = classify_validation.derive_trusted_evidence(
        tmp_path,
        base=current_base,
        head=current_base,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
        reusable_evidence=seed,
    )
    assert expected is not None
    subprocess.run(["git", "checkout", "-q", current_base], cwd=tmp_path, check=True)
    sidecar = tmp_path / ".github" / "issue-transitions" / "reuse-evidence.json"
    sidecar.write_text(json.dumps(expected), encoding="utf-8")
    anchored_base = _commit(tmp_path, "anchor prior evidence")
    projection = tmp_path / "docs" / "product-completion" / "PROGRESS.md"
    projection.parent.mkdir(parents=True)
    projection.write_text("integrated\n", encoding="utf-8")
    current_head = _commit(tmp_path, "E projection")

    assert (
        classify_validation.main(
            [
                "--root",
                str(tmp_path),
                "--base",
                anchored_base,
                "--head",
                current_head,
                "--reuse-evidence",
                str(sidecar),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["tier"] == "E"
    assert report["evidence_reuse"]["authorized"] is True
    # O-tier cadence does not invalidate exact E-tier evidence reuse.
    assert report["package_gate_required"] is False
    assert report["ordinary_full_gate_cadence"]["known"] is False
    assert report["ordinary_full_gate_cadence"]["source"] == "exact-first-parent-origin-main"


def test_reuse_rejects_reviewed_head_outside_current_base_ancestry(
    tmp_path: Path,
) -> None:
    _, reviewed_head, current_base, current_head, seed = _evidence_repo(tmp_path)
    subprocess.run(["git", "branch", "current-line", current_head], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-q", reviewed_head], cwd=tmp_path, check=True)
    (tmp_path / "divergent.txt").write_text("reviewed elsewhere\n", encoding="utf-8")
    divergent_head = _commit(tmp_path, "divergent reviewed head")
    seed["head_sha"] = divergent_head

    assert (
        classify_validation.derive_trusted_evidence(
            tmp_path,
            base=current_base,
            head=current_head,
            artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
            reusable_evidence=seed,
        )
        is None
    )


def test_reuse_rejects_current_head_outside_current_base_ancestry(
    tmp_path: Path,
) -> None:
    _, reviewed_head, current_base, _, seed = _evidence_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", reviewed_head], cwd=tmp_path, check=True)
    (tmp_path / "divergent.txt").write_text("E elsewhere\n", encoding="utf-8")
    divergent_head = _commit(tmp_path, "divergent E head")

    assert (
        classify_validation.derive_trusted_evidence(
            tmp_path,
            base=current_base,
            head=divergent_head,
            artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
            reusable_evidence=seed,
        )
        is None
    )


@pytest.mark.parametrize(
    ("changed_path", "content"),
    [
        ("src/product.py", "VALUE = 2\n"),
        ("requirements-release.txt", "changed==1\n"),
        ("configs/policy.json", '{"changed": true}\n'),
        (
            ".github/issue-transitions/protected-evidence-manifest.json",
            '{"changed": true}\n',
        ),
    ],
)
def test_reuse_rejects_protected_identity_changes(
    tmp_path: Path, changed_path: str, content: str
) -> None:
    _, _, current_base, _, seed = _evidence_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", current_base], cwd=tmp_path, check=True)
    (tmp_path / changed_path).write_text(content, encoding="utf-8")
    changed_head = _commit(tmp_path, "change protected identity")

    assert (
        classify_validation.derive_trusted_evidence(
            tmp_path,
            base=current_base,
            head=changed_head,
            artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
            reusable_evidence=seed,
        )
        is None
    )


def test_reuse_rejects_protected_identity_change_before_current_base(
    tmp_path: Path,
) -> None:
    _, _, current_base, _, seed = _evidence_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", current_base], cwd=tmp_path, check=True)
    (tmp_path / "src" / "product.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed_base = _commit(tmp_path, "protected change before E base")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "projection.md").write_text("integrated\n", encoding="utf-8")
    changed_head = _commit(tmp_path, "E projection")

    assert (
        classify_validation.derive_trusted_evidence(
            tmp_path,
            base=changed_base,
            head=changed_head,
            artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
            reusable_evidence=seed,
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

    boundary = build_report(
        ["src/etf_cockpit/app/restore.py"], ordinary_issues_since_full_gate=0
    )
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
    assert "ETF_COCKPIT_VALIDATION_HEAD_SHA: ${{ needs.classifier.outputs.head_sha }}" in workflow
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
