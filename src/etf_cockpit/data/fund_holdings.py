from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR


FUND_HOLDINGS_PATH = CLEAN_DIR / "fund_holdings.parquet"
HOLDINGS_CLEAN_PATH = FUND_HOLDINGS_PATH
_EXPLICIT_IDENTITY_COLUMNS = ("isin", "ticker", "holding_id", "security_id")
_REQUIRED_HOLDINGS_COLUMNS = (
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
    if value in {"issuer", "official_issuer", "issuer_csv", "issuer_xlsx", "issuer_json", "official"} or value.startswith("issuer"):
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
        return None


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
    clean[weight_column] = pd.to_numeric(clean[weight_column], errors="coerce")
    if clean[weight_column].isna().any():
        return _empty_result(instrument, as_of_text, source, "non_numeric_weight", authority=authority)
    if (clean[weight_column] < 0).any():
        return _empty_result(instrument, as_of_text, source, "negative_weight", authority=authority)
    raw_max = float(clean[weight_column].max())
    if raw_max > 100:
        return _empty_result(instrument, as_of_text, source, "weight_over_100_percent", authority=authority)
    weights = clean[weight_column].astype(float)
    if weight_column in {"weight_percent", "weight_pct"} or raw_max > 1:
        weights = weights / 100.0
    if (weights > 1).any():
        return _empty_result(instrument, as_of_text, source, "weight_over_100_percent", authority=authority)

    selected = pd.DataFrame({"security": clean[security_column], "weight": weights})
    for column in ("isin", "ticker", "sector", "region", "currency", "holding_id", "security_id"):
        if column in clean.columns and column not in selected.columns:
            selected[column] = clean[column]
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
    if freshness == "stale":
        completeness = "stale"
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
    canonical = selected.sort_values(["security", "weight"], kind="stable").to_json(orient="records", date_format="iso")
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


def write_holdings_records(
    result: HoldingsNormalisationResult,
    *,
    destination: Path = FUND_HOLDINGS_PATH,
) -> Path:
    """Persist normalised holdings plus provenance in one atomic transaction."""
    frame = result.frame.copy() if isinstance(result.frame, pd.DataFrame) else result.frame
    reasons = _holdings_write_reasons(result, frame)
    if reasons:
        detail = "; ".join(reasons)
        raise ValueError(f"Holdings result is not score-eligible; refusing to replace canonical store ({detail}).")
    if "schema_version" not in frame.columns:
        frame.insert(0, "schema_version", 1)
    destination = Path(destination)
    csv_destination = destination.with_suffix(".csv")
    requests = (
        AtomicWriteRequest(destination, parquet_payload(frame), validate_parquet_file),
        AtomicWriteRequest(csv_destination, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
    )
    atomic_write_group(requests)
    return destination


def _holdings_write_reasons(result: HoldingsNormalisationResult, frame: pd.DataFrame) -> list[str]:
    """Return fail-closed reasons for a frame about to replace canonical holdings."""
    reasons: list[str] = []
    if not isinstance(frame, pd.DataFrame):
        return ["frame is not a DataFrame"]
    if bool(frame.columns.duplicated().any()):
        return ["duplicate frame columns"]
    missing = [column for column in _REQUIRED_HOLDINGS_COLUMNS if column not in frame.columns]
    if missing:
        reasons.append(f"missing required columns={','.join(missing)}")
    if frame.empty:
        reasons.append("empty frame")
    if result.completeness != "full":
        reasons.append(f"completeness={result.completeness!r}")
    if result.freshness != "fresh":
        reasons.append(f"freshness={result.freshness!r}")
    if result.authority != "issuer":
        reasons.append(f"authority={result.authority!r}")
    if result.score_eligible is not True:
        reasons.append("score_eligible=False")
    if missing or frame.empty:
        return reasons

    text_columns = ("security", "instrument_id", "source", "source_id", "completeness", "freshness", "authority")
    for column in text_columns:
        values = frame[column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any():
            reasons.append(f"missing row provenance={column}")

    identity_columns = [column for column in _EXPLICIT_IDENTITY_COLUMNS if column in frame.columns]
    if not identity_columns:
        reasons.append("missing required holding identity")
    else:
        identified = pd.Series(False, index=frame.index)
        for column in identity_columns:
            values = frame[column]
            identified |= values.notna() & values.astype(str).str.strip().ne("")
        if not bool(identified.all()):
            reasons.append("row missing required holding identity")

    weights = pd.to_numeric(frame["weight"], errors="coerce")
    if weights.isna().any():
        reasons.append("non-numeric weight")
    else:
        numeric_weights = weights.astype(float)
        if not bool((numeric_weights >= 0).all()) or not bool((numeric_weights <= 1).all()):
            reasons.append("weight outside [0, 1]")
        elif not 0.99 - 1e-9 <= float(numeric_weights.sum()) <= 1.01 + 1e-9:
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
    if not bool(score_values.map(lambda value: type(value) is bool and value).all()):
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

    canonical_columns = ["security", "weight"] + [
        column for column in ("isin", "ticker", "sector", "region", "currency", "holding_id", "security_id") if column in frame.columns
    ]
    canonical = frame[canonical_columns].sort_values(["security", "weight"], kind="stable").to_json(orient="records", date_format="iso")
    expected_source_id = "fundhold:" + hashlib.sha256(
        f"{instrument_values.iloc[0]}|{as_of_date.isoformat() if as_of_date else result.as_of}|{result.source}|{canonical}".encode("utf-8")
    ).hexdigest()[:24]
    if str(result.source_id) != expected_source_id:
        reasons.append("mismatched source_id")
    if not bool(frame["source_id"].astype(str).str.strip().eq(expected_source_id).all()):
        reasons.append("mismatched row source_id")
    return reasons


persist_holdings = write_holdings_records
