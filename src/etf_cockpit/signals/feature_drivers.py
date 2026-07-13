from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


FEATURE_DRIVER_COLUMNS = [
    "instrument",
    "instrument_id",  # legacy alias retained for existing exports
    "component",
    "raw_metric",
    "normalised_score",
    "direction",
    "authority",
    "driver_text",
    "source_dataset",
    "as_of_date",
    "freshness_status",
    "classification",
    "authority_classification",
    "freshness_classification",
    "flags",
    "source_id",
    "execution_allowed",
]


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
    frame["normalised_score"] = pd.to_numeric(frame["normalised_score"], errors="coerce")
    if "raw_metric" not in frame.columns:
        frame["raw_metric"] = frame.get("raw_metric_value", frame.get("raw_score"))
    if "source_id" not in frame.columns:
        frame["source_id"] = frame.get("source", "")
    if ledger is not None and not ledger.empty:
        frame = _merge_ledger(frame, ledger)
    for column, default in (
        ("authority", "unknown"),
        ("driver_text", ""),
        ("source_dataset", ""),
        ("as_of_date", ""),
        ("freshness_status", "unknown"),
    ):
        if column not in frame.columns:
            frame[column] = default
    frame["authority"] = frame["authority"].map(_text).replace("", "unknown")
    frame["source_id"] = frame["source_id"].map(_text)
    frame["source_dataset"] = frame.apply(_source_dataset, axis=1)
    frame["as_of_date"] = frame["as_of_date"].map(_text)
    frame["freshness_status"] = frame["freshness_status"].map(_text).replace("", "unknown")
    frame["direction"] = frame["normalised_score"].map(_direction)
    frame["driver_text"] = frame.apply(_driver_text, axis=1)
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
        for component in getattr(score, "components", []) or []:
            rows.append(
                {
                    "instrument": instrument,
                    "instrument_id": instrument,
                    "component": getattr(component, "key", ""),
                    "raw_metric": getattr(component, "raw_score", None),
                    "normalised_score": getattr(component, "score_10", None),
                    "authority": getattr(component, "authority", "unknown"),
                    "driver_text": getattr(component, "why", ""),
                    "source_id": getattr(component, "source_id", ""),
                    "as_of_date": getattr(component, "as_of_date", getattr(score, "latest_date", "")),
                    "freshness_status": getattr(component, "freshness_status", "unknown"),
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
    columns = keys + [column for column in ("source_id", "source_authority", "authority", "source_dataset", "as_of_date", "freshness_status") if column in source.columns]
    source = source[columns].drop_duplicates(keys, keep="last")
    merged = frame.merge(source, on=keys, how="left", suffixes=("", "_ledger"))
    for column in ("source_id", "authority", "source_dataset", "as_of_date", "freshness_status"):
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
    existing = _text(row.get("driver_text"))
    if existing:
        return existing
    component = _text(row.get("component")) or "component"
    direction = _text(row.get("direction"))
    score = row.get("normalised_score")
    if direction == "missing":
        return f"{component}: unavailable (N/A); informational only."
    return f"{component}: {direction} driver at {float(score):.1f}/10; informational only."


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
