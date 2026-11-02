"""MCP score and analysis tools.

Open defaults: ranked and research lists use 25 rows per page, score history
uses one year and at most 500 points, detail defaults to overview and score,
comparisons use one year, and selection uses the app's configured medium risk
profile without persisting a run. Job tools use local-only derived work.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from etf_cockpit.core.paths import ROOT
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool


_CURSORS = CursorCodec()
_DEFAULT_SESSION: Any = None


def _session() -> Any:
    global _DEFAULT_SESSION
    active = current_call_context().session
    if active is not None and getattr(active, "snapshot", None) is not None:
        return active
    if _DEFAULT_SESSION is None:
        from etf_cockpit.application.headless_session import HeadlessSession
        from etf_cockpit.application.snapshot_builder import build_snapshot

        _DEFAULT_SESSION = HeadlessSession(build_snapshot(force_sample=False), root=ROOT)
    if getattr(_DEFAULT_SESSION, "root", ROOT).resolve() != ROOT.resolve():
        raise MCPToolError("DATA_ROOT_MISMATCH", "The analysis session is outside the configured data root", "Restart the MCP server with the configured owner data root.")
    return _DEFAULT_SESSION


def _snapshot() -> tuple[Any, Any]:
    session = _session()
    snapshot = getattr(session, "snapshot", None)
    if snapshot is None:
        raise MCPToolError("SCORE_DATA_UNAVAILABLE", "The application snapshot is unavailable", "Load the configured local snapshot before requesting score analysis.")
    return session, snapshot


def _number(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _job(root: Path, workflow_type: str, label: str, payload: Mapping[str, object], handler) -> dict[str, Any]:
    from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobSpec

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    dedupe_key = "mcp-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:40]
    scheduler = DurableJobScheduler(root)
    try:
        workflow = scheduler.submit(
            workflow_type,
            label,
            (JobSpec("run", f"{label}:run"),),
            input_payload=dict(payload),
            dedupe_key=dedupe_key,
        )
        job = scheduler.run_once(handler, workflow_id=workflow.workflow_id)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise MCPToolError("ANALYSIS_JOB_UNAVAILABLE", "The local analysis job could not be started", f"Check local job storage and retry ({type(exc).__name__}).") from None
    if job is None:
        job = scheduler.list_jobs(workflow.workflow_id)[0]
    return {"job_id": job.job_id, "workflow_id": workflow.workflow_id, "status": job.status.value, "result": job.result, "execution_allowed": False}


@tool(tier="read", description="Read the canonical ranked scores with eligibility, gate, coverage, rank authority, and publication age.", read_only_hint=True, idempotent_hint=True)
def scores_ranked(
    asset_type: str | None = None,
    region: str | None = None,
    top_n: int = DEFAULT_PAGE_SIZE,
    buy_eligible_only: bool = False,
    include_gated: bool = False,
    cursor: str | None = None,
) -> dict[str, Any]:
    from etf_cockpit.application.score_views import (
        _rank_sort_key,
        published_scores,
        score_buy_eligible,
        score_coverage,
        score_gate_failed,
    )
    from etf_cockpit.application.scoreboard_publication import score_rank_authority, scoreboard_status

    try:
        page_size = validate_page_size(top_n, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    session, snapshot = _snapshot()
    identities = {str(item.id): item for item in getattr(getattr(snapshot.config, "universe", None), "etfs", ())}
    scores = published_scores(snapshot, str(getattr(snapshot, "universe_revision", "") or ""))
    selected = []
    for score in sorted(scores, key=_rank_sort_key):
        identity = identities.get(str(getattr(score, "display_id", "")))
        if asset_type and str(getattr(identity, "instrument_type", "")).casefold() != asset_type.casefold():
            continue
        if region and str(getattr(identity, "region", "")).casefold() != region.casefold():
            continue
        if score_gate_failed(score) and not include_gated:
            continue
        if buy_eligible_only and not score_buy_eligible(score):
            continue
        selected.append(score)
    filters = {"asset_type": asset_type, "region": region, "buy_eligible_only": buy_eligible_only, "include_gated": include_gated}
    offset = _CURSORS.decode(cursor, filters=filters) if cursor else 0
    page = selected[offset : offset + page_size + 1]
    has_more = len(page) > page_size
    page = page[:page_size]
    status = scoreboard_status(root=Path(session.root))
    scoreboard_age_seconds = None
    if status.get("status") == "available":
        try:
            modified = Path(str(status["path"])).stat().st_mtime
            scoreboard_age_seconds = max(0.0, datetime.now(timezone.utc).timestamp() - modified)
        except (KeyError, OSError, ValueError):
            scoreboard_age_seconds = None
    authority = score_rank_authority()
    rows = []
    for score in page:
        identity = identities.get(str(getattr(score, "display_id", "")))
        rows.append({
            "rank": getattr(score, "rank", None),
            "instrument_id": str(getattr(score, "display_id", "")),
            "name": getattr(score, "name", None),
            "asset_type": getattr(score, "asset_type", None),
            "region": getattr(identity, "region", None),
            "score_10": _number(getattr(score, "final_score_10", None)),
            "label": getattr(score, "final_label", "unavailable"),
            "action": getattr(score, "final_action", "unavailable"),
            "buy_eligible": score_buy_eligible(score),
            "gate_failed": score_gate_failed(score),
            "coverage": score_coverage(score),
            "reason": str(getattr(score, "one_line_reason", "") or "")[:240],
            "rank_delta": None,
            "rank_delta_status": "unavailable",
            "authority": authority,
            "scoreboard_age_seconds": scoreboard_age_seconds,
        })
    next_cursor = _CURSORS.encode(offset + page_size, filters=filters) if has_more else None
    return {"rows": rows, "next_cursor": next_cursor, "scoreboard_status": status.get("status", "unavailable"), "execution_allowed": False}


@tool(tier="read", description="Explain one canonical score and its critical evidence gates.", read_only_hint=True, idempotent_hint=True)
def score_explain(instrument_id: str) -> dict[str, Any]:
    from etf_cockpit.application.score_explain import explain_score

    _session, snapshot = _snapshot()
    return explain_score(snapshot, instrument_id.strip())


@tool(tier="read", description="Read stored score history for one instrument over the requested range.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def score_history(instrument_id: str, range: str = "1y") -> dict[str, Any]:
    from etf_cockpit.application.score_explain import load_score_history

    session, _snapshot_value = _snapshot()
    try:
        return load_score_history(instrument_id.strip(), range_key=range, root=Path(session.root))
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="read", description="Run a typed screener query against the current local snapshot.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def screen_run(
    filters: Sequence[Mapping[str, object]] | None = None,
    sort: Sequence[Mapping[str, object]] | None = None,
    fields: Sequence[str] | None = None,
    top_n: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> dict[str, Any]:
    from etf_cockpit.application.decision_views import build_screen_rows
    from etf_cockpit.application.screening_data import filter_from_dict, load_screening_fundamentals, run_screen_query, sort_from_dict

    try:
        page_size = validate_page_size(top_n, maximum=MAX_PAGE_SIZE)
        typed_filters = tuple(filter_from_dict(item) for item in (filters or ()))
        typed_sort = tuple(sort_from_dict(item) for item in (sort or ()))
        if fields is not None and (len(fields) > 50 or any(not isinstance(value, str) or not value.strip() for value in fields)):
            raise ValueError("fields must contain at most 50 non-empty names")
    except (ValueError, TypeError) as exc:
        raise InvalidArgumentsError(str(exc)) from None
    session, snapshot = _snapshot()
    fundamentals = load_screening_fundamentals(Path(session.root))
    rows = build_screen_rows(snapshot, fundamentals)
    result = run_screen_query(
        snapshot, rows, filters=typed_filters, sort=typed_sort,
        requested_fields=tuple(fields or ()),
    )
    offset = _CURSORS.decode(cursor, filters={"query": result.query_checksum}) if cursor else 0
    selected = result.rows[offset : offset + page_size + 1]
    has_more = len(selected) > page_size
    page = list(selected[:page_size])
    return {
        "rows": page,
        "total_input": result.total_input,
        "total_matched": result.total_matched,
        "available_fields": list(result.available_fields),
        "unavailable_fields": list(result.unavailable_fields),
        "warnings": list(result.warnings),
        "query_checksum": result.query_checksum,
        "next_cursor": _CURSORS.encode(offset + page_size, filters={"query": result.query_checksum}) if has_more else None,
        "execution_allowed": False,
    }


@tool(tier="read", description="Load selected canonical instrument detail sections without a UI.", read_only_hint=True, idempotent_hint=True)
def instrument_detail(instrument_id: str, sections: Sequence[str] | None = None) -> dict[str, Any]:
    from etf_cockpit.application.instrument_detail_loader import load_instrument_detail

    _session_value, snapshot = _snapshot()
    try:
        return load_instrument_detail(snapshot, instrument_id.strip(), tuple(sections or ("overview", "score")))
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="read", description="Compare 2 to 5 instruments using canonical scores and stored comparison evidence.", read_only_hint=True, idempotent_hint=True)
def compare_instruments(ids: Sequence[str], range: str = "1y") -> dict[str, Any]:
    from etf_cockpit.application.score_explain import compare_instruments as compare_service

    session, snapshot = _snapshot()
    try:
        return compare_service(snapshot, ids, range_key=range, root=Path(session.root))
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="read", description="Show canonical attractiveness and evidence coverage by configured sector.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def sector_overview(sectors: Sequence[str] | None = None) -> dict[str, Any]:
    from etf_cockpit.application.sector_views import build_sector_attractiveness

    _session_value, snapshot = _snapshot()
    available = sorted({str(getattr(item, "sector", "")).strip() for item in getattr(snapshot.config.universe, "etfs", ()) if str(getattr(item, "sector", "")).strip()})
    selected = list(dict.fromkeys(str(value).strip() for value in (sectors or available) if str(value).strip()))
    if len(selected) > 100:
        raise InvalidArgumentsError("sectors may contain at most 100 values")
    return {"sectors": build_sector_attractiveness(snapshot, selected), "execution_allowed": False}


@tool(tier="read", description="Select policy-based top-N candidates without persisting a selection run.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def top_n_selection(
    mode: str = "cross_asset",
    top_n: int = 25,
    risk_profile: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    from etf_cockpit.application.selection_views import load_top_n_selection

    session, snapshot = _snapshot()
    if mode not in {"asset_specific", "cross_asset"}:
        raise InvalidArgumentsError("mode must be 'asset_specific' or 'cross_asset'")
    try:
        count = validate_page_size(top_n, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    raw_time = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    decision_time = str(raw_time or "").strip()
    if len(decision_time) == 10:
        decision_time += "T23:59:59Z"
    result = load_top_n_selection(
        mode=mode, decision_time=decision_time or None, top_n=count,
        risk_profile=risk_profile, snapshot=snapshot,
        storage_root=Path(session.root), persist=False,
    )
    return result


@tool(tier="read_job", description="Analyse configured instruments with a frozen local depth profile.", read_only_hint=False, idempotent_hint=False, profiles=("full",))
def analysis_run(profile: str = "quick") -> dict[str, Any]:
    from etf_cockpit.application.analysis_depth import load_analysis_depth_profiles, run_analysis_profile_set
    from etf_cockpit.application.interactive_profile_run import build_profile_bindings

    session, snapshot = _snapshot()
    try:
        profiles = load_analysis_depth_profiles()
        selected = profiles.get(profile)
        if selected is None:
            raise InvalidArgumentsError("profile must be quick, medium, high, or full")
        bindings = build_profile_bindings(snapshot)
    except (KeyError, OSError, ValueError) as exc:
        if isinstance(exc, InvalidArgumentsError):
            raise
        raise MCPToolError("ANALYSIS_UNAVAILABLE", "The configured analysis profile is unavailable", f"Check local profile and snapshot evidence ({type(exc).__name__}).") from None

    def run(_job_context):
        result = run_analysis_profile_set(selected, bindings, root=Path(session.root))
        return {
            "run_id": result.run_id, "profile": result.profile_id, "status": result.status,
            "reason": result.reason, "completed_stages": list(result.completed_stages),
            "total_stages": result.total_stages, "output": result.output,
            "execution_allowed": False,
        }

    return _job(Path(session.root), "analysis_run", "MCP analysis run", {"profile": profile}, run)


@tool(tier="read_job", description="Run provisional analysis for identifiers outside the ranked universe.", read_only_hint=False, open_world_hint=True, idempotent_hint=False, profiles=("full",))
def candidate_analyse(identifiers: Sequence[str], years: int = 5) -> dict[str, Any]:
    selected = tuple(dict.fromkeys(str(value).strip() for value in identifiers if str(value).strip()))
    if not selected or len(selected) > 25:
        raise InvalidArgumentsError("identifiers must contain between 1 and 25 non-empty values")
    if isinstance(years, bool) or years < 1 or years > 20:
        raise InvalidArgumentsError("years must be between 1 and 20")
    raise MCPToolError(
        "CANDIDATE_FILTER_UNAVAILABLE",
        "The candidate analysis service cannot restrict work to the requested identifiers",
        "Add identifier filtering to the existing candidate application service before enabling this tool.",
    )


@tool(tier="read_job", description="Run read-only champion versus challenger rank validation from stored point-in-time inputs.", read_only_hint=False, idempotent_hint=False, profiles=("full",))
def rank_validation_run(
    years: Sequence[int] = (1, 3, 5),
    scope: str = "listing:euronext_oslo:all",
    benchmark_id: str | None = None,
) -> dict[str, Any]:
    from etf_cockpit.application.rank_validation_service import build_rank_validation_report

    session, _snapshot_value = _snapshot()
    if not years or len(years) > 5 or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in years):
        raise InvalidArgumentsError("years must contain 1 to 5 positive integers")

    def run(_job_context):
        return build_rank_validation_report(
            root=Path(session.root), years=years, scope=scope, benchmark_id=benchmark_id,
        )

    return _job(Path(session.root), "rank_validation", "MCP rank validation", {"years": list(years), "scope": scope, "benchmark_id": benchmark_id}, run)


__all__ = [
    "analysis_run", "candidate_analyse", "compare_instruments", "instrument_detail",
    "rank_validation_run", "score_explain", "score_history", "scores_ranked",
    "screen_run", "sector_overview", "top_n_selection",
]
