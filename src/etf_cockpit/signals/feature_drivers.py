from __future__ import annotations

import json
import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
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
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AWARE_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$"
)
_PROVENANCE_PLACEHOLDERS = {"", "unknown", "unavailable", "nan", "none", "<na>", "n/a", "na"}
_SAFE_INTERACTION_STATES = {"none", "not_observed", "observed", "mixed"}
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
            "as_of_date",
        }:
            frame[column] = frame[column].map(_text).replace("", default)
    frame["authority"] = frame["authority"].map(_text).replace("", "unknown")
    frame["source_authority"] = frame["source_authority"].map(_source_provenance_text).replace("", "unavailable")
    frame["source_span"] = frame["source_span"].map(_source_provenance_text).replace("", "unavailable")
    frame["source_vintage_hash"] = frame["source_vintage_hash"].map(_source_vintage_hash).replace("", "unavailable")
    frame["source_id"] = frame["source_id"].map(_text)
    frame["source_dataset"] = frame.apply(_source_dataset, axis=1)
    frame["_pit_valid"] = frame.apply(_score_pit_is_valid, axis=1)
    frame["as_of_date"] = frame["as_of_date"].map(_canonical_cohort_time).replace("", "unavailable")
    frame["freshness_status"] = frame["freshness_status"].map(_text).replace("", "unknown")
    frame["direction"] = frame["normalised_score"].map(_direction)
    _derive_peer_percentiles(frame)
    _normalise_numeric_evidence(frame)
    frame["uncertainty"] = frame["uncertainty"].map(_uncertainty)
    frame["interaction"] = frame["interaction"].map(_normalise_interaction)
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
    keys = ("instrument_id", "component")
    if any(key not in frame.columns or key not in source.columns for key in keys):
        return frame
    evidence_columns = [
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
    result = frame.copy().reset_index(drop=True)
    for index, score_row in result.iterrows():
        selected = _latest_eligible_ledger_row(score_row, source)
        if selected is None:
            continue
        for column in evidence_columns:
            if column not in result.columns:
                result[column] = None
            if not _has_value(result.at[index, column]):
                result.at[index, column] = selected.get(column)
    if "source_authority" in result.columns:
        if "authority" not in result.columns:
            result["authority"] = result["source_authority"]
        else:
            missing_authority = result["authority"].isna() | result["authority"].astype(str).str.strip().isin({"", "unknown"})
            result.loc[missing_authority, "authority"] = result.loc[missing_authority, "source_authority"]
    return result


def _latest_eligible_ledger_row(score_row: pd.Series, ledger: pd.DataFrame) -> pd.Series | None:
    cutoff = _score_cutoff_time(score_row)
    if cutoff is None:
        return None
    instrument = _scalar_text(score_row.get("instrument_id"))
    component = _scalar_text(score_row.get("component"))
    if not instrument or not component:
        return None
    candidates: list[tuple[pd.Timestamp, pd.Series]] = []
    for _, candidate in ledger.iterrows():
        if _scalar_text(candidate.get("instrument_id")) != instrument or _scalar_text(candidate.get("component")) != component:
            continue
        evidence_time = _required_row_time(candidate, ("evidence_at", "valid_at", "as_of_date"))
        if evidence_time is None or evidence_time > cutoff:
            continue
        if not _ledger_chronology_is_valid(candidate, evidence_time, cutoff):
            continue
        candidates.append((evidence_time, candidate))
    if not candidates:
        return None
    latest_time = max(item[0] for item in candidates)
    latest = [row for timestamp, row in candidates if timestamp == latest_time]
    identities = {_deterministic_ledger_row_key(row) for row in latest}
    if len(identities) != 1:
        return None
    return min(latest, key=_deterministic_ledger_row_key)


def _required_row_time(row: pd.Series, columns: tuple[str, ...]) -> pd.Timestamp | None:
    for column in columns:
        if column not in row.index:
            continue
        value = row.get(column)
        if not _has_value(value):
            continue
        return _parse_canonical_time(value)
    return None


def _score_cutoff_time(row: pd.Series) -> pd.Timestamp | None:
    as_of = _required_row_time(row, ("as_of_date",))
    if as_of is None:
        return None
    decisions: list[pd.Timestamp] = []
    for column in ("decision_time", "decision_at"):
        if column not in row.index or not _has_value(row.get(column)):
            continue
        parsed = _parse_canonical_time(row.get(column))
        if parsed is None:
            return None
        decisions.append(parsed)
    if decisions and any(value != decisions[0] for value in decisions[1:]):
        return None
    cutoff = decisions[0] if decisions else as_of
    return cutoff if cutoff >= as_of else None


def _score_pit_is_valid(row: pd.Series) -> bool:
    return _score_cutoff_time(row) is not None


def _ledger_chronology_is_valid(
    row: pd.Series,
    evidence_time: pd.Timestamp,
    cutoff: pd.Timestamp,
) -> bool:
    chronology = [evidence_time]
    for column in ("known_at", "available_at"):
        if column not in row.index or not _has_value(row.get(column)):
            continue
        timestamp = _parse_canonical_time(row.get(column))
        if timestamp is None:
            return False
        chronology.append(timestamp)
    return (
        all(left <= right for left, right in zip(chronology, chronology[1:]))
        and chronology[-1] <= cutoff
    )


def _deterministic_ledger_row_key(row: pd.Series) -> str:
    return json.dumps(
        {str(column): row.get(column) for column in sorted(row.index)},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _has_value(value: object) -> bool:
    if value is None:
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return True
    if not pd.api.types.is_scalar(missing):
        return True
    if bool(missing):
        return False
    return not isinstance(value, str) or bool(value.strip())


def _normalise_evidence_columns(frame: pd.DataFrame) -> None:
    """Map known producer aliases without manufacturing absent evidence."""

    aliases = {
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
    _normalise_peer_percentile_alias(frame)
    for target, candidates in aliases.items():
        if target in frame.columns:
            continue
        for candidate in candidates:
            if candidate in frame.columns:
                frame[target] = frame[candidate]
                break
        else:
            frame[target] = None


def _normalise_peer_percentile_alias(frame: pd.DataFrame) -> None:
    if "peer_percentile" in frame.columns:
        return
    if "peer_percentile_0_1" in frame.columns:
        frame["peer_percentile"] = frame["peer_percentile_0_1"].map(
            lambda value: (
                number * 100.0
                if (number := _evidence_number(value, minimum=0.0, maximum=1.0)) is not None
                else None
            )
        )
        return
    for candidate in ("peer_percentile_pct", "percentile"):
        if candidate in frame.columns:
            frame["peer_percentile"] = frame[candidate]
            return
    frame["peer_percentile"] = None


def _derive_peer_percentiles(frame: pd.DataFrame) -> None:
    """Derive only descriptive cohort ranks from explicit peer-group evidence."""

    if "peer_percentile" not in frame.columns or "peer_group" not in frame.columns:
        return
    values = frame["normalised_score"]
    groups = frame["peer_group"].map(_text)
    components = frame["component"].map(_text)
    dates = frame["as_of_date"].map(_canonical_cohort_time)
    vintages = frame["source_vintage_hash"].map(_source_vintage_hash)
    derivable = frame["peer_percentile"].map(_missing_peer_percentile)
    frame["peer_percentile"] = [
        _evidence_number(value, minimum=0.0, maximum=100.0)
        for value in frame["peer_percentile"]
    ]
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
            if derivable.loc[index] and pd.isna(current):
                frame.at[index, "peer_percentile"] = round(float(percentile), 6)


def _missing_peer_percentile(value: object) -> bool:
    if not _has_value(value):
        return True
    return isinstance(value, str) and value.strip().casefold() in {
        "unavailable",
        "nan",
        "none",
        "<na>",
    }


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
    if text in {"fresh", "ok", "current"}:
        return "fresh"
    if text in {"partial", "warning", "missing_or_pending", "unknown", ""}:
        return "partial"
    return "partial"


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
    source_span = _source_provenance_text(row.get("source_span"))
    source_authority = _source_provenance_text(row.get("source_authority"))
    claim = deterministic_driver_claim(row.get("component"), row.get("normalised_score"))
    if claim and source_span and source_authority and bool(row.get("_pit_valid", False)):
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
    source_span = _source_provenance_text(row.get("source_span"))
    source_authority = _source_provenance_text(row.get("source_authority"))
    if not claim or not source_span or not source_authority or not bool(row.get("_pit_valid", False)):
        return "unavailable"
    return claim_binding_hash(claim, source_vintage_hash, source_span, source_authority)


def claim_binding_hash(
    claim: str,
    source_vintage_hash: str | None,
    source_span: str,
    source_authority: str,
) -> str:
    payload = json.dumps(
        {
            "claim": claim,
            "source_span": source_span or "unavailable",
            "source_authority": source_authority or "unavailable",
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
    source_authority: object,
    claim_hash: object,
    require_claim_hash: bool,
    as_of_date: object,
    decision_time: object = None,
    decision_at: object = None,
) -> tuple[str, str]:
    """Return only the deterministic claim bound to validated provenance."""

    vintage = _source_vintage_hash(source_vintage_hash)
    span = _source_provenance_text(source_span)
    authority = _source_provenance_text(source_authority)
    claim = deterministic_driver_claim(component, score)
    if not claim:
        return "unavailable (non-traceable claim; score unavailable).", "unavailable"
    pit_row = pd.Series(
        {"as_of_date": as_of_date, "decision_time": decision_time, "decision_at": decision_at}
    )
    if not span or not authority or not _score_pit_is_valid(pit_row):
        return _UNAVAILABLE_CLAIM, "unavailable"
    supplied_claim = value.strip() if isinstance(value, str) else ""
    if supplied_claim != claim:
        return "unavailable (non-traceable claim; claim content inconsistent).", "unavailable"
    expected = claim_binding_hash(claim, vintage, span, authority)
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


def _source_provenance_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return "" if text.casefold() in _PROVENANCE_PLACEHOLDERS else text


def _normalise_interaction(value: object) -> object:
    number = _evidence_number(value, minimum=None, maximum=None)
    if number is not None:
        return number
    if isinstance(value, str):
        state = value.strip().casefold().replace("-", "_").replace(" ", "_")
        if state in _SAFE_INTERACTION_STATES:
            return state
    return "unavailable"


def _canonical_cohort_time(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, date, datetime, pd.Timestamp)):
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if _DATE_ONLY_RE.fullmatch(text):
            timestamp = _parse_canonical_time(text)
            return timestamp.date().isoformat() if timestamp is not None else ""
    elif isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    timestamp = _parse_canonical_time(value)
    if timestamp is None:
        return ""
    return timestamp.isoformat().replace("+00:00", "Z")


def _parse_canonical_time(value: object) -> pd.Timestamp | None:
    if isinstance(value, bool) or not isinstance(value, (str, date, datetime, pd.Timestamp)):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if _DATE_ONLY_RE.fullmatch(text):
            try:
                date.fromisoformat(text)
            except ValueError:
                return None
        elif not _AWARE_TIMESTAMP_RE.fullmatch(text):
            return None
        value = text
    elif isinstance(value, datetime) and value.tzinfo is None:
        return None
    elif isinstance(value, pd.Timestamp) and value.tzinfo is None:
        return None
    try:
        timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError, OverflowError):
        return None
    return timestamp if isinstance(timestamp, pd.Timestamp) and not pd.isna(timestamp) else None


def _source_vintage_hash(value: object) -> str:
    text = _scalar_text(value)
    return text if _SHA256_RE.fullmatch(text) else ""
