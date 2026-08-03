"""Fail-closed ETF structural and document-risk projection.

This module is deliberately a read model.  It does not fetch documents, parse
OCR, call models, calculate alpha, or grant execution authority.  Candidates
are usable only when their identity can be matched exactly to the local fund
document registry at a known point in time.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
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
class LocalStructuralEvidence:
    """Canonical local structural inputs shared by score and backtest paths."""

    document_registry: object
    report_records: object
    supplemental_rows: object
    holdings: object


def load_local_structural_evidence(
    *,
    registry_reader: Callable[[], object] | None = None,
    report_reader: Callable[[], object] | None = None,
    factsheet_path: object = None,
    holdings_path: object = None,
) -> LocalStructuralEvidence:
    """Load canonical local registry, reports, factsheet rows and holdings."""

    if registry_reader is None:
        from etf_cockpit.data.fund_documents import read_document_registry

        registry_reader = read_document_registry
    if report_reader is None:
        from etf_cockpit.data.parsed_disclosures import read_etf_report_records

        report_reader = read_etf_report_records
    if factsheet_path is None:
        from etf_cockpit.data.reference_data import ETF_METADATA_CLEAN_PATH

        factsheet_path = ETF_METADATA_CLEAN_PATH
    if holdings_path is None:
        from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH

        holdings_path = FUND_HOLDINGS_PATH

    registry = registry_reader()
    reports = report_reader()
    factsheet = _read_local_structural_rows(factsheet_path, "factsheet")
    try:
        holdings = pd.read_parquet(holdings_path) if Path(holdings_path).exists() else pd.DataFrame()
    except Exception as exc:
        raise ValueError(f"Canonical holdings store is corrupt: {holdings_path}") from exc
    _validate_canonical_frame(holdings, "holdings", holdings_path)
    return LocalStructuralEvidence(registry, reports, factsheet, holdings)


def _read_local_structural_rows(path: object, default_document_type: str) -> pd.DataFrame:
    """Adapt canonical reference rows to the structural projection contract."""

    candidate = Path(path)
    if not candidate.is_file():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(candidate)
    except Exception as exc:
        raise ValueError(f"Canonical {default_document_type} store is corrupt: {candidate}") from exc
    if frame.empty:
        return pd.DataFrame()
    _validate_canonical_frame(frame, default_document_type, candidate)
    records: list[dict[str, object]] = []
    for source in frame.to_dict("records"):
        common = {
            "instrument_id": source.get("instrument_id", source.get("etf_id")),
            "source_id": source.get("source_id"),
            "document_type": source.get("document_type") or default_document_type,
            "checksum": source.get("checksum") or source.get("sha256"),
            "document_date": source.get("document_date") or source.get("as_of_date") or source.get("as_of"),
            "known_at": source.get("known_at") or source.get("ingested_at") or source.get("imported_at"),
            "page": source.get("page") or source.get("source_page"),
            "confidence": source.get("confidence"),
            "status": source.get("status", "unknown"),
        }
        if source.get("field_name") or source.get("field"):
            records.append({**common, "field_name": source.get("field_name") or source.get("field"), "value": source.get("value")})
            continue
        # A structural claim is accepted only through the explicit
        # field/value columns.  Ordinary analytical columns are not evidence.
    return pd.DataFrame(records)


def _validate_canonical_frame(frame: pd.DataFrame, document_type: str, path: object) -> None:
    """Reject valid Parquet files that cannot be canonical evidence stores."""

    if bool(frame.columns.duplicated().any()):
        raise ValueError(f"Canonical {document_type} store has duplicate columns: {path}")
    # ``source_id`` is retained for legacy local fixtures; the projection
    # still rejects it later when the exact instrument binding is absent.
    identity_columns = {"instrument_id", "etf_id", "fund_id", "source_id"}
    if not identity_columns.intersection(frame.columns):
        raise ValueError(f"Canonical {document_type} store is missing instrument identity: {path}")


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
    review_event: Mapping[str, object] | None = None


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
    report_records: object = None,
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
        report_records=report_records,
        decision=decision,
        instrument_id=instrument_id,
    )
    collateral = _decimal_input(
        collateral_fraction,
        allowed_units={"fraction_of_exposure"},
        field_name="collateral_fraction",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        report_records=report_records,
        decision=decision,
        instrument_id=instrument_id,
    )
    haircut = _decimal_input(
        haircut_fraction,
        allowed_units={"scenario_haircut_fraction"},
        field_name="haircut_fraction",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        report_records=report_records,
        decision=decision,
        instrument_id=instrument_id,
    )
    limit = _decimal_input(
        concentration_limit_fraction,
        allowed_units={"fraction_of_collateral"},
        field_name="concentration_limit_fraction",
        bounds=(Decimal("0"), Decimal("1")),
        registry=registry,
        report_records=report_records,
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
        "provenance": {
            field: _numeric_provenance_payload(value)
            for field, value in (
                ("exposure", exposure),
                ("collateral_fraction", collateral_fraction),
                ("haircut_fraction", haircut_fraction),
                ("concentration_limit_fraction", concentration_limit_fraction),
            )
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
    numeric_candidates: object = None,
) -> dict[str, object]:
    """Project latest usable structural evidence as of ``decision_time``."""

    target = str(instrument_id or "").strip()
    registry_rows = _rows(document_registry)
    decision = _timestamp(decision_time) if decision_time is not None else None
    supplied_report_error: str | None = None
    try:
        validated_reports = _validated_report_rows(report_records)
    except ValueError as exc:
        validated_reports = []
        supplied_report_error = str(exc)
    registry, rejected_registry = _bound_registry(target, registry_rows, decision)
    candidates, rejected_candidates = _report_candidates(validated_reports, registry, target, decision)
    supplemental, supplemental_rejections = _supplemental_candidates(supplemental_rows, registry, target, decision)
    holding_candidates, holding_rejections = _supplemental_candidates(holdings, registry, target, decision, default_document_type="holdings")
    candidates.extend(supplemental)
    candidates.extend(holding_candidates)
    rejected = [*rejected_registry, *rejected_candidates, *supplemental_rejections, *holding_rejections]
    if supplied_report_error:
        rejected.append({"reason_code": "supplied_report_records_invalid", "detail": supplied_report_error})
    selected_sources = _latest_sources(registry, candidates)
    usable = [item for item in candidates if item.source_id in selected_sources.get(_family(item.document_type), set())]
    source_vintage = {
        source_id: dict(event)
        for source_id, event in sorted(
            {
                item.source_id: item.review_event
                for item in usable
                if item.review_event
            }.items()
        )
    }

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
    derived_numeric_inputs, derived_numeric_candidates = _report_numeric_inputs(
        validated_reports, registry, target, decision, selected_sources
    )
    effective_numeric_inputs = numeric_inputs if numeric_inputs is not None else derived_numeric_inputs
    effective_numeric_candidates = numeric_candidates if numeric_candidates is not None else derived_numeric_candidates
    stress = (
        calculate_structural_stress(
            **effective_numeric_inputs,
            registry=registry,
            report_records=validated_reports,
            candidates=effective_numeric_candidates,
            decision_time=decision,
            instrument_id=target,
        )
        if effective_numeric_inputs and set(_NUMERIC_UNITS).issubset(effective_numeric_inputs)
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
            source_vintage=source_vintage,
        ),
        "structure_confidence_cap": confidence_cap,
        "source_vintage": source_vintage,
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
        "source_vintage": source_vintage,
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
    try:
        report_rows = _validated_report_rows(report_records)
    except ValueError:
        report_rows = []
        invalid_reports = True
    else:
        invalid_reports = False
    supplemental = _rows(supplemental_rows)
    holding_rows = _rows(holdings)
    if invalid_reports:
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

    registry_rows = _rows(document_registry)
    duplicate_registry_ids = _duplicate_source_ids(registry_rows)
    if duplicate_registry_ids:
        raise ValueError(f"document registry contains duplicate source_id values: {', '.join(sorted(duplicate_registry_ids))}")
    validated_reports = _validated_report_rows(report_records)
    payload = {
        "projection_version": STRUCTURE_PROJECTION_VERSION,
        "schema_version": STRUCTURE_SCHEMA_VERSION,
        "confidence_version": STRUCTURE_CONFIDENCE_VERSION,
        "document_registry": _stable_rows(registry_rows),
        "report_records": _stable_rows(validated_reports),
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


def _validated_report_rows(value: object) -> list[dict[str, object]]:
    from etf_cockpit.data.parsed_disclosures import validate_supplied_etf_report_records

    return validate_supplied_etf_report_records(value).to_dict("records")


def _bound_registry(target: str, rows: list[dict[str, object]], decision: datetime | None) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    bound: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    duplicate_source_ids = _duplicate_source_ids(rows)
    for row in rows:
        if str(row.get("instrument_id") or "").strip() != target:
            continue
        source_id = _text(row.get("source_id"))
        if source_id in duplicate_source_ids:
            rejected.append({"reason_code": "duplicate_registry_source_id", "source_id": source_id})
            continue
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


def _duplicate_source_ids(rows: Iterable[Mapping[str, object]]) -> set[str]:
    source_counts: dict[str, int] = {}
    for row in rows:
        source_id = _text(row.get("source_id"))
        if source_id:
            source_counts[source_id] = source_counts.get(source_id, 0) + 1
    return {source_id for source_id, count in source_counts.items() if count > 1}


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
        if not _report_family_matches_registry(row, registered):
            rejected.append({"reason_code": "candidate_document_family_mismatch", "source_id": source_id})
            continue
        report_kind = _text(row.get("document_kind"))
        registry_kind = _text(registered.get("document_kind"))
        if not report_kind or not registry_kind or report_kind != registry_kind:
            rejected.append({"reason_code": "candidate_document_kind_mismatch", "source_id": source_id})
            continue
        report_authority = _text(row.get("source_authority"))
        registry_authority = _text(registered.get("authority")) or _text(registered.get("source_authority"))
        if not report_authority or not registry_authority or report_authority != registry_authority:
            rejected.append({"reason_code": "candidate_source_authority_mismatch", "source_id": source_id})
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
        review_event, review_reason = _selected_review_event(row, row_checksum, decision)
        if review_event is None:
            rejected.append({"reason_code": review_reason or "report_evidence_not_eligible", "source_id": source_id})
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
            candidate, reason = _make_candidate(target, field, value_text, source_id, registered, page, item.get("confidence"), decision, review_event=review_event)
            if candidate is None:
                rejected.append({"field_name": field, "reason_code": reason, "source_id": source_id})
            else:
                result.append(candidate)
    return result, rejected


def _selected_review_event(row: Mapping[str, object], checksum: str, decision: datetime | None) -> tuple[dict[str, object] | None, str | None]:
    fingerprint = _text(row.get("stored_extraction_sha256")) or _text(row.get("extraction_sha256"))
    history = _review_history_rows(row)
    if history is None:
        return None, "report_review_history_malformed"
    matching: list[tuple[int, dict[str, object], datetime]] = []
    current_status = _text(row.get("verification_status"))
    current_evidence_eligible = _stored_true(row.get("evidence_eligible"))
    if history:
        validated_history: list[tuple[dict[str, object], datetime]] = []
        previous_at: datetime | None = None
        for item in history:
            event_decision = item.get("decision")
            event_reviewer = item.get("reviewer")
            event_fingerprint = item.get("extraction_sha256")
            event_reviewed_at = item.get("reviewed_at")
            event_note = item.get("note")
            if (
                not isinstance(event_decision, str)
                or event_decision not in {"verified", "rejected"}
                or not isinstance(event_reviewer, str)
                or not event_reviewer.strip()
                or "note" not in item
                or not isinstance(event_note, str)
                or not isinstance(event_fingerprint, str)
                or not _is_sha256_fingerprint(event_fingerprint)
                or not isinstance(event_reviewed_at, str)
                or not event_reviewed_at
            ):
                return None, "report_review_history_malformed"
            try:
                reviewed_at = _parse_timestamp(event_reviewed_at)
            except (TypeError, ValueError):
                return None, "report_review_history_malformed"
            if previous_at is not None and reviewed_at < previous_at:
                return None, "report_review_history_malformed"
            previous_at = reviewed_at
            validated_history.append((item, reviewed_at))
        latest, latest_at = validated_history[-1]
        current_decision = latest["decision"]
        top_level_fingerprint = _text(row.get("extraction_sha256"))
        if top_level_fingerprint and fingerprint and top_level_fingerprint != fingerprint:
            return None, "report_review_state_inconsistent"
        if (
            current_status != current_decision
            or type(row.get("evidence_eligible")).__name__ not in {"bool", "bool_"}
            or current_evidence_eligible != (current_decision == "verified")
            or not fingerprint
            or latest["extraction_sha256"] != fingerprint
            or not isinstance(row.get("verified_by"), str)
            or row.get("verified_by") != latest["reviewer"]
            or not isinstance(row.get("verified_at"), str)
            or not _review_timestamp_matches(row.get("verified_at"), latest_at)
            or not isinstance(row.get("review_note"), str)
            or row.get("review_note") != latest["note"]
        ):
            return None, "report_review_state_inconsistent"
    for index, item in enumerate(history):
        event_fingerprint = _text(item.get("extraction_sha256"))
        if not fingerprint or event_fingerprint != fingerprint:
            continue
        try:
            reviewed_at = _parse_timestamp(str(item.get("reviewed_at")))
        except (TypeError, ValueError):
            continue
        if decision is not None and reviewed_at > decision:
            continue
        matching.append((index, item, reviewed_at))
    if matching:
        _, selected, selected_at = max(matching, key=lambda item: (item[2], item[0]))
        decision_value = _text(selected.get("decision"))
        if decision_value != "verified":
            return None, "report_review_rejected_at_decision_time"
        identity_payload = {
            "source_id": _text(row.get("source_id")) or "unavailable",
            "extraction_sha256": fingerprint,
            "reviewed_at": _text(selected.get("reviewed_at")) or "unavailable",
            "reviewer": _text(selected.get("reviewer")) or "unavailable",
            "decision": decision_value,
        }
        identity_payload["event_id"] = hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return identity_payload, None
    return None, "report_review_not_verified_at_decision_time" if decision is not None else "report_evidence_not_eligible"


def _review_history_rows(row: Mapping[str, object]) -> list[dict[str, object]] | None:
    if "review_history" not in row:
        return None
    value = row.get("review_history")
    if isinstance(value, (str, bytes, bytearray)):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        return None
    return [dict(item) for item in value]


def _review_timestamp_matches(value: object, expected: datetime) -> bool:
    try:
        return _parse_timestamp(str(value)) == expected
    except (TypeError, ValueError):
        return False


def _supplemental_candidates(value: object, registry: list[dict[str, object]], target: str, decision: datetime | None, *, default_document_type: str | None = None) -> tuple[list[StructureCandidate], list[dict[str, object]]]:
    result: list[StructureCandidate] = []
    rejected: list[dict[str, object]] = []
    registry_by_id = {str(row["source_id"]): row for row in registry}
    for row in _rows(value):
        field = _canonical_field(row.get("field_name", row.get("field")))
        if field not in STRUCTURAL_FIELDS:
            continue
        # Holdings keep their internal fundhold identity for cache lineage,
        # while document_source_id binds structural claims to the registry.
        source_id = _text(row.get("document_source_id")) or _text(row.get("registered_source_id")) or _text(row.get("source_id"))
        registered = registry_by_id.get(source_id or "")
        document_type = _text(row.get("document_type")) or default_document_type
        page = _page(row.get("page", row.get("source_page", row.get("document_page"))))
        value_text = _text(row.get("value"))
        row_checksum = _text(row.get("checksum")) or _text(row.get("sha256")) or _text(row.get("document_checksum"))
        row_date = _date_text(row.get("document_date")) or _date_text(row.get("as_of"))
        row_known_at = _date_time_text(row.get("known_at")) or _date_time_text(row.get("document_known_at"))
        status = (_text(row.get("status")) or _text(row.get("coverage_status")) or _text(row.get("document_status")) or "extracted").casefold()
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
        elif status not in _USABLE_STATUSES:
            reason = "candidate_unusable"
        if reason:
            rejected.append({"field_name": field, "reason_code": reason, "source_id": source_id or "unavailable"})
            continue
        confidence = row.get("structural_confidence") if "structural_confidence" in row else row.get("confidence")
        candidate, candidate_reason = _make_candidate(target, field, value_text, source_id, registered, page, confidence, decision, status=status)
        if candidate is None:
            rejected.append({"field_name": field, "reason_code": candidate_reason, "source_id": source_id})
        else:
            result.append(candidate)
    return result, rejected


def _make_candidate(target: str, field: str, value: str, source_id: str, registered: Mapping[str, object], page: int | None, confidence: object, decision: datetime | None, *, status: str = "extracted", review_event: Mapping[str, object] | None = None) -> tuple[StructureCandidate | None, str]:
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
    return StructureCandidate(target, field, value, source_id, _text(registered.get("document_type")) or _text(registered.get("document_kind")) or "unknown", document_date, page, confidence_value, known_at, checksum, status, dict(review_event) if review_event else None), ""


def _latest_sources(registry: list[dict[str, object]], candidates: Iterable[StructureCandidate] = ()) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    candidate_source_ids = {item.source_id for item in candidates}
    for row in registry:
        family = _family(str(row.get("document_kind") or row.get("document_type") or ""))
        if family not in DOCUMENT_FAMILIES:
            continue
        if str(row.get("coverage_status") or "available") not in _USABLE_STATUSES:
            continue
        if candidate_source_ids and str(row.get("source_id")) not in candidate_source_ids:
            continue
        kind = _text(row.get("document_kind")) or _text(row.get("document_type")) or ""
        normalised_kind = kind.casefold().replace("-", "_")
        selection_key = normalised_kind if family == "prospectus" and normalised_kind in _REPORT_KINDS else family
        grouped.setdefault((family, selection_key), []).append(row)
    for (family, _selection_key), rows in grouped.items():
        latest = max(rows, key=lambda row: (_date_text(row.get("document_date")) or "", _date_time_text(row.get("known_at")) or "", str(row.get("source_id"))))
        result.setdefault(family, set()).add(str(latest["source_id"]))
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
    synthetic = _positive_disclosure(f"{replication} {derivatives}", ("synthetic", "swap", "derivative"))
    if fields.get("replication_method", {}).get("status") in {"unknown", "conflict", "unusable"}:
        flags.append("replication_structure_unknown_or_conflicted")
    if synthetic:
        if fields.get("counterparties", {}).get("status") != "resolved":
            flags.append("synthetic_counterparty_evidence_missing_or_conflicted")
        if fields.get("collateral_terms", {}).get("status") != "resolved":
            flags.append("synthetic_collateral_evidence_missing_or_conflicted")
    lending_enabled = _positive_disclosure(lending, ("allow", "enabled", "up to", "may lend", "lending"), negative_terms=("no lending", "no securities lending", "not permitted", "prohibited", "not allowed"))
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
    synthetic_or_derivatives = _positive_disclosure(f"{replication} {derivatives}", ("synthetic", "swap", "derivative"))
    lending_enabled = _positive_disclosure(lending, ("allow", "enabled", "up to", "may lend", "lending"), negative_terms=("no lending", "no securities lending", "not permitted", "prohibited", "not allowed"))
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


def _positive_disclosure(value: str, positive_terms: Iterable[str], *, negative_terms: Iterable[str] = ("no derivative", "no swaps", "not synthetic", "not used", "none used", "none", "not permitted", "prohibited", "not allowed")) -> bool:
    text = " ".join(str(value or "").casefold().replace("-", " ").split())
    if any(term in text for term in negative_terms):
        return False
    return any(term in text for term in positive_terms)


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
        "review_event": dict(candidate.review_event) if candidate is not None and status == "resolved" and candidate.review_event else None,
        "candidates": [_candidate_payload(item) for item in items],
        "execution_allowed": False,
    }


def _candidate_payload(item: StructureCandidate) -> dict[str, object]:
    return {"value": item.value, "source_id": item.source_id, "document_type": item.document_type, "document_date": item.document_date, "page": item.page, "confidence": item.confidence, "known_at": item.known_at, "checksum": item.checksum, "review_event": dict(item.review_event) if item.review_event else None}


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


def _report_numeric_inputs(
    report_records: object,
    registry: list[dict[str, object]],
    target: str,
    decision: datetime | None,
    selected_sources: Mapping[str, set[str]],
) -> tuple[dict[str, NumericEvidence], list[NumericEvidence]]:
    """Build typed stress inputs only from reviewed, selected report evidence."""

    registry_by_id = {str(row.get("source_id")): row for row in registry}
    selected = {
        source_id
        for family in ("prospectus", "annual_report", "half_year_report")
        for source_id in selected_sources.get(family, set())
    }
    by_source: dict[str, dict[str, list[NumericEvidence]]] = {}
    source_row_counts: dict[str, int] = {}
    for row in _rows(report_records):
        source_id = _text(row.get("source_id"))
        registered = registry_by_id.get(source_id or "")
        if source_id not in selected or registered is None or _text(row.get("instrument_id")) != target:
            continue
        checksum = _text(registered.get("checksum")) or _text(registered.get("sha256"))
        document_date = _date_text(registered.get("document_date"))
        known_at = _date_time_text(registered.get("known_at")) or _date_time_text(registered.get("ingested_at"))
        if not checksum or not document_date or not known_at or not _report_identity_matches(
            row,
            row_checksum=checksum,
            row_date=document_date,
            row_known_at=known_at,
            registered=registered,
        ):
            continue
        review_event, _ = _selected_review_event(row, checksum, decision)
        if review_event is None:
            continue
        source_row_counts[source_id] = source_row_counts.get(source_id, 0) + 1
        source_fields = by_source.setdefault(source_id, {field: [] for field in _NUMERIC_UNITS})
        for item in _json_rows(row.get("field_evidence")):
            field = _canonical_field(item.get("field_name"))
            unit = _text(item.get("unit"))
            if field not in _NUMERIC_UNITS or unit != _NUMERIC_UNITS[field]:
                continue
            status = str(item.get("status") or "unknown").casefold()
            page = _page(item.get("source_page")) or _first_page(item.get("candidate_pages"))
            candidate = NumericEvidence(
                item.get("value"),
                unit,
                source_id=source_id,
                document_date=document_date,
                page=page,
                confidence=item.get("confidence"),
                known_at=known_at,
                checksum=checksum,
                instrument_id=target,
                field_name=field,
                status=status,
            )
            if status in _USABLE_STATUSES and candidate.normalized_value is not None:
                source_fields[field].append(candidate)

    complete: list[tuple[tuple[str, str, str], dict[str, NumericEvidence]]] = []
    for source_id, fields in by_source.items():
        if source_row_counts.get(source_id) != 1 or any(not values for values in fields.values()):
            continue
        chosen: dict[str, NumericEvidence] = {}
        for field, values in fields.items():
            distinct = {(item.normalized_value, item.unit) for item in values}
            if len(distinct) != 1:
                break
            chosen[field] = max(values, key=lambda item: (item.document_date, item.known_at, item.source_id, item.page or 0))
        else:
            registered = registry_by_id[source_id]
            ordering = (
                _date_text(registered.get("document_date")),
                _date_time_text(registered.get("known_at")) or _date_time_text(registered.get("ingested_at")),
                source_id,
            )
            complete.append((ordering, chosen))
    if not complete:
        return {}, []
    chosen = max(complete, key=lambda item: item[0])[1]
    return chosen, list(chosen.values())


def _decimal_input(
    value: object,
    *,
    allowed_units: set[str],
    field_name: str,
    bounds: tuple[Decimal, Decimal] | None = None,
    registry: object = None,
    report_records: object = None,
    candidates: object = None,
    decision: datetime | None = None,
    instrument_id: str = "",
) -> Decimal | None:
    if not isinstance(value, NumericEvidence):
        return None
    raw, unit = value.value, value.unit
    if value.field_name != field_name or unit not in allowed_units or isinstance(raw, bool):
        return None
    if str(value.status).casefold() not in _USABLE_STATUSES:
        return None
    if not _numeric_provenance_is_bound(
        value,
        registry,
        report_records,
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
    report_records: object,
    decision: datetime | None,
    instrument_id: str,
    field_name: str,
    normalized_value: Decimal | None,
    unit: str,
) -> bool:
    try:
        validated_report_rows = _validated_report_rows(report_records)
    except ValueError:
        return False
    source_id = _text(value.source_id)
    checksum = _text(value.checksum)
    document_date = _date_text(value.document_date)
    known_at = _date_time_text(value.known_at)
    page = _page(value.page)
    confidence = _confidence_value(value.confidence)
    if not source_id or not checksum or not document_date or not known_at or page is None or confidence is None:
        return False
    if not instrument_id or _text(value.instrument_id) != instrument_id:
        return False
    if value.field_name != field_name or value.unit != unit or normalized_value is None or str(value.status).casefold() not in _USABLE_STATUSES:
        return False
    registry_rows = _rows(registry)
    matches = [row for row in registry_rows if _text(row.get("source_id")) == source_id]
    if len(matches) != 1:
        return False
    registered = matches[0]
    registered_checksum = _text(registered.get("sha256")) or _text(registered.get("checksum"))
    registered_date = _date_text(registered.get("document_date"))
    registered_known_at = _date_time_text(registered.get("known_at")) or _date_time_text(registered.get("ingested_at"))
    if checksum != registered_checksum or document_date != registered_date or known_at != registered_known_at:
        return False
    if instrument_id and _text(registered.get("instrument_id")) != instrument_id:
        return False
    if decision is not None and _parse_timestamp(known_at) > decision:
        return False
    for report_row in validated_report_rows:
        if str(report_row.get("instrument_id") or "").strip() != instrument_id or _text(report_row.get("source_id")) != source_id:
            continue
        if not _report_identity_matches(report_row, row_checksum=checksum, row_date=document_date, row_known_at=known_at, registered=registered):
            continue
        review_event, _ = _selected_review_event(report_row, checksum, decision)
        if review_event is None:
            continue
        for item in _json_rows(report_row.get("field_evidence")):
            if _canonical_field(item.get("field_name")) != field_name:
                continue
            item_value = _normalise_decimal(item.get("value"))
            item_unit = _text(item.get("unit"))
            item_page = _page(item.get("source_page")) or _first_page(item.get("candidate_pages"))
            item_confidence = _confidence_value(item.get("confidence"))
            item_status = str(item.get("status") or "unknown").casefold()
            if (
                item_status in _USABLE_STATUSES
                and item_unit == unit
                and item_value == normalized_value
                and item_page == page
                and item_confidence == confidence
            ):
                return True
    return False


def _report_identity_matches(
    row: Mapping[str, object],
    *,
    row_checksum: str,
    row_date: str,
    row_known_at: str,
    registered: Mapping[str, object],
) -> bool:
    return (
        (_text(row.get("source_sha256")) or _text(row.get("sha256")) or _text(row.get("checksum"))) == row_checksum
        and _date_text(row.get("document_date")) == row_date
        and _date_time_text(row.get("known_at")) == row_known_at
        and row_checksum == (_text(registered.get("checksum")) or _text(registered.get("sha256")))
        and row_date == _date_text(registered.get("document_date"))
        and row_known_at == (_date_time_text(registered.get("known_at")) or _date_time_text(registered.get("ingested_at")))
        and _report_family_matches_registry(row, registered)
        and _text(row.get("document_kind")) == _text(registered.get("document_kind"))
        and _text(row.get("source_authority")) == (_text(registered.get("authority")) or _text(registered.get("source_authority")))
    )


def _report_family_matches_registry(row: Mapping[str, object], registered: Mapping[str, object]) -> bool:
    registry_family = _family(str(registered.get("document_kind") or registered.get("document_type") or ""))
    report_types = [_text(row.get("document_type")), _text(row.get("document_kind"))]
    report_families = {_family(item) for item in report_types if item}
    return bool(registry_family and report_families and report_families.issubset({registry_family}))


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


def _numeric_provenance_payload(value: object) -> dict[str, object]:
    if not isinstance(value, NumericEvidence):
        return {"status": "unavailable"}
    return {
        "source_id": value.source_id,
        "document_date": value.document_date,
        "page": value.page,
        "confidence": _confidence_value(value.confidence),
        "known_at": value.known_at,
        "checksum": value.checksum,
        "instrument_id": value.instrument_id,
        "field_name": value.field_name,
        "unit": value.unit,
        "value": str(value.value),
    }


def _json_rows(value: object) -> list[dict[str, object]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return _rows(value)


def _normalise_decimal(value: object) -> Decimal | None:
    from etf_cockpit.parsers.etf_report import normalise_bare_decimal_fraction

    return normalise_bare_decimal_fraction(value)


def _stored_true(value: object) -> bool:
    return type(value).__name__ in {"bool", "bool_"} and bool(value)


def _is_sha256_fingerprint(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value)


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
    source_vintage: object,
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
        "source_vintage": _stable_value(source_vintage),
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
    "LocalStructuralEvidence", "STRUCTURE_CONFIDENCE_VERSION", "STRUCTURE_SCHEMA_VERSION", "build_etf_structure_analysis", "build_etf_structure_projection",
    "STRUCTURE_PROJECTION_VERSION", "calculate_counterparty_collateral_stress", "calculate_structural_stress", "load_local_structural_evidence", "project_etf_structure", "structure_confidence_caps", "structure_input_checksum",
]


NumericCandidate = NumericEvidence
