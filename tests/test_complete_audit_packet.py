from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from etf_cockpit.chatgpt_bridge.audit_packet import extract_and_validate_audit_archive, validate_audit_archive
from etf_cockpit.chatgpt_bridge import export_pack


COMPLETE_AUDIT_ARTEFACTS = {
    "evidence_export/provider_probe_results.csv",
    "evidence_export/instrument_identity.csv",
    "evidence_export/statement_facts.csv",
    "evidence_export/filings_statements.csv",
    "evidence_export/fund_documents.csv",
    "evidence_export/fund_holdings.csv",
    "evidence_export/etf_disclosures.csv",
    "evidence_export/priips_kid_records.csv",
    "evidence_export/index_methodology_records.csv",
    "evidence_export/news_context.csv",
    "evidence_export/news_timestamp_validation.csv",
    "evidence_export/source_conflicts.csv",
    "evidence_export/evidence_ledger.csv",
    "evidence_export/score_components.csv",
    "evidence_export/score_history.csv",
    "evidence_export/score_metric_history.csv",
    "evidence_export/score_formula_registry.json",
    "evidence_export/version_registry.json",
    "evidence_export/feature_drivers.csv",
    "evidence_export/correlation_clusters.csv",
    "evidence_export/benchmark_attribution.csv",
    "evidence_export/data_health.csv",
    "evidence_export/decision_journal_summary.json",
    "evidence_export/macro_warehouse_summary.json",
    "evidence_export/data_catalogue_summary.json",
    "evidence_export/governance/strategy_capability_matrix.json",
    "evidence_export/bitemporal_vintage_manifest.json",
    "evidence_export/session.jsonl",
    "evidence_export/workflow.jsonl",
    "evidence_export/configs/data_providers_redacted.json",
    "evidence_export/configs/settings_bundle.json",
    "evidence_export/configs/audit_manifest.yaml",
    "evidence_export/project_docs/issue_dossiers.json",
    "evidence_export/checksum_manifest.json",
    "checksum_manifest.json",
}


def test_strategy_capability_matrix_is_exported_as_governance_evidence(tmp_path: Path) -> None:
    destination = tmp_path / "strategy_capability_matrix.json"

    export_pack._export_strategy_capability_matrix(destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["matrix_version"] == "2026-07-21"
    assert payload["execution_allowed"] is False
    assert payload["strategy_matrix"]
    assert payload["instrument_matrix"]
    assert payload["instrument_stage_matrix"]
    assert all(row["execution_allowed"] is False for row in payload["strategy_matrix"])


def test_settings_bundle_export_is_versioned_and_secret_free(tmp_path: Path) -> None:
    destination = tmp_path / "settings_bundle.json"

    export_pack._export_settings_bundle(destination, root=tmp_path)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    text = destination.read_text(encoding="utf-8").lower()

    assert payload["schema_version"] == "settings_bundle.v1"
    assert payload["execution_allowed"] is False
    assert payload["run_identity"]["settings_revision"] == payload["revision"]
    assert "api_key" not in text
    assert "raw-secret" not in text


def test_generated_audit_manifest_declares_complete_canonical_artefact_set(tmp_path: Path) -> None:
    export_pack._write_audit_manifest(tmp_path, {}, {})
    manifest = json.loads((tmp_path / "audit_manifest.json").read_text(encoding="utf-8"))
    required = {str(item["path"]) for item in manifest["required"]}
    assert COMPLETE_AUDIT_ARTEFACTS <= required
    for item in manifest["required"]:
        assert {"path", "schema_version", "source_authority", "sha256", "allow_unavailable"} <= set(item)


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


def test_strict_manifest_rejects_missing_schema_and_checksum(tmp_path: Path) -> None:
    archive_path = tmp_path / "strict-invalid.zip"
    manifest = {
        "schema_version": 1,
        "contract": "complete-audit-v1",
        "required": [{"path": "session.jsonl", "allow_unavailable": False}],
        "checksums": {},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session.jsonl", b"session")
        archive.writestr("audit_manifest.json", json.dumps(manifest))
    report = validate_audit_archive(archive_path)
    assert report.valid is False
    assert "required_field_missing:schema_version" in report.missing
    assert "required_sha_missing:session.jsonl" in report.checksum_errors


def test_strict_manifest_requires_complete_canonical_paths_and_object_checksums(tmp_path: Path) -> None:
    archive_path = tmp_path / "strict-empty.zip"
    manifest = {
        "schema_version": 1,
        "contract": "complete-audit-v1",
        "required": [],
        "checksums": [],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("audit_manifest.json", json.dumps(manifest))
    report = validate_audit_archive(archive_path)
    assert report.valid is False
    assert "checksums_not_object" in report.missing
    assert "canonical_required_missing:checksum_manifest.json" in report.missing


def test_archive_extraction_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "traversal.zip"
    payload = b"safe"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": 1,
        "required": [{
            "path": "safe.txt",
            "allow_unavailable": False,
            "sha256": digest,
        }],
        "checksums": {"safe.txt": digest, "../outside.txt": hashlib.sha256(b"unsafe").hexdigest()},
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe.txt", payload)
        archive.writestr("../outside.txt", b"unsafe")
        archive.writestr("audit_manifest.json", json.dumps(manifest))
    report = extract_and_validate_audit_archive(archive_path, tmp_path / "extract")
    assert report.valid is False
    assert "extract_path_traversal" in report.checksum_errors


def test_unavailable_markers_are_unique_for_same_stem(tmp_path: Path) -> None:
    manifest: dict[str, object] = {}
    export_pack._copy_evidence_file(tmp_path / "news_context.csv", tmp_path / "evidence", manifest)
    export_pack._copy_evidence_file(tmp_path / "news_context.parquet", tmp_path / "evidence", manifest)
    included = list(manifest["included"])
    assert len(included) == 2
    assert len(set(included)) == 2
