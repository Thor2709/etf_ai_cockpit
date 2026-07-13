from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

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
)


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
    dimension_changes: Mapping[str, bool] = field(default_factory=dict)
    summary: str = ""

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
        frame = score_history_frame(root=root)
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
        changes.append(_change_for(instrument_id, row, old))
    changes.sort(key=lambda change: change.instrument_id)
    report_summary = _report_summary(current, previous, changes)
    return RunChangeReport(current, previous, tuple(changes), summary=report_summary)


def _change_for(instrument_id: str, current: Mapping[str, Any], old: Mapping[str, Any] | None) -> RunChange:
    current_score = _float(_first(current, "final_combined_score_10", "score_10", "score"))
    previous_score = _float(_first(old or {}, "final_combined_score_10", "score_10", "score"))
    score_delta = None if current_score is None or previous_score is None else round(current_score - previous_score, 4)
    current_rank = _float(_first(current, "score_rank", "rank", "current_rank"))
    previous_rank = _float(_first(old or {}, "score_rank", "rank", "previous_rank"))
    rank_delta = None if current_rank is None or previous_rank is None else current_rank - previous_rank

    current_action = _clean_text(_first(current, "final_action", "legacy_action", "action")) or "unavailable"
    previous_action = _optional_text(_first(old or {}, "final_action", "legacy_action", "action"))
    dimensions: dict[str, bool] = {}
    values: dict[str, tuple[str, str | None, bool]] = {}
    for key, aliases in (
        ("warnings", ("warnings", "blocked_by", "warning_flags")),
        ("freshness", ("freshness_status", "data_freshness", "price_freshness")),
        ("model_availability", ("model_available", "model_availability", "model_status", "model_authority_label")),
        ("forecasts", ("forecast_status", "forecast_available", "forecasts", "forecast")),
        ("news_inventory", ("news_inventory", "news_count", "news_items", "news_status")),
        ("backtest_trust", ("backtest_trust", "backtest_trust_label", "backtest_validity")),
        ("portfolio_risk", ("portfolio_risk", "portfolio_risk_status", "portfolio_fit_label")),
    ):
        current_value = _stable_marker(_first(current, *aliases))
        previous_raw = _first(old or {}, *aliases)
        previous_value = None if old is None else _stable_marker(previous_raw)
        changed = old is not None and current_value != previous_value
        dimensions[key] = changed
        values[key] = (current_value, previous_value, changed)
    dimensions["score"] = old is not None and score_delta not in (None, 0)
    dimensions["rank"] = old is not None and rank_delta not in (None, 0)
    warnings_added, warnings_removed = _warning_delta(values["warnings"][0], values["warnings"][1])
    news_delta = _numeric_delta(_first(current, "news_inventory", "news_count", "news_items"), _first(old or {}, "news_inventory", "news_count", "news_items"))
    risk_delta = _numeric_delta(_first(current, "portfolio_risk", "portfolio_risk_status", "portfolio_fit_score_10"), _first(old or {}, "portfolio_risk", "portfolio_risk_status", "portfolio_fit_score_10"))

    summary = _change_summary(score_delta, rank_delta, current_action, previous_action, values, old is not None, warnings_added, warnings_removed)
    return RunChange(
        instrument_id=instrument_id,
        score_delta=score_delta,
        current_action=current_action,
        previous_action=previous_action,
        action_changed=old is not None and current_action != (previous_action or ""),
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
        dimension_changes=dimensions,
        summary=summary,
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
    if current_action != (previous_action or ""):
        fragments.append(f"action changed from {previous_action or 'unavailable'} to {current_action or 'unavailable'}")
    return "; ".join(fragments) + "." if fragments else "No tracked changes."


def _report_summary(current: str, previous: str | None, changes: list[RunChange]) -> str:
    if not changes:
        return f"Run {current or 'unavailable'} has no comparable instrument rows."
    changed = sum(bool(change.summary and change.summary != "No tracked changes.") for change in changes)
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
    return str(value).strip() or "unavailable"


def _float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number
