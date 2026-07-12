from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from etf_cockpit.signals.research_states import (
    PortfolioReviewState,
    ResearchState,
    research_state_for_legacy_action,
)


@dataclass(frozen=True)
class ScoreHistoryWriteResult:
    path: Path
    rows_written: int
    run_id: str
    snapshot_hash: str
    schema_version: str = "2.0"


_COLUMNS = [
    "run_id",
    "run_completed_at",
    "instrument_id",
    "final_combined_score_10",
    "research_state",
    "portfolio_review_state",
    "analysis_status",
    "research_promotion_allowed",
    "portfolio_review_allowed",
    "execution_allowed",
    "legacy_action",
    "migration_version",
    "gate_policy_version",
    "gate_policy_checksum",
    "schema_version",
    "blocked_by",
    "snapshot_hash",
]
LEGACY_COLUMNS = ["run_id", "run_completed_at", "instrument_id", "final_combined_score_10", "final_action", "blocked_by", "snapshot_hash"]


def append_score_run(scores: pd.DataFrame, run_id: str, created_at: str, *, root: Path) -> ScoreHistoryWriteResult:
    path = root / "data" / "derived" / "score_history.parquet"
    frame = scores.copy()
    if "instrument_id" not in frame.columns or "final_combined_score_10" not in frame.columns:
        raise ValueError("score history requires instrument_id and final_combined_score_10")
    frame["final_combined_score_10"] = pd.to_numeric(frame["final_combined_score_10"], errors="coerce")
    frame = frame.dropna(subset=["instrument_id", "final_combined_score_10"])
    frame["run_id"] = run_id
    frame["run_completed_at"] = created_at
    if "legacy_action" not in frame.columns:
        frame["legacy_action"] = frame.get("final_action", "")
    frame["legacy_action"] = frame["legacy_action"].map(lambda value: None if pd.isna(value) else str(value).strip() or None)
    frame["research_state"] = frame.apply(
        lambda row: _state_for_row(row), axis=1
    )
    frame["portfolio_review_state"] = frame.get("portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE.value)
    frame["portfolio_review_state"] = frame["portfolio_review_state"].map(_safe_portfolio_state)
    frame["analysis_status"] = frame.apply(lambda row: _analysis_status_for_row(row), axis=1)
    frame["research_promotion_allowed"] = False
    frame["portfolio_review_allowed"] = frame["portfolio_review_state"].ne(PortfolioReviewState.NOT_APPLICABLE.value)
    frame["execution_allowed"] = False
    frame["migration_version"] = frame.get("migration_version", "2.0")
    frame["gate_policy_version"] = frame.get("gate_policy_version", "unavailable")
    frame["gate_policy_checksum"] = frame.get("gate_policy_checksum", "unavailable")
    frame["schema_version"] = "2.0"
    if "blocked_by" not in frame.columns:
        frame["blocked_by"] = ""
    snapshot_hash = hashlib.sha256(frame.sort_values("instrument_id").to_json().encode()).hexdigest()
    frame["snapshot_hash"] = snapshot_hash
    frame = frame[_COLUMNS]
    existing = _normalise_history_frame(pd.read_parquet(path)) if path.exists() else pd.DataFrame(columns=_COLUMNS)
    duplicate = existing[(existing.get("run_id", "") == run_id) & (existing.get("snapshot_hash", "") == snapshot_hash)] if not existing.empty else pd.DataFrame()
    if not duplicate.empty:
        return ScoreHistoryWriteResult(path, 0, run_id, snapshot_hash)
    combined = pd.concat([existing, frame], ignore_index=True).reindex(columns=_COLUMNS).drop_duplicates(subset=["run_id", "instrument_id"], keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return ScoreHistoryWriteResult(path, len(frame), run_id, snapshot_hash)


def score_history_frame(*, root: Path) -> pd.DataFrame:
    path = root / "data" / "derived" / "score_history.parquet"
    if not path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    try:
        frame = _normalise_history_frame(pd.read_parquet(path))
    except Exception:
        return pd.DataFrame(columns=_COLUMNS)
    return frame.reindex(columns=_COLUMNS).copy()


def score_history_v2_payload(row: object) -> dict[str, object]:
    """Serialise a score/history row without ``action`` or ``final_action``."""

    if isinstance(row, pd.Series):
        values = row.to_dict()
    elif isinstance(row, dict):
        values = dict(row)
    else:
        values = {column: getattr(row, column, None) for column in _COLUMNS}
    legacy = values.get("legacy_action", values.get("final_action"))
    state = values.get("research_state") or research_state_for_legacy_action(legacy).value
    portfolio_state = values.get("portfolio_review_state") or PortfolioReviewState.NOT_APPLICABLE.value
    return {
        "research_state": ResearchState(str(state)).value if str(state) in {item.value for item in ResearchState} else ResearchState.MANUAL_REVIEW.value,
        "portfolio_review_state": _safe_portfolio_state(portfolio_state),
        "analysis_status": _analysis_status_for_row(values),
        "research_promotion_allowed": False,
        "portfolio_review_allowed": _safe_portfolio_state(portfolio_state) != PortfolioReviewState.NOT_APPLICABLE.value,
        "execution_allowed": False,
        "legacy_action": None if legacy is None or (isinstance(legacy, float) and pd.isna(legacy)) else str(legacy).strip() or None,
        "migration_version": str(values.get("migration_version") or "2.0"),
        "gate_policy_version": str(values.get("gate_policy_version") or "unavailable"),
        "gate_policy_checksum": str(values.get("gate_policy_checksum") or "unavailable"),
        "schema_version": "2.0",
    }


def append_score_run_v2(scores: pd.DataFrame, run_id: str, created_at: str, *, root: Path) -> ScoreHistoryWriteResult:
    """Explicit v2 name for callers migrating away from the legacy API."""

    return append_score_run(scores, run_id, created_at, root=root)


def _state_for_row(row: object) -> str:
    values = row.to_dict() if isinstance(row, pd.Series) else row
    if isinstance(values, dict) and values.get("research_state"):
        try:
            return ResearchState(str(values["research_state"])).value
        except ValueError:
            pass
    legacy = values.get("legacy_action") if isinstance(values, dict) else None
    if legacy is None and isinstance(values, dict):
        legacy = values.get("final_action")
    return research_state_for_legacy_action(legacy).value


def _safe_portfolio_state(value: object) -> str:
    try:
        return PortfolioReviewState(str(value)).value
    except ValueError:
        return PortfolioReviewState.NOT_APPLICABLE.value


def _analysis_status_for_row(row: object) -> Literal["complete", "partial", "unavailable"]:
    values = row.to_dict() if isinstance(row, pd.Series) else row
    candidate = values.get("analysis_status") if isinstance(values, dict) else None
    if str(candidate or "").casefold() in {"complete", "partial", "unavailable"}:
        return str(candidate).casefold()  # type: ignore[return-value]
    if isinstance(values, dict) and values.get("research_state"):
        return "partial"
    return "partial" if isinstance(values, dict) and values.get("legacy_action", values.get("final_action")) else "unavailable"


def _normalise_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=_COLUMNS)
    result = frame.copy()
    if "legacy_action" not in result.columns:
        result["legacy_action"] = result.get("final_action", None)
    if "research_state" not in result.columns:
        result["research_state"] = result.apply(_state_for_row, axis=1)
    else:
        result["research_state"] = result["research_state"].map(lambda value: _state_for_row({"research_state": value}))
    if "portfolio_review_state" not in result.columns:
        result["portfolio_review_state"] = PortfolioReviewState.NOT_APPLICABLE.value
    result["portfolio_review_state"] = result["portfolio_review_state"].map(_safe_portfolio_state)
    if "analysis_status" not in result.columns:
        result["analysis_status"] = result.apply(_analysis_status_for_row, axis=1)
    result["research_promotion_allowed"] = False
    result["portfolio_review_allowed"] = result["portfolio_review_state"].ne(PortfolioReviewState.NOT_APPLICABLE.value)
    result["execution_allowed"] = False
    for column, default in (
        ("migration_version", "2.0"),
        ("gate_policy_version", "unavailable"),
        ("gate_policy_checksum", "unavailable"),
        ("schema_version", "2.0"),
        ("blocked_by", ""),
        ("snapshot_hash", ""),
    ):
        if column not in result.columns:
            result[column] = default
    return result.reindex(columns=_COLUMNS)
