from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, wait_for_atomic_group
from etf_cockpit.governance.migrations import _snapshot_checksum, validated_portfolio_snapshot
from etf_cockpit.core.paths import ROOT
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
    "run_started_at",
    "run_completed_at",
    "instrument_id",
    "display_name",
    "yahoo_ticker",
    "asset_type",
    "analysis_tier",
    "source_group",
    "data_as_of_date",
    "price_as_of_date",
    "evidence_score_10",
    "evidence_quality_10",
    "risk_friction_10",
    "final_combined_score_10",
    # Comparison dimensions are retained as informational snapshots.  They
    # deliberately do not participate in current action or authority gates.
    "rank",
    "score_rank",
    "warnings",
    "freshness_status",
    "model_available",
    "model_availability",
    "forecast_status",
    "news_inventory",
    "backtest_trust",
    "portfolio_risk",
    "final_action",
    "final_label",
    "reason_short",
    "reason_full",
    "research_state",
    "portfolio_review_state",
    "portfolio_snapshot_validated",
    "portfolio_snapshot_provenance",
    "portfolio_snapshot_json",
    "portfolio_snapshot_checksum",
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
    "source_snapshot_hash",
    "score_schema_version",
    "snapshot_hash",
]
LEGACY_COLUMNS = ["run_id", "run_completed_at", "instrument_id", "final_combined_score_10", "final_action", "blocked_by", "snapshot_hash"]


def _clean_optional_text(value: object) -> str | None:
    """Convert scalar/legacy null values to a stable text representation."""

    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item).strip() for item in value if str(item).strip()) or None
    text = str(value).strip()
    return text or None


def _model_value_is_real(value: object) -> bool:
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip().casefold()
    return bool(text) and text not in {
        "none",
        "null",
        "nan",
        "unavailable",
        "pending",
        "pending refresh",
        "false",
    }


def _row_has_real_model(values: dict[str, object]) -> bool:
    versions = values.get("model_versions_used")
    if isinstance(versions, dict):
        return any(_model_value_is_real(version) for version in versions.values())
    for key in ("model_version", "model_id", "model_name"):
        if _model_value_is_real(values.get(key)):
            return True
    if values.get("model_row_exists") is True:
        return True
    availability = values.get("model_availability")
    if _model_value_is_real(availability) and str(availability).casefold() not in {"false", "not_available"}:
        return True
    label = str(values.get("model_authority_label") or "").strip().casefold()
    if "pending" in label or "unavailable" in label:
        return False
    # A positive boolean without a model row/version is not evidence.  This
    # avoids promoting configured/candidate placeholders by metadata alone.
    return False


def _normalise_model_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    normalised: list[tuple[bool, str]] = []
    for _, row in result.iterrows():
        values = row.to_dict()
        available = _row_has_real_model(values)
        supplied = _clean_optional_text(values.get("model_availability"))
        label = _clean_optional_text(values.get("model_authority_label"))
        normalised.append((available, (supplied or label or "available") if available else "unavailable"))
    result["model_available"] = [item[0] for item in normalised]
    result["model_availability"] = [item[1] for item in normalised]
    return result


def append_score_run(
    scores: pd.DataFrame,
    run_id: str,
    created_at: str,
    *,
    root: Path | None = None,
) -> ScoreHistoryWriteResult:
    """Append one deterministic score snapshot, replacing only a changed run.

    ``root`` remains injectable for tests and migrations; production callers
    default to the configured project root.  A history row is informational
    and is always written with ``execution_allowed=False``.
    """

    root = Path(root) if root is not None else ROOT
    path = root / "data" / "derived" / "score_history.parquet"
    frame = scores.copy()
    # An explicitly supplied empty frame is a valid complete run snapshot.  A
    # caller-provided run_id is the durable identity for that zero-instrument
    # snapshot; no rows from any other run may be touched.
    if frame.empty:
        for column in ("instrument_id", "final_combined_score_10"):
            if column not in frame.columns:
                frame[column] = pd.Series(dtype=object)
    if "instrument_id" not in frame.columns or "final_combined_score_10" not in frame.columns:
        raise ValueError("score history requires instrument_id and final_combined_score_10")
    frame["final_combined_score_10"] = pd.to_numeric(frame["final_combined_score_10"], errors="coerce")
    frame = frame.dropna(subset=["instrument_id", "final_combined_score_10"])
    frame["run_id"] = run_id
    frame["run_started_at"] = created_at
    frame["run_completed_at"] = created_at
    if "legacy_action" not in frame.columns:
        frame["legacy_action"] = frame.get("final_action", "")
    frame["legacy_action"] = frame["legacy_action"].map(_clean_optional_text)
    if "final_action" not in frame.columns:
        frame["final_action"] = frame["legacy_action"]
    frame["research_state"] = frame.apply(
        lambda row: _state_for_row(row), axis=1
    )
    frame["portfolio_snapshot_json"] = frame.apply(_snapshot_json_for_row, axis=1)
    frame["portfolio_snapshot_checksum"] = frame.apply(_snapshot_checksum_for_row, axis=1)
    frame["portfolio_snapshot_validated"] = frame.apply(_snapshot_context_for_row, axis=1)
    frame["portfolio_snapshot_provenance"] = frame["portfolio_snapshot_validated"].map(
        lambda value: "validated_snapshot" if value is True else "unavailable"
    )
    frame["portfolio_review_state"] = frame.get("portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE.value)
    frame["portfolio_review_state"] = frame.apply(_portfolio_state_for_row, axis=1)
    frame["analysis_status"] = frame.apply(lambda row: _analysis_status_for_row(row), axis=1)
    frame["research_promotion_allowed"] = False
    frame["portfolio_review_allowed"] = frame["portfolio_snapshot_validated"] & frame["portfolio_review_state"].ne(
        PortfolioReviewState.NOT_APPLICABLE.value
    )
    frame["execution_allowed"] = False
    frame["migration_version"] = frame.get("migration_version", "2.0")
    frame["gate_policy_version"] = frame.get("gate_policy_version", "unavailable")
    frame["gate_policy_checksum"] = frame.get("gate_policy_checksum", "unavailable")
    frame["schema_version"] = "2.0"
    if "blocked_by" not in frame.columns:
        frame["blocked_by"] = ""
    if "warnings" not in frame.columns:
        frame["warnings"] = frame["blocked_by"]
    for column, default in (
        ("display_name", ""),
        ("yahoo_ticker", ""),
        ("asset_type", ""),
        ("analysis_tier", ""),
        ("source_group", ""),
        ("data_as_of_date", ""),
        ("price_as_of_date", ""),
        ("evidence_score_10", None),
        ("evidence_quality_10", None),
        ("risk_friction_10", None),
        ("rank", None),
        ("score_rank", None),
        ("freshness_status", "unknown"),
        ("model_available", None),
        ("model_availability", None),
        ("forecast_status", "unavailable"),
        ("news_inventory", None),
        ("backtest_trust", "not_evaluated"),
        ("portfolio_risk", "not_evaluated"),
        ("final_label", ""),
        ("reason_short", ""),
        ("reason_full", ""),
        ("source_snapshot_hash", ""),
        ("score_schema_version", "2.0"),
    ):
        if column not in frame.columns:
            frame[column] = default
    frame = _normalise_model_columns(frame)
    # Hash only canonical content, not the row ordering, so retries are
    # idempotent while a changed snapshot for the same run is replaced.
    hash_frame = frame.sort_values(["instrument_id", "run_id"], kind="stable").reindex(
        sorted(frame.columns), axis=1
    )
    snapshot_hash = hashlib.sha256(
        hash_frame.to_json(orient="records", date_format="iso", default_handler=str).encode("utf-8")
    ).hexdigest()
    frame["snapshot_hash"] = snapshot_hash
    frame = frame[_COLUMNS]
    existing = _read_history_raw(path)
    duplicate = (
        existing.loc[
            existing["run_id"].astype(str).eq(str(run_id))
            & existing["snapshot_hash"].astype(str).eq(snapshot_hash)
        ]
        if not existing.empty
        else pd.DataFrame()
    )
    if not duplicate.empty:
        return ScoreHistoryWriteResult(path, 0, run_id, snapshot_hash)
    # A changed hash replaces the complete run snapshot, preventing stale
    # instruments from surviving a deterministic retry with a narrower frame.
    if not existing.empty and "run_id" in existing.columns:
        existing = existing.loc[~existing["run_id"].astype(str).eq(str(run_id))]
    combined = (
        frame.copy().reindex(columns=_COLUMNS)
        if existing.empty
        else pd.concat([existing, frame], ignore_index=True, sort=False).reindex(columns=_COLUMNS)
    )
    combined = combined.drop_duplicates(subset=["run_id", "instrument_id"], keep="last")
    # Keep parquet and the legacy CSV mirror within one repository atomic
    # write-group.  Readers never observe one format from a newer generation
    # than the other, and injected publication failures roll back both.
    _write_history_group(combined, path)
    return ScoreHistoryWriteResult(path, len(frame), run_id, snapshot_hash)


def score_history_frame(*, root: Path | None = None) -> pd.DataFrame:
    root = Path(root) if root is not None else ROOT
    path = root / "data" / "derived" / "score_history.parquet"
    if not path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    try:
        frame = _normalise_history_frame(pd.read_parquet(path))
    except Exception:
        return pd.DataFrame(columns=_COLUMNS)
    return frame.reindex(columns=_COLUMNS).copy()


def _read_history_raw(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    try:
        wait_for_atomic_group(path)
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=_COLUMNS)


def _write_history_group(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet_buffer = BytesIO()
    frame.to_parquet(parquet_buffer, index=False)
    csv_path = path.with_suffix(".csv")

    def validate_parquet(candidate: Path) -> None:
        pd.read_parquet(candidate)

    def validate_csv(candidate: Path) -> None:
        pd.read_csv(candidate)

    atomic_write_group(
        (
            AtomicWriteRequest(path, parquet_buffer.getvalue(), validate_parquet),
            AtomicWriteRequest(csv_path, frame.to_csv(index=False).encode("utf-8"), validate_csv),
        )
    )


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
    portfolio_state = _portfolio_state_for_row(values)
    snapshot_validated = _snapshot_context_for_row(values)
    snapshot = validated_portfolio_snapshot(values) if snapshot_validated else None
    snapshot_checksum = _snapshot_checksum(snapshot) if snapshot is not None else "unavailable"
    return {
        "research_state": ResearchState(str(state)).value if str(state) in {item.value for item in ResearchState} else ResearchState.MANUAL_REVIEW.value,
        "portfolio_review_state": _safe_portfolio_state(portfolio_state),
        "analysis_status": _analysis_status_for_row(values),
        "research_promotion_allowed": False,
        "portfolio_snapshot_validated": snapshot_validated,
        "portfolio_snapshot_provenance": "validated_snapshot" if snapshot_validated else "unavailable",
        "portfolio_snapshot": dict(snapshot) if snapshot is not None else None,
        "portfolio_snapshot_checksum": snapshot_checksum,
        "portfolio_review_allowed": snapshot_validated
        and _safe_portfolio_state(portfolio_state) != PortfolioReviewState.NOT_APPLICABLE.value,
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


def _values_for_row(row: object) -> dict[str, object]:
    if isinstance(row, pd.Series):
        return row.to_dict()
    if isinstance(row, dict):
        return dict(row)
    return {column: getattr(row, column, None) for column in _COLUMNS}


def _snapshot_context_for_row(row: object) -> bool:
    values = _values_for_row(row)
    snapshot = validated_portfolio_snapshot(values)
    if snapshot is None:
        # A marker without the retained source object is not evidence.
        return False
    expected_checksum = _snapshot_checksum(snapshot)
    supplied_checksum = str(values.get("portfolio_snapshot_checksum") or "").strip().casefold()
    if supplied_checksum not in {"", "unavailable", expected_checksum}:
        return False
    # The marker/provenance flags are diagnostic metadata only.  Source
    # evidence is accepted when it validates and its optional checksum agrees;
    # caller-supplied positive flags cannot create context by themselves.
    return True


def _snapshot_json_for_row(row: object) -> str | None:
    snapshot = validated_portfolio_snapshot(_values_for_row(row))
    if snapshot is None:
        return None
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _snapshot_checksum_for_row(row: object) -> str:
    snapshot = validated_portfolio_snapshot(_values_for_row(row))
    return _snapshot_checksum(snapshot) if snapshot is not None else "unavailable"


def _portfolio_state_for_row(row: object) -> str:
    values = _values_for_row(row)
    snapshot = None
    try:
        snapshot = validated_portfolio_snapshot(values)
    except (TypeError, ValueError):
        snapshot = None
    if snapshot is not None:
        value = snapshot.get("portfolio_review_state", snapshot.get("review_state", snapshot.get("state")))
        if value is None:
            return PortfolioReviewState.MAINTAIN_REVIEW.value
        return _safe_portfolio_state(value)
    return _safe_portfolio_state(values.get("portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE.value))


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
    # Old stores may contain only a subset of columns or malformed rows.  Add
    # compatibility defaults first, then validate the key identity/score.
    if "final_combined_score_10" not in result.columns:
        result["final_combined_score_10"] = None
    result["final_combined_score_10"] = pd.to_numeric(result["final_combined_score_10"], errors="coerce")
    if "instrument_id" not in result.columns:
        result["instrument_id"] = None
    result["instrument_id"] = result["instrument_id"].map(_clean_optional_text)
    result = result.loc[result["instrument_id"].notna() & result["final_combined_score_10"].notna()].copy()
    if result.empty:
        return pd.DataFrame(columns=_COLUMNS)
    if "run_id" not in result.columns:
        result["run_id"] = ""
    result["run_id"] = result["run_id"].map(lambda value: _clean_optional_text(value) or "")
    if "legacy_action" not in result.columns:
        result["legacy_action"] = result.get("final_action", None)
    result["legacy_action"] = result["legacy_action"].map(_clean_optional_text)
    if "research_state" not in result.columns:
        result["research_state"] = result.apply(_state_for_row, axis=1)
    else:
        result["research_state"] = result["research_state"].map(lambda value: _state_for_row({"research_state": value}))
    if "portfolio_review_state" not in result.columns:
        result["portfolio_review_state"] = PortfolioReviewState.NOT_APPLICABLE.value
    result["portfolio_snapshot_json"] = result.apply(_snapshot_json_for_row, axis=1)
    result["portfolio_snapshot_checksum"] = result.apply(_snapshot_checksum_for_row, axis=1)
    result["portfolio_snapshot_validated"] = result.apply(_snapshot_context_for_row, axis=1)
    result["portfolio_snapshot_provenance"] = result["portfolio_snapshot_validated"].map(
        lambda value: "validated_snapshot" if value is True else "unavailable"
    )
    result["portfolio_review_state"] = result.apply(_portfolio_state_for_row, axis=1)
    if "analysis_status" not in result.columns:
        result["analysis_status"] = result.apply(_analysis_status_for_row, axis=1)
    result["research_promotion_allowed"] = False
    result["portfolio_review_allowed"] = result["portfolio_snapshot_validated"] & result["portfolio_review_state"].ne(
        PortfolioReviewState.NOT_APPLICABLE.value
    )
    result["execution_allowed"] = False
    for column, default in (
        ("run_started_at", ""),
        ("run_completed_at", ""),
        ("display_name", ""),
        ("yahoo_ticker", ""),
        ("asset_type", ""),
        ("analysis_tier", ""),
        ("source_group", ""),
        ("data_as_of_date", ""),
        ("price_as_of_date", ""),
        ("evidence_score_10", None),
        ("evidence_quality_10", None),
        ("risk_friction_10", None),
        ("final_action", None),
        ("rank", None),
        ("score_rank", None),
        ("warnings", None),
        ("freshness_status", "unknown"),
        ("model_available", None),
        ("model_availability", None),
        ("forecast_status", "unavailable"),
        ("news_inventory", None),
        ("backtest_trust", "not_evaluated"),
        ("portfolio_risk", "not_evaluated"),
        ("final_label", ""),
        ("reason_short", ""),
        ("reason_full", ""),
        ("source_snapshot_hash", ""),
        ("score_schema_version", "2.0"),
        ("migration_version", "2.0"),
        ("gate_policy_version", "unavailable"),
        ("gate_policy_checksum", "unavailable"),
        ("schema_version", "2.0"),
        ("blocked_by", ""),
        ("snapshot_hash", ""),
    ):
        if column not in result.columns:
            result[column] = default
    # Preserve warnings under both the modern comparison name and the legacy
    # blocked_by field without allowing either to become action authority.
    if "warnings" in result.columns:
        result["warnings"] = result["warnings"].map(_clean_optional_text)
        result["blocked_by"] = result["blocked_by"].where(
            result["blocked_by"].map(_clean_optional_text).notna(), result["warnings"]
        )
    result["final_action"] = result["final_action"].map(_clean_optional_text)
    result["execution_allowed"] = False
    return result.reindex(columns=_COLUMNS)
