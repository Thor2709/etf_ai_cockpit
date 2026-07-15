from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


COMPLETE_AUDIT_REQUIRED_PATHS: tuple[str, ...] = (
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
    "evidence_export/feature_drivers.csv",
    "evidence_export/correlation_clusters.csv",
    "evidence_export/benchmark_attribution.csv",
    "evidence_export/edge_cost.csv",
    "evidence_export/data_health.csv",
    "evidence_export/session.jsonl",
    "evidence_export/workflow.jsonl",
    "evidence_export/configs/data_providers_redacted.json",
    "evidence_export/configs/audit_manifest.yaml",
    "evidence_export/project_docs/issue_dossiers.json",
    "evidence_export/checksum_manifest.json",
    "checksum_manifest.json",
)


@dataclass(frozen=True)
class AuditValidationReport:
    valid: bool
    included: tuple[str, ...]
    missing: tuple[str, ...]
    checksum_errors: tuple[str, ...]
    secret_findings: tuple[str, ...]


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?ix)"
    r"(?<![A-Za-z0-9_])"
    r"(?P<key>(?:[A-Za-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|passwd|authorization|bearer))"
    r"\s*(?:[\"']?\s*)?(?:=|:)\s*[\"']?"
    r"(?P<scheme>bearer\s+)?(?P<value>[^\"'\s,;}\]]+)"
)
_REDACTED_VALUE = "***redacted***"


def _contains_unredacted_secret(text: str) -> bool:
    for match in _SECRET_ASSIGNMENT_RE.finditer(text):
        key = match.group("key").lower().replace("-", "_")
        if key in {"has_api_key", "requires_api_key"}:
            continue
        if match.group("value") != _REDACTED_VALUE:
            return True
    return False


def validate_audit_archive(path: Path) -> AuditValidationReport:
    included: list[str] = []
    missing: list[str] = []
    checksum_errors: list[str] = []
    secret_findings: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "audit_manifest.json" not in names:
                return AuditValidationReport(False, (), ("audit_manifest.json",), (), ())
            manifest = json.loads(archive.read("audit_manifest.json"))
            required_items = manifest.get("required", [])
            if not isinstance(required_items, list):
                return AuditValidationReport(False, (), ("required_not_list",), (), ())
            strict_contract = manifest.get("contract") == "complete-audit-v1" or any(
                isinstance(item, dict) and "source_authority" in item for item in required_items
            )
            raw_checksums = manifest.get("checksums")
            if strict_contract and not isinstance(raw_checksums, dict):
                missing.append("checksums_not_object")
                checksums: dict[str, object] = {}
            else:
                checksums = raw_checksums if isinstance(raw_checksums, dict) else {}
            if strict_contract:
                declared_names = {
                    str(item.get("path")) for item in required_items if isinstance(item, dict) and item.get("path")
                }
                for canonical_path in COMPLETE_AUDIT_REQUIRED_PATHS:
                    if canonical_path not in declared_names:
                        missing.append(f"canonical_required_missing:{canonical_path}")
            for item in required_items:
                if not isinstance(item, dict):
                    missing.append("required_record_invalid")
                    continue
                if strict_contract:
                    for field in ("path", "schema_version", "source_authority", "allow_unavailable"):
                        if field not in item or item[field] in (None, ""):
                            missing.append(f"required_field_missing:{field}")
                    if not isinstance(item.get("schema_version"), (int, str)):
                        missing.append("required_schema_version_invalid")
                    if not isinstance(item.get("allow_unavailable"), bool):
                        missing.append("required_allow_unavailable_invalid")
                name = str(item.get("path") or "")
                if name in names:
                    included.append(name)
                    expected_sha = str(item.get("sha256") or "")
                    if strict_contract and not expected_sha:
                        checksum_errors.append(f"required_sha_missing:{name}")
                    if expected_sha and hashlib.sha256(archive.read(name)).hexdigest() != expected_sha:
                        checksum_errors.append(f"required:{name}")
                elif bool(item.get("allow_unavailable")):
                    marker = str(item.get("unavailable_marker") or "")
                    if not marker or marker not in names:
                        missing.append(f"unavailable_marker_missing:{marker or name}")
                    else:
                        included.append(name)
                        expected_sha = str(item.get("sha256") or "")
                        if strict_contract and not expected_sha:
                            checksum_errors.append(f"required_sha_missing:{name}")
                        if expected_sha and hashlib.sha256(archive.read(marker)).hexdigest() != expected_sha:
                            checksum_errors.append(f"required:{name}")
                else:
                    missing.append(name)
            for name, expected in checksums.items():
                if name not in names or hashlib.sha256(archive.read(name)).hexdigest() != str(expected):
                    checksum_errors.append(str(name))
            checksummed = {str(name) for name in checksums}
            for name in names:
                if name != "audit_manifest.json" and not name.endswith("/") and name not in checksummed:
                    checksum_errors.append(f"unlisted:{name}")
            for name in names:
                if name.endswith("/"):
                    continue
                text = archive.read(name).decode("utf-8", errors="replace")
                if _contains_unredacted_secret(text):
                    secret_findings.append(name)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, TypeError, ValueError) as exc:
        return AuditValidationReport(False, (), (f"archive_invalid:{type(exc).__name__}",), (), ())
    return AuditValidationReport(not missing and not checksum_errors and not secret_findings, tuple(included), tuple(missing), tuple(checksum_errors), tuple(secret_findings))


def extract_and_validate_audit_archive(path: Path, destination: Path) -> AuditValidationReport:
    """Extract a packet only after validating its manifest and checksums."""

    report = validate_audit_archive(path)
    if not report.valid:
        return report
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as archive:
            root = destination.resolve()
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if target != root and root not in target.parents:
                    return AuditValidationReport(False, report.included, report.missing, report.checksum_errors + ("extract_path_traversal",), report.secret_findings)
            archive.extractall(destination)
    except (OSError, zipfile.BadZipFile):
        return AuditValidationReport(False, report.included, report.missing, report.checksum_errors + ("extract_failed",), report.secret_findings)
    return report


__all__ = ["AuditValidationReport", "COMPLETE_AUDIT_REQUIRED_PATHS", "extract_and_validate_audit_archive", "validate_audit_archive"]
