"""Deterministic multi-period statement views over retained filing facts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import STATEMENT_FACTS_PATH


STATEMENT_VIEW_SCHEMA_VERSION = "canonical_statements.v1"
_IDENTITY_TOLERANCE = 0.01
_HISTORY_COLUMNS = (
    "view",
    "canonical_metric",
    "concept",
    "period_type",
    "start",
    "end",
    "instant",
    "fiscal_year",
    "fiscal_period",
    "value",
    "unit",
    "currency",
    "dimensions",
    "filed",
    "form",
    "restatement_kind",
    "mapping_status",
    "mapping_confidence",
    "manual_review_required",
    "source_id",
)


def normalise_statement_facts(records: Iterable[object] | pd.DataFrame) -> pd.DataFrame:
    """Return a stable statement frame while retaining unmapped facts."""

    frame = _as_frame(records)
    if frame.empty:
        return _empty_frame()
    for column, default in {
        "instrument_id": "",
        "concept": "",
        "unit": "",
        "value": None,
        "start": None,
        "end": None,
        "instant": None,
        "filed": None,
        "form": None,
        "accession": None,
        "fiscal_year": None,
        "fiscal_period": None,
        "source_id": "",
        "canonical_metric": None,
        "dimensions": "",
        "currency": None,
        "period_type": "unknown",
        "mapping_status": "unmapped",
        "mapping_confidence": "unknown",
        "manual_review_required": True,
        "restatement_kind": "reported",
        "available_at": None,
    }.items():
        if column not in frame.columns:
            frame[column] = default
        else:
            frame[column] = frame[column].where(frame[column].notna(), default)
    frame["period_type"] = frame.apply(_period_type, axis=1)
    frame["period_key"] = frame.apply(_period_key, axis=1)
    frame["period_end"] = frame.apply(lambda row: row.get("end") or row.get("instant") or "", axis=1)
    frame["period_start"] = frame.get("start", pd.Series(index=frame.index, dtype="object"))
    frame["availability_status"] = frame["available_at"].map(lambda value: "exact" if _text(value) else "unknown")
    frame["restatement_kind"] = frame.apply(_restatement_kind, axis=1)
    return frame.sort_values(
        ["instrument_id", "canonical_metric", "concept", "period_type", "period_key", "dimensions", "filed", "source_id"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


def statement_view(
    records: Iterable[object] | pd.DataFrame,
    view: str,
    *,
    as_known_at: str | date | None = None,
) -> pd.DataFrame:
    """Build reported, latest-restated or point-in-time as-known facts."""

    frame = normalise_statement_facts(records)
    if frame.empty:
        return frame
    if view == "reported":
        return frame.copy()
    if view == "as_known_at":
        if as_known_at is None:
            raise ValueError("as_known_at requires a date or ISO timestamp")
        cutoff = _date_text(as_known_at)
        available = frame[frame["available_at"].map(lambda value: bool(_text(value))) & (frame["available_at"].astype(str) <= cutoff)].copy()
        return _latest_per_period(available)
    if view == "latest_restated":
        return _latest_per_period(frame)
    raise ValueError(f"unsupported statement view: {view}")


def statement_coverage(frame: pd.DataFrame) -> dict[str, object]:
    normalised = normalise_statement_facts(frame)
    annual = normalised.loc[normalised["period_type"].eq("annual"), "period_key"].nunique()
    quarterly = normalised.loc[normalised["period_type"].eq("quarterly"), "period_key"].nunique()
    mapped = int(normalised["canonical_metric"].notna().sum())
    return {
        "schema_version": STATEMENT_VIEW_SCHEMA_VERSION,
        "total_facts": int(len(normalised)),
        "mapped_facts": mapped,
        "unmapped_facts": int(len(normalised) - mapped),
        "manual_review_facts": int(normalised["manual_review_required"].astype(bool).sum()),
        "annual_periods": int(annual),
        "quarterly_periods": int(quarterly),
        "annual_target_met": bool(annual >= 5),
        "quarterly_target_met": bool(quarterly >= 12),
        "source_count": int(normalised["source_id"].nunique()) if "source_id" in normalised else 0,
    }


def reconcile_statement_identities(frame: pd.DataFrame, *, tolerance: float = _IDENTITY_TOLERANCE) -> dict[str, object]:
    """Check only identities with complete comparable inputs; missing is not failure."""

    latest = statement_view(frame, "latest_restated")
    if latest.empty:
        return {"status": "unavailable", "checked": 0, "passed": 0, "failed": 0, "unavailable": 1, "tolerance": tolerance}
    checked = passed = failed = 0
    for _key, group in latest.groupby(["instrument_id", "period_key"], dropna=False):
        values = _unique_numeric_values(group)
        if {"assets", "liabilities", "equity"} <= values.keys():
            checked += 1
            if abs(values["assets"] - values["liabilities"] - values["equity"]) <= tolerance:
                passed += 1
            else:
                failed += 1
        cash_components = {"cash_from_operations", "cash_from_investing", "cash_from_financing", "cash_net_change"}
        if cash_components <= values.keys():
            checked += 1
            expected = values["cash_from_operations"] + values["cash_from_investing"] + values["cash_from_financing"]
            if "cash_from_fx" in values:
                expected += values["cash_from_fx"]
            if abs(expected - values["cash_net_change"]) <= tolerance:
                passed += 1
            else:
                failed += 1
    return {
        "status": "failed" if failed else "passed" if checked else "unavailable",
        "checked": checked,
        "passed": passed,
        "failed": failed,
        "unavailable": 0 if checked else 1,
        "tolerance": tolerance,
    }


def load_statement_evidence(
    path: Path = STATEMENT_FACTS_PATH,
    *,
    instrument_id: str | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    """Load one instrument's canonical statement evidence for the UI."""

    try:
        frame = pd.read_parquet(path) if Path(path).is_file() else pd.DataFrame()
    except (OSError, ValueError, ImportError):
        frame = pd.DataFrame()
    if instrument_id and "instrument_id" in frame.columns:
        frame = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    if frame.empty:
        return {
            "status": "unavailable",
            "message": "Canonical statement evidence unavailable; import an official filing or local statement package.",
            "statement_history": [],
            "coverage": statement_coverage(frame),
            "reconciliation": reconcile_statement_identities(frame),
            "execution_allowed": False,
        }
    reported = statement_view(frame, "reported")
    latest = statement_view(frame, "latest_restated")
    known = statement_view(frame, "as_known_at", as_known_at=as_known_at) if as_known_at else pd.DataFrame()
    history = _history_rows(reported, "reported") + _history_rows(latest, "latest_restated")
    if as_known_at:
        history.extend(_history_rows(known, "as_known_at"))
    coverage = statement_coverage(latest)
    coverage["reported_facts"] = int(len(reported))
    coverage["latest_restated_facts"] = int(len(latest))
    coverage["as_known_at"] = _date_text(as_known_at) if as_known_at else "not_requested"
    return {
        "status": "available",
        "message": "Reported, latest-restated and optional point-in-time statement views are evidence-only.",
        "statement_history": history,
        "coverage": coverage,
        "reconciliation": reconcile_statement_identities(latest),
        "execution_allowed": False,
    }


def _as_frame(records: Iterable[object] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        return records.copy()
    rows = [dict(item) if isinstance(item, Mapping) else _object_dict(item) for item in records]
    return pd.DataFrame(rows)


def _object_dict(item: object) -> dict[str, object]:
    if hasattr(item, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(item)
    return {key: getattr(item, key) for key in dir(item) if not key.startswith("_") and not callable(getattr(item, key))}


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "instrument_id",
            "canonical_metric",
            "concept",
            "unit",
            "value",
            "start",
            "end",
            "instant",
            "filed",
            "form",
            "accession",
            "fiscal_year",
            "fiscal_period",
            "source_id",
            "dimensions",
            "currency",
            "period_type",
            "mapping_status",
            "mapping_confidence",
            "manual_review_required",
            "restatement_kind",
            "available_at",
            "period_key",
            "period_end",
            "period_start",
            "availability_status",
        ]
    )


def _latest_per_period(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    result["_filed_sort"] = result["filed"].map(_text)
    result["_amended_sort"] = result["restatement_kind"].eq("amended").astype(int)
    keys = ["instrument_id", "canonical_metric", "concept", "unit", "period_type", "period_key", "dimensions"]
    result = result.sort_values(keys + ["_filed_sort", "_amended_sort", "accession", "source_id"], kind="stable", na_position="last")
    result = result.drop_duplicates(subset=keys, keep="last")
    return result.drop(columns=["_filed_sort", "_amended_sort"], errors="ignore").reset_index(drop=True)


def _period_type(row: Mapping[str, object]) -> str:
    current = _text(row.get("period_type"))
    if current in {"annual", "quarterly", "instant", "duration"}:
        if current in {"instant", "duration"}:
            fiscal = _text(row.get("fiscal_period")).upper()
            return "annual" if fiscal == "FY" else "quarterly" if fiscal.startswith("Q") else current
        return current
    fiscal = _text(row.get("fiscal_period")).upper()
    if fiscal == "FY":
        return "annual"
    if fiscal.startswith("Q"):
        return "quarterly"
    return "instant" if _text(row.get("instant")) or not _text(row.get("start")) else "duration"


def _period_key(row: Mapping[str, object]) -> str:
    if _text(row.get("instant")) or (not _text(row.get("start")) and _text(row.get("end"))):
        return f"instant:{_text(row.get('instant')) or _text(row.get('end'))}"
    return f"duration:{_text(row.get('start'))}:{_text(row.get('end'))}:{_text(row.get('fiscal_period'))}"


def _restatement_kind(row: Mapping[str, object]) -> str:
    form = _text(row.get("form")).upper()
    return "amended" if form.endswith("/A") else _text(row.get("restatement_kind")) or "reported"


def _unique_numeric_values(group: pd.DataFrame) -> dict[str, float]:
    values: dict[str, float] = {}
    for metric, metric_rows in group.groupby("canonical_metric", dropna=True):
        numeric = pd.to_numeric(metric_rows["value"], errors="coerce").dropna().unique()
        if len(numeric) == 1:
            values[str(metric)] = float(numeric[0])
    return values


def _history_rows(frame: pd.DataFrame, view: str) -> list[dict[str, object]]:
    if frame.empty:
        return []
    result = frame[frame["canonical_metric"].notna()].copy()
    result = result.sort_values(["period_end", "canonical_metric", "filed", "source_id"], kind="stable", na_position="last").tail(250)
    rows: list[dict[str, object]] = []
    for item in result.to_dict("records"):
        rows.append({"view": view, **{column: item.get(column) for column in _HISTORY_COLUMNS if column != "view"}})
    return rows


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _date_text(value: str | date | None) -> str:
    if value is None:
        return ""
    return pd.Timestamp(value).date().isoformat()


__all__ = [
    "STATEMENT_FACTS_PATH",
    "STATEMENT_VIEW_SCHEMA_VERSION",
    "load_statement_evidence",
    "normalise_statement_facts",
    "reconcile_statement_identities",
    "statement_coverage",
    "statement_view",
]
