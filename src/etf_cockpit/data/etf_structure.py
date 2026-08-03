"""Fail-closed ETF structural and document-risk projection.

This module is deliberately a read model.  It does not fetch documents, parse
OCR, call models, calculate alpha, or grant execution authority.  Candidates
are usable only when their identity can be matched exactly to the local fund
document registry at a known point in time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import pandas as pd


STRUCTURE_SCHEMA_VERSION = 1
STRUCTURE_PROJECTION_VERSION = "etf-structure-documents.v1"
STRUCTURE_CONFIDENCE_VERSION = "etf-structure-confidence.v1"
STRESS_FORMULA_VERSION = "etf-structure-stress.v1"
STRUCTURAL_FIELDS = (
    "replication_method",
    "derivatives",
    "counterparties",
    "collateral_terms",
    "lending_policy",
    "lending_revenue_split",
    "domicile",
    "legal_form",
    "concentration_limits",
)
BASE_REQUIRED_STRUCTURE_FIELDS = (
    "replication_method",
    "derivatives",
    "domicile",
    "legal_form",
    "concentration_limits",
    "lending_policy",
)
DOCUMENT_FAMILIES = ("factsheet", "prospectus", "holdings")
_FIELD_ALIASES = {
    "legal_structure": "legal_form",
    "securities_lending": "lending_policy",
    "collateral_policy": "collateral_terms",
}
_CONFIDENCE = {"high": 1.0, "medium": 0.75, "partial": 0.5, "low": 0.25, "unknown": 0.0}
_USABLE_STATUSES = {"extracted", "resolved", "available", "complete", "imported", "mapped"}
_REPORT_KINDS = {"prospectus", "annual_report", "half_year_report"}
_NUMERIC_UNITS = {
    "exposure": "fraction_of_nav",
    "collateral_fraction": "fraction_of_exposure",
    "haircut_fraction": "scenario_haircut_fraction",
    "concentration_limit_fraction": "fraction_of_collateral",
}


@dataclass(frozen=True)
class StructureCandidate:
    """One structural claim with its complete source binding."""

    instrument_id: str
    field_name: str
    value: str
    source_id: str
    document_type: str
    document_date: str
    page: int
    confidence: float
    known_at: str
    checksum: str
    status: str = "extracted"


@dataclass(frozen=True)
class NumericEvidence:
    """An immutable, typed numeric candidate with an exact source binding."""

    value: object
    unit: str
    source_id: str = ""
    document_date: str = ""
    page: int | None = None
    confidence: object = "high"
    known_at: str = ""
    checksum: str = ""
    instrument_id: str = ""
    field_name: str = ""
    status: str = "extracted"
    normalized_value: Decimal | None = dataclass_field(init=False, default=None)

    def __post_init__(self) -> None:
        expected_unit = _NUMERIC_UNITS.get(str(self.field_name or "").strip())
        unit = str(self.unit or "").strip()
        normalized = _normalise_decimal(self.value)
        if expected_unit != unit or normalized is None:
            normalized = None
        object.__setattr__(self, "normalized_value", normalized)


class StructureConfidenceCaps(dict[str, float]):
    """Float-compatible caps carrying the structural provenance used to derive them."""

    def __init__(self) -> None:
        super().__init__()
        self.provenance: dict[str, dict[str, object]] = {}


def calculate_structural_stress(
    *,
    exposure: object,
    collateral_fraction: object,
    haircut_fraction: object,
    concentration_limit_fraction: object,
    registry: object = None,
    candidates: object = None,
    decision_time: object = None,
    instrument_id: str = "",
) -> dict[str, object]:
    """Calculate separate unsecured and collateral-concentration stresses.

    Every input must carry an explicit unit.  Fractions must already be decimal
    fractions in [0, 1]; percentages, implicit numbers, non-finite values and
    ambiguous units are unavailable rather than coerced or zero-filled.
    """

    decision = _timestamp(decision_time) if decision_time is not None else None
    amount = _decimal_input(
        exposure,
        allowed_units={"fraction_of_nav"},
        field_name="exposure",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        candidates=candidates,
        decision=decision,
        instrument_id=instrument_id,
    )
    collateral = _decimal_input(
        collateral_fraction,
        allowed_units={"fraction_of_exposure"},
        field_name="collateral_fraction",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        candidates=candidates,
        decision=decision,
        instrument_id=instrument_id,
    )
    haircut = _decimal_input(
        haircut_fraction,
        allowed_units={"scenario_haircut_fraction"},
        field_name="haircut_fraction",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        candidates=candidates,
        decision=decision,
        instrument_id=instrument_id,
    )
    limit = _decimal_input(
        concentration_limit_fraction,
        allowed_units={"fraction_of_collateral"},
        field_name="concentration_limit_fraction",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        candidates=candidates,
        decision=decision,
        instrument_id=instrument_id,
    )
    if amount is None or collateral is None or haircut is None or limit is None:
        return _unavailable_stress("numeric_evidence_missing_invalid_or_unbound")
    unsecured = max(Decimal("0"), amount - amount * collateral * (Decimal("1") - haircut))
    concentration = amount * collateral * limit * haircut
    return {
        "status": "available",
        "unsecured_pct_nav": float(unsecured),
        "concentration_pct_nav": float(concentration),
        "unsecured": float(unsecured),
        "concentration": float(concentration),
        "unsecured_exposure": float(unsecured),
        "concentration_exposure": float(concentration),
        "units": {
            "exposure": "fraction_of_nav",
            "collateral_fraction": "fraction_of_exposure",
            "haircut_fraction": "scenario_haircut_fraction",
            "concentration_limit_fraction": "fraction_of_collateral",
            "outputs": "fraction_of_nav",
        },
        "formula_version": STRESS_FORMULA_VERSION,
        "execution_allowed": False,
    }


calculate_counterparty_collateral_stress = calculate_structural_stress


def project_etf_structure(
    instrument_id: str,
    *,
    document_registry: object = None,
    report_records: object = None,
    supplemental_rows: object = None,
    holdings: object = None,
    decision_time: object = None,
    numeric_inputs: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project latest usable structural evidence as of ``decision_time``."""

    target = str(instrument_id or "").strip()
    registry_rows = _rows(document_registry)
    decision = _timestamp(decision_time) if decision_time is not None else None
    registry, rejected_registry = _bound_registry(target, registry_rows, decision)
    candidates, rejected_candidates = _report_candidates(report_records, registry, target, decision)
    supplemental, supplemental_rejections = _supplemental_candidates(supplemental_rows, registry, target, decision)
    holding_candidates, holding_rejections = _supplemental_candidates(holdings, registry, target, decision, default_document_type="holdings")
    candidates.extend(supplemental)
    candidates.extend(holding_candidates)
    rejected = [*rejected_registry, *rejected_candidates, *supplemental_rejections, *holding_rejections]
    selected_sources = _latest_sources(registry, candidates)
    usable = [item for item in candidates if item.source_id in selected_sources.get(_family(item.document_type), set())]

    fields: dict[str, dict[str, object]] = {}
    for field in STRUCTURAL_FIELDS:
        applicable = [item for item in usable if item.field_name == field]
        invalid_for_field = any(item.get("field_name") == field for item in rejected if isinstance(item, dict))
        if not applicable:
            status = "unusable" if invalid_for_field else "unknown"
            fields[field] = _field_payload(field, status=status)
            continue
        values = {item.value.casefold(): item for item in applicable}
        if len(values) > 1:
            fields[field] = _field_payload(
                field,
                status="conflict",
                candidates=applicable,
            )
        else:
            chosen = max(applicable, key=lambda item: (item.document_date, item.known_at, item.source_id, item.page))
            fields[field] = _field_payload(field, status="resolved", candidate=chosen, candidates=applicable)

    versions = _version_rows(registry, selected_sources)
    matrix = _document_matrix(registry, selected_sources, usable)
    flags = _risk_flags(fields)
    stress = (
        calculate_structural_stress(
            **numeric_inputs,
            registry=registry,
            candidates=usable,
            decision_time=decision,
            instrument_id=target,
        )
        if numeric_inputs
        else _unavailable_stress()
    )
    applicable_fields, applicability_evidence = _applicable_fields(fields)
    confidence_values = [
        float(fields[field]["confidence"]) if fields[field]["status"] == "resolved" else 0.0
        for field in applicable_fields
    ]
    confidence_cap = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    unknown_fields = tuple(field for field, value in fields.items() if value["status"] == "unknown")
    conflict_fields = tuple(field for field, value in fields.items() if value["status"] == "conflict")
    unusable_fields = tuple(field for field, value in fields.items() if value["status"] == "unusable")
    if rejected and not usable:
        status = "unusable"
    elif conflict_fields:
        status = "conflict"
    elif unknown_fields or unusable_fields:
        status = "partial"
    else:
        status = "available"
    structure_identity = {
        "structure_projection_version": STRUCTURE_PROJECTION_VERSION,
        "structure_schema_version": STRUCTURE_SCHEMA_VERSION,
        "structure_confidence_version": STRUCTURE_CONFIDENCE_VERSION,
        "structure_provenance_hash": _structure_provenance_hash(
            fields=fields,
            documents=matrix,
            versions=versions,
            rejected_candidates=rejected,
            applicable_fields=applicable_fields,
            applicability_evidence=applicability_evidence,
        ),
        "structure_confidence_cap": confidence_cap,
    }
    return {
        "schema_version": STRUCTURE_SCHEMA_VERSION,
        "contract": STRUCTURE_PROJECTION_VERSION,
        "instrument_id": target,
        "status": status,
        "fields": fields,
        "documents": matrix,
        "versions": versions,
        "flags": flags,
        "unknown_fields": list(unknown_fields),
        "conflict_fields": list(conflict_fields),
        "unusable_fields": list(unusable_fields),
        "rejected_candidates": rejected,
        "confidence_version": STRUCTURE_CONFIDENCE_VERSION,
        "applicable_fields": list(applicable_fields),
        "applicability_evidence": applicability_evidence,
        "applicable_field_count": len(applicable_fields),
        "applicable_resolved_field_count": sum(value > 0.0 for value in confidence_values),
        "coverage_evidence": {
            "applicable_fields": list(applicable_fields),
            "resolved_fields": [field for field in applicable_fields if fields[field]["status"] == "resolved"],
            "coverage_ratio": confidence_cap,
            "method": "equal_weight_mean_of_applicable_direct_confidence",
            "version": STRUCTURE_CONFIDENCE_VERSION,
        },
        "evidence_confidence_cap": confidence_cap,
        "confidence_cap": confidence_cap,
        "coverage_cap": confidence_cap,
        **structure_identity,
        "structure_identity": structure_identity,
        "confidence_limitation": "Unknown and conflicted structural evidence contributes 0; this caps evidence confidence only.",
        "stress": stress,
        "alpha_eligible": False,
        "score_impact": "evidence_confidence_only",
        "sustainability_or_legal_labels_affect_alpha": False,
        "execution_allowed": False,
    }


build_etf_structure_analysis = project_etf_structure
build_etf_structure_projection = project_etf_structure


def structure_confidence_caps(
    instrument_ids: Iterable[object],
    *,
    document_registry: object = None,
    report_records: object = None,
    supplemental_rows: object = None,
    holdings: object = None,
    decision_time: object = None,
) -> dict[str, float]:
    """Project a fail-closed cap for every instrument at one decision time.

    Evidence is intentionally supplied by the caller so a service/backtest
    boundary can load each local evidence source once and reuse the immutable
    rows for every point-in-time projection.
    """

    caps = StructureConfidenceCaps()
    registry_rows = _rows(document_registry)
    report_rows = _rows(report_records)
    supplemental = _rows(supplemental_rows)
    holding_rows = _rows(holdings)
    if not any((registry_rows, report_rows, supplemental, holding_rows)):
        for instrument_id in instrument_ids:
            target = str(instrument_id)
            caps[target] = 0.0
            caps.provenance[target] = {
                "structure_projection_version": STRUCTURE_PROJECTION_VERSION,
                "structure_schema_version": STRUCTURE_SCHEMA_VERSION,
                "structure_confidence_version": STRUCTURE_CONFIDENCE_VERSION,
                "structure_provenance_hash": "unavailable",
                "structure_confidence_cap": 0.0,
            }
        return caps
    for instrument_id in instrument_ids:
        target = str(instrument_id)
        try:
            projection = project_etf_structure(
                target,
                document_registry=registry_rows,
                report_records=report_rows,
                supplemental_rows=supplemental,
                holdings=holding_rows,
                decision_time=decision_time,
            )
            cap = projection.get("evidence_confidence_cap", 0.0)
            caps[target] = float(cap) if isinstance(cap, (int, float)) and math.isfinite(float(cap)) else 0.0
            caps.provenance[target] = dict(projection.get("structure_identity", {}))
        except Exception:
            caps[target] = 0.0
            caps.provenance[target] = {
                "structure_projection_version": STRUCTURE_PROJECTION_VERSION,
                "structure_schema_version": STRUCTURE_SCHEMA_VERSION,
                "structure_confidence_version": STRUCTURE_CONFIDENCE_VERSION,
                "structure_provenance_hash": "unavailable",
                "structure_confidence_cap": 0.0,
            }
    return caps


def structure_input_checksum(
    *,
    document_registry: object = None,
    report_records: object = None,
    supplemental_rows: object = None,
    holdings: object = None,
) -> str:
    """Fingerprint every local structural input that can change a projection."""

    payload = {
        "projection_version": STRUCTURE_PROJECTION_VERSION,
        "schema_version": STRUCTURE_SCHEMA_VERSION,
        "confidence_version": STRUCTURE_CONFIDENCE_VERSION,
        "document_registry": _stable_rows(document_registry),
        "report_records": _stable_rows(report_records),
        "supplemental_rows": _stable_rows(supplemental_rows),
        "holdings": _stable_rows(holdings),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _rows(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        return [{str(key): item for key, item in row.items()} for row in value.to_dict("records")]
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (str, bytes)):
        return []
    try:
        result: list[dict[str, object]] = []
        for item in value:  # type: ignore[union-attr]
            if isinstance(item, Mapping):
                result.append(dict(item))
            elif hasattr(item, "__dict__"):
                result.append(dict(vars(item)))
        return result
    except TypeError:
        return []


def _bound_registry(target: str, rows: list[dict[str, object]], decision: datetime | None) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    bound: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("instrument_id") or "").strip() != target:
            continue
        source_id = _text(row.get("source_id"))
        checksum = _text(row.get("sha256")) or _text(row.get("checksum"))
        document_date = _date_text(row.get("document_date"))
        known_at = _date_time_text(row.get("known_at")) or _date_time_text(row.get("ingested_at"))
        if not source_id or not checksum or not document_date or not known_at:
            rejected.append({"reason_code": "registry_identity_incomplete", "source_id": source_id or "unavailable"})
            continue
        if decision is not None and _parse_timestamp(known_at) > decision:
            continue
        item = dict(row)
        item.update({"source_id": source_id, "checksum": checksum, "document_date": document_date, "known_at": known_at})
        bound.append(item)
    return bound, rejected


def _report_candidates(value: object, registry: list[dict[str, object]], target: str, decision: datetime | None) -> tuple[list[StructureCandidate], list[dict[str, object]]]:
    result: list[StructureCandidate] = []
    rejected: list[dict[str, object]] = []
    registry_by_id = {str(row["source_id"]): row for row in registry}
    for row in _rows(value):
        source_id = _text(row.get("source_id"))
        registered = registry_by_id.get(source_id or "")
        if not source_id or registered is None or str(row.get("instrument_id") or "").strip() != target:
            rejected.append({"reason_code": "candidate_not_bound_to_registry", "source_id": source_id or "unavailable"})
            continue
        if str(row.get("verification_status") or "").strip().casefold() != "verified" or not _stored_true(row.get("evidence_eligible")):
            rejected.append({"reason_code": "report_evidence_not_eligible", "source_id": source_id})
            continue
        row_checksum = _text(row.get("source_sha256")) or _text(row.get("sha256")) or _text(row.get("checksum"))
        row_date = _date_text(row.get("document_date"))
        row_known_at = _date_time_text(row.get("known_at"))
        if not row_checksum or not row_date or not row_known_at:
            rejected.append({"reason_code": "report_identity_incomplete", "source_id": source_id})
            continue
        if row_checksum != _text(registered.get("checksum")):
            rejected.append({"reason_code": "candidate_checksum_mismatch", "source_id": source_id})
            continue
        if row_date and row_date != _date_text(registered.get("document_date")):
            rejected.append({"reason_code": "candidate_date_mismatch", "source_id": source_id})
            continue
        if row_known_at != (_date_time_text(registered.get("known_at")) or _date_time_text(registered.get("ingested_at"))):
            rejected.append({"reason_code": "candidate_known_at_mismatch", "source_id": source_id})
            continue
        evidence = _json_rows(row.get("field_evidence"))
        for item in evidence:
            field = _canonical_field(item.get("field_name"))
            if field not in STRUCTURAL_FIELDS:
                continue
            status = _text(item.get("status")) or "unknown"
            value_text = _text(item.get("value"))
            page = _page(item.get("source_page")) or _first_page(item.get("candidate_pages"))
            if status not in _USABLE_STATUSES or not value_text:
                if status not in {"unknown", ""}:
                    rejected.append({"field_name": field, "reason_code": "candidate_unusable", "source_id": source_id})
                continue
            candidate, reason = _make_candidate(target, field, value_text, source_id, registered, page, item.get("confidence"), decision)
            if candidate is None:
                rejected.append({"field_name": field, "reason_code": reason, "source_id": source_id})
            else:
                result.append(candidate)
    return result, rejected


def _supplemental_candidates(value: object, registry: list[dict[str, object]], target: str, decision: datetime | None, *, default_document_type: str | None = None) -> tuple[list[StructureCandidate], list[dict[str, object]]]:
    result: list[StructureCandidate] = []
    rejected: list[dict[str, object]] = []
    registry_by_id = {str(row["source_id"]): row for row in registry}
    for row in _rows(value):
        field = _canonical_field(row.get("field_name", row.get("field")))
        if field not in STRUCTURAL_FIELDS:
            continue
        source_id = _text(row.get("source_id"))
        registered = registry_by_id.get(source_id or "")
        document_type = _text(row.get("document_type")) or default_document_type
        page = _page(row.get("page", row.get("source_page")))
        value_text = _text(row.get("value"))
        row_checksum = _text(row.get("checksum")) or _text(row.get("sha256"))
        row_date = _date_text(row.get("document_date"))
        row_known_at = _date_time_text(row.get("known_at"))
        reason = None
        if str(row.get("instrument_id") or "").strip() != target or not source_id or registered is None:
            reason = "candidate_not_bound_to_registry"
        elif not document_type or _family(document_type) != _family(str(registered.get("document_type") or registered.get("document_kind") or "")):
            reason = "candidate_document_family_mismatch"
        elif not value_text or page is None:
            reason = "candidate_page_or_value_missing"
        elif not row_checksum or not row_date or not row_known_at:
            reason = "candidate_registry_binding_incomplete"
        elif row_checksum != _text(registered.get("checksum")) or row_date != _date_text(registered.get("document_date")) or row_known_at != _date_time_text(registered.get("known_at")):
            reason = "candidate_registry_binding_mismatch"
        if reason:
            rejected.append({"field_name": field, "reason_code": reason, "source_id": source_id or "unavailable"})
            continue
        candidate, candidate_reason = _make_candidate(target, field, value_text, source_id, registered, page, row.get("confidence"), decision, status=_text(row.get("status")) or "extracted")
        if candidate is None:
            rejected.append({"field_name": field, "reason_code": candidate_reason, "source_id": source_id})
        else:
            result.append(candidate)
    return result, rejected


def _make_candidate(target: str, field: str, value: str, source_id: str, registered: Mapping[str, object], page: int | None, confidence: object, decision: datetime | None, *, status: str = "extracted") -> tuple[StructureCandidate | None, str]:
    if page is None or page <= 0:
        return None, "candidate_page_invalid"
    confidence_value = _confidence_value(confidence)
    if confidence_value is None:
        return None, "candidate_confidence_invalid"
    known_at = _date_time_text(registered.get("known_at")) or _date_time_text(registered.get("ingested_at"))
    checksum = _text(registered.get("checksum")) or _text(registered.get("sha256"))
    document_date = _date_text(registered.get("document_date"))
    if not known_at or not checksum or not document_date:
        return None, "candidate_registry_binding_incomplete"
    if decision is not None and _parse_timestamp(known_at) > decision:
        return None, "candidate_not_known_at_decision_time"
    return StructureCandidate(target, field, value, source_id, _text(registered.get("document_type")) or _text(registered.get("document_kind")) or "unknown", document_date, page, confidence_value, known_at, checksum, status), ""


def _latest_sources(registry: list[dict[str, object]], candidates: Iterable[StructureCandidate] = ()) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    grouped: dict[str, list[dict[str, object]]] = {}
    candidate_source_ids = {item.source_id for item in candidates}
    for row in registry:
        family = _family(str(row.get("document_kind") or row.get("document_type") or ""))
        if family not in DOCUMENT_FAMILIES:
            continue
        if str(row.get("coverage_status") or "available") not in _USABLE_STATUSES:
            continue
        if candidate_source_ids and str(row.get("source_id")) not in candidate_source_ids:
            continue
        grouped.setdefault(family, []).append(row)
    for family, rows in grouped.items():
        latest = max(rows, key=lambda row: (_date_text(row.get("document_date")) or "", _date_time_text(row.get("known_at")) or "", str(row.get("source_id"))))
        result[family] = {str(latest["source_id"])}
    return result


def _document_matrix(registry: list[dict[str, object]], selected: dict[str, set[str]], candidates: list[StructureCandidate]) -> dict[str, dict[str, object]]:
    matrix: dict[str, dict[str, object]] = {}
    for family in DOCUMENT_FAMILIES:
        rows = [row for row in registry if _family(str(row.get("document_kind") or row.get("document_type") or "")) == family]
        source_ids = selected.get(family, set())
        chosen = [row for row in rows if str(row.get("source_id")) in source_ids]
        if not chosen:
            matrix[family] = {"status": "unknown", "source_id": "unavailable", "document_date": "unavailable", "checksum": "unavailable", "version": "unavailable", "fields": [], "execution_allowed": False}
            continue
        row = chosen[0]
        family_candidates = [item for item in candidates if _family(item.document_type) == family and item.source_id in source_ids]
        matrix[family] = {
            "status": "available" if family_candidates else "unknown",
            "source_id": row.get("source_id", "unavailable"),
            "document_date": row.get("document_date", "unavailable"),
            "checksum": row.get("checksum", "unavailable"),
            "version": row.get("document_version", row.get("version", "unavailable")) or "unavailable",
            "known_at": row.get("known_at", "unavailable"),
            "fields": sorted({item.field_name for item in family_candidates}),
            "execution_allowed": False,
        }
    return matrix


def _version_rows(registry: list[dict[str, object]], selected: dict[str, set[str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in registry:
        family = _family(str(row.get("document_kind") or row.get("document_type") or ""))
        if family not in {"prospectus", "factsheet", "holdings", "kid", "sfdr"}:
            continue
        rows.append({"family": family, "document_type": row.get("document_type", "unavailable"), "document_kind": row.get("document_kind", "unavailable"), "version": row.get("document_version", row.get("version", "unavailable")) or "unavailable", "document_date": row.get("document_date", "unavailable"), "known_at": row.get("known_at", "unavailable"), "source_id": row.get("source_id", "unavailable"), "checksum": row.get("checksum", "unavailable"), "latest_usable": str(row.get("source_id")) in selected.get(family, set()), "execution_allowed": False})
    return sorted(rows, key=lambda row: (str(row["family"]), str(row["document_date"]), str(row["source_id"])))


def _risk_flags(fields: Mapping[str, Mapping[str, object]]) -> list[str]:
    flags: list[str] = []
    replication = str(fields.get("replication_method", {}).get("value") or "").casefold()
    derivatives = str(fields.get("derivatives", {}).get("value") or "").casefold()
    lending = str(fields.get("lending_policy", {}).get("value") or "").casefold()
    synthetic = any(token in f"{replication} {derivatives}" for token in ("synthetic", "swap", "derivative"))
    if fields.get("replication_method", {}).get("status") in {"unknown", "conflict", "unusable"}:
        flags.append("replication_structure_unknown_or_conflicted")
    if synthetic:
        if fields.get("counterparties", {}).get("status") != "resolved":
            flags.append("synthetic_counterparty_evidence_missing_or_conflicted")
        if fields.get("collateral_terms", {}).get("status") != "resolved":
            flags.append("synthetic_collateral_evidence_missing_or_conflicted")
    lending_enabled = any(token in lending for token in ("allow", "enabled", "up to", "may lend", "lending")) and not any(token in lending for token in ("not permitted", "prohibited", "no lending"))
    if lending_enabled and fields.get("collateral_terms", {}).get("status") != "resolved":
        flags.append("lending_collateral_terms_missing_or_conflicted")
    if fields.get("concentration_limits", {}).get("status") in {"unknown", "conflict", "unusable"}:
        flags.append("concentration_limits_unknown_or_conflicted")
    return flags


def _applicable_fields(fields: Mapping[str, Mapping[str, object]]) -> tuple[tuple[str, ...], dict[str, dict[str, object]]]:
    """Return the versioned set of structural fields that can affect coverage.

    Base fields are always required.  Counterparty/collateral evidence is
    required only when the selected evidence discloses synthetic or derivative
    exposure; lending revenue and collateral terms are required only when the
    lending policy enables lending.  Unknown evidence never infers either
    branch.
    """

    applicable = list(BASE_REQUIRED_STRUCTURE_FIELDS)
    reasons: dict[str, list[str]] = {field: ["base_required"] for field in BASE_REQUIRED_STRUCTURE_FIELDS}
    replication = str(fields.get("replication_method", {}).get("value") or "").casefold()
    derivatives = str(fields.get("derivatives", {}).get("value") or "").casefold()
    lending = str(fields.get("lending_policy", {}).get("value") or "").casefold()
    synthetic_or_derivatives = any(token in f"{replication} {derivatives}" for token in ("synthetic", "swap", "derivative"))
    lending_enabled = (
        any(token in lending for token in ("allow", "enabled", "up to", "may lend", "lending"))
        and not any(token in lending for token in ("not permitted", "prohibited", "no lending"))
    )
    if synthetic_or_derivatives:
        for field in ("counterparties", "collateral_terms"):
            if field not in applicable:
                applicable.append(field)
            reasons.setdefault(field, []).append("synthetic_or_derivatives_disclosed")
    if lending_enabled:
        for field in ("collateral_terms", "lending_revenue_split"):
            if field not in applicable:
                applicable.append(field)
            reasons.setdefault(field, []).append("lending_enabled")
    evidence = {
        field: {
            "applicable": field in applicable,
            "reasons": reasons.get(field, ["not_applicable"]),
            "status": fields.get(field, {}).get("status", "unknown"),
        }
        for field in STRUCTURAL_FIELDS
    }
    return tuple(applicable), evidence


def _field_payload(field: str, *, status: str, candidate: StructureCandidate | None = None, candidates: Iterable[StructureCandidate] = ()) -> dict[str, object]:
    items = tuple(candidates)
    if candidate is None and items:
        candidate = max(items, key=lambda item: (item.document_date, item.known_at, item.source_id, item.page))
    return {
        "field_name": field,
        "status": status,
        "value": candidate.value if candidate is not None and status == "resolved" else None,
        "document_id": candidate.source_id if candidate is not None and status == "resolved" else "unavailable",
        "source_id": candidate.source_id if candidate is not None and status == "resolved" else "unavailable",
        "document_type": candidate.document_type if candidate is not None and status == "resolved" else "unavailable",
        "document_date": candidate.document_date if candidate is not None and status == "resolved" else "unavailable",
        "page": candidate.page if candidate is not None and status == "resolved" else None,
        "confidence": candidate.confidence if candidate is not None and status == "resolved" else 0.0,
        "known_at": candidate.known_at if candidate is not None and status == "resolved" else "unavailable",
        "checksum": candidate.checksum if candidate is not None and status == "resolved" else "unavailable",
        "candidates": [_candidate_payload(item) for item in items],
        "execution_allowed": False,
    }


def _candidate_payload(item: StructureCandidate) -> dict[str, object]:
    return {"value": item.value, "source_id": item.source_id, "document_type": item.document_type, "document_date": item.document_date, "page": item.page, "confidence": item.confidence, "known_at": item.known_at, "checksum": item.checksum}


def _family(document_type: str) -> str:
    value = str(document_type or "").strip().casefold().replace("-", "_")
    if value in _REPORT_KINDS or value == "prospectus_report":
        return "prospectus"
    return {"priips_kid": "kid", "index_methodology": "methodology", "sfdr_disclosure": "sfdr"}.get(value, value)


def _canonical_field(value: object) -> str:
    return _FIELD_ALIASES.get(str(value or "").strip().casefold(), str(value or "").strip().casefold())


def _confidence_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None
    return _CONFIDENCE.get(str(value or "").strip().casefold())


def _decimal_input(
    value: object,
    *,
    allowed_units: set[str],
    field_name: str,
    bounds: tuple[Decimal, Decimal] | None = None,
    registry: object = None,
    candidates: object = None,
    decision: datetime | None = None,
    instrument_id: str = "",
) -> Decimal | None:
    if not isinstance(value, NumericEvidence):
        return None
    raw, unit = value.value, value.unit
    if value.field_name != field_name or unit not in allowed_units or isinstance(raw, bool):
        return None
    if not _numeric_provenance_is_bound(
        value,
        registry,
        candidates,
        decision,
        instrument_id,
        field_name,
        value.normalized_value,
        unit,
    ):
        return None
    number = value.normalized_value
    if number is None:
        return None
    if not number.is_finite() or (bounds is not None and not bounds[0] <= number <= bounds[1]) or (bounds is None and number < 0):
        return None
    return number


def _numeric_provenance_is_bound(
    value: NumericEvidence,
    registry: object,
    candidates: object,
    decision: datetime | None,
    instrument_id: str,
    field_name: str,
    normalized_value: Decimal | None,
    unit: str,
) -> bool:
    source_id = _text(value.source_id)
    checksum = _text(value.checksum)
    document_date = _date_text(value.document_date)
    known_at = _date_time_text(value.known_at)
    page = _page(value.page)
    confidence = _confidence_value(value.confidence)
    if not source_id or not checksum or not document_date or not known_at or page is None or confidence is None:
        return False
    if value.field_name != field_name or value.unit != unit or normalized_value is None:
        return False
    registry_rows = _rows(registry)
    matches = [row for row in registry_rows if _text(row.get("source_id")) == source_id]
    if len(matches) != 1:
        return False
    row = matches[0]
    registered_checksum = _text(row.get("sha256")) or _text(row.get("checksum"))
    registered_date = _date_text(row.get("document_date"))
    registered_known_at = _date_time_text(row.get("known_at")) or _date_time_text(row.get("ingested_at"))
    if checksum != registered_checksum or document_date != registered_date or known_at != registered_known_at:
        return False
    if instrument_id and _text(row.get("instrument_id")) != instrument_id:
        return False
    if decision is not None and _parse_timestamp(known_at) > decision:
        return False
    candidate_rows: list[NumericEvidence] = []
    if candidates is not None and not isinstance(candidates, (str, bytes, Mapping, pd.DataFrame)):
        try:
            candidate_rows = [item for item in candidates if isinstance(item, NumericEvidence)]
        except TypeError:
            candidate_rows = []
    return any(
        item.source_id == source_id
        and item.checksum == checksum
        and _date_text(item.document_date) == document_date
        and _date_time_text(item.known_at) == known_at
        and _page(item.page) == page
        and _confidence_value(item.confidence) == confidence
        and item.field_name == field_name
        and item.unit == unit
        and item.normalized_value == normalized_value
        and item.instrument_id == instrument_id
        and str(item.status).casefold() in _USABLE_STATUSES
        for item in candidate_rows
    )


def _unavailable_stress(reason_code: str = "numeric_evidence_not_supplied") -> dict[str, object]:
    return {
        "status": "unavailable",
        "reason_code": reason_code,
        "unsecured_pct_nav": None,
        "concentration_pct_nav": None,
        "unsecured": None,
        "concentration": None,
        "unsecured_exposure": None,
        "concentration_exposure": None,
        "formula_version": STRESS_FORMULA_VERSION,
        "execution_allowed": False,
    }


def _json_rows(value: object) -> list[dict[str, object]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return _rows(value)


def _normalise_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _stored_true(value: object) -> bool:
    return type(value).__name__ in {"bool", "bool_"} and bool(value)


def _stable_rows(value: object) -> list[object]:
    rows = _rows(value)
    normalised = [
        {str(key): _stable_value(item) for key, item in sorted(row.items(), key=lambda pair: str(pair[0]))}
        for row in rows
    ]
    return sorted(normalised, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))


def _stable_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _stable_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return _stable_value(value.item())
        except (AttributeError, ValueError):
            pass
    return value


def _structure_provenance_hash(
    *,
    fields: Mapping[str, object],
    documents: Mapping[str, object],
    versions: object,
    rejected_candidates: object,
    applicable_fields: object,
    applicability_evidence: object,
) -> str:
    payload = {
        "projection_version": STRUCTURE_PROJECTION_VERSION,
        "schema_version": STRUCTURE_SCHEMA_VERSION,
        "confidence_version": STRUCTURE_CONFIDENCE_VERSION,
        "fields": _stable_value(fields),
        "documents": _stable_value(documents),
        "versions": _stable_value(versions),
        "rejected_candidates": _stable_value(rejected_candidates),
        "applicable_fields": _stable_value(applicable_fields),
        "applicability_evidence": _stable_value(applicability_evidence),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def _page(value: object) -> int | None:
    try:
        page = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _first_page(value: object) -> int | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and value:
        return _page(value[0])
    return None


def _date_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None


def _date_time_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = _parse_timestamp(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time(23, 59, 59), tzinfo=timezone.utc)
    return _parse_timestamp(str(value))


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "BASE_REQUIRED_STRUCTURE_FIELDS", "DOCUMENT_FAMILIES", "NumericCandidate", "NumericEvidence", "STRESS_FORMULA_VERSION", "STRUCTURAL_FIELDS", "StructureCandidate",
    "STRUCTURE_CONFIDENCE_VERSION", "STRUCTURE_SCHEMA_VERSION", "build_etf_structure_analysis", "build_etf_structure_projection",
    "STRUCTURE_PROJECTION_VERSION", "calculate_counterparty_collateral_stress", "calculate_structural_stress", "project_etf_structure", "structure_confidence_caps", "structure_input_checksum",
]


NumericCandidate = NumericEvidence
