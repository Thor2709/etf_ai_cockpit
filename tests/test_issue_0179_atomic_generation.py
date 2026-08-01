from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import generate_programme


def _write(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_atomic_publish_rolls_back_the_complete_prior_set(tmp_path: Path) -> None:
    root = tmp_path / "root"
    stage = tmp_path / "stage"
    outputs = frozenset({"a.json", "nested/b.md"})
    for relative in outputs:
        _write(root, relative, b"prior")
        _write(stage, relative, b"next")
    _write(stage, generate_programme.MANIFEST_PATH.as_posix(), b"manifest")

    def fail_validation(state: str, _journal: Path) -> None:
        if state == "prepared":
            raise OSError("injected publication failure")

    with pytest.raises(OSError, match="injected publication failure"):
        generate_programme.atomic_publish(root, stage, outputs, lifecycle_hook=fail_validation)

    assert {relative: (root / relative).read_bytes() for relative in outputs} == {
        relative: b"prior" for relative in outputs
    }
    assert not (root / generate_programme.MANIFEST_PATH).exists()


def test_interrupted_group_is_recovered_before_next_publication(tmp_path: Path) -> None:
    root = tmp_path / "root"
    stage = tmp_path / "stage"
    outputs = frozenset({"a.json", "nested/b.md"})
    for relative in outputs:
        _write(root, relative, b"prior")
        _write(stage, relative, b"next")
    _write(stage, generate_programme.MANIFEST_PATH.as_posix(), b"manifest")

    def interrupt(state: str, _journal: Path) -> None:
        if state == "committing":
            raise generate_programme.atomic_io.AtomicWriteInterrupted("simulated process interruption")

    with pytest.raises(generate_programme.atomic_io.AtomicWriteInterrupted):
        generate_programme.atomic_publish(root, stage, outputs, lifecycle_hook=interrupt)

    generate_programme.atomic_publish(root, stage, outputs)
    assert all((root / relative).read_bytes() == b"next" for relative in outputs)


def test_manifest_is_byte_clean_and_rejects_any_mandatory_omission(tmp_path: Path) -> None:
    outputs = frozenset({"CURRENT_STATUS.json", "PROGRESS.md"})
    for relative in outputs:
        _write(tmp_path, relative, relative.encode())
    first = generate_programme.build_manifest(tmp_path, outputs)
    second = generate_programme.build_manifest(tmp_path, outputs)
    assert first == second
    assert json.loads(first)["execution_allowed"] is False

    (tmp_path / "PROGRESS.md").unlink()
    with pytest.raises(ValueError, match="mandatory programme outputs are absent: PROGRESS.md"):
        generate_programme.build_manifest(tmp_path, outputs)


def test_manifest_text_hashes_are_independent_of_checkout_line_endings(tmp_path: Path) -> None:
    outputs = frozenset({"status.txt"})
    _write(tmp_path, "status.txt", b"first\r\nsecond\r\n")
    windows_manifest = generate_programme.build_manifest(tmp_path, outputs)
    _write(tmp_path, "status.txt", b"first\nsecond\n")

    assert generate_programme.build_manifest(tmp_path, outputs) == windows_manifest


def test_closed_manifest_covers_status_readiness_reconciliation_remote_and_sync_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_programme,
        "load_control_state",
        lambda _root: {
            "metadata": {"generation_base_commit": "a" * 40},
            "phase_definitions": [],
        },
    )
    outputs = generate_programme.required_outputs(tmp_path)
    expected = {
        "issues/programme_control_state.json",
        "docs/product-completion/CURRENT_STATUS.json",
        "docs/product-completion/PROGRESS.md",
        "docs/product-completion/programme/readiness.json",
        "docs/product-completion/reconciliation/2026-07-21-aaaaaaa/canonical-dag.json",
        "docs/product-completion/reconciliation/2026-07-21-aaaaaaa/github-remote-summary.json",
        "docs/product-completion/reconciliation/2026-07-21-aaaaaaa/github-sync-evidence.json",
        ".github/status-transition-guard-manifest.json",
    }
    assert expected <= outputs
    assert "docs/product-completion/DELIVERY_WORKFLOW.md" in outputs


def test_convergence_evidence_requires_zero_action_and_separate_authority(
    tmp_path: Path,
) -> None:
    prefix = "docs/product-completion/reconciliation/run"
    outputs = frozenset(
        {
            f"{prefix}/github-remote-summary.json",
            f"{prefix}/github-sync-evidence.json",
            f"{prefix}/github-sync-evidence.json.sha256",
        }
    )
    _write(
        tmp_path,
        f"{prefix}/github-remote-summary.json",
        json.dumps({"inventory_sha256": "a" * 64}).encode(),
    )
    evidence = {
        "schema_version": "etf-ai-cockpit.safe-sync-evidence/1.0",
        "repository": "Thor2709/etf_ai_cockpit",
        "apply_authority": False,
        "fresh_exact_plan_required_for_apply": True,
        "plan_semantic_sha256": "b" * 64,
        "remote_inventory_sha256": "a" * 64,
        "summary": {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0},
        "actions": [],
        "authority_reconciliation": {"accepted": True},
    }
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", json.dumps(evidence).encode())
    evidence_bytes = json.dumps(evidence).encode()
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", evidence_bytes)
    _write(
        tmp_path,
        f"{prefix}/github-sync-evidence.json.sha256",
        f"{__import__('hashlib').sha256(evidence_bytes).hexdigest()}  github-sync-evidence.json\n".encode(),
    )

    generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)

    evidence["authority_reconciliation"] = None
    offline_payload = json.dumps(evidence).encode()
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", offline_payload)
    _write(
        tmp_path,
        f"{prefix}/github-sync-evidence.json.sha256",
        f"{__import__('hashlib').sha256(offline_payload).hexdigest()}  github-sync-evidence.json\n".encode(),
    )
    generate_programme._validate_and_emit_convergence_evidence(
        tmp_path,
        outputs,
        require_authority_reconciliation=False,
    )
    with pytest.raises(ValueError, match="authority ledger"):
        generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)
    evidence["authority_reconciliation"] = {"accepted": True}

    evidence["apply_authority"] = True
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", json.dumps(evidence).encode())
    with pytest.raises(ValueError, match="must not grant GitHub apply authority"):
        generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)

    evidence["apply_authority"] = False
    evidence["summary"]["update"] = 1
    evidence["actions"] = [{"kind": "update", "stable_id": "ISSUE-0179"}]
    payload = json.dumps(evidence).encode()
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", payload)
    _write(
        tmp_path,
        f"{prefix}/github-sync-evidence.json.sha256",
        f"{__import__('hashlib').sha256(payload).hexdigest()}  github-sync-evidence.json\n".encode(),
    )
    with pytest.raises(ValueError, match="mandatory zero-action"):
        generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)


def test_convergence_rejects_empty_summary_and_mismatched_exact_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "docs/product-completion/reconciliation/run"
    outputs = frozenset(
        {
            f"{prefix}/github-remote-summary.json",
            f"{prefix}/github-sync-evidence.json",
            f"{prefix}/github-sync-evidence.json.sha256",
        }
    )
    _write(tmp_path, f"{prefix}/github-remote-summary.json", b'{"inventory_sha256":"a"}')
    evidence = {
        "schema_version": "etf-ai-cockpit.safe-sync-evidence/1.0",
        "repository": "Thor2709/etf_ai_cockpit",
        "apply_authority": False,
        "fresh_exact_plan_required_for_apply": True,
        "plan_semantic_sha256": "b" * 64,
        "remote_inventory_sha256": "a",
        "summary": {},
        "actions": [],
    }
    payload = json.dumps(evidence).encode()
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", payload)
    _write(
        tmp_path,
        f"{prefix}/github-sync-evidence.json.sha256",
        f"{__import__('hashlib').sha256(payload).hexdigest()}  github-sync-evidence.json\n".encode(),
    )
    with pytest.raises(ValueError, match="mandatory zero-action"):
        generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)

    monkeypatch.setattr(
        generate_programme.subprocess,
        "check_output",
        lambda command, **_kwargs: ("a" * 40 + "\n") if command[-1] == "HEAD" else ("b" * 40 + "\n"),
    )
    with pytest.raises(ValueError, match="fresh main"):
        generate_programme._verify_exact_head(tmp_path, "a" * 40, "origin/main")


def test_fresh_zero_action_readback_accepts_inventory_checksum_drift(
    tmp_path: Path,
) -> None:
    reviewed = tmp_path / "reviewed.sha256"
    generated = tmp_path / "generated.sha256"
    reviewed.write_text(f"{'a' * 64}  github-sync-evidence.json\n", encoding="utf-8")
    generated.write_text(f"{'b' * 64}  github-sync-evidence.json\n", encoding="utf-8")

    generate_programme._accept_reviewed_or_fresh_noop_sidecar(reviewed, generated)

    reviewed.write_text("not-a-reviewed-checksum\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed convergence checksum is invalid"):
        generate_programme._accept_reviewed_or_fresh_noop_sidecar(reviewed, generated)


def test_consecutive_main_advances_each_use_their_fresh_exact_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "a" * 40
    second = "b" * 40
    observed = iter((first, first, second, second))
    monkeypatch.setattr(
        generate_programme.subprocess,
        "check_output",
        lambda *_args, **_kwargs: next(observed) + "\n",
    )

    generate_programme._verify_exact_head(tmp_path, first, "origin/main")
    generate_programme._verify_exact_head(tmp_path, second, "origin/main")


def test_post_merge_workflow_is_read_only_exact_head_and_reviewable() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/programme-convergence.yml"
    ).read_text(encoding="utf-8")
    assert "contents: read" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "group: github-mutations-${{ github.repository }}" in workflow
    assert "queue: max" in workflow
    assert "git rev-parse origin/main" in workflow
    assert "--converge" in workflow
    assert "--reviewed-sidecar" in workflow
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert ".github/issue-transitions/post-merge-control-candidate.json" in workflow
    assert "git rev-parse HEAD^" not in workflow
    assert "--control-candidate" not in workflow
    assert "deferring to programme-status-completion zero-action readback" in workflow
    assert 'git diff --quiet "${{ github.event.before }}" "${{ github.sha }}"' in workflow
    assert "--apply" not in workflow
    assert "git push" not in workflow
