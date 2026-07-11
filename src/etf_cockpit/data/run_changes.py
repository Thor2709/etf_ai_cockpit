from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RunChange:
    instrument_id: str
    score_delta: float | None
    current_action: str
    previous_action: str | None
    action_changed: bool
    blocked_by_changed: bool


@dataclass(frozen=True)
class RunChangeReport:
    current_run_id: str
    previous_run_id: str | None
    changes: tuple[RunChange, ...]


def compare_runs(history: pd.DataFrame, current_run_id: str, previous_run_id: str | None) -> RunChangeReport:
    current = history[history.get("run_id", pd.Series(dtype=str)).astype(str) == current_run_id]
    previous = history[history.get("run_id", pd.Series(dtype=str)).astype(str) == previous_run_id] if previous_run_id else pd.DataFrame()
    previous_by_id = {str(row.instrument_id): row for row in previous.itertuples(index=False)}
    changes: list[RunChange] = []
    for row in current.itertuples(index=False):
        instrument_id = str(getattr(row, "instrument_id", ""))
        old = previous_by_id.get(instrument_id)
        current_score = _float(getattr(row, "final_combined_score_10", None))
        old_score = _float(getattr(old, "final_combined_score_10", None)) if old else None
        changes.append(RunChange(instrument_id, None if old_score is None or current_score is None else round(current_score - old_score, 4), str(getattr(row, "final_action", "")), None if old is None else str(getattr(old, "final_action", "")), old is not None and str(getattr(row, "final_action", "")) != str(getattr(old, "final_action", "")), old is not None and str(getattr(row, "blocked_by", "")) != str(getattr(old, "blocked_by", ""))))
    return RunChangeReport(current_run_id, previous_run_id, tuple(changes))


def _float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
