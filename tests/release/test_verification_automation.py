from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _verifier():
    try:
        from scripts.verify_issue import verify_issue
    except ImportError:
        return None
    return verify_issue


def _write_output(root: Path, relative: str, content: bytes = b"verified") -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _run(
    root: Path,
    issue_id: str,
    source_hash: str,
    *,
    gates: list[str],
    result: str = "pass",
    skipped: bool = False,
    informational: bool = False,
    output_name: str = "runs/output.txt",
    output_checksum: str | None = None,
) -> dict[str, object]:
    checksum = _write_output(root, output_name)
    return {
        "verification_run_id": f"run-{gates[0]}",
        "verification_type": gates[0],
        "command": "python -m pytest tests -q",
        "source_hash": source_hash,
        "result": result,
        "exit_code": 0 if result == "pass" else 1,
        "output_paths": [output_name],
        "output_checksums": [output_checksum or checksum],
        "issue_ids": [issue_id],
        "gates": gates,
        "skipped": skipped,
        "informational": informational,
    }


def _manifest(
    root: Path,
    issue_id: str = "DATA-05",
    *,
    source_hash: str = "a" * 64,
    environment_hash: str = "b" * 64,
    runs: list[dict[str, object]] | None = None,
    review: dict[str, object] | None = None,
    generated_at: datetime | None = None,
) -> None:
    payload = {
        "schema_version": "1.0",
        "issue_id": issue_id,
        "requirement_version": "2",
        "source_hash": source_hash,
        "environment_hash": environment_hash,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "runs": runs or [],
        "review": review or {
            "builder": "implementer",
            "independent_reviewer": "reviewer",
            "review_result": "approved",
        },
        "limitations": [],
    }
    target = root / "DATA-05" / "verification_manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _shared_manifest(
    root: Path,
    runs: list[dict[str, object]],
    *,
    source_hash: str,
    environment_hash: str,
    shared_record_ids: list[str],
    reviewer: str = "reviewer",
) -> None:
    _manifest(
        root,
        source_hash=source_hash,
        environment_hash=environment_hash,
        runs=runs,
        review={
            "builder": "implementer",
            "independent_reviewer": reviewer,
            "review_result": "approved",
        },
    )
    target = root / "DATA-05" / "verification_manifest.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.update(
        {
            "commit": "commit-a",
            "executable_hash": "e" * 64,
            "evidence_state": "final",
            "verification_records_path": str(root / "records.json"),
            "shared_record_ids": shared_record_ids,
        }
    )
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_final_generation_manifest_is_discoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_issue

    monkeypatch.setattr(verify_issue, "ROOT", tmp_path)
    target = tmp_path / "evidence" / "final" / "generation-001" / "verification_manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n", encoding="utf-8")

    assert verify_issue._manifest_path(target.parents[1], "DATA-05") == target
    assert verify_issue._is_canonical_final_root(target.parents[0]) is True


def test_generation_manifest_validates_generation_relative_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_issue

    monkeypatch.setattr(verify_issue, "ROOT", tmp_path)
    final_root = tmp_path / "evidence" / "final"
    generation_root = final_root / "generation-001"
    source_hash = "a" * 64
    environment_hash = "b" * 64
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    output = generation_root / "tests" / "output.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"verified")
    checksum = hashlib.sha256(b"verified").hexdigest()
    command = verify_issue._plan_command_text(verify_issue.fixed_command_plan(["tests"])[0].argv)
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text(
        """
programme_schema_version: 1
historic_baseline_count: 1
verification_policy:
  version: '1.0'
  requirement_version: '2'
  max_age_hours: 168
  gate_layers:
    tests: {}
issues:
  - issue_id: DATA-05
    title: Test issue
    wave: 1
    status: still_open
    criteria:
      - criterion_id: DATA-05-C-TESTS
        text: Tests pass.
        required_gates: [tests]
        evidence_paths: []
""",
        encoding="utf-8",
    )
    manifest = generation_root / "verification_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "issue_id": "DATA-05",
                "requirement_version": "2",
                "source_hash": source_hash,
                "environment_hash": environment_hash,
                "generated_at": now.isoformat(),
                "evidence_state": "final",
                "runs": [
                    {
                        "verification_run_id": "run-tests",
                        "verification_type": "tests",
                        "command": command,
                        "source_hash": source_hash,
                        "environment_hash": environment_hash,
                        "result": "pass",
                        "exit_code": 0,
                        "output_paths": ["tests/output.txt"],
                        "output_checksums": [checksum],
                        "issue_ids": ["DATA-05"],
                        "gates": ["tests"],
                    }
                ],
                "review": {
                    "builder": "implementer",
                    "independent_reviewer": "reviewer",
                    "review_result": "approved",
                },
                "limitations": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = verify_issue.verify_issue(
        "DATA-05",
        source_hash=source_hash,
        environment_hash=environment_hash,
        evidence_root=final_root,
        matrix_path=matrix,
        now=now,
    )

    assert result.status == "pass"
    assert result.manifest_path == manifest.as_posix()


def test_manifest_shared_records_map_to_separate_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_issue

    source_hash = "a" * 64
    environment_hash = "b" * 64
    source_command = verify_issue._plan_command_text(verify_issue.fixed_command_plan(["source"])[0].argv)
    tests_command = verify_issue._plan_command_text(verify_issue.fixed_command_plan(["tests"])[0].argv)
    source_run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    tests_run = _run(tmp_path, "DATA-05", source_hash, gates=["tests"])
    source_run["command"] = source_command
    tests_run["command"] = tests_command
    _shared_manifest(
        tmp_path,
        [source_run, tests_run],
        source_hash=source_hash,
        environment_hash=environment_hash,
        shared_record_ids=["record-source", "record-tests"],
    )

    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(verify_issue, "VerificationRecordLedger", lambda _path: object())

    def validate(_ledger, record_id: str, *, key, gate: str, **_kwargs):
        calls.append((record_id, key.command, gate))
        return SimpleNamespace(issue_ids=["DATA-05"], review_id="reviewer")

    monkeypatch.setattr(verify_issue, "validate_shared_record", validate)
    verify_issue.verify_issue(
        "DATA-05",
        source_hash=source_hash,
        environment_hash=environment_hash,
        evidence_root=tmp_path,
    )

    assert calls == [
        ("record-source", source_command, "source"),
        ("record-tests", tests_command, "tests"),
    ]


def test_manifest_shared_records_reject_multiple_ids_for_one_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_issue

    source_hash = "a" * 64
    environment_hash = "b" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    run["command"] = verify_issue._plan_command_text(verify_issue.fixed_command_plan(["source"])[0].argv)
    _shared_manifest(
        tmp_path,
        [run],
        source_hash=source_hash,
        environment_hash=environment_hash,
        shared_record_ids=["record-a", "record-b"],
    )
    monkeypatch.setattr(verify_issue, "VerificationRecordLedger", lambda _path: object())
    monkeypatch.setattr(
        verify_issue,
        "validate_shared_record",
        lambda *_args, **_kwargs: SimpleNamespace(issue_ids=["DATA-05"], review_id="reviewer"),
    )

    result = verify_issue.verify_issue(
        "DATA-05",
        source_hash=source_hash,
        environment_hash=environment_hash,
        evidence_root=tmp_path,
    )

    assert result.status == "blocked"
    assert any("one-to-one" in limitation for limitation in result.limitations)


def test_manifest_and_run_shared_records_cannot_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_issue

    source_hash = "a" * 64
    environment_hash = "b" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    run["command"] = verify_issue._plan_command_text(verify_issue.fixed_command_plan(["source"])[0].argv)
    run["shared_record_id"] = "record-run"
    _shared_manifest(
        tmp_path,
        [run],
        source_hash=source_hash,
        environment_hash=environment_hash,
        shared_record_ids=["record-manifest"],
    )
    monkeypatch.setattr(verify_issue, "VerificationRecordLedger", lambda _path: object())
    monkeypatch.setattr(
        verify_issue,
        "validate_shared_record",
        lambda *_args, **_kwargs: SimpleNamespace(issue_ids=["DATA-05"], review_id="reviewer"),
    )

    result = verify_issue.verify_issue(
        "DATA-05",
        source_hash=source_hash,
        environment_hash=environment_hash,
        evidence_root=tmp_path,
    )

    assert result.status == "blocked"
    assert any("cannot be combined" in limitation for limitation in result.limitations)


def test_shared_record_associations_are_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_issue

    source_hash = "a" * 64
    environment_hash = "b" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    run["command"] = verify_issue._plan_command_text(verify_issue.fixed_command_plan(["source"])[0].argv)
    _shared_manifest(
        tmp_path,
        [run],
        source_hash=source_hash,
        environment_hash=environment_hash,
        shared_record_ids=["record-source"],
    )
    monkeypatch.setattr(verify_issue, "VerificationRecordLedger", lambda _path: object())
    monkeypatch.setattr(
        verify_issue,
        "validate_shared_record",
        lambda *_args, **_kwargs: SimpleNamespace(issue_ids=[], review_id="different-reviewer"),
    )

    result = verify_issue.verify_issue(
        "DATA-05",
        source_hash=source_hash,
        environment_hash=environment_hash,
        evidence_root=tmp_path,
    )

    assert result.status == "blocked"
    assert any("does not reference issue DATA-05" in limitation for limitation in result.limitations)
    assert any("reviewer association" in limitation for limitation in result.limitations)


def test_verify_issue_rejects_a_passing_result_from_a_different_source_hash(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    _manifest(tmp_path, source_hash="a" * 64, generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash="c" * 64,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert "source hash" in result.limitations[0].lower()


def test_verify_issue_never_updates_tracker_state(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None

    result = verifier("ISSUE-0013", evidence_root=tmp_path)

    assert result.status == "blocked"
    assert result.tracker_mutated is False
    assert not (tmp_path / "issues").exists()


def test_missing_required_layer_and_skipped_test_cannot_pass(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["tests"], skipped=True)
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("skipped" in limitation.lower() for limitation in result.limitations)
    assert result.missing_gates


def test_live_informational_result_cannot_satisfy_deterministic_gate(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"], informational=True)
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier("DATA-05", source_hash=source_hash, environment_hash="b" * 64, evidence_root=tmp_path, now=now)

    assert result.status == "blocked"
    assert any("informational" in limitation.lower() for limitation in result.limitations)


def test_builder_and_reviewer_must_be_distinct_for_approval(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    _manifest(
        tmp_path,
        source_hash="a" * 64,
        environment_hash="b" * 64,
        generated_at=now,
        review={"builder": "same", "independent_reviewer": "same", "review_result": "approved"},
    )

    result = verifier("DATA-05", source_hash="a" * 64, environment_hash="b" * 64, evidence_root=tmp_path, now=now)

    assert result.status == "blocked"
    assert any("independent" in limitation.lower() for limitation in result.limitations)


def test_package_and_browser_evidence_require_real_screenshot_metadata(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    browser_run = _run(tmp_path, "DATA-05", source_hash, gates=["browser"], output_name="browser/fake.png")
    browser_run["screenshot"] = {"path": "browser/fake.png", "sha256": "0" * 64, "width": 0, "height": 0}
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[browser_run], generated_at=now)

    result = verifier("DATA-05", source_hash=source_hash, environment_hash="b" * 64, evidence_root=tmp_path, now=now)

    assert result.status == "blocked"
    assert any("screenshot" in limitation.lower() for limitation in result.limitations)


def test_corrupted_output_checksum_is_blocked(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"], output_checksum="0" * 64)
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier("DATA-05", source_hash=source_hash, environment_hash="b" * 64, evidence_root=tmp_path, now=now)

    assert result.status == "blocked"
    assert any("checksum" in limitation.lower() for limitation in result.limitations)


def test_stale_manifest_is_blocked_even_when_source_hash_matches(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    _manifest(
        tmp_path,
        source_hash="a" * 64,
        environment_hash="b" * 64,
        generated_at=now - timedelta(days=31),
    )

    result = verifier("DATA-05", source_hash="a" * 64, environment_hash="b" * 64, evidence_root=tmp_path, now=now)

    assert result.status == "blocked"
    assert any("fresh" in limitation.lower() for limitation in result.limitations)


def test_manifest_command_must_match_the_fixed_plan_for_its_gate(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    run["command"] = "python -m pytest tests -q"
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("command" in limitation.lower() and "plan" in limitation.lower() for limitation in result.limitations)


@pytest.mark.parametrize(
    ("gates", "command"),
    [
        (["source"], ""),
        (["not-a-gate"], "not-a-command"),
    ],
)
def test_manifest_empty_or_unknown_command_cannot_pass(
    tmp_path: Path, gates: list[str], command: str
) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=gates)
    run["command"] = command
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("command" in limitation.lower() or "gate" in limitation.lower() for limitation in result.limitations)


def test_passing_run_requires_non_empty_output_captures_and_checksums(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    run.pop("output_paths")
    run.pop("output_checksums")
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("at least one" in limitation.lower() or "output" in limitation.lower() for limitation in result.limitations)


def test_passing_run_requires_its_own_environment_hash(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["source"])
    run.pop("environment_hash", None)
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("environment hash" in limitation.lower() for limitation in result.limitations)


def test_package_gate_requires_screenshot_metadata(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    run = _run(tmp_path, "DATA-05", source_hash, gates=["package"])
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("screenshot" in limitation.lower() for limitation in result.limitations)


def test_screenshot_bytes_must_be_a_real_image_with_declared_dimensions(tmp_path: Path) -> None:
    verifier = _verifier()
    assert verifier is not None
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    source_hash = "a" * 64
    fake_path = tmp_path / "browser" / "fake.png"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_bytes = b"this is text, not a PNG"
    run = _run(tmp_path, "DATA-05", source_hash, gates=["browser"], output_name="browser/fake.png")
    fake_path.write_bytes(fake_bytes)
    run["output_checksums"] = [hashlib.sha256(fake_bytes).hexdigest()]
    run["screenshot"] = {
        "path": "browser/fake.png",
        "sha256": hashlib.sha256(fake_bytes).hexdigest(),
        "width": 1,
        "height": 1,
    }
    _manifest(tmp_path, source_hash=source_hash, environment_hash="b" * 64, runs=[run], generated_at=now)

    result = verifier(
        "DATA-05",
        source_hash=source_hash,
        environment_hash="b" * 64,
        evidence_root=tmp_path,
        now=now,
    )

    assert result.status == "blocked"
    assert any("image" in limitation.lower() or "screenshot" in limitation.lower() for limitation in result.limitations)


def test_execute_command_plan_records_missing_tool_as_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.verify_issue import VerificationCommand, execute_command_plan

    def missing_tool(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("fixed tool is unavailable")

    monkeypatch.setattr("scripts.verify_issue.subprocess.run", missing_tool)

    runs = execute_command_plan(
        "DATA-05",
        evidence_root=tmp_path,
        gates=["source"],
        source_hash="a" * 64,
        environment_hash="b" * 64,
        commands=[VerificationCommand("source", ("missing-fixed-tool",))],
    )

    assert runs[0]["result"] == "blocked"
    assert runs[0]["exit_code"] == 127
    stderr_path = tmp_path / runs[0]["output_paths"][1]
    assert "unavailable" in stderr_path.read_text(encoding="utf-8").lower()
