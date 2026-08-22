from __future__ import annotations

import json
import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


FEATURE_DRIVER_COLUMNS = [
    "instrument",
    "instrument_id",  # legacy alias retained for existing exports
    "component",
    "raw_metric",
    "normalised_score",
    "peer_group",
    "peer_percentile",
    "historical_contribution",
    "coverage",
    "uncertainty",
    "interaction",
    "counterfactual_sensitivity",
    "direction",
    "authority",
    "source_authority",
    "driver_text",
    "source_dataset",
    "source_span",
    "source_vintage_hash",
    "claim_hash",
    "as_of_date",
    "freshness_status",
    "missingness",
    "conflict",
    "conflict_id",
    "contribution",
    "classification",
    "authority_classification",
    "freshness_classification",
    "flags",
    "source_id",
    "execution_allowed",
]

_NUMERIC_EVIDENCE_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "peer_percentile": (0.0, 100.0),
    "historical_contribution": (None, None),
    "coverage": (0.0, 1.0),
    "counterfactual_sensitivity": (None, None),
    "contribution": (None, None),
}
_SCORE_BOUNDS = (0.0, 10.0)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNAVAILABLE_CLAIM = "unavailable (non-traceable claim; source provenance unavailable)."


def build_feature_drivers(scores: pd.DataFrame | Iterable[Any], ledger: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build deterministic, informational feature-driver rows.

    Rows can be supplied as a component DataFrame or as
    ``SimpleInstrumentScore`` objects.  Driver metadata never feeds back into
    score/action calculation and every output row is explicitly non-executable.
    """

    frame = _as_frame(scores)
    if frame.empty:
        return pd.DataFrame(columns=FEATURE_DRIVER_COLUMNS)
    frame = frame.copy()
    if "instrument_id" not in frame.columns:
        frame["instrument_id"] = frame.get("instrument", "")
    if "instrument" not in frame.columns:
        frame["instrument"] = frame["instrument_id"]
    frame["instrument_id"] = frame["instrument_id"].map(_text)
    frame["instrument"] = frame["instrument"].map(_text)
    if "component" not in frame.columns:
        frame["component"] = frame.get("component_name", "")
    frame["component"] = frame["component"].map(_text)
    if "normalised_score" not in frame.columns:
        frame["normalised_score"] = frame.get("normalised_score_10", frame.get("score_10"))
    frame["normalised_score"] = pd.array(
        [
            _evidence_number(value, minimum=_SCORE_BOUNDS[0], maximum=_SCORE_BOUNDS[1])
            for value in frame["normalised_score"]
        ],
        dtype="Float64",
    )
    if "raw_metric" not in frame.columns:
        frame["raw_metric"] = frame.get("raw_metric_value", frame.get("raw_score"))
    if "source_id" not in frame.columns:
        frame["source_id"] = frame.get("source", "")
    if ledger is not None and not ledger.empty:
        frame = _merge_ledger(frame, ledger)
    _normalise_evidence_columns(frame)
    for column, default in (
        ("authority", "unknown"),
        ("source_authority", "unavailable"),
        ("driver_text", ""),
        ("source_dataset", ""),
        ("source_span", "unavailable"),
        ("source_vintage_hash", "unavailable"),
        ("claim_hash", "unavailable"),
        ("as_of_date", ""),
        ("freshness_status", "unknown"),
        ("uncertainty", "unavailable"),
        ("interaction", "unavailable"),
        ("counterfactual_sensitivity", "unavailable"),
        ("conflict", "unavailable"),
        ("conflict_id", "unavailable"),
    ):
        if column not in frame.columns:
            frame[column] = default
        elif column not in {
            "peer_group",
            "peer_percentile",
            "historical_contribution",
            "coverage",
            "counterfactual_sensitivity",
            "contribution",
            "driver_text",
            "source_authority",
            "source_span",
            "source_vintage_hash",
            "claim_hash",
        }:
            frame[column] = frame[column].map(_text).replace("", default)
    frame["authority"] = frame["authority"].map(_text).replace("", "unknown")
    frame["source_authority"] = frame["source_authority"].map(_scalar_text).replace("", "unavailable")
    frame["source_span"] = frame["source_span"].map(_scalar_text).replace("", "unavailable")
    frame["source_vintage_hash"] = frame["source_vintage_hash"].map(_source_vintage_hash).replace("", "unavailable")
    frame["source_id"] = frame["source_id"].map(_text)
    frame["source_dataset"] = frame.apply(_source_dataset, axis=1)
    frame["as_of_date"] = frame["as_of_date"].map(_text)
    frame["freshness_status"] = frame["freshness_status"].map(_text).replace("", "unknown")
    frame["direction"] = frame["normalised_score"].map(_direction)
    _derive_peer_percentiles(frame)
    _normalise_numeric_evidence(frame)
    frame["uncertainty"] = frame["uncertainty"].map(_uncertainty)
    frame["missingness"] = frame["normalised_score"].map(
        lambda value: "missing" if pd.isna(value) else "not_missing"
    )
    frame["conflict"] = frame.apply(_conflict, axis=1)
    frame["conflict_id"] = frame["conflict_id"].map(_text).replace("", "unavailable")
    frame["driver_text"] = frame.apply(_driver_text, axis=1)
    frame["claim_hash"] = frame.apply(_claim_hash_for_row, axis=1)
    frame["authority_classification"] = frame["authority"].map(_authority_classification)
    frame["freshness_classification"] = frame["freshness_status"].map(_freshness_classification)
    frame["classification"] = frame.apply(_classification, axis=1)
    frame["flags"] = frame.apply(_flags, axis=1)
    frame["execution_allowed"] = False
    for column in FEATURE_DRIVER_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    result = frame[FEATURE_DRIVER_COLUMNS].copy()
    return result.sort_values(["instrument", "component"], kind="stable").reset_index(drop=True)


def _as_frame(scores: pd.DataFrame | Iterable[Any]) -> pd.DataFrame:
    if isinstance(scores, pd.DataFrame):
        return scores
    rows: list[dict[str, Any]] = []
    for score in scores or []:
        instrument = getattr(score, "display_id", getattr(score, "instrument_id", ""))
        canonical = getattr(score, "canonical_score", None)
        canonical_rows = {
            str(row.get("key")): row
            for row in (getattr(canonical, "components", ()) or ())
            if isinstance(row, Mapping)
        }
        for component in getattr(score, "components", []) or []:
            canonical_row = canonical_rows.get(str(getattr(component, "key", "")), {})
            rows.append(
                {
                    "instrument": instrument,
                    "instrument_id": instrument,
                    "component": getattr(component, "key", ""),
                    "raw_metric": getattr(component, "raw_score", None),
                    "normalised_score": getattr(component, "score_10", None),
                    "authority": getattr(component, "authority", "unknown"),
                    "source_authority": canonical_row.get("source_authority", getattr(component, "source_authority", "unavailable")),
                    "driver_text": getattr(component, "why", ""),
                    "source_id": getattr(component, "source_id", ""),
                    "source_span": canonical_row.get("source_span", getattr(component, "source_span", getattr(component, "exact_source_span", "unavailable"))),
                    "source_vintage_hash": getattr(canonical, "source_vintage_hash", None) or canonical_row.get("source_vintage_hash", "unavailable"),
                    "as_of_date": getattr(component, "as_of_date", getattr(score, "latest_date", getattr(canonical, "decision_time", ""))),
                    "freshness_status": getattr(component, "freshness_status", "unknown"),
                    "peer_group": canonical_row.get("peer_group", getattr(component, "peer_group", "unavailable")),
                    "peer_percentile": canonical_row.get("peer_percentile", getattr(component, "peer_percentile", None)),
                    "historical_contribution": canonical_row.get("historical_contribution", getattr(component, "historical_contribution", None)),
                    "coverage": canonical_row.get("coverage", getattr(component, "coverage", getattr(canonical, "coverage", None))),
                    "uncertainty": canonical_row.get("uncertainty", getattr(component, "uncertainty", "unavailable")),
                    "interaction": canonical_row.get("interaction", getattr(component, "interaction", "unavailable")),
                    "counterfactual_sensitivity": canonical_row.get("counterfactual_sensitivity", getattr(component, "counterfactual_sensitivity", "unavailable")),
                    "conflict": canonical_row.get("conflict_id", getattr(component, "conflict_id", "unavailable")),
                    "conflict_id": canonical_row.get("conflict_id", getattr(component, "conflict_id", "unavailable")),
                    "contribution": canonical_row.get("contribution_raw", getattr(component, "contribution", None)),
                }
            )
    return pd.DataFrame(rows)


def _merge_ledger(frame: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    source = ledger.copy()
    if "instrument_id" not in source.columns and "instrument" in source.columns:
        source["instrument_id"] = source["instrument"]
    keys = [key for key in ("instrument_id", "component") if key in frame.columns and key in source.columns]
    if not keys:
        return frame
    columns = keys + [
        column
        for column in (
            "source_id", "source_authority", "authority", "source_dataset", "source_span",
            "source_vintage_hash", "claim_hash",
            "as_of_date", "freshness_status", "missingness", "conflict", "conflict_id",
            "contribution", "historical_contribution", "coverage", "uncertainty",
            "interaction", "counterfactual_sensitivity", "peer_group", "peer_percentile",
        )
        if column in source.columns
    ]
    source = source[columns].drop_duplicates(keys, keep="last")
    merged = frame.merge(source, on=keys, how="left", suffixes=("", "_ledger"))
    for column in (
        "source_id", "authority", "source_authority", "source_dataset", "source_span",
        "source_vintage_hash", "claim_hash",
        "as_of_date", "freshness_status", "missingness", "conflict", "conflict_id",
        "contribution", "historical_contribution", "coverage", "uncertainty",
        "interaction", "counterfactual_sensitivity", "peer_group", "peer_percentile",
    ):
        ledger_column = f"{column}_ledger"
        if ledger_column in merged.columns:
            merged[column] = merged[column].where(merged[column].notna() & merged[column].astype(str).ne(""), merged[ledger_column])
            merged = merged.drop(columns=[ledger_column])
    if "source_authority" in merged.columns:
        if "authority" not in merged.columns:
            merged["authority"] = merged["source_authority"]
        else:
            missing_authority = merged["authority"].isna() | merged["authority"].astype(str).str.strip().isin({"", "unknown"})
            merged.loc[missing_authority, "authority"] = merged.loc[missing_authority, "source_authority"]
    return merged


def _normalise_evidence_columns(frame: pd.DataFrame) -> None:
    """Map known producer aliases without manufacturing absent evidence."""

    aliases = {
        "peer_percentile": ("peer_percentile_0_1", "peer_percentile_pct", "percentile"),
        "historical_contribution": ("historical_contribution_raw", "contribution_history"),
        "coverage": ("coverage_ratio", "canonical_coverage"),
        "uncertainty": ("evidence_uncertainty", "evidence_quality"),
        "interaction": ("interaction_effect", "interaction_note"),
        "counterfactual_sensitivity": ("counterfactual", "counterfactual_effect"),
        "source_span": ("exact_source_span", "citation_span"),
        "source_authority": ("authority_source",),
        "source_vintage_hash": ("vintage_hash", "canonical_source_vintage_hash"),
        "conflict": ("conflict_status",),
        "conflict_id": ("conflict_reference",),
        "contribution": ("canonical_contribution_raw",),
    }
    for target, candidates in aliases.items():
        if target in frame.columns:
            continue
        for candidate in candidates:
            if candidate in frame.columns:
                frame[target] = frame[candidate]
                break
        else:
            frame[target] = None


def _derive_peer_percentiles(frame: pd.DataFrame) -> None:
    """Derive only descriptive cohort ranks from explicit peer-group evidence."""

    if "peer_percentile" not in frame.columns or "peer_group" not in frame.columns:
        return
    values = frame["normalised_score"]
    groups = frame["peer_group"].map(_text)
    components = frame["component"].map(_text)
    dates = frame["as_of_date"].map(_scalar_text)
    vintages = frame["source_vintage_hash"].map(_source_vintage_hash)
    frame["peer_percentile"] = None
    for (component, peer_group, as_of_date, source_vintage_hash), indices in frame.groupby(
        [components, groups, dates, vintages], sort=False, dropna=False
    ).groups.items():
        if (
            not component
            or not peer_group
            or peer_group.casefold() in {"unknown", "unavailable"}
            or not as_of_date
            or not _SHA256_RE.fullmatch(str(source_vintage_hash or ""))
        ):
            continue
        valid = [index for index in indices if pd.notna(values.loc[index])]
        if len(valid) < 2:
            continue
        ranks = values.loc[valid].rank(method="average", pct=True) * 100.0
        for index, percentile in ranks.items():
            current = frame.at[index, "peer_percentile"]
            if _text(current) == "":
                frame.at[index, "peer_percentile"] = round(float(percentile), 6)


def _normalise_numeric_evidence(frame: pd.DataFrame) -> None:
    """Keep finite numeric truth and represent unavailable evidence as nullable values."""

    for column, (minimum, maximum) in _NUMERIC_EVIDENCE_BOUNDS.items():
        frame[column] = pd.array(
            [
                _evidence_number(value, minimum=minimum, maximum=maximum)
                for value in frame[column]
            ],
            dtype="Float64",
        )


def _evidence_number(
    value: object,
    *,
    minimum: float | None,
    maximum: float | None,
) -> float | None:
    if isinstance(value, bool) or not pd.api.types.is_scalar(value):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _uncertainty(value: object) -> str:
    text = _text(value)
    if text.casefold() in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return "unavailable"
    return text or "unavailable"


def _missingness(row: pd.Series) -> str:
    return "missing" if _text(row.get("direction")) == "missing" else "not_missing"


def _conflict(row: pd.Series) -> str:
    explicit = _text(row.get("conflict"))
    if explicit:
        return explicit
    conflict_id = _text(row.get("conflict_id"))
    return conflict_id or "unavailable"


def _direction(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "missing"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "missing"
    if pd.isna(number):
        return "missing"
    return "positive" if number >= 6.5 else "negative" if number < 4.0 else "mixed"


def _authority_classification(value: object) -> str:
    text = _text(value).casefold()
    if text in {"low", "unknown", "model", "model_advisory", "manual_context"} or not text:
        return "low_authority"
    return "authoritative"


def _freshness_classification(value: object) -> str:
    text = _text(value).casefold()
    if text in {"stale", "stale_block", "expired", "old"}:
        return "stale"
    if text in {"partial", "warning", "missing_or_pending", "unknown", ""}:
        return "partial"
    return "fresh"


def _classification(row: pd.Series) -> str:
    direction = str(row.get("direction") or "missing")
    if direction == "missing":
        return "missing"
    authority = str(row.get("authority_classification") or "")
    freshness = str(row.get("freshness_classification") or "")
    if authority == "low_authority":
        return "low_authority"
    if freshness == "stale":
        return "stale"
    if freshness == "partial":
        return "partial"
    return direction


def _flags(row: pd.Series) -> str:
    flags: list[str] = []
    if row.get("authority_classification") == "low_authority":
        flags.append("low_authority")
    if row.get("freshness_classification") == "stale":
        flags.append("stale")
    elif row.get("freshness_classification") == "partial":
        flags.append("partial")
    if row.get("direction") == "missing":
        flags.append("missing")
    return "|".join(flags) or "none"


def _driver_text(row: pd.Series) -> str:
    source_vintage_hash = _source_vintage_hash(row.get("source_vintage_hash"))
    source_span = _scalar_text(row.get("source_span"))
    claim = deterministic_driver_claim(row.get("component"), row.get("normalised_score"))
    if claim and (source_vintage_hash or source_span):
        return claim
    if not claim:
        return "unavailable (non-traceable claim; score unavailable)."
    return _UNAVAILABLE_CLAIM


def deterministic_driver_claim(component: object, score: object) -> str:
    component_text = _scalar_text(component) or "component"
    number = _evidence_number(score, minimum=_SCORE_BOUNDS[0], maximum=_SCORE_BOUNDS[1])
    if number is None:
        return ""
    return f"{component_text}: observed score {number:.1f}/10 in the bound evidence; descriptive only."


def _claim_hash_for_row(row: pd.Series) -> str:
    claim = deterministic_driver_claim(row.get("component"), row.get("normalised_score"))
    source_vintage_hash = _source_vintage_hash(row.get("source_vintage_hash"))
    source_span = _scalar_text(row.get("source_span"))
    if not claim or not (source_vintage_hash or source_span):
        return "unavailable"
    return claim_binding_hash(claim, source_vintage_hash, source_span)


def claim_binding_hash(claim: str, source_vintage_hash: str | None, source_span: str | None) -> str:
    payload = json.dumps(
        {
            "claim": claim,
            "source_span": source_span or "unavailable",
            "source_vintage_hash": source_vintage_hash or "unavailable",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalise_bound_claim(
    value: object,
    *,
    component: object,
    score: object,
    source_vintage_hash: object,
    source_span: object,
    claim_hash: object,
    require_claim_hash: bool,
) -> tuple[str, str]:
    """Return only the deterministic claim bound to validated provenance."""

    vintage = _source_vintage_hash(source_vintage_hash)
    span = _scalar_text(source_span)
    claim = deterministic_driver_claim(component, score)
    if not claim:
        return "unavailable (non-traceable claim; score unavailable).", "unavailable"
    if not (vintage or span):
        return _UNAVAILABLE_CLAIM, "unavailable"
    supplied_claim = value.strip() if isinstance(value, str) else ""
    if supplied_claim != claim:
        return "unavailable (non-traceable claim; claim content inconsistent).", "unavailable"
    expected = claim_binding_hash(claim, vintage, span)
    supplied = _source_vintage_hash(claim_hash)
    if require_claim_hash and supplied != expected:
        return "unavailable (non-traceable claim; claim binding unavailable).", "unavailable"
    return claim, expected


def _source_dataset(row: pd.Series) -> str:
    existing = _text(row.get("source_dataset"))
    if existing:
        return existing
    source_id = _text(row.get("source_id"))
    return source_id.split(":", 1)[0] if source_id else "unavailable"


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return str(value).strip()


def _scalar_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return "" if text.casefold() in {"", "unavailable", "nan", "none", "<na>"} else text


def _source_vintage_hash(value: object) -> str:
    text = _scalar_text(value)
    return text if _SHA256_RE.fullmatch(text) else ""
