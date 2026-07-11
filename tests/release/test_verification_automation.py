from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

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
