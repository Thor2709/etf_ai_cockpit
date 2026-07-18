"""Strict, non-executable fundamental evidence contracts and local stores.

Fundamentals are useful context, but they are not an action authority.  This
module deliberately distinguishes a missing metric from a measured negative
metric and preserves vendor limitations in the clean evidence row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR
from etf_cockpit.data.provenance import sha256_dataframe


FUNDAMENTAL_SCHEMA_VERSION = "fundamental_evidence.v4"
FUNDAMENTAL_CLEAN_PATH = CLEAN_DIR / "fundamentals.parquet"
FUNDAMENTAL_RAW_DIR = RAW_DIR / "fundamentals"
_FIELDS = ("valuation", "profitability", "leverage", "growth", "shareholder_return")
_FIELD_LABELS = {
    "valuation": "valuation",
    "profitability": "profitability",
    "leverage": "leverage",
    "growth": "growth",
    "shareholder_return": "shareholder_return",
}


@dataclass(frozen=True)
class FundamentalEvidence:
    instrument_id: str
    as_of: str
    values: Mapping[str, float]
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    eligibility: str
    source_authority: str
    source_id: str = "vendor_unofficial"
    manual_review: bool = False
    merge_status: str = "single_source"
    rejected_source_count: int = 0
    sections: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    sector_relative_status: str = "unavailable"
    sector_relative_value: float | None = None
    sector_relative_peer: str = ""
    sector_relative_benchmark: str = ""
    sector_relative_delta: float | None = None
    sector_relative_limitation: str = "No sector-relative comparison evidence supplied."
    source: str = "vendor"
    limitations: tuple[str, ...] = ()
    stale_fields: tuple[str, ...] = ()
    executable_authority: bool = False
    schema_version: str = FUNDAMENTAL_SCHEMA_VERSION

    @property
    def score_eligible(self) -> bool:
        return self.eligibility in {"eligible", "eligible_negative_evidence"}

    @property
    def source_limitations(self) -> tuple[str, ...]:
        return self.limitations


@dataclass(frozen=True)
class FundamentalPersistenceResult:
    raw_path: Path
    clean_path: Path
    audit_path: Path
    rows: int
    checksum: str
    idempotent: bool = False


@dataclass(frozen=True)
class FundamentalRowAssessment:
    score_eligible: bool
    freshness_status: str
    freshness_days: int | None
    values: Mapping[str, float | None]
    sections: Mapping[str, Mapping[str, Any]]
    reasons: tuple[str, ...]


def build_fundamental_evidence(
    claims: Mapping[str, object],
    instrument_id: str | Mapping[str, object],
    as_of: str,
    *,
    source_authority: str | None = None,
    source: str | None = None,
    source_id: str | None = None,
    sector_relative: Mapping[str, object] | None = None,
    stale_after_days: int = 120,
    today: date | None = None,
) -> FundamentalEvidence:
    """Build a typed evidence row without inventing absent fields.

    The positional signature remains compatible with the first implementation.
    Values may be supplied directly under one of the five section names or as
    ``sections`` mappings containing a ``value`` key.
    """

    canonical_instrument_id = _instrument_id_from_identity(instrument_id)
    claimed_authority = _first_claim_text(claims, ("source_authority", "source"))
    authority = str(source_authority or claimed_authority or source or "vendor_unofficial").strip().lower() or "vendor_unofficial"
    source_name = str(source or claimed_authority or authority).strip().lower() or "vendor"
    resolved_source_id = _first_claim_text(claims, ("source_id",)) or str(source_id or source_name).strip() or "unavailable"
    values: dict[str, float] = {}
    missing: list[str] = []
    sections: dict[str, Mapping[str, Any]] = {}
    raw_sections = claims.get("sections") if isinstance(claims, Mapping) else None
    for field_name in _FIELDS:
        raw_value: object = claims.get(field_name)
        metadata: Mapping[str, Any] = {}
        if isinstance(raw_sections, Mapping) and field_name in raw_sections:
            section_value = raw_sections[field_name]
            if isinstance(section_value, Mapping):
                metadata = dict(section_value)
                raw_value = metadata.get("value", metadata.get("score", raw_value))
            elif raw_value is None:
                raw_value = section_value
        try:
            if pd.api.types.is_bool(raw_value) or raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                raise ValueError
            value = float(raw_value)
            if pd.isna(value) or not math.isfinite(value):
                raise ValueError
            values[field_name] = value
            sections[field_name] = {
                **metadata,
                "value": value,
                "period_end": str(metadata.get("period_end") or as_of),
                "source_id": str(metadata.get("source_id") or resolved_source_id),
            }
        except (TypeError, ValueError):
            missing.append(field_name)
            sections[field_name] = {
                **metadata,
                "value": None,
                "period_end": str(metadata.get("period_end") or as_of),
                "source_id": str(metadata.get("source_id") or resolved_source_id),
                "status": "missing",
            }

    parsed_as_of = _parse_date(as_of)
    reference_date = today or date.today()
    stale_fields: list[str] = []
    warnings: list[str] = []
    temporal_valid = True
    if parsed_as_of is None:
        warnings.append("ambiguous_as_of")
        temporal_valid = False
    elif parsed_as_of > reference_date:
        warnings.append("future_as_of")
        temporal_valid = False
    elif (reference_date - parsed_as_of).days > max(0, stale_after_days):
        stale_fields.extend(values.keys())
        warnings.append("stale_fundamentals")
        temporal_valid = False
    if missing:
        warnings.append("missing_fundamental_fields")
    sector_data = _normalise_sector_relative(sector_relative)
    sector_status = "available" if sector_data["status"] == "available" else "unavailable"
    if sector_status == "unavailable":
        warnings.append("sector_relative_unavailable")

    limitations = _limitations_for_source(authority)
    raw_manual_review = claims.get("manual_review", False)
    manual_review = bool(raw_manual_review) if pd.api.types.is_bool(raw_manual_review) else "manual_review" in claims
    try:
        rejected_source_count = max(0, int(claims.get("rejected_source_count", 0)))
    except (TypeError, ValueError):
        rejected_source_count = 1
        manual_review = True
    merge_status = _scalar_text(claims.get("merge_status")) or "single_source"
    if rejected_source_count or merge_status in {"manual_review", "conflict", "unavailable"}:
        manual_review = True

    # Strict records need all five sections.  Missing sections are unavailable,
    # not negative evidence; only a complete five-section row may be eligible.
    if not missing and temporal_valid and not manual_review:
        eligibility = "eligible_negative_evidence" if any(value < 0 for value in values.values()) else "eligible"
    else:
        eligibility = "not_score_eligible"
    return FundamentalEvidence(
        instrument_id=canonical_instrument_id,
        as_of=str(as_of),
        values=values,
        missing_fields=tuple(missing),
        warnings=tuple(dict.fromkeys(warnings)),
        eligibility=eligibility,
        source_authority=authority,
        source_id=resolved_source_id,
        manual_review=manual_review,
        merge_status=merge_status,
        rejected_source_count=rejected_source_count,
        sections=sections,
        sector_relative_status=sector_status,
        sector_relative_value=sector_data["value"],
        sector_relative_peer=sector_data["peer"],
        sector_relative_benchmark=sector_data["benchmark"],
        sector_relative_delta=sector_data["delta"],
        sector_relative_limitation=sector_data["limitation"],
        source=source_name,
        limitations=limitations,
        stale_fields=tuple(stale_fields),
        executable_authority=False,
    )


def persist_fundamental_evidence(
    evidence: FundamentalEvidence,
    *,
    raw_dir: Path = FUNDAMENTAL_RAW_DIR,
    clean_path: Path = FUNDAMENTAL_CLEAN_PATH,
    audit_path: Path | None = None,
) -> FundamentalPersistenceResult:
    """Persist an immutable raw generation and idempotent clean/audit rows."""

    raw_dir = Path(raw_dir)
    clean_path = Path(clean_path)
    audit_path = Path(audit_path or clean_path.with_name(clean_path.stem + "_audit.json"))
    payload = _evidence_payload(evidence)
    checksum = _payload_checksum(payload)
    raw_path = raw_dir / f"{_safe_id(evidence.instrument_id)}-{checksum}.json"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_payload = (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")

    existing = _read_clean(clean_path)
    row = _clean_row(evidence, checksum)
    combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["instrument_id", "evidence_checksum"], keep="last")
        combined = sort_fundamental_evidence(combined)
    audit_payload = {
        "schema_version": FUNDAMENTAL_SCHEMA_VERSION,
        "dataset_type": "fundamentals",
        "raw_path": str(raw_path),
        "clean_path": str(clean_path),
        "checksum": sha256_dataframe(combined),
        "rows": len(combined),
        "source_authority": evidence.source_authority,
        "source_id": evidence.source_id,
        "manual_review": evidence.manual_review,
        "merge_status": evidence.merge_status,
        "rejected_source_count": evidence.rejected_source_count,
        "executable_authority": False,
        "limitations": list(evidence.limitations),
        "sector_relative": {
            "status": evidence.sector_relative_status,
            "value": evidence.sector_relative_value,
            "peer": evidence.sector_relative_peer or "unavailable",
            "benchmark": evidence.sector_relative_benchmark or "unavailable",
            "delta": evidence.sector_relative_delta,
            "limitation": evidence.sector_relative_limitation,
        },
    }
    csv_path = clean_path.with_suffix(".csv")
    requests = [
        AtomicWriteRequest(clean_path, parquet_payload(combined), validate_parquet_file),
        AtomicWriteRequest(csv_path, combined.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
        AtomicWriteRequest(audit_path, (json.dumps(audit_payload, indent=2, sort_keys=True) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))),
    ]
    # A raw generation is immutable.  New raw bytes must be published in the
    # same transaction as the clean and audit mirrors so a failed generation
    # cannot leave an orphan raw file behind.
    if not raw_path.exists():
        requests.append(
            AtomicWriteRequest(
                raw_path,
                raw_payload,
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            )
        )
    atomic_write_group(tuple(requests))
    return FundamentalPersistenceResult(raw_path, clean_path, audit_path, len(combined), checksum, len(existing) == len(combined))


def merge_fundamental_sources(*sources: Mapping[str, object]) -> dict[str, object]:
    """Merge claims with deterministic authority precedence.

    Official SEC facts outrank vendor values when both provide a metric.  The
    function keeps source/limitation metadata visible rather than silently
    coercing a conflict into a score.
    """

    ranked = {"official": 100, "sec": 100, "sec_edgar": 100, "issuer": 85, "vendor": 55, "vendor_unofficial": 55, "community": 25, "manual": 20}
    if not sources:
        return {
            "source_authority": "unavailable",
            "source": "unavailable",
            "limitations": "No fundamental sources supplied.",
            "rejected_source_count": 0,
            "merge_status": "unavailable",
            "manual_review": True,
            "executable_authority": False,
        }

    anchor = sources[0]
    anchor_instrument = _first_claim_text(anchor, ("instrument_id", "id", "ticker", "symbol"))
    anchor_as_of = _first_claim_text(anchor, ("as_of_date", "as_of"))
    if not anchor_instrument or not anchor_as_of:
        return {
            "source_authority": "unavailable",
            "source": "unavailable",
            "limitations": "The anchor source requires a canonical instrument and reporting period.",
            "rejected_source_count": len(sources),
            "merge_status": "unavailable",
            "manual_review": True,
            "executable_authority": False,
            "execution_allowed": False,
        }
    selected: dict[str, object] = {}
    selected_owner: dict[str, tuple[int, str, str]] = {}
    selected_sections: dict[str, dict[str, object]] = {}
    rejected = 0
    for source in sources:
        source_instrument = _first_claim_text(source, ("instrument_id", "id", "ticker", "symbol"))
        source_as_of = _first_claim_text(source, ("as_of_date", "as_of"))
        identity_matches = source_instrument == anchor_instrument
        period_matches = source_as_of == anchor_as_of
        if not identity_matches or not period_matches:
            rejected += 1
            continue
        authority = str(source.get("source_authority") or source.get("source") or "vendor").strip().lower()
        rank = ranked.get(authority, 0)
        source_id = _first_claim_text(source, ("source_id",)) or authority
        raw_sections = source.get("sections")
        for key in _FIELDS:
            value = source.get(key)
            section: Mapping[str, object] = {}
            if isinstance(raw_sections, Mapping) and isinstance(raw_sections.get(key), Mapping):
                section = raw_sections[key]  # type: ignore[assignment]
                value = section.get("value", section.get("score", value))
            if value is None:
                continue
            owner = (rank, source_id, authority)
            if key not in selected or owner > selected_owner[key]:
                selected[key] = value
                selected_owner[key] = owner
                selected_sections[key] = {
                    **dict(section),
                    "value": value,
                    "period_end": str(section.get("period_end") or source_as_of),
                    "source_id": str(section.get("source_id") or source_id),
                    "source_authority": authority,
                }
    if anchor_instrument:
        selected["instrument_id"] = anchor_instrument
    if anchor_as_of:
        selected["as_of_date"] = anchor_as_of
    contributing_authorities = sorted({owner[2] for owner in selected_owner.values()})
    contributing_source_ids = sorted({owner[1] for owner in selected_owner.values()})
    selected["source_authority"] = contributing_authorities[0] if len(contributing_authorities) == 1 else ("mixed" if contributing_authorities else "unavailable")
    selected["source_id"] = contributing_source_ids[0] if len(contributing_source_ids) == 1 else ("|".join(contributing_source_ids) if contributing_source_ids else "unavailable")
    selected["source"] = selected["source_authority"]
    selected["sections"] = selected_sections
    base_limitation = "Official SEC facts outrank vendor fundamentals where identity and period match." if selected["source_authority"] in {"official", "sec", "sec_edgar"} else "Metric-level provenance is retained; mixed or vendor fundamentals may be partial or revised."
    selected["limitations"] = base_limitation + (f" {rejected} mismatched source record(s) were excluded." if rejected else "")
    selected["rejected_source_count"] = rejected
    selected["merge_status"] = "manual_review" if rejected or not selected_owner else "merged"
    selected["manual_review"] = bool(rejected or not selected_owner)
    selected["executable_authority"] = False
    selected["execution_allowed"] = False
    return selected


def load_fundamental_evidence(path: Path = FUNDAMENTAL_CLEAN_PATH) -> pd.DataFrame:
    return sort_fundamental_evidence(_read_clean(Path(path)))


def assess_fundamental_row(
    row: Mapping[str, object],
    *,
    today: date | None = None,
    stale_after_days: int = 120,
) -> FundamentalRowAssessment:
    """Validate one persisted/UI row against the shared fail-closed contract."""

    reasons: list[str] = []
    values: dict[str, float | None] = {}
    for field_name in _FIELDS:
        raw_value = row.get(field_name)
        if pd.api.types.is_bool(raw_value):
            values[field_name] = None
            reasons.append(f"invalid_{field_name}")
            continue
        try:
            number = float(raw_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number = math.nan
        if not math.isfinite(number):
            values[field_name] = None
            reasons.append(f"invalid_{field_name}")
        else:
            values[field_name] = number

    eligibility = _scalar_text(row.get("eligibility")).casefold()
    if eligibility not in {"eligible", "eligible_negative_evidence"}:
        reasons.append("ineligible_status")
    score_flag = row.get("score_eligible")
    if not pd.api.types.is_bool(score_flag) or not bool(score_flag):
        reasons.append("score_flag_false_or_invalid")
    manual_review = row.get("manual_review", False)
    if not pd.api.types.is_bool(manual_review) or bool(manual_review):
        reasons.append("manual_review_required")
    rejected_count = row.get("rejected_source_count", 0)
    if pd.api.types.is_bool(rejected_count):
        reasons.append("invalid_rejected_source_count")
    else:
        try:
            if int(rejected_count) != 0:
                reasons.append("rejected_sources_present")
        except (TypeError, ValueError):
            reasons.append("invalid_rejected_source_count")
    merge_status = _scalar_text(row.get("merge_status")) or "single_source"
    if merge_status in {"manual_review", "conflict", "unavailable"}:
        reasons.append("unresolved_merge_status")

    source_id = _scalar_text(row.get("source_id"))
    source_authority = _scalar_text(row.get("source_authority")) or _scalar_text(row.get("source"))
    if source_id.casefold() in {"", "unavailable", "unknown"}:
        reasons.append("source_id_unavailable")
    if source_authority.casefold() in {"", "unavailable", "unknown"}:
        reasons.append("source_authority_unavailable")

    as_of = _parse_date(row.get("as_of_date", row.get("as_of")))
    reference_date = today or date.today()
    freshness_days: int | None = None
    if as_of is None:
        freshness_status = "unavailable"
        reasons.append("ambiguous_as_of")
    elif as_of > reference_date:
        freshness_status = "future"
        freshness_days = (reference_date - as_of).days
        reasons.append("future_as_of")
    else:
        freshness_days = (reference_date - as_of).days
        if freshness_days > max(0, stale_after_days):
            freshness_status = "stale"
            reasons.append("stale_fundamentals")
        else:
            freshness_status = "fresh"

    sections = _row_sections(row.get("sections_json"))
    for field_name in _FIELDS:
        section = sections.get(field_name)
        if not isinstance(section, Mapping):
            reasons.append(f"missing_{field_name}_provenance")
            continue
        section_value = section.get("value")
        if pd.api.types.is_bool(section_value):
            reasons.append(f"invalid_{field_name}_provenance_value")
        else:
            try:
                section_number = float(section_value)  # type: ignore[arg-type]
                if not math.isfinite(section_number):
                    raise ValueError
            except (TypeError, ValueError):
                reasons.append(f"invalid_{field_name}_provenance_value")
            else:
                row_number = values.get(field_name)
                if row_number is None or not math.isclose(section_number, row_number, rel_tol=0.0, abs_tol=1e-12):
                    reasons.append(f"mismatched_{field_name}_provenance_value")
        period_end = _parse_date(section.get("period_end"))
        if period_end is None or (as_of is not None and period_end > as_of):
            reasons.append(f"invalid_{field_name}_period")
        section_source_id = _scalar_text(section.get("source_id"))
        if section_source_id.casefold() in {"", "unavailable", "unknown"}:
            reasons.append(f"invalid_{field_name}_source_id")

    warning_text = _scalar_text(row.get("warnings"))
    warnings = {item for item in warning_text.split("|") if item}
    for warning in sorted(warnings & {"ambiguous_as_of", "future_as_of", "stale_fundamentals"}):
        reasons.append(warning)

    unique_reasons = tuple(dict.fromkeys(reasons))
    return FundamentalRowAssessment(
        score_eligible=not unique_reasons,
        freshness_status=freshness_status,
        freshness_days=freshness_days,
        values=values,
        sections={key: dict(value) for key, value in sections.items() if isinstance(value, Mapping)},
        reasons=unique_reasons,
    )


def sort_fundamental_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    """Return deterministic chronological fundamentals without mutating ``frame``."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    result = frame.copy()
    result["_as_of_sort"] = pd.to_datetime(
        result.get("as_of_date", pd.Series(index=result.index)),
        errors="coerce",
        format="mixed",
    )
    result["_instrument_sort"] = result.get("instrument_id", pd.Series(index=result.index)).astype(str)
    result["_checksum_sort"] = result.get("evidence_checksum", pd.Series(index=result.index)).astype(str)
    result["_row_sort"] = result.apply(_stable_row_digest, axis=1)
    result = result.sort_values(
        ["_as_of_sort", "_instrument_sort", "_checksum_sort", "_row_sort"],
        kind="stable",
        na_position="first",
    )
    return result.drop(columns=["_as_of_sort", "_instrument_sort", "_checksum_sort", "_row_sort"]).reset_index(drop=True)


def latest_fundamental_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Select one latest deterministic evidence row per instrument."""

    ordered = sort_fundamental_evidence(frame)
    if ordered.empty or "instrument_id" not in ordered.columns:
        return ordered
    return ordered.groupby(ordered["instrument_id"].astype(str), sort=True, as_index=False, group_keys=False).tail(1).reset_index(drop=True)


def _normalise_sector_relative(value: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(value, Mapping) or not value:
        return {
            "status": "unavailable",
            "value": None,
            "peer": "unavailable",
            "benchmark": "unavailable",
            "delta": None,
            "limitation": "No sector-relative comparison evidence supplied.",
        }
    def _number(*keys: str) -> float | None:
        for key in keys:
            raw = value.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
        return None
    def _text(*keys: str) -> str:
        for key in keys:
            raw = str(value.get(key) or "").strip()
            if raw:
                return raw
        return "unavailable"
    peer = _text("peer", "peer_group", "peer_set", "peer_label")
    benchmark = _text("benchmark", "benchmark_id", "benchmark_label")
    comparison_value = _number("value", "instrument_value", "comparison_value", "metric_value")
    delta = _number("delta", "relative_delta", "difference", "alpha")
    limitation = _text("limitation", "limitations", "reason")
    meaningful = comparison_value is not None or delta is not None or peer != "unavailable" or benchmark != "unavailable"
    return {
        "status": "available" if meaningful else "unavailable",
        "value": comparison_value,
        "peer": peer,
        "benchmark": benchmark,
        "delta": delta,
        "limitation": limitation if limitation != "unavailable" else "No sector-relative comparison evidence supplied.",
    }


def _evidence_payload(evidence: FundamentalEvidence) -> dict[str, Any]:
    payload = asdict(evidence)
    payload["values"] = dict(evidence.values)
    payload["sections"] = {key: dict(value) for key, value in evidence.sections.items()}
    payload["missing_fields"] = list(evidence.missing_fields)
    payload["warnings"] = list(evidence.warnings)
    payload["limitations"] = list(evidence.limitations)
    payload["stale_fields"] = list(evidence.stale_fields)
    payload["executable_authority"] = False
    return payload


def _clean_row(evidence: FundamentalEvidence, checksum: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": evidence.schema_version,
        "instrument_id": evidence.instrument_id,
        "as_of_date": evidence.as_of,
        "eligibility": evidence.eligibility,
        "score_eligible": evidence.score_eligible,
        "missing_fields": "|".join(evidence.missing_fields),
        "warnings": "|".join(evidence.warnings),
        "stale_fields": "|".join(evidence.stale_fields),
        "sector_relative_status": evidence.sector_relative_status,
        "sector_relative_value": evidence.sector_relative_value,
        "sector_relative_peer": evidence.sector_relative_peer or "unavailable",
        "sector_relative_benchmark": evidence.sector_relative_benchmark or "unavailable",
        "sector_relative_delta": evidence.sector_relative_delta,
        "sector_relative_limitation": evidence.sector_relative_limitation,
        "source": evidence.source,
        "source_authority": evidence.source_authority,
        "source_id": evidence.source_id,
        "manual_review": evidence.manual_review,
        "merge_status": evidence.merge_status,
        "rejected_source_count": evidence.rejected_source_count,
        "limitations": "|".join(evidence.limitations),
        "sections_json": json.dumps(
            {key: dict(value) for key, value in evidence.sections.items()},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ),
        "executable_authority": False,
        "evidence_checksum": checksum,
    }
    row.update(evidence.values)
    return row


def _read_clean(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
        if "executable_authority" in frame.columns:
            frame["executable_authority"] = False
        defaults: dict[str, object] = {
            "sections_json": "{}",
            "manual_review": False,
            "merge_status": "single_source",
            "rejected_source_count": 0,
            "sector_relative_status": "unavailable",
            "sector_relative_value": None,
            "sector_relative_peer": "unavailable",
            "sector_relative_benchmark": "unavailable",
            "sector_relative_delta": None,
            "sector_relative_limitation": "No sector-relative comparison evidence supplied.",
        }
        for column, default in defaults.items():
            if column not in frame.columns:
                frame[column] = default
            elif default is not None:
                frame[column] = frame[column].fillna(default)
        return frame
    except Exception:
        return pd.DataFrame()


def _limitations_for_source(authority: str) -> tuple[str, ...]:
    if authority in {"official", "sec_edgar", "sec"}:
        return ("Official SEC facts outrank vendor fundamentals when identity and period match.",)
    return (
        "Vendor fundamentals may be partial, revised or stale.",
        "Missing metrics remain unavailable and are not treated as negative values.",
        "Fundamentals are context-only and cannot authorise an action.",
    )


def _parse_date(value: object) -> date | None:
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date() if hasattr(parsed, "date") else None
    except Exception:
        return None


def _payload_checksum(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value)) or "unknown"


def _instrument_id_from_identity(identity: str | Mapping[str, object]) -> str:
    if isinstance(identity, Mapping):
        for key in ("instrument_id", "id", "ticker", "symbol"):
            value = str(identity.get(key) or "").strip()
            if value:
                return value
        return "unknown"
    return str(identity).strip()


def _first_claim_text(claims: Mapping[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _scalar_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _row_sections(value: object) -> dict[str, Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items() if isinstance(item, Mapping)}
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    return {str(key): item for key, item in parsed.items() if isinstance(item, Mapping)}


def _stable_row_digest(row: pd.Series) -> str:
    payload = {
        str(key): value
        for key, value in row.to_dict().items()
        if not str(key).startswith("_")
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


persist_fundamentals = persist_fundamental_evidence
write_fundamental_evidence = persist_fundamental_evidence


__all__ = [
    "FUNDAMENTAL_CLEAN_PATH",
    "FUNDAMENTAL_RAW_DIR",
    "FUNDAMENTAL_SCHEMA_VERSION",
    "FundamentalEvidence",
    "FundamentalPersistenceResult",
    "FundamentalRowAssessment",
    "assess_fundamental_row",
    "build_fundamental_evidence",
    "load_fundamental_evidence",
    "latest_fundamental_rows",
    "merge_fundamental_sources",
    "persist_fundamental_evidence",
    "persist_fundamentals",
    "sort_fundamental_evidence",
    "write_fundamental_evidence",
]
