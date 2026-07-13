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


FUNDAMENTAL_SCHEMA_VERSION = "fundamental_evidence.v3"
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


def build_fundamental_evidence(
    claims: Mapping[str, object],
    instrument_id: str | Mapping[str, object],
    as_of: str,
    *,
    source_authority: str = "vendor_unofficial",
    source: str | None = None,
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
            if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                raise ValueError
            value = float(raw_value)
            if pd.isna(value) or not math.isfinite(value):
                raise ValueError
            values[field_name] = value
            sections[field_name] = {**metadata, "value": value}
        except (TypeError, ValueError):
            missing.append(field_name)
            sections[field_name] = {**metadata, "value": None, "status": "missing"}

    parsed_as_of = _parse_date(as_of)
    reference_date = today or date.today()
    stale_fields: list[str] = []
    warnings: list[str] = []
    if parsed_as_of is None:
        warnings.append("ambiguous_as_of")
    elif (reference_date - parsed_as_of).days > max(0, stale_after_days):
        stale_fields.extend(values.keys())
        warnings.append("stale_fundamentals")
    if missing:
        warnings.append("missing_fundamental_fields")
    sector_data = _normalise_sector_relative(sector_relative)
    sector_status = "available" if sector_data["status"] == "available" else "unavailable"
    if sector_status == "unavailable":
        warnings.append("sector_relative_unavailable")

    authority = str(source_authority or source or "vendor_unofficial").strip().lower() or "vendor_unofficial"
    source_name = str(source or authority).strip().lower() or "vendor"
    limitations = _limitations_for_source(authority)

    # Strict records need all five sections.  Missing sections are unavailable,
    # not negative evidence; only a complete five-section row may be eligible.
    if not missing:
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
    selected: dict[str, object] = {}
    selected_rank: dict[str, int] = {}
    for source in sources:
        authority = str(source.get("source_authority") or source.get("source") or "vendor").strip().lower()
        rank = ranked.get(authority, 0)
        for key, value in source.items():
            if key in {"source", "source_authority", "limitations", "as_of", "as_of_date"} or value is None:
                continue
            if key not in selected or rank > selected_rank.get(key, -1):
                selected[key] = value
                selected_rank[key] = rank
    authorities = [str(item.get("source_authority") or item.get("source") or "vendor").strip().lower() for item in sources]
    selected["source_authority"] = max(authorities, key=lambda value: ranked.get(value, 0), default="vendor")
    selected["source"] = selected["source_authority"]
    selected["limitations"] = "Official SEC facts outrank vendor fundamentals where identity and period match." if selected["source_authority"] in {"official", "sec", "sec_edgar"} else "Vendor fundamentals may be partial or revised; missing values remain unavailable."
    return selected


def load_fundamental_evidence(path: Path = FUNDAMENTAL_CLEAN_PATH) -> pd.DataFrame:
    return sort_fundamental_evidence(_read_clean(Path(path)))


def sort_fundamental_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    """Return deterministic chronological fundamentals without mutating ``frame``."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    result = frame.copy()
    result["_as_of_sort"] = pd.to_datetime(result.get("as_of_date", pd.Series(index=result.index)), errors="coerce")
    result["_instrument_sort"] = result.get("instrument_id", pd.Series(index=result.index)).astype(str)
    result["_checksum_sort"] = result.get("evidence_checksum", pd.Series(index=result.index)).astype(str)
    result = result.sort_values(
        ["_as_of_sort", "_instrument_sort", "_checksum_sort"],
        kind="stable",
        na_position="first",
    )
    return result.drop(columns=["_as_of_sort", "_instrument_sort", "_checksum_sort"]).reset_index(drop=True)


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
        "limitations": "|".join(evidence.limitations),
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


persist_fundamentals = persist_fundamental_evidence
write_fundamental_evidence = persist_fundamental_evidence


__all__ = [
    "FUNDAMENTAL_CLEAN_PATH",
    "FUNDAMENTAL_RAW_DIR",
    "FUNDAMENTAL_SCHEMA_VERSION",
    "FundamentalEvidence",
    "FundamentalPersistenceResult",
    "build_fundamental_evidence",
    "load_fundamental_evidence",
    "latest_fundamental_rows",
    "merge_fundamental_sources",
    "persist_fundamental_evidence",
    "persist_fundamentals",
    "sort_fundamental_evidence",
    "write_fundamental_evidence",
]
