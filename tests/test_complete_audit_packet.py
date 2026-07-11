from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from etf_cockpit.chatgpt_bridge.audit_packet import validate_audit_archive


def test_audit_archive_manifest_checksums_and_unavailable_policy(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit.zip"
    data = b"session"
    manifest = {"schema_version": 1, "required": [{"path": "session.jsonl", "allow_unavailable": False}], "checksums": {"session.jsonl": hashlib.sha256(data).hexdigest()}}
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session.jsonl", data)
        archive.writestr("audit_manifest.json", json.dumps(manifest))
    report = validate_audit_archive(archive_path)
    assert report.valid is True
    assert "session.jsonl" in report.included


def test_audit_archive_allows_explicitly_redacted_secret_values(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit-redacted.zip"
    data = b'{"has_api_key":false,"requires_api_key":false,"message":"api_key=***redacted*** password=***redacted*** OPENAI_API_KEY=***redacted*** access_token=***redacted*** client_secret=***redacted*** authorization: Bearer ***redacted***"}'
    manifest = {
        "schema_version": 1,
        "required": [{"path": "session.jsonl", "allow_unavailable": False}],
        "checksums": {"session.jsonl": hashlib.sha256(data).hexdigest()},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session.jsonl", data)
        archive.writestr("audit_manifest.json", json.dumps(manifest))

    report = validate_audit_archive(archive_path)

    assert report.valid is True
    assert report.secret_findings == ()


def test_audit_archive_rejects_unredacted_secret_values(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit-secret.zip"
    data = b'{"message":"api_key=raw-secret-value"}'
    manifest = {
        "schema_version": 1,
        "required": [{"path": "session.jsonl", "allow_unavailable": False}],
        "checksums": {"session.jsonl": hashlib.sha256(data).hexdigest()},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session.jsonl", data)
        archive.writestr("audit_manifest.json", json.dumps(manifest))

    report = validate_audit_archive(archive_path)

    assert report.valid is False
    assert report.secret_findings == ("session.jsonl",)


def test_audit_archive_rejects_env_and_bearer_secret_forms(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit-secret-forms.zip"
    data = b'{"message":"OPENAI_API_KEY=raw-openai access_token=raw-access client_secret=raw-client authorization: Bearer raw-bearer"}'
    manifest = {
        "schema_version": 1,
        "required": [{"path": "session.jsonl", "allow_unavailable": False}],
        "checksums": {"session.jsonl": hashlib.sha256(data).hexdigest()},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session.jsonl", data)
        archive.writestr("audit_manifest.json", json.dumps(manifest))

    report = validate_audit_archive(archive_path)

    assert report.valid is False
    assert report.secret_findings == ("session.jsonl",)


def test_audit_archive_missing_required_path_fails(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("audit_manifest.json", json.dumps({"schema_version": 1, "required": [{"path": "identity.json", "allow_unavailable": False}], "checksums": {}}))
    assert validate_audit_archive(archive_path).valid is False


def test_allowed_unavailable_path_requires_explicit_marker(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit-unavailable.zip"
    marker = b"candle_context.parquet is unavailable; no evidence was invented.\n"
    manifest = {
        "schema_version": 1,
        "required": [
            {
                "path": "candle_context.parquet",
                "allow_unavailable": True,
                "unavailable_marker": "candle_context_unavailable.txt",
            }
        ],
        "checksums": {"candle_context_unavailable.txt": hashlib.sha256(marker).hexdigest()},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("candle_context_unavailable.txt", marker)
        archive.writestr("audit_manifest.json", json.dumps(manifest))

    report = validate_audit_archive(archive_path)

    assert report.valid is True
    assert "candle_context.parquet" not in report.missing


def test_allowed_unavailable_path_without_marker_fails(tmp_path: Path) -> None:
    archive_path = tmp_path / "audit-unavailable-without-marker.zip"
    manifest = {
        "schema_version": 1,
        "required": [
            {
                "path": "candle_context.parquet",
                "allow_unavailable": True,
                "unavailable_marker": "candle_context_unavailable.txt",
            }
        ],
        "checksums": {},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("audit_manifest.json", json.dumps(manifest))

    report = validate_audit_archive(archive_path)

    assert report.valid is False
    assert "unavailable_marker_missing:candle_context_unavailable.txt" in report.missing
