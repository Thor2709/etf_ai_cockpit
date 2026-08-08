from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from numbers import Integral
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.paths import CLEAN_DIR
from etf_cockpit.data.fund_documents import (
    FUND_DOCUMENTS_PATH,
    build_document_inventory,
    fund_document_registry_guard,
    read_document_registry,
    register_document,
)


FUND_HOLDINGS_PATH = CLEAN_DIR / "fund_holdings.parquet"
HOLDINGS_CLEAN_PATH = FUND_HOLDINGS_PATH
_EXPLICIT_IDENTITY_COLUMNS = ("isin", "ticker", "holding_id", "security_id")
REQUIRED_HOLDINGS_COLUMNS = (
    "security",
    "weight",
    "instrument_id",
    "as_of",
    "source",
    "source_id",
    "completeness",
    "freshness",
    "confidence",
    "authority",
    "score_eligible",
)
_HOLDING_CANONICAL_COLUMNS = (
    "security", "weight", "isin", "ticker", "sector", "region", "country", "currency", "issuer", "company",
    "holding_id", "holding_id_namespace", "security_id", "security_id_namespace", "exchange", "venue",
    "identity_type", "identity_namespace", "identity_value", "instrument_type",
)


@dataclass(frozen=True)
class HoldingsNormalisationResult:
    frame: pd.DataFrame
    completeness: str
    source: str
    as_of: str
    warnings: tuple[str, ...]
    source_id: str
    freshness: str = "unknown"
    confidence: float = 0.0
    authority: str = "unknown"
    score_eligible: bool = False

    @property
    def exposure_eligible(self) -> bool:
        return self.score_eligible


def _authority_for_source(source: str) -> str:
    value = str(source or "").strip().lower()
    if value in {"issuer", "official_issuer", "issuer_csv", "issuer_xlsx", "issuer_json", "official"}:
        return "issuer"
    if value in {"yfinance", "yahoo", "vendor", "vendor_top_holdings"} or "yfinance" in value or "yahoo" in value:
        return "vendor"
    return "unknown"


def _date_value(value: str | date | datetime) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed.date()


def _today_value(value: str | date | datetime | None) -> date:
    parsed = _date_value(value) if value is not None else None
    return parsed or datetime.now(timezone.utc).date()


def _empty_result(
    instrument_id: str,
    as_of: str,
    source: str,
    warning: str,
    *,
    authority: str = "unknown",
    freshness: str = "invalid",
) -> HoldingsNormalisationResult:
    columns = ["security", "weight", "instrument_id", "as_of", "source", "source_id", "completeness", "freshness", "confidence", "authority", "score_eligible"]
    return HoldingsNormalisationResult(pd.DataFrame(columns=columns), "invalid", source, str(as_of), (warning,), "", freshness, 0.0, authority, False)


def normalise_holdings(
    frame: pd.DataFrame,
    instrument_id: str,
    as_of: str | date | datetime,
    source: str,
    *,
    today: str | date | datetime | None = None,
    stale_after_days: int = 90,
) -> HoldingsNormalisationResult:
    """Normalise issuer/vendor holdings while retaining explicit evidence limits."""
    authority = _authority_for_source(source)
    instrument = str(instrument_id or "").strip()
    as_of_text = as_of.isoformat() if isinstance(as_of, (date, datetime)) else str(as_of)
    as_of_date = _date_value(as_of)
    if not instrument:
        return _empty_result(instrument, as_of_text, source, "missing_instrument_id", authority=authority)
    if as_of_date is None:
        return _empty_result(instrument, as_of_text, source, "invalid_as_of_date", authority=authority)
    today_date = _today_value(today)
    if as_of_date > today_date:
        return _empty_result(instrument, as_of_text, source, "future_holdings", authority=authority, freshness="invalid")
    if frame is None or frame.empty:
        return _empty_result(instrument, as_of_text, source, "empty_holdings", authority=authority)

    # Keep the established identity aliases for compatibility, but only the
    # explicit identity columns below can make a holding score-eligible.
    security_column = next((column for column in ("security", "holding_name", "security_name", "name", "ticker", "symbol", "isin", "holding_id", "security_id") if column in frame.columns), None)
    weight_column = next((column for column in ("weight", "weight_decimal", "weight_percent", "weight_pct") if column in frame.columns), None)
    if security_column is None or weight_column is None:
        return _empty_result(instrument, as_of_text, source, "missing_security_or_weight", authority=authority)

    clean = frame.copy()
    clean[security_column] = clean[security_column].fillna("").astype(str).str.strip()
    if clean[security_column].eq("").any():
        return _empty_result(instrument, as_of_text, source, "empty_security", authority=authority)
    if clean[weight_column].map(pd.api.types.is_bool).any():
        return _empty_result(instrument, as_of_text, source, "boolean_weight", authority=authority)
    clean[weight_column] = pd.to_numeric(clean[weight_column], errors="coerce")
    if clean[weight_column].isna().any():
        return _empty_result(instrument, as_of_text, source, "non_numeric_weight", authority=authority)
    if (clean[weight_column] < 0).any():
        return _empty_result(instrument, as_of_text, source, "negative_weight", authority=authority)
    weights = clean[weight_column].astype(float)
    if not weights.map(lambda value: math.isfinite(float(value))).all():
        return _empty_result(instrument, as_of_text, source, "non_finite_weight", authority=authority)
    if weight_column in {"weight_percent", "weight_pct"}:
        if (weights > 100).any():
            return _empty_result(instrument, as_of_text, source, "weight_over_100_percent", authority=authority)
        weights = weights / 100.0
    if (weights > 1).any():
        return _empty_result(instrument, as_of_text, source, "decimal_weight_over_1_use_weight_percent", authority=authority)

    selected = pd.DataFrame({"security": clean[security_column], "weight": weights})
    for column in (
        "isin",
        "ticker",
        "sector",
        "region",
        "country",
        "currency",
        "issuer",
        "company",
        "holding_id",
        "holding_id_namespace",
        "security_id",
        "security_id_namespace",
        "exchange",
        "venue",
        "identity_type",
        "identity_namespace",
        "identity_value",
        "instrument_type",
    ):
        if column in clean.columns and column not in selected.columns:
            selected[column] = clean[column]
    # Preserve explicit structural claims for the shared read model. These
    # are optional and are never inferred from ordinary holding columns.
    for column in ("field_name", "field", "value", "page", "source_page", "status"):
        if column in clean.columns and column not in selected.columns:
            selected[column] = clean[column]
    if "confidence" in clean.columns:
        selected["structural_confidence"] = clean["confidence"]
    duplicate_count = int(selected.duplicated(keep="first").sum())
    if duplicate_count:
        selected = selected.drop_duplicates(keep="first").reset_index(drop=True)
    total = float(selected["weight"].sum())
    if total <= 0 or total > 1.01 + 1e-9:
        return _empty_result(instrument, as_of_text, source, "weights_not_usable", authority=authority)
    completeness = "full" if 0.99 - 1e-9 <= total <= 1.01 + 1e-9 else "partial"
    freshness = "fresh" if (today_date - as_of_date) <= timedelta(days=max(0, int(stale_after_days))) else "stale"
    warnings: list[str] = []
    if duplicate_count:
        warnings.append("exact_duplicate_rows_removed")
    if completeness == "partial":
        warnings.append("partial_top_holdings")
    if freshness == "stale":
        warnings.append("stale_holdings")
    if authority == "vendor":
        completeness = "partial"
        if "partial_top_holdings" not in warnings:
            warnings.append("partial_top_holdings")
    row_has_explicit_identifier = pd.Series(False, index=clean.index)
    for column in _EXPLICIT_IDENTITY_COLUMNS:
        if column in clean.columns:
            row_has_explicit_identifier |= clean[column].fillna("").astype(str).str.strip().ne("")
    name_only_manual_review = not bool(row_has_explicit_identifier.all())
    if name_only_manual_review:
        warnings.append("missing_isin_or_ticker_manual_review")
    confidence = 1.0 if completeness == "full" and authority == "issuer" else 0.60 if completeness == "full" else 0.50 if authority == "vendor" else 0.55
    if freshness == "stale":
        confidence = min(confidence, 0.25)
    if name_only_manual_review:
        confidence = min(confidence, 0.55)
    score_eligible = completeness == "full" and freshness == "fresh" and authority == "issuer" and not name_only_manual_review
    canonical = _canonical_holdings_json(selected[[column for column in _HOLDING_CANONICAL_COLUMNS if column in selected.columns]])
    source_id = "fundhold:" + hashlib.sha256(f"{instrument}|{as_of_date.isoformat()}|{source}|{canonical}".encode("utf-8")).hexdigest()[:24]
    selected["instrument_id"] = instrument
    selected["as_of"] = as_of_date.isoformat()
    # Keep the reference-data aliases consumed by the existing Risk analytics.
    selected["etf_id"] = instrument
    selected["as_of_date"] = as_of_date.isoformat()
    selected["holding_name"] = selected["security"]
    selected["source"] = str(source)
    selected["source_id"] = source_id
    selected["completeness"] = completeness
    selected["freshness"] = freshness
    selected["confidence"] = confidence
    selected["authority"] = authority
    selected["score_eligible"] = score_eligible
    return HoldingsNormalisationResult(selected, completeness, str(source), as_of_date.isoformat(), tuple(warnings), source_id, freshness, confidence, authority, score_eligible)


def _canonical_holdings_json(frame: pd.DataFrame) -> str:
    """Return an order-independent finite JSON representation for provenance."""

    records: list[dict[str, object]] = []
    for row in frame.to_dict(orient="records"):
        clean: dict[str, object] = {}
        for key, value in row.items():
            if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
                clean[str(key)] = None
            elif isinstance(value, float):
                if not math.isfinite(value):
                    raise ValueError("canonical holdings contain a non-finite value")
                clean[str(key)] = float(value)
            else:
                clean[str(key)] = value
        records.append(clean)
    records.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))
    return json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)


def write_holdings_records(
    result: HoldingsNormalisationResult,
    *,
    destination: Path = FUND_HOLDINGS_PATH,
) -> Path:
    """Persist normalised holdings plus provenance in one atomic transaction."""
    destination = Path(destination)
    with holdings_store_guard(destination):
        frame = result.frame.copy() if isinstance(result.frame, pd.DataFrame) else result.frame
        reasons = _holdings_write_reasons(result, frame)
        if reasons:
            detail = "; ".join(reasons)
            raise ValueError(f"Holdings result is not score-eligible; refusing to replace canonical store ({detail}).")
        if "schema_version" not in frame.columns:
            frame.insert(0, "schema_version", 1)
        _read_existing_holdings(destination)
        _write_holdings_frame(frame, destination=destination)
    return destination


@contextmanager
def holdings_store_guard(destination: Path, *, timeout_seconds: float = 5.0):
    """Serialize each complete holdings-store read/validate/merge/write transaction."""

    candidate = Path(destination)
    with persistent_file_guard(candidate.with_name(candidate.name + ".guard"), timeout_seconds=timeout_seconds):
        yield


def _write_holdings_frame(frame: pd.DataFrame, *, destination: Path) -> None:
    """Publish a canonical/context holdings frame and its CSV mirror atomically."""
    destination = Path(destination)
    validate_holdings_store_frame(frame, destination=destination)
    csv_destination = destination.with_suffix(".csv")
    requests = (
        AtomicWriteRequest(destination, parquet_payload(frame), validate_parquet_file),
        AtomicWriteRequest(csv_destination, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
    )
    atomic_write_group(requests)


def _read_existing_holdings(destination: Path) -> pd.DataFrame:
    if not destination.exists():
        return pd.DataFrame()
    try:
        existing = pd.read_parquet(destination)
    except Exception as exc:
        raise ValueError(f"Existing holdings store could not be read: {destination}") from exc
    validate_holdings_store_frame(existing, destination=destination)
    return existing


def _merge_holdings_frame(existing: pd.DataFrame, result_frame: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    incoming = result_frame.copy()
    if "schema_version" not in incoming.columns:
        incoming.insert(0, "schema_version", 1)
    if existing.empty:
        return incoming
    retained = existing.loc[existing["instrument_id"].astype(str).str.strip().ne(str(instrument_id).strip())].copy()
    merged = pd.concat([retained, incoming], ignore_index=True, sort=False)
    if "schema_version" not in merged.columns:
        merged.insert(0, "schema_version", 1)
    else:
        merged["schema_version"] = merged["schema_version"].fillna(1)
    return merged


def _holdings_write_reasons(
    result: HoldingsNormalisationResult,
    frame: pd.DataFrame,
    *,
    require_score_eligibility: bool = True,
    require_explicit_identity: bool = True,
    require_full_weights: bool = True,
    require_schema_version: bool = False,
) -> list[str]:
    """Return fail-closed reasons for a frame about to replace canonical holdings."""
    reasons: list[str] = []
    if not isinstance(frame, pd.DataFrame):
        return ["frame is not a DataFrame"]
    if bool(frame.columns.duplicated().any()):
        return ["duplicate frame columns"]
    missing = [column for column in REQUIRED_HOLDINGS_COLUMNS if column not in frame.columns]
    if missing:
        reasons.append(f"missing required columns={','.join(missing)}")
    if frame.empty:
        reasons.append("empty frame")
    if require_score_eligibility and result.completeness != "full":
        reasons.append(f"completeness={result.completeness!r}")
    if require_score_eligibility and result.freshness != "fresh":
        reasons.append(f"freshness={result.freshness!r}")
    if require_score_eligibility and result.authority != "issuer":
        reasons.append(f"authority={result.authority!r}")
    if require_score_eligibility and result.score_eligible is not True:
        reasons.append("score_eligible=False")
    if missing or frame.empty:
        return reasons

    if require_schema_version and "schema_version" not in frame.columns:
        reasons.append("missing schema_version")
    if "schema_version" in frame.columns:
        schema_values = frame["schema_version"]
        valid_schema = schema_values.notna() & schema_values.map(
            lambda value: isinstance(value, Integral) and not isinstance(value, bool) and int(value) == 1
        )
        if not bool(valid_schema.all()):
            reasons.append("schema_version must be canonical integer 1")

    text_columns = ("security", "instrument_id", "source", "source_id", "completeness", "freshness", "authority")
    for column in text_columns:
        values = frame[column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any():
            reasons.append(f"missing row provenance={column}")

    identity_columns = [column for column in _EXPLICIT_IDENTITY_COLUMNS if column in frame.columns]
    if not identity_columns:
        if require_explicit_identity:
            reasons.append("missing required holding identity")
    else:
        identified = pd.Series(False, index=frame.index)
        for column in identity_columns:
            values = frame[column]
            identified |= values.notna() & values.astype(str).str.strip().ne("")
        if require_explicit_identity and not bool(identified.all()):
            reasons.append("row missing required holding identity")

    weights = pd.to_numeric(frame["weight"], errors="coerce")
    if weights.isna().any():
        reasons.append("non-numeric weight")
    else:
        numeric_weights = weights.astype(float)
        if not bool((numeric_weights >= 0).all()) or not bool((numeric_weights <= 1).all()):
            reasons.append("weight outside [0, 1]")
        elif require_full_weights and not 0.99 - 1e-9 <= float(numeric_weights.sum()) <= 1.01 + 1e-9:
            reasons.append("weights are not full")

    expected_values = {
        "source": str(result.source),
        "source_id": str(result.source_id),
        "completeness": str(result.completeness),
        "freshness": str(result.freshness),
        "authority": str(result.authority),
    }
    for column, expected in expected_values.items():
        if not frame[column].astype(str).str.strip().eq(expected.strip()).all():
            reasons.append(f"mismatched summary={column}")

    score_values = frame["score_eligible"]
    if not bool(score_values.map(lambda value: isinstance(value, (bool, np.bool_))).all()):
        reasons.append("row score_eligible is not boolean")
    elif require_score_eligibility and not bool(score_values.all()):
        reasons.append("row score_eligible is not True")
    confidence = pd.to_numeric(frame["confidence"], errors="coerce")
    if confidence.isna().any() or not bool(confidence.between(0, 1).all()):
        reasons.append("invalid confidence")
    elif not bool((confidence - float(result.confidence)).abs().le(1e-12).all()):
        reasons.append("mismatched summary=confidence")

    as_of_date = _date_value(result.as_of)
    if as_of_date is None:
        reasons.append("invalid result as_of")
    else:
        row_dates = frame["as_of"].map(_date_value)
        if row_dates.isna().any() or not bool(row_dates.eq(as_of_date).all()):
            reasons.append("mismatched summary=as_of")
        if as_of_date > datetime.now(timezone.utc).date():
            reasons.append("future holdings")
        if "as_of_date" in frame.columns:
            alias_dates = frame["as_of_date"].map(_date_value)
            if alias_dates.isna().any() or not bool(alias_dates.eq(as_of_date).all()):
                reasons.append("mismatched summary=as_of_date")

    instrument_values = frame["instrument_id"].astype(str).str.strip()
    if instrument_values.nunique(dropna=False) != 1:
        reasons.append("mismatched row instrument_id")
    if "etf_id" in frame.columns and not frame["etf_id"].astype(str).str.strip().eq(instrument_values.iloc[0]).all():
        reasons.append("mismatched summary=etf_id")
    if "holding_name" in frame.columns and not frame["holding_name"].astype(str).str.strip().eq(frame["security"].astype(str).str.strip()).all():
        reasons.append("mismatched summary=holding_name")

    canonical_columns = [column for column in _HOLDING_CANONICAL_COLUMNS if column in frame.columns]
    canonical = _canonical_holdings_json(frame[canonical_columns])
    expected_source_id = "fundhold:" + hashlib.sha256(
        f"{instrument_values.iloc[0]}|{as_of_date.isoformat() if as_of_date else result.as_of}|{result.source}|{canonical}".encode("utf-8")
    ).hexdigest()[:24]
    if str(result.source_id) != expected_source_id:
        reasons.append("mismatched source_id")
    if not bool(frame["source_id"].astype(str).str.strip().eq(expected_source_id).all()):
        reasons.append("mismatched row source_id")
    return reasons


def validate_holdings_store_frame(frame: pd.DataFrame, *, destination: Path) -> None:
    """Validate every persisted holdings row before it can be retained or published."""

    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f"Existing holdings store is not tabular: {destination}")
    if bool(frame.columns.duplicated().any()):
        raise ValueError(f"Existing holdings store contains duplicate columns: {destination}")
    if frame.empty:
        return
    missing = [column for column in REQUIRED_HOLDINGS_COLUMNS if column not in frame.columns]
    if "schema_version" not in frame.columns:
        missing.append("schema_version")
    if missing:
        raise ValueError(f"Existing holdings store is missing required columns={','.join(missing)}: {destination}")

    for instrument_id, group in frame.groupby("instrument_id", sort=False, dropna=False):
        if not str(instrument_id).strip():
            raise ValueError(f"Existing holdings store contains an empty instrument_id: {destination}")
        score_values = group["score_eligible"]
        if score_values.nunique(dropna=False) != 1:
            raise ValueError(f"Existing holdings store contains mixed score_eligible rows: {destination}")
        score_eligible = score_values.iloc[0]
        if not isinstance(score_eligible, (bool, np.bool_)):
            raise ValueError(f"Existing holdings store contains a non-boolean score_eligible row: {destination}")
        score_eligible = bool(score_eligible)
        try:
            confidence = float(group["confidence"].iloc[0])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Existing holdings store contains invalid confidence: {destination}") from exc
        result = HoldingsNormalisationResult(
            group,
            str(group["completeness"].iloc[0]),
            str(group["source"].iloc[0]),
            str(group["as_of"].iloc[0]),
            (),
            str(group["source_id"].iloc[0]),
            str(group["freshness"].iloc[0]),
            confidence,
            str(group["authority"].iloc[0]),
            score_eligible,
        )
        reasons = _holdings_write_reasons(
            result,
            group,
            require_score_eligibility=score_eligible,
            require_explicit_identity=score_eligible,
            require_full_weights=score_eligible,
            require_schema_version=True,
        )
        if reasons:
            raise ValueError(f"Existing holdings store is corrupt: {destination}: {'; '.join(reasons)}")
        if result.completeness not in {"full", "partial"}:
            raise ValueError(f"Existing holdings store has invalid completeness: {destination}")
        if result.freshness not in {"fresh", "stale"}:
            raise ValueError(f"Existing holdings store has invalid freshness: {destination}")
        if result.authority not in {"issuer", "vendor", "unknown"}:
            raise ValueError(f"Existing holdings store has invalid authority: {destination}")


def import_etf_holdings(
    path: Path,
    instrument_id: str,
    as_of: str | date | datetime | None,
    source: str = "issuer",
    *,
    destination: Path | None = None,
    today: str | date | datetime | None = None,
) -> HoldingsNormalisationResult:
    """Read a local CSV/XLSX holdings file, validate it and persist only eligible data."""
    destination = Path(destination or FUND_HOLDINGS_PATH)
    with holdings_store_guard(destination):
        _, frame, effective_as_of = _read_holdings_import(path, as_of)
        result = normalise_holdings(frame, instrument_id, effective_as_of, source, today=today)
        if not result.score_eligible:
            detail = ", ".join(result.warnings) or f"completeness={result.completeness}, freshness={result.freshness}"
            raise ValueError(f"Holdings import is invalid or ineligible; no data changed ({detail}).")
        merged = _merge_holdings_frame(_read_existing_holdings(destination), result.frame, instrument_id)
        _write_holdings_frame(merged, destination=destination)
    return result


def _read_holdings_import(path: Path, as_of: str | date | datetime | None) -> tuple[Path, pd.DataFrame, str | date | datetime]:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"Holdings file is missing: {candidate}")
    suffix = candidate.suffix.lower()
    if suffix == ".csv":
        try:
            frame = pd.read_csv(candidate)
        except Exception as exc:
            raise ValueError(f"Holdings CSV could not be read: {candidate}") from exc
    elif suffix in {".xlsx", ".xls"}:
        try:
            frame = pd.read_excel(candidate)
        except Exception as exc:
            raise ValueError(f"Holdings workbook could not be read: {candidate}") from exc
    else:
        raise ValueError("Holdings import supports CSV and XLSX files only")

    effective_as_of = as_of
    if effective_as_of is None:
        for column in ("as_of", "as_of_date", "date"):
            if column in frame.columns and not frame[column].dropna().empty:
                effective_as_of = frame[column].dropna().iloc[0]
                break
    if effective_as_of is None:
        raise ValueError("Holdings import requires an as_of date")
    return candidate, frame, effective_as_of


def import_etf_holdings_with_document(
    path: Path,
    instrument_id: str,
    as_of: str | date | datetime | None,
    source: str = "issuer",
    *,
    holdings_destination: Path | None = None,
    registry_destination: Path | None = None,
    configured_instrument_ids: list[str] | tuple[str, ...] | None = None,
    today: str | date | datetime | None = None,
) -> HoldingsNormalisationResult:
    """Import eligible holdings and register their source in one atomic group."""
    holdings_destination = Path(holdings_destination or FUND_HOLDINGS_PATH)
    registry_destination = Path(registry_destination or FUND_DOCUMENTS_PATH)
    with fund_document_registry_guard(registry_destination):
        with holdings_store_guard(holdings_destination):
            candidate, frame, effective_as_of = _read_holdings_import(path, as_of)
            result = normalise_holdings(frame, instrument_id, effective_as_of, source, today=today)
            if not result.score_eligible:
                detail = ", ".join(result.warnings) or f"completeness={result.completeness}, freshness={result.freshness}"
                raise ValueError(f"Holdings import is invalid or ineligible; no data changed ({detail}).")
            existing_holdings = _read_existing_holdings(holdings_destination)
            merged_holdings = _merge_holdings_frame(existing_holdings, result.frame, instrument_id)
            document = register_document(
                candidate,
                "holdings",
                str(instrument_id).strip(),
                "",
                "issuer_document",
                document_date=result.as_of,
            )
            merged_holdings = _attach_document_binding(merged_holdings, document)
            existing_registry = read_document_registry(path=registry_destination)
            instrument_ids = [str(item).strip() for item in configured_instrument_ids or () if str(item).strip()]
            if not existing_registry.empty and "instrument_id" in existing_registry.columns:
                instrument_ids.extend(value for value in existing_registry["instrument_id"].dropna().astype(str).map(str.strip) if value)
            instrument_ids.append(str(instrument_id).strip())
            inventory = build_document_inventory(instrument_ids, [*existing_registry.to_dict("records"), document])

            holdings_csv_destination = holdings_destination.with_suffix(".csv")
            registry_csv_destination = registry_destination.with_suffix(".csv")
            requests = (
                AtomicWriteRequest(holdings_destination, parquet_payload(merged_holdings), validate_parquet_file),
                AtomicWriteRequest(holdings_csv_destination, merged_holdings.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
                AtomicWriteRequest(registry_destination, parquet_payload(inventory), validate_parquet_file),
                AtomicWriteRequest(registry_csv_destination, inventory.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
            )
            atomic_write_group(requests)
    return result


def _attach_document_binding(frame: pd.DataFrame, document: object) -> pd.DataFrame:
    """Expose the registered document identity without replacing fundhold IDs."""

    result = frame.copy()
    instrument_id = str(getattr(document, "instrument_id", "")).strip()
    mask = result["instrument_id"].astype(str).str.strip().eq(instrument_id)
    bindings = {
        "document_source_id": str(getattr(document, "source_id", "")),
        "document_checksum": str(getattr(document, "sha256", "")),
        "document_date": getattr(document, "document_date", None),
        "document_known_at": str(getattr(document, "ingested_at", "")),
        "document_type": "holdings",
        "document_status": str(getattr(document, "coverage_status", "unavailable")),
    }
    for column, value in bindings.items():
        if column not in result.columns:
            result[column] = None
        result.loc[mask, column] = value
    return result


persist_holdings = write_holdings_records
