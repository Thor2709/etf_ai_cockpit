"""Versioned source, model and jurisdiction terms for local-first operation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


LEGAL_TERMS_SCHEMA_VERSION = "legal-terms.v1"
DEFAULT_LEGAL_TERMS_PATH = Path("configs/legal_terms_registry.yaml")
_EXPORT_POLICIES = frozenset({"allowed", "allowed_with_attribution", "metadata_only", "prohibited", "prohibited_without_permission", "attribution_required", "allowed_with_notice"})


class LegalTermsError(ValueError):
    """Raised when the terms registry is missing, malformed or unsafe."""


@dataclass(frozen=True)
class LegalTermsEntry:
    entry_id: str
    entry_kind: str
    terms_status: str
    terms_reference: str
    permitted_cache: str | None
    redistribution: str
    audit_export: str
    attribution: str
    review_note: str

    @property
    def unresolved(self) -> bool:
        return self.terms_status in {"", "unresolved", "unknown", "review_required"}

    def export_decision(self, export_kind: str) -> str:
        if export_kind in {"audit", "audit_export", "standard_audit_export"}:
            return self.audit_export
        if export_kind in {"redistribution", "share"}:
            return self.redistribution
        if export_kind in {"cache", "local_cache"}:
            return self.permitted_cache or "prohibited"
        raise LegalTermsError(f"unknown export kind: {export_kind}")

    def to_row(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "entry_kind": self.entry_kind,
            "terms_status": self.terms_status,
            "permitted_cache": self.permitted_cache or "not_applicable",
            "redistribution": self.redistribution,
            "audit_export": self.audit_export,
            "attribution": self.attribution,
        }


@dataclass(frozen=True)
class LegalTermsRegistry:
    registry_version: str
    review_status: str
    professional_review_required: bool
    mandatory_source_ids: tuple[str, ...]
    mandatory_model_ids: tuple[str, ...]
    sources: tuple[LegalTermsEntry, ...]
    models: tuple[LegalTermsEntry, ...]
    code_and_packages: tuple[LegalTermsEntry, ...]
    jurisdictions: tuple[dict[str, object], ...]
    terms_change_policy: Mapping[str, object]
    network_policy: Mapping[str, object]
    export_policy: Mapping[str, object]
    checksum: str

    def entry(self, entry_id: str) -> LegalTermsEntry | None:
        return next((item for item in (*self.sources, *self.models, *self.code_and_packages) if item.entry_id == entry_id), None)

    @property
    def unresolved_mandatory(self) -> tuple[str, ...]:
        unresolved = [entry_id for entry_id in self.mandatory_source_ids if (self.entry(entry_id) is None or self.entry(entry_id).unresolved)]
        unresolved.extend(entry_id for entry_id in self.mandatory_model_ids if (self.entry(entry_id) is None or self.entry(entry_id).unresolved))
        return tuple(sorted(set(unresolved)))

    def export_permission(self, entry_id: str, export_kind: str = "audit_export", *, user_owned: bool = False) -> str:
        entry = self.entry(entry_id)
        if entry is None:
            return "prohibited"
        decision = entry.export_decision(export_kind)
        if decision == "user_responsibility" and not user_owned:
            return "prohibited_without_permission"
        return decision

    def can_export(self, entry_id: str, export_kind: str = "audit_export", *, user_owned: bool = False) -> bool:
        return self.export_permission(entry_id, export_kind, user_owned=user_owned) in {"allowed", "allowed_with_attribution"}

    def disclaimer(self, jurisdiction: str = "AU") -> str:
        wanted = str(jurisdiction or "AU").strip().upper()
        for item in self.jurisdictions:
            if str(item.get("jurisdiction_id", "")).upper() == wanted:
                return str(item.get("disclaimer", ""))
        return str(self.jurisdictions[0].get("disclaimer", "")) if self.jurisdictions else "Research and education only. Not financial or tax advice. No broker execution or order transmission."

    def rows(self) -> tuple[dict[str, object], ...]:
        return tuple(item.to_row() for item in (*self.sources, *self.models, *self.code_and_packages))

    def terms_payload(self) -> dict[str, object]:
        return {
            "sources": [item.to_row() | {"terms_reference": item.terms_reference, "review_note": item.review_note} for item in self.sources],
            "models": [item.to_row() | {"terms_reference": item.terms_reference, "review_note": item.review_note} for item in self.models],
            "code_and_packages": [item.to_row() | {"terms_reference": item.terms_reference, "review_note": item.review_note} for item in self.code_and_packages],
            "jurisdictions": list(self.jurisdictions),
            "terms_change_policy": dict(self.terms_change_policy),
        }


def _entry(raw: object, kind: str) -> LegalTermsEntry:
    if not isinstance(raw, dict):
        raise LegalTermsError(f"{kind} terms row must be an object")
    entry_id = str(raw.get("source_id", raw.get("model_id", raw.get("component_id", "")))).strip().lower()
    if not entry_id:
        raise LegalTermsError(f"{kind} terms row requires an identifier")
    terms_status = str(raw.get("terms_status", "")).strip().lower()
    terms_reference = str(raw.get("terms_reference", "")).strip()
    redistribution = str(raw.get("redistribution", "")).strip().lower()
    audit_export = str(raw.get("audit_export", "")).strip().lower()
    if not terms_status or not terms_reference or not redistribution or redistribution not in _EXPORT_POLICIES | {"user_responsibility"}:
        raise LegalTermsError(f"{entry_id} has incomplete terms metadata")
    if audit_export not in _EXPORT_POLICIES:
        raise LegalTermsError(f"{entry_id} has an invalid audit export permission")
    if kind == "source" and not str(raw.get("permitted_cache", "")).strip():
        raise LegalTermsError(f"{entry_id} has no cache permission")
    return LegalTermsEntry(
        entry_id=entry_id,
        entry_kind=kind,
        terms_status=terms_status,
        terms_reference=terms_reference,
        permitted_cache=str(raw.get("permitted_cache", "")).strip() or None,
        redistribution=redistribution,
        audit_export=audit_export,
        attribution=str(raw.get("attribution", "")).strip(),
        review_note=str(raw.get("review_note", "")).strip(),
    )


def _rows(payload: dict[str, object], key: str, kind: str) -> tuple[LegalTermsEntry, ...]:
    raw_rows = payload.get(key)
    if not isinstance(raw_rows, list) or not raw_rows:
        raise LegalTermsError(f"legal terms registry requires {key}")
    result = tuple(_entry(raw, kind) for raw in raw_rows)
    identifiers = [item.entry_id for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise LegalTermsError(f"legal terms registry contains duplicate {key} identifiers")
    return result


def load_legal_terms(path: Path | None = None) -> LegalTermsRegistry:
    source = Path(path or DEFAULT_LEGAL_TERMS_PATH)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise LegalTermsError(f"Could not load legal terms registry: {source}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != LEGAL_TERMS_SCHEMA_VERSION:
        raise LegalTermsError(f"legal terms registry must use schema {LEGAL_TERMS_SCHEMA_VERSION}")
    sources = _rows(payload, "sources", "source")
    models = _rows(payload, "models", "model")
    code = _rows(payload, "code_and_packages", "code")
    source_ids = tuple(str(item).strip().lower() for item in payload.get("mandatory_source_ids", []))
    model_ids = tuple(str(item).strip().lower() for item in payload.get("mandatory_model_ids", []))
    if not source_ids or not model_ids:
        raise LegalTermsError("mandatory source and model identifiers are required")
    jurisdictions = payload.get("jurisdictions")
    if not isinstance(jurisdictions, list) or not jurisdictions:
        raise LegalTermsError("at least one jurisdiction disclaimer is required")
    for item in jurisdictions:
        if not isinstance(item, dict) or not str(item.get("jurisdiction_id", "")).strip() or not str(item.get("disclaimer", "")).strip():
            raise LegalTermsError("jurisdiction entries require an identifier and disclaimer")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    registry = LegalTermsRegistry(
        registry_version=str(payload.get("registry_version", "")).strip(),
        review_status=str(payload.get("review_status", "")).strip().lower(),
        professional_review_required=bool(payload.get("professional_review_required", False)),
        mandatory_source_ids=source_ids,
        mandatory_model_ids=model_ids,
        sources=sources,
        models=models,
        code_and_packages=code,
        jurisdictions=tuple(jurisdictions),
        terms_change_policy=payload.get("terms_change_policy") if isinstance(payload.get("terms_change_policy"), dict) else {},
        network_policy=payload.get("network_policy") if isinstance(payload.get("network_policy"), dict) else {},
        export_policy=payload.get("export_policy") if isinstance(payload.get("export_policy"), dict) else {},
        checksum=hashlib.sha256(canonical).hexdigest(),
    )
    missing = set(source_ids + model_ids) - {item.entry_id for item in (*sources, *models)}
    if missing:
        raise LegalTermsError(f"mandatory terms entries are missing: {', '.join(sorted(missing))}")
    if registry.unresolved_mandatory:
        raise LegalTermsError(f"mandatory terms entries are unresolved: {', '.join(registry.unresolved_mandatory)}")
    return registry


def terms_change_requires_review(previous: LegalTermsRegistry, current: LegalTermsRegistry) -> bool:
    """Return true when source/model/disclaimer terms changed between registries."""

    return previous.terms_payload() != current.terms_payload()


def filter_restricted_exports(records: list[Mapping[str, object]], registry: LegalTermsRegistry, *, export_kind: str = "audit_export") -> tuple[dict[str, object], ...]:
    """Keep only rows whose provider/model explicitly permits the export."""

    allowed: list[dict[str, object]] = []
    for record in records:
        entry_id = str(record.get("source_id", record.get("provider_id", record.get("model_id", "")))).strip().lower()
        if registry.can_export(entry_id, export_kind, user_owned=bool(record.get("user_owned", False))):
            allowed.append(dict(record))
    return tuple(allowed)


def legal_terms_report(root: Path, path: Path | None = None) -> dict[str, Any]:
    registry = load_legal_terms(path or (Path(root) / DEFAULT_LEGAL_TERMS_PATH))
    return {
        "schema_version": LEGAL_TERMS_SCHEMA_VERSION,
        "registry_version": registry.registry_version,
        "status": "passed" if not registry.unresolved_mandatory else "failed",
        "review_status": registry.review_status,
        "professional_review_required": registry.professional_review_required,
        "network_calls": False,
        "registry_sha256": registry.checksum,
        "mandatory_source_ids": list(registry.mandatory_source_ids),
        "mandatory_model_ids": list(registry.mandatory_model_ids),
        "unresolved_mandatory": list(registry.unresolved_mandatory),
        "rows": list(registry.rows()),
        "jurisdictions": list(registry.jurisdictions),
        "failures": [],
    }


def legal_terms_rows(root: Path, path: Path | None = None) -> tuple[dict[str, object], ...]:
    return tuple(legal_terms_report(root, path)["rows"])


def write_legal_terms_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# Legal terms report",
        "",
        f"- Schema: `{report.get('schema_version', 'unavailable')}`",
        f"- Registry: `{report.get('registry_version', 'unavailable')}`",
        f"- Status: `{report.get('status', 'failed')}`",
        f"- Review status: `{report.get('review_status', 'unavailable')}`",
        f"- Professional review required: `{str(report.get('professional_review_required', True)).lower()}`",
        "- Network calls: `false`",
        f"- Duration: `{report.get('duration_ms', 'unavailable')} ms`",
        "",
        "| Entry | Kind | Terms status | Cache | Redistribution | Audit export |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("rows", []):
        lines.append("| " + " | ".join(f"`{row.get(key, 'unavailable')}`" for key in ("entry_id", "entry_kind", "terms_status", "permitted_cache", "redistribution", "audit_export")) + " |")
    if report.get("failures"):
        lines.extend(["", "## Failures", "", *[f"- {item}" for item in report["failures"]]])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


__all__ = [
    "DEFAULT_LEGAL_TERMS_PATH",
    "LEGAL_TERMS_SCHEMA_VERSION",
    "LegalTermsEntry",
    "LegalTermsError",
    "LegalTermsRegistry",
    "filter_restricted_exports",
    "legal_terms_report",
    "legal_terms_rows",
    "load_legal_terms",
    "terms_change_requires_review",
    "write_legal_terms_report",
]
