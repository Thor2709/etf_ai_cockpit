"""Opportunity assessment, rank routing, score-metric history and screen-row read models (application; ADR-0002)."""

from collections.abc import Mapping
import json
from pathlib import Path
import pandas as pd

from etf_cockpit.core.paths import LOG_DIR
from etf_cockpit.application.screening_data import build_screen_rows as _build_screen_rows_v3


def load_opportunity_assessment(
    instrument_id: str,
    *,
    decision_time: object = None,
    run_id: str | None = None,
    artifact_directory: Path | None = None,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> dict[str, object]:
    """Read the latest valid local opportunity result without recalculation."""

    instrument = str(instrument_id or "").strip()
    unavailable = {
        "status": "unavailable",
        "instrument": instrument,
        "reason_code": "opportunity_result_unavailable",
        "execution_allowed": False,
    }
    if not instrument:
        return unavailable | {"reason_code": "instrument_id_unavailable"}
    root = Path(artifact_directory or LOG_DIR)
    cutoff = None
    if decision_time is not None:
        try:
            cutoff = pd.Timestamp(decision_time)
            if cutoff.tzinfo is None:
                cutoff = cutoff.tz_localize("UTC")
            else:
                cutoff = cutoff.tz_convert("UTC")
            if len(str(decision_time).strip()) == 10:
                cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        except (TypeError, ValueError, OverflowError):
            return unavailable | {"reason_code": "decision_time_invalid"}
    records: list[tuple[pd.Timestamp, str, dict[str, object]]] = []
    try:
        paths = sorted(root.glob("decision_opportunity_*.json"))
    except OSError:
        return unavailable
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or payload.get("artifact_version") != "decision-opportunity-shadow-v1"
            or payload.get("execution_allowed") is not False
            or (run_id is not None and str(payload.get("run_id")) != run_id)
        ):
            continue
        try:
            timestamp = pd.Timestamp(payload.get("decision_time"))
            if timestamp.tzinfo is None:
                continue
            timestamp = timestamp.tz_convert("UTC")
        except (TypeError, ValueError, OverflowError):
            continue
        if cutoff is not None and timestamp > cutoff:
            continue
        hashes = payload.get("config_hashes")
        if not isinstance(hashes, Mapping):
            continue
        rows = payload.get("results")
        if not isinstance(rows, list):
            continue
        result = next(
            (
                dict(item)
                for item in rows
                if isinstance(item, Mapping)
                and str(item.get("instrument", "")) == instrument
                and item.get("execution_allowed") is False
            ),
            None,
        )
        if result is None:
            continue
        result.update(
            {
                "artifact_status": str(payload.get("status", "unavailable")),
                "run_id": str(payload.get("run_id", "")),
                "config_hashes": dict(hashes),
            }
        )
        records.append((timestamp, str(payload.get("run_id", "")), result))
    if not records:
        return unavailable
    records.sort(key=lambda item: (item[0], item[1]))
    result = records[-1][2]
    ranker_rows = result.get("benchmark_rankers", ())
    rank_scores = {
        str(item.get("ranker")): item.get("score")
        for item in ranker_rows
        if isinstance(item, Mapping) and item.get("ranker")
    } if isinstance(ranker_rows, (list, tuple)) else {}
    route = _ui_decision_rank_route(
        "instrument_detail", rank_scores, promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )
    result["rank_cutover"] = route
    result["active_ranker"] = route["ranker"]
    result["active_rank_score"] = route["rank_score"]
    result["v3_replay_score"] = route["v3_replay_score"]
    return result


# Explicit presentation schema: future/private artifact fields are never projected.
_METRIC_HISTORY_DISPLAY_COLUMNS = (
    "run_id", "instrument_id", "component_group", "component_name", "source_id",
    "raw_metric_value", "normalised_score_10", "score_available", "na_reason",
    "source_dataset", "as_of_date", "freshness_status", "authority_label",
    "formula_version", "formula_checksum", "source_vintage_hash", "execution_allowed",
)


def load_score_metric_history_projection(
    instrument_id: str,
    *,
    frame=None,
    rank_scores: Mapping[str, object] | None = None,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> dict:
    """Read stored component snapshots without deriving scores or PIT authority."""
    import math
    from numbers import Real

    import pandas as pd

    from etf_cockpit.data.trust_artifacts import SCORE_METRIC_HISTORY_PATH

    def unavailable(reason: str) -> dict:
        return {"status": "unavailable", "reason_code": reason, "rows": [],
                "message": "Score-component metric history unavailable: " + reason + ".",
                "execution_allowed": False}

    if frame is None:
        try:
            frame = pd.read_parquet(SCORE_METRIC_HISTORY_PATH)
        except FileNotFoundError:
            return unavailable("missing_local_artifact")
        except Exception:
            return unavailable("unreadable_local_artifact")
    if (not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique
            or not set(_METRIC_HISTORY_DISPLAY_COLUMNS).issubset(frame.columns)):
        return unavailable("malformed_metric_history")
    rows = frame.loc[frame["instrument_id"].eq(instrument_id), list(_METRIC_HISTORY_DISPLAY_COLUMNS)]
    if rows.empty:
        return unavailable("no_instrument_metric_history")
    records = []
    for record in rows.to_dict("records"):
        for field, value in record.items():
            if not pd.api.types.is_scalar(value):
                return unavailable("malformed_metric_history")
            if pd.isna(value):
                record[field] = None
        for field in ("run_id", "instrument_id", "component_name"):
            if not isinstance(record[field], str) or not record[field].strip():
                return unavailable("malformed_metric_history")
        for field in ("raw_metric_value", "normalised_score_10"):
            value = record[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)):
                return unavailable("malformed_metric_history")
        record["execution_allowed"] = False
        records.append(record)
    rank_evidence_reason = None
    if rank_scores is None:
        stored_assessment = load_opportunity_assessment(
            instrument_id,
            promotion_record=promotion_record,
            cutover_enabled=cutover_enabled,
        )
        ranker_rows = stored_assessment.get("benchmark_rankers", ())
        if isinstance(ranker_rows, (list, tuple)):
            rank_scores = {
                str(item.get("ranker")): item.get("score")
                for item in ranker_rows
                if isinstance(item, Mapping) and item.get("ranker")
            }
        else:
            rank_scores = {}
        if not rank_scores:
            rank_evidence_reason = str(
                stored_assessment.get("reason_code", "stored_rank_scores_unavailable")
            )
    elif not rank_scores:
        rank_evidence_reason = "caller_rank_scores_empty"
    route = _ui_decision_rank_route(
        "score_history", rank_scores, promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )
    if route["rank_score"] is None:
        if route["cutover_enabled"]:
            return unavailable("rank_evidence_unavailable") | {
                "rank_evidence_reason": rank_evidence_reason or "active_rank_score_unavailable",
                "rank_route_reason": route.get("reason"),
            }
        rank_evidence_reason = rank_evidence_reason or "active_rank_score_unavailable"
    return {"status": "available", "instrument_id": instrument_id, "rows": records,
            "rank_cutover": route, "active_ranker": route["ranker"],
            "active_rank_score": route["rank_score"], "v3_replay_score": route["v3_replay_score"],
            "active_rank_score_reason": rank_evidence_reason,
            "message": "Persisted score-component snapshots across local runs. As-of dates and stored provenance do not establish knowledge-time availability or replay guarantees.",
            "execution_allowed": False}


def _ui_decision_rank_route(
    consumer: str,
    rank_scores: Mapping[str, object],
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> dict[str, object]:
    from etf_cockpit.analysis.decision.rank_validation import route_consumer_rank

    return route_consumer_rank(
        consumer,
        rank_scores or {},
        promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )


def route_decision_rank_rows(
    frame: pd.DataFrame,
    consumer: str,
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> pd.DataFrame:
    """Apply the configured rank route to frame rows carrying rank scores."""

    from etf_cockpit.analysis.decision.rank_validation import route_ranked_frame

    return route_ranked_frame(
        frame,
        consumer,
        promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )


def build_screen_rows(
    snapshot: object,
    fundamentals: pd.DataFrame,
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> pd.DataFrame:
    """Build screener evidence and route an available rank through the facade."""

    frame = _build_screen_rows_v3(snapshot, fundamentals)
    return route_decision_rank_rows(
        frame,
        "screener",
        promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )
