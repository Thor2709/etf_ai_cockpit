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
    calls = 0

    def fail_second(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication failure")
        source.replace(destination)

    with pytest.raises(OSError, match="injected publication failure"):
        generate_programme.atomic_publish(root, stage, outputs, replace=fail_second)

    assert {relative: (root / relative).read_bytes() for relative in outputs} == {
        relative: b"prior" for relative in outputs
    }
    assert not (root / generate_programme.MANIFEST_PATH).exists()


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
        "docs/product-completion/CURRENT_STATUS.json",
        "docs/product-completion/PROGRESS.md",
        "docs/product-completion/programme/readiness.json",
        "docs/product-completion/reconciliation/2026-07-21-aaaaaaa/canonical-dag.json",
        "docs/product-completion/reconciliation/2026-07-21-aaaaaaa/github-remote-summary.json",
        "docs/product-completion/reconciliation/2026-07-21-aaaaaaa/github-sync-evidence.json",
        ".github/status-transition-guard-manifest.json",
    }
    assert expected <= outputs


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
        "apply_authority": False,
        "fresh_exact_plan_required_for_apply": True,
        "remote_inventory_sha256": "a" * 64,
        "summary": {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0},
        "actions": [],
    }
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", json.dumps(evidence).encode())
    _write(tmp_path, f"{prefix}/github-sync-evidence.json.sha256", b"stale")

    generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)

    evidence["apply_authority"] = True
    _write(tmp_path, f"{prefix}/github-sync-evidence.json", json.dumps(evidence).encode())
    with pytest.raises(ValueError, match="must not grant GitHub apply authority"):
        generate_programme._validate_and_emit_convergence_evidence(tmp_path, outputs)
