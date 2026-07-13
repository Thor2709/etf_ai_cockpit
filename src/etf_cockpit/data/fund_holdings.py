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
    frame = result.frame.copy()
    reasons: list[str] = []
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


persist_holdings = write_holdings_records
