from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.score_history import score_history_frame


REQUIRED_CHANGE_DIMENSIONS = (
    "score",
    "rank",
    "warnings",
    "freshness",
    "model_availability",
    "forecasts",
    "news_inventory",
    "backtest_trust",
    "portfolio_risk",
    "lineage",
)

# Upstream reasons persisted on every score-history row.  Each compares the
# run's own recorded values, so a previous run is never re-derived from
# current configuration.
UPSTREAM_CHANGE_FIELDS: dict[str, tuple[str, ...]] = {
    "source_revisions": ("source_snapshot_hash", "source_vintage_hash"),
    "classification": (
        "classification_version_id",
        "classification_invalidation_hash",
        "classification_dependency_status",
    ),
    "policy_versions": (
        "formula_version",
        "formula_checksum",
        "gate_policy_version",
        "gate_policy_checksum",
    ),
    "portfolio_targets": ("portfolio_snapshot_checksum",),
}
# A dimension counts as recorded only when one of its identity fields was
# written by the run itself; history-normaliser defaults (for example a
# legacy "legacy_unbound" dependency status) must not look like evidence.
UPSTREAM_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "source_revisions": ("source_snapshot_hash", "source_vintage_hash"),
    "classification": ("classification_version_id", "classification_invalidation_hash"),
    "policy_versions": ("formula_version", "formula_checksum", "gate_policy_version", "gate_policy_checksum"),
    "portfolio_targets": ("portfolio_snapshot_checksum",),
}
UPSTREAM_CHANGE_DIMENSIONS = tuple(UPSTREAM_CHANGE_FIELDS)
@dataclass(frozen=True)
class RunChange:
    instrument_id: str
    score_delta: float | None
    current_action: str
    previous_action: str | None
    action_changed: bool
    blocked_by_changed: bool
    score_rank_delta: float | None = None
    current_rank: float | None = None
    previous_rank: float | None = None
    warnings_changed: bool = False
    current_warnings: str = "unavailable"
    previous_warnings: str | None = None
    warnings_added: tuple[str, ...] = ()
    warnings_removed: tuple[str, ...] = ()
    freshness_changed: bool = False
    current_freshness: str = "unavailable"
    previous_freshness: str | None = None
    model_availability_changed: bool = False
    current_model_availability: str = "unavailable"
    previous_model_availability: str | None = None
    forecast_changed: bool = False
    current_forecast: str = "unavailable"
    previous_forecast: str | None = None
    news_inventory_changed: bool = False
    current_news_inventory: str = "unavailable"
    previous_news_inventory: str | None = None
    news_inventory_delta: float | None = None
    backtest_trust_changed: bool = False
    current_backtest_trust: str = "unavailable"
    previous_backtest_trust: str | None = None
    portfolio_risk_changed: bool = False
    current_portfolio_risk: str = "unavailable"
    previous_portfolio_risk: str | None = None
    portfolio_risk_delta: float | None = None
    lineage_changed: bool = False
    current_lineage: str = "unavailable"
    previous_lineage: str | None = None
    dimension_changes: Mapping[str, bool] = field(default_factory=dict)
    summary: str = ""
    upstream_changes: Mapping[str, tuple[str, str | None, bool | None]] = field(default_factory=dict)
    causal_paths: tuple[str, ...] = ()
    dimension_statuses: Mapping[str, str] = field(default_factory=dict)
    causal_paths_status: str = "unavailable"
    causal_paths_reason: str | None = None

    @property
    def rank_changed(self) -> bool:
        return self.score_rank_delta is not None and self.score_rank_delta != 0

    @property
    def score_rank_changed(self) -> bool:
        return self.rank_changed

    @property
    def warning_changed(self) -> bool:
        return self.warnings_changed

    @property
    def freshness_status_changed(self) -> bool:
        return self.freshness_changed

    @property
    def model_changed(self) -> bool:
        return self.model_availability_changed

    @property
    def forecast_status_changed(self) -> bool:
        return self.forecast_changed

    @property
    def news_changed(self) -> bool:
        return self.news_inventory_changed

    @property
    def backtest_changed(self) -> bool:
        return self.backtest_trust_changed

    @property
    def new_warnings(self) -> tuple[str, ...]:
        return self.warnings_added

    @property
    def removed_warnings(self) -> tuple[str, ...]:
        return self.warnings_removed

    @property
    def news_delta(self) -> float | None:
        return self.news_inventory_delta


@dataclass(frozen=True)
class RunChangeReport:
    current_run_id: str
    previous_run_id: str | None
    changes: tuple[RunChange, ...]
    dimensions: tuple[str, ...] = REQUIRED_CHANGE_DIMENSIONS
    summary: str = ""


def compare_runs(
    history_or_current: pd.DataFrame | str | None = None,
    current_run_id: str | None = None,
    previous_run_id: str | None = None,
    *,
    root: Path | None = None,
    history: pd.DataFrame | None = None,
) -> RunChangeReport:
    """Compare two score runs while retaining the legacy DataFrame API.

    Supported forms are ``compare_runs(frame, current, previous)`` and
    ``compare_runs(current, previous, root=...)``.  The latter reads the local
    score-history store and is intentionally informational only.
    """

    if history is not None:
        frame = history
        current = str(current_run_id or "")
        previous = None if previous_run_id is None else str(previous_run_id)
    elif isinstance(history_or_current, pd.DataFrame):
        frame = history_or_current
        current = str(current_run_id or "")
        previous = None if previous_run_id is None else str(previous_run_id)
    else:
        current = str(history_or_current or current_run_id or "")
        previous = None if (current_run_id if history_or_current is not None else previous_run_id) is None else str(
            current_run_id if history_or_current is not None else previous_run_id
        )
        frame = _raw_history_frame(root)
    frame = _safe_frame(frame)
    run_column = frame.get("run_id", pd.Series(dtype=str)).astype(str)
    current_frame = frame.loc[run_column.eq(current)]
    previous_frame = frame.loc[run_column.eq(previous)] if previous else pd.DataFrame(columns=frame.columns)
    previous_by_id = {
        str(row.get("instrument_id")): row
        for row in previous_frame.to_dict(orient="records")
        if _clean_text(row.get("instrument_id"))
    }
    current_by_id = {
        str(row.get("instrument_id")): row
        for row in current_frame.to_dict(orient="records")
        if _clean_text(row.get("instrument_id"))
    }
    changes: list[RunChange] = []
    for instrument_id in sorted(set(current_by_id) | set(previous_by_id)):
        # A previous-only instrument is retained as a removal with an explicit
        # unavailable current state, so What Changed and its digest do not
        # silently lose coverage when a run's universe narrows.
        row = current_by_id.get(instrument_id, {"instrument_id": instrument_id})
        old = previous_by_id.get(instrument_id)
        changes.append(_change_for(instrument_id, row, old, root=root, current_run_id=current, previous_run_id=previous))
    changes.sort(key=lambda change: change.instrument_id)
    report_summary = _report_summary(current, previous, changes)
    return RunChangeReport(current, previous, tuple(changes), summary=report_summary)


def _change_for(
    instrument_id: str,
    current: Mapping[str, Any],
    old: Mapping[str, Any] | None,
    *,
    root: Path | None = None,
    current_run_id: str | None = None,
    previous_run_id: str | None = None,
) -> RunChange:
    current_score = _float(_first(current, "final_combined_score_10", "score_10", "score"))
    previous_score = _float(_first(old or {}, "final_combined_score_10", "score_10", "score"))
    score_delta = None if current_score is None or previous_score is None else round(current_score - previous_score, 4)
    current_rank = _float(_first(current, "score_rank", "rank", "current_rank"))
    previous_rank = _float(_first(old or {}, "score_rank", "rank", "previous_rank"))
    rank_delta = None if current_rank is None or previous_rank is None else current_rank - previous_rank

    current_action = _clean_text(_first(current, "final_action", "legacy_action", "action")) or "unavailable"
    previous_action = _optional_text(_first(old or {}, "final_action", "legacy_action", "action"))
    dimensions: dict[str, bool] = {}
    statuses: dict[str, str] = {}
    values: dict[str, tuple[str, str | None, bool]] = {}
    current_action_marker = _dimension_marker(_evidence_first(current, "final_action", "legacy_action", "action"))
    previous_action_marker = "unavailable" if old is None else _dimension_marker(_evidence_first(old, "final_action", "legacy_action", "action"))
    action_complete = old is not None and "unavailable" not in (current_action_marker, previous_action_marker)
    action_changed = action_complete and current_action_marker != previous_action_marker
    statuses["action"] = "changed" if action_changed else "unchanged" if action_complete else "unavailable"
    for key, aliases in (
        ("warnings", ("warnings", "blocked_by", "warning_flags")),
        ("freshness", ("freshness_status", "data_freshness", "price_freshness")),
        ("model_availability", ("model_available", "model_availability", "model_status", "model_authority_label")),
        ("forecasts", ("forecast_status", "forecast_available", "forecasts", "forecast")),
        ("news_inventory", ("news_inventory", "news_count", "news_items", "news_status")),
        ("backtest_trust", ("backtest_trust", "backtest_trust_label", "backtest_validity")),
        ("portfolio_risk", ("portfolio_risk", "portfolio_risk_status", "portfolio_fit_label")),
    ):
        current_raw = _evidence_first(current, *aliases)
        current_value = _warning_marker(current_raw) if key == "warnings" else _dimension_marker(current_raw)
        previous_raw = _evidence_first(old or {}, *aliases)
        previous_value = None if old is None else (
            _warning_marker(previous_raw) if key == "warnings" else _dimension_marker(previous_raw)
        )
        complete = (
            old is not None
            and current_value != "unavailable"
            and previous_value not in (None, "unavailable")
        )
        changed = complete and current_value != previous_value
        statuses[key] = "changed" if changed else "unchanged" if complete else "unavailable"
        dimensions[key] = changed
        values[key] = (current_value, previous_value, changed)
    current_lineage = _lineage_marker(current)
    previous_lineage = None if old is None else _lineage_marker(old)
    lineage_complete = old is not None and "unavailable" not in (current_lineage, previous_lineage)
    dimensions["lineage"] = lineage_complete and current_lineage != previous_lineage
    statuses["lineage"] = "changed" if dimensions["lineage"] else "unchanged" if lineage_complete else "unavailable"
    values["lineage"] = (current_lineage, previous_lineage, dimensions["lineage"])
    upstream: dict[str, tuple[str, str | None, bool | None]] = {}
    for key, fields in UPSTREAM_CHANGE_FIELDS.items():
        identity = UPSTREAM_IDENTITY_FIELDS[key]
        if key == "portfolio_targets":
            current_value = _portfolio_target_marker(current)
            previous_value = None if old is None else _portfolio_target_marker(old)
        else:
            current_value = _composite_marker(current, fields, identity)
            previous_value = None if old is None else _composite_marker(old, fields, identity)
        # Only two recorded values can explain a change; a missing side
        # (legacy history or a removed instrument) is not evidence of one.
        complete = previous_value is not None and current_value != "unavailable" and previous_value != "unavailable"
        changed = complete and current_value != previous_value
        statuses[key] = "changed" if changed else "unchanged" if complete else "unavailable"
        dimensions[key] = changed
        upstream[key] = (current_value, previous_value, True if changed else False if complete else None)
    score_complete = old is not None and score_delta is not None
    dimensions["score"] = score_complete and score_delta != 0
    statuses["score"] = "changed" if dimensions["score"] else "unchanged" if score_complete else "unavailable"
    rank_complete = old is not None and rank_delta is not None
    dimensions["rank"] = rank_complete and rank_delta != 0
    statuses["rank"] = "changed" if dimensions["rank"] else "unchanged" if rank_complete else "unavailable"
    causal_root = Path(root) if root is not None else ROOT
    causal_paths, causal_status, causal_reason = _causal_paths_from_manifests(
        current_run_id, previous_run_id, causal_root
    )
    warnings_added, warnings_removed = (
        _warning_delta(values["warnings"][0], values["warnings"][1])
        if statuses["warnings"] == "changed"
        else ((), ())
    )
    news_delta = (
        _numeric_delta(_first(current, "news_inventory", "news_count", "news_items"), _first(old or {}, "news_inventory", "news_count", "news_items"))
        if statuses["news_inventory"] != "unavailable"
        else None
    )
    risk_delta = (
        _numeric_delta(_first(current, "portfolio_risk", "portfolio_risk_status", "portfolio_fit_score_10"), _first(old or {}, "portfolio_risk", "portfolio_risk_status", "portfolio_fit_score_10"))
        if statuses["portfolio_risk"] != "unavailable"
        else None
    )

    summary = _change_summary(score_delta, rank_delta, current_action, previous_action, values, old is not None, warnings_added, warnings_removed)
    upstream_labels = [key.replace("_", " ") for key, (_current, _previous, changed) in upstream.items() if changed is True]
    if upstream_labels:
        prefix = "" if summary == "No tracked changes." else summary.rstrip(".") + "; "
        summary = f"{prefix}upstream changed: {', '.join(upstream_labels)}."
    return RunChange(
        instrument_id=instrument_id,
        score_delta=score_delta,
        current_action=current_action,
        previous_action=previous_action,
        action_changed=action_changed,
        blocked_by_changed=dimensions["warnings"],
        score_rank_delta=rank_delta,
        current_rank=current_rank,
        previous_rank=previous_rank,
        warnings_changed=dimensions["warnings"],
        current_warnings=values["warnings"][0],
        previous_warnings=values["warnings"][1],
        warnings_added=warnings_added,
        warnings_removed=warnings_removed,
        freshness_changed=dimensions["freshness"],
        current_freshness=values["freshness"][0],
        previous_freshness=values["freshness"][1],
        model_availability_changed=dimensions["model_availability"],
        current_model_availability=values["model_availability"][0],
        previous_model_availability=values["model_availability"][1],
        forecast_changed=dimensions["forecasts"],
        current_forecast=values["forecasts"][0],
        previous_forecast=values["forecasts"][1],
        news_inventory_changed=dimensions["news_inventory"],
        current_news_inventory=values["news_inventory"][0],
        previous_news_inventory=values["news_inventory"][1],
        news_inventory_delta=news_delta,
        backtest_trust_changed=dimensions["backtest_trust"],
        current_backtest_trust=values["backtest_trust"][0],
        previous_backtest_trust=values["backtest_trust"][1],
        portfolio_risk_changed=dimensions["portfolio_risk"],
        current_portfolio_risk=values["portfolio_risk"][0],
        previous_portfolio_risk=values["portfolio_risk"][1],
        portfolio_risk_delta=risk_delta,
        lineage_changed=dimensions["lineage"],
        current_lineage=values["lineage"][0],
        previous_lineage=values["lineage"][1],
        dimension_changes=dimensions,
        summary=summary,
        upstream_changes=upstream,
        causal_paths=causal_paths,
        dimension_statuses=statuses,
        causal_paths_status=causal_status,
        causal_paths_reason=causal_reason,
    )


def _change_summary(
    score_delta: float | None,
    rank_delta: float | None,
    current_action: str,
    previous_action: str | None,
    values: Mapping[str, tuple[str, str | None, bool]],
    has_previous: bool,
    warnings_added: tuple[str, ...],
    warnings_removed: tuple[str, ...],
) -> str:
    if not has_previous:
        return f"No previous snapshot; current action is {current_action or 'unavailable'}."
    if current_action == "unavailable" and previous_action:
        return f"Instrument removed from current run; previous action was {previous_action}."
    fragments: list[str] = []
    if score_delta is not None and score_delta != 0:
        fragments.append(f"score {'increased' if score_delta > 0 else 'decreased'} by {abs(score_delta):.1f}")
    if rank_delta is not None and rank_delta != 0:
        fragments.append(f"rank {'improved' if rank_delta < 0 else 'fell'} by {abs(rank_delta):.0f}")
    labels = {
        "warnings": "warnings",
        "freshness": "freshness",
        "model_availability": "model availability",
        "forecasts": "forecasts",
        "news_inventory": "news inventory",
        "backtest_trust": "backtest trust",
        "portfolio_risk": "portfolio risk",
        "lineage": "lineage",
    }
    for key, label in labels.items():
        current, previous, changed = values[key]
        if changed:
            if key == "warnings" and (warnings_added or warnings_removed):
                warning_parts = []
                if warnings_added:
                    warning_parts.append("added " + ", ".join(warnings_added))
                if warnings_removed:
                    warning_parts.append("removed " + ", ".join(warnings_removed))
                fragments.append("warnings " + " and ".join(warning_parts))
            else:
                fragments.append(f"{label} changed from {previous or 'unavailable'} to {current}")
    if current_action != (previous_action or "") and current_action != "unavailable" and previous_action is not None:
        fragments.append(f"action changed from {previous_action or 'unavailable'} to {current_action or 'unavailable'}")
    return "; ".join(fragments) + "." if fragments else "No tracked changes."


def _report_summary(current: str, previous: str | None, changes: list[RunChange]) -> str:
    if not changes:
        return f"Run {current or 'unavailable'} has no comparable instrument rows."
    changed = sum(any(status == "changed" for status in change.dimension_statuses.values()) for change in changes)
    return f"Compared run {current or 'unavailable'} with {previous or 'no previous run'}: {changed} instrument(s) with tracked changes."


def _warning_delta(current: str, previous: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    def split(value: str | None) -> set[str]:
        if not value or value == "unavailable":
            return set()
        return {item.strip() for item in value.replace(",", "|").split("|") if item.strip()}

    current_set = split(current)
    previous_set = split(previous)
    return tuple(sorted(current_set - previous_set)), tuple(sorted(previous_set - current_set))


def _numeric_delta(current: Any, previous: Any) -> float | None:
    current_value = _float(current)
    previous_value = _float(previous)
    return None if current_value is None or previous_value is None else round(current_value - previous_value, 4)


def _safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=["run_id", "instrument_id"])
    result = frame.copy()
    # A malformed non-empty legacy frame can omit either identity column.  Add
    # aligned unavailable values so boolean selection remains index-safe and
    # comparison deterministically yields an empty report for named runs.
    for column in ("run_id", "instrument_id"):
        if column not in result.columns:
            result[column] = pd.Series("", index=result.index, dtype=object)
    return result


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            value = row[name]
            try:
                if bool(pd.isna(value)):
                    continue
            except (TypeError, ValueError):
                pass
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return None


def _evidence_first(row: Mapping[str, Any], *names: str) -> Any:
    """Read an explicitly stored scalar, preserving an intentional blank."""

    for name in names:
        if name not in row:
            continue
        value = row[name]
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _optional_text(value: Any) -> str | None:
    marker = _stable_marker(value)
    return None if marker == "unavailable" else marker


def _clean_text(value: Any) -> str:
    marker = _optional_text(value)
    return marker or ""


def _stable_marker(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        if bool(pd.isna(value)):
            return "unavailable"
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, tuple, set)):
        return "|".join(sorted(str(item).strip() for item in value if str(item).strip())) or "unavailable"
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    marker = str(value).strip()
    return "unavailable" if marker.casefold() in {"", "unavailable", "unknown", "not_evaluated", "legacy_unbound", "n/a", "na"} else marker


def _dimension_marker(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        if bool(pd.isna(value)):
            return "unavailable"
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        marker = value.strip()
        return "unavailable" if marker.casefold() in {"", "unavailable", "unknown", "not_evaluated", "legacy_unbound", "n/a", "na"} else marker
    return _stable_marker(value)


def _warning_marker(value: Any) -> str:
    # An explicitly stored blank warning list is valid evidence of no warnings.
    if isinstance(value, str) and not value.strip():
        return ""
    return _dimension_marker(value)


def _composite_marker(row: Mapping[str, Any], fields: tuple[str, ...], identity: tuple[str, ...]) -> str:
    """Join complete recorded values; missing fields keep the result unavailable."""

    markers = [(name, _dimension_marker(_evidence_first(row, name))) for name in fields]
    if any(value == "unavailable" for _name, value in markers):
        return "unavailable"
    return "|".join(f"{name}={value}" for name, value in markers)


def _portfolio_target_marker(row: Mapping[str, Any]) -> str:
    """Validate the run-owned raw snapshot and compare only target fields."""

    from etf_cockpit.governance.migrations import _snapshot_checksum, validated_portfolio_snapshot

    encoded = row.get("portfolio_snapshot_json")
    checksum = _first(row, "portfolio_snapshot_checksum")
    if not isinstance(encoded, str) or not encoded.strip() or not isinstance(checksum, str):
        return "unavailable"
    try:
        snapshot = json.loads(encoded, object_pairs_hook=_unique_json_object)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "unavailable"
    if not isinstance(snapshot, Mapping):
        return "unavailable"
    validated = validated_portfolio_snapshot({**row, "portfolio_snapshot": snapshot})
    if validated is None:
        return "unavailable"
    if "portfolio_snapshot_validated" in row and not _truthy_marker(row.get("portfolio_snapshot_validated")):
        return "unavailable"
    if _truthy_marker(row.get("portfolio_snapshot_conflicted")) or _truthy_marker(row.get("portfolio_snapshot_conflict")):
        return "unavailable"
    if str(checksum).strip().casefold() != _snapshot_checksum(validated).casefold():
        return "unavailable"
    targets = _target_subset(validated)
    if not targets:
        return "unavailable"
    return json.dumps(targets, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _truthy_marker(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1"}
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _target_subset(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key, value in snapshot.items():
        text = str(key).casefold()
        if "target" in text:
            selected[str(key)] = value
    return selected


def _raw_history_frame(root: Path | None) -> pd.DataFrame:
    if root is not None:
        path = Path(root) / "data" / "derived" / "score_history.parquet"
        try:
            if path.is_file():
                return pd.read_parquet(path)
        except Exception:  # noqa: BLE001 - comparison is informational
            pass
    return score_history_frame(root=root)


def run_completion_time(history: pd.DataFrame, run_id: str | None) -> pd.Timestamp | None:
    """Return one unambiguous timezone-aware UTC completion time for a run."""

    if not run_id or not isinstance(history, pd.DataFrame):
        return None
    if "run_id" not in history.columns or "run_completed_at" not in history.columns:
        return None
    rows = history.loc[history["run_id"].astype(str).eq(str(run_id)), "run_completed_at"]
    if rows.empty:
        return None
    raw_values: set[str] = set()
    instants: set[int] = set()
    parsed_values: list[pd.Timestamp] = []
    for value in rows:
        if value is None:
            return None
        raw_values.add(str(value).strip())
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        utc_value = parsed.tz_convert("UTC")
        instants.add(utc_value.value)
        parsed_values.append(utc_value)
    if len(raw_values) != 1 or len(instants) != 1:
        return None
    return parsed_values[0]


def select_comparison_runs(history: pd.DataFrame) -> tuple[str | None, str | None]:
    """Select latest complete runs using explicit timezone-aware UTC times."""

    if not isinstance(history, pd.DataFrame) or history.empty or "run_id" not in history.columns:
        return None, None
    valid: list[tuple[pd.Timestamp, str]] = []
    for run_id in dict.fromkeys(history["run_id"].astype(str).tolist()):
        completed = run_completion_time(history, run_id)
        if completed is not None:
            valid.append((completed, str(run_id)))
    valid.sort(key=lambda item: (item[0], item[1]))
    if not valid:
        return None, None
    return valid[-1][1], valid[-2][1] if len(valid) > 1 else None


def _causal_paths_from_manifests(
    current_run_id: str | None,
    previous_run_id: str | None,
    root: Path | None,
) -> tuple[tuple[str, ...], str, str | None]:
    if root is None or not current_run_id or not previous_run_id:
        return (), "unavailable", "run manifests are not available to the comparison"
    try:
        current = _load_manifest(current_run_id, root)
        previous = _load_manifest(previous_run_id, root)
    except ValueError as exc:
        return (), "unavailable", str(exc)
    current_deps = _dependency_map(current)
    previous_deps = _dependency_map(previous)
    changed_nodes = {
        artifact_id
        for artifact_id in set(current_deps) | set(previous_deps)
        if current_deps.get(artifact_id) != previous_deps.get(artifact_id)
    }
    current_edges, current_result, current_error = _manifest_edge_data(current)
    previous_edges, previous_result, previous_error = _manifest_edge_data(previous)
    if current_error or previous_error:
        return (), "unavailable", current_error or previous_error
    if current_result != previous_result:
        return (), "unavailable", "run manifests identify different result artifacts"
    paths = {
        " -> ".join(path)
        for artifact_id in changed_nodes
        for edges in (previous_edges, current_edges)
        if (path := _graph_path_to_result(artifact_id, edges, current_result)) is not None
    }
    return tuple(sorted(paths)), "available", None


def _load_manifest(run_id: str, root: Path) -> dict[str, Any]:
    from etf_cockpit.core.versioning import verify_run_manifest_signature

    path = Path(root) / "data" / "derived" / "run_manifests" / f"{run_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
    except (OSError, ValueError) as exc:
        raise ValueError("a run manifest is missing or unreadable") from exc
    if not isinstance(payload, dict) or not verify_run_manifest_signature(payload):
        raise ValueError("a run manifest is unsigned or has an invalid signature")
    if payload.get("run_id") != run_id or payload.get("schema_version") not in {"1.0", "1.1"}:
        raise ValueError("a run manifest has an invalid run identity or schema")
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("a run manifest has no dependency list")
    ids: list[str] = []
    for item in dependencies:
        if not isinstance(item, Mapping):
            raise ValueError("a run manifest contains an invalid dependency entry")
        artifact_id = item.get("artifact_id")
        version = item.get("version")
        content_hash = item.get("content_hash")
        if not all(isinstance(value, str) and value.strip() for value in (artifact_id, version, content_hash)):
            raise ValueError("a run manifest contains an incomplete dependency entry")
        ids.append(artifact_id)
    if len(ids) != len(set(ids)):
        raise ValueError("a run manifest contains duplicate artifact ids")
    return payload


def _dependency_map(payload: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {
        str(item["artifact_id"]): (item.get("version"), item.get("content_hash"))
        for item in payload.get("dependencies", [])
        if isinstance(item, Mapping) and item.get("artifact_id")
    }


def _manifest_edge_data(manifest: Mapping[str, Any]) -> tuple[tuple[tuple[str, str], ...], str | None, str | None]:
    graph = manifest.get("dependency_graph")
    raw_edges = manifest.get("dependency_edges")
    result_artifact = manifest.get("result_artifact_id")
    if raw_edges is None and isinstance(graph, Mapping):
        raw_edges = graph.get("edges")
        result_artifact = result_artifact or graph.get("result_artifact_id")
    if not isinstance(raw_edges, list):
        return (), None, "a run manifest lacks dependency edge data"
    edges: list[tuple[str, str]] = []
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            return (), None, "a run manifest has invalid dependency edge data"
        source = edge.get("from")
        target = edge.get("to")
        if not all(isinstance(value, str) and value.strip() for value in (source, target)) or source == target:
            return (), None, "a run manifest has invalid dependency edge data"
        pair = (source, target)
        if pair in edges:
            return (), None, "a run manifest has duplicate dependency edges"
        edges.append(pair)
    if not isinstance(result_artifact, str) or not result_artifact.strip():
        sources = {source for source, _target in edges}
        targets = {target for _source, target in edges}
        terminals = sorted(targets - sources)
        preferred = [item for item in terminals if any(token in item.casefold() for token in ("score", "result", "action"))]
        result_artifact = preferred[0] if len(preferred) == 1 else terminals[0] if len(terminals) == 1 else None
    if result_artifact is None:
        return (), None, "a run manifest lacks a result artifact id"
    if not any(result_artifact in edge for edge in edges):
        return (), None, "a run manifest dependency graph does not include its result artifact"
    return tuple(edges), result_artifact, None


def _graph_path_to_result(
    start: str,
    edges: tuple[tuple[str, str], ...],
    result_artifact: str | None,
) -> tuple[str, ...] | None:
    if result_artifact is None:
        return None
    downstream: dict[str, list[str]] = {}
    for source, target in edges:
        downstream.setdefault(source, []).append(target)
    for children in downstream.values():
        children.sort()
    queue: list[tuple[str, ...]] = [(start,)]
    visited = {start}
    while queue:
        path = queue.pop(0)
        if path[-1] == result_artifact:
            return path if len(path) > 1 else None
        for child in downstream.get(path[-1], ()):
            if child not in visited:
                visited.add(child)
                queue.append((*path, child))
    return None


def _lineage_marker(row: Mapping[str, Any]) -> str:
    fields = (
        "version_registry_signature",
        "dependency_graph_hash",
        "formula_version",
        "formula_checksum",
        "source_vintage_hash",
    )
    markers = [(field, _dimension_marker(_evidence_first(row, field))) for field in fields]
    if any(value == "unavailable" for _field, value in markers):
        return "unavailable"
    return "|".join(f"{field}={value}" for field, value in markers)


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) and number not in (float("inf"), float("-inf")) else None
