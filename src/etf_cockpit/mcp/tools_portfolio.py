"""MCP adapters for the owner's portfolio and decision journal.

Open defaults: overview currency is EUR and includes the five documented
projection sections; risk uses the ``medium`` profile; candidate cash is 0,
candidate notional is unavailable unless supplied, and optimiser objective is
``equal_weight``. Import parsing defaults to canonical/en_US. Read pages default
to 25 rows and are capped at 100. Write calls default to ``dry_run=True``; a
commit requires the fresh confirmation token returned by that preview.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, is_dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool


_CURSORS = CursorCodec()
_OVERVIEW_SECTIONS = frozenset({"holdings", "exposure", "performance", "forecast", "calendar"})
_PAGE_KEYS = frozenset({"rows", "events", "event_versions", "cash_flows", "points", "holdings", "allocations"})


def _session():
    session = current_call_context().session
    if session is None or getattr(session, "snapshot", None) is None:
        raise MCPToolError("PORTFOLIO_SERVICE_UNAVAILABLE", "The headless portfolio service is unavailable", "Start the configured headless application session and retry.")
    return session


def _issue_token(arguments: Mapping[str, Any]) -> str:
    context = current_call_context()
    payload = {**dict(arguments), "dry_run": False}
    payload.pop("confirm_token", None)
    return context.confirmation_store.issue(
        payload,
        store_revision=context.store_revision,
        client_id=context.client_id,
    )


def _page(items: Sequence[Any], *, cursor: str | None, limit: int, filters: Mapping[str, object], key: str) -> dict[str, Any]:
    try:
        page_size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters=dict(filters)) if cursor else 0
    rows = list(items)
    selected = rows[offset : offset + page_size + 1]
    has_more = len(selected) > page_size
    next_cursor = _CURSORS.encode(offset + page_size, filters=dict(filters)) if has_more else None
    return {key: selected[:page_size], "next_cursor": next_cursor, "total": len(rows)}


def _page_projection(value: Any, *, offset: int, limit: int) -> tuple[Any, bool]:
    has_more = False
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        selected: dict[str, Any] = {}
        for key, item in value.items():
            if key in _PAGE_KEYS and isinstance(item, (list, tuple)):
                rows = list(item)
                selected[key] = rows[offset : offset + limit]
                selected[f"{key}_total"] = len(rows)
                has_more = has_more or offset + limit < len(rows)
            else:
                selected[key], nested_more = _page_projection(item, offset=offset, limit=limit)
                has_more = has_more or nested_more
        return selected, has_more
    if isinstance(value, (list, tuple)):
        rows = []
        for item in value:
            selected, nested_more = _page_projection(item, offset=offset, limit=limit)
            rows.append(selected)
            has_more = has_more or nested_more
        return rows, has_more
    return value, False


def _analysis(snapshot: object):
    from etf_cockpit.application.portfolio_sandbox import analyse_portfolio_candidate, draft_portfolio_candidate

    candidate = draft_portfolio_candidate(snapshot)
    return analyse_portfolio_candidate(snapshot, candidate)


@tool(tier="read", description="Show bound portfolio holdings, exposure, performance, valuation, forecast and calendar projections.", read_only_hint=True, idempotent_hint=True, profiles=("core", "full"))
def portfolio_overview(
    as_of: str | None = None,
    currency: str = "EUR",
    sections: list[str] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.portfolio_views import (
        load_portfolio_calendar_projection,
        load_portfolio_exposure_projection,
        load_portfolio_forecast_aggregation,
        load_portfolio_holdings_projection,
        load_portfolio_performance_series,
    )

    selected = tuple(sections or sorted(_OVERVIEW_SECTIONS))
    if any(item not in _OVERVIEW_SECTIONS for item in selected):
        raise InvalidArgumentsError("sections may contain holdings, exposure, performance, forecast, and calendar")
    try:
        analysis = _analysis(session.snapshot)
        binding = analysis.snapshot_binding
        bound_as_of = getattr(binding, "as_of", None) if binding is not None else None
        if as_of is not None and (bound_as_of is None or str(bound_as_of)[:10] != as_of[:10]):
            return {"status": "unavailable", "unavailable_reason": "requested_as_of_snapshot_unavailable", "data_as_of": bound_as_of, "sections": {}, "execution_allowed": False}
        projection: dict[str, Any] = {}
        if "holdings" in selected:
            projection["holdings"] = load_portfolio_holdings_projection(
                session.snapshot, analysis, horizon_days=20, output_currency=currency, storage_root=session.root
            )
        if "exposure" in selected:
            binding = analysis.snapshot_binding
            decision_time = getattr(binding, "as_of", None) if binding is not None else None
            if decision_time is None:
                projection["exposure"] = {"status": "unavailable", "reason": "portfolio_snapshot_binding_unavailable", "rows": []}
            else:
                weights = {
                    str(row.instrument_id): float(row.current_weight)
                    for row in analysis.allocations
                    if getattr(row, "instrument_id", None) is not None
                }
                projection["exposure"] = load_portfolio_exposure_projection(
                    weights, decision_time=decision_time, analysis_date=decision_time,
                    holdings=getattr(session.snapshot, "holdings", None), root=session.root,
                )
        if "performance" in selected:
            result = load_portfolio_performance_series(currency=currency)
            projection["performance"] = asdict(result)
        if "forecast" in selected:
            projection["forecast"] = asdict(load_portfolio_forecast_aggregation(
                session.snapshot, analysis, horizon_days=20, output_currency=currency
            ))
        if "calendar" in selected:
            projection["calendar"] = load_portfolio_calendar_projection(
                session.snapshot, analysis, output_currency=currency
            )
        try:
            page_size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
        except ValueError as exc:
            raise InvalidArgumentsError(str(exc)) from None
        offset = _CURSORS.decode(cursor, filters={"as_of": as_of, "currency": currency, "sections": selected}) if cursor else 0
        bounded, has_more = _page_projection(projection, offset=offset, limit=page_size)
        return {
            "as_of": as_of or bound_as_of,
            "data_as_of": bound_as_of,
            "currency": currency,
            "sections": bounded,
            "next_cursor": _CURSORS.encode(offset + page_size, filters={"as_of": as_of, "currency": currency, "sections": selected}) if has_more else None,
            "execution_allowed": False,
        }
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "unavailable_reason": f"portfolio_projection_unavailable:{type(exc).__name__}", "sections": {}, "execution_allowed": False}


@tool(tier="read", description="Show the advisory portfolio risk profile and limit headroom.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def portfolio_risk(profile_id: str = "medium") -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.portfolio_views import load_portfolio_risk_profile_projection

    try:
        analysis = _analysis(session.snapshot)
        return load_portfolio_risk_profile_projection(session.snapshot, analysis, profile_id=profile_id)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "reason": f"portfolio_risk_unavailable:{type(exc).__name__}", "execution_allowed": False}


@tool(tier="read", description="Analyse non-executable target portfolio weights using the canonical portfolio sandbox.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def portfolio_candidate_analyse(
    target_weights: Mapping[str, float],
    cash_weight: float = 0.0,
    notional: float | None = None,
) -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.portfolio_sandbox import (
        analyse_portfolio_candidate,
        build_portfolio_candidate,
        portfolio_analysis_payload,
    )

    if not target_weights:
        raise InvalidArgumentsError("target_weights must not be empty")
    try:
        candidate = build_portfolio_candidate(
            session.snapshot, name="MCP candidate", analysis_notional_eur=notional,
            target_weights=target_weights, cash_weight=cash_weight,
        )
        analysis = analyse_portfolio_candidate(session.snapshot, candidate)
        return portfolio_analysis_payload(analysis)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "reason": f"portfolio_candidate_unavailable:{type(exc).__name__}", "execution_allowed": False}


@tool(tier="read", description="Solve bounded advisory portfolio weights with the canonical optimiser.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def portfolio_optimise(objective: str = "equal_weight", constraints: Mapping[str, Any] | None = None) -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.portfolio_optimiser import OptimiserConstraints, build_portfolio_optimiser

    try:
        optimiser, returns = build_portfolio_optimiser(getattr(session.snapshot, "prices", None))
        constraint_model = OptimiserConstraints(**dict(constraints or {}))
        solution = optimiser.solve(objective, constraints=constraint_model)
        return {
            "status": solution.status,
            "method": solution.method,
            "weights": solution.weights.to_dict() if solution.status == "success" else None,
            "diagnostics": solution.diagnostics,
            "warnings": list(solution.warnings),
            "return_observations": len(returns),
            "execution_allowed": False,
        }
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "reason": f"portfolio_optimiser_unavailable:{type(exc).__name__}", "weights": None, "execution_allowed": False}


@tool(tier="read", description="Reconcile broker imports with the local portfolio ledger at an as-of and known-at cutoff.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def portfolio_reconcile(as_of: str | None = None, known_at: str | None = None) -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication

    now = datetime.now(timezone.utc).isoformat()
    cutoff_as_of, cutoff_known_at = as_of or now, known_at or now
    try:
        result = PortfolioImportApplication(session.root).reconcile(as_of=cutoff_as_of, known_at=cutoff_known_at)
        return {**result.__dict__, "execution_allowed": False}
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "reason": f"portfolio_reconcile_unavailable:{type(exc).__name__}", "execution_allowed": False}


@tool(tier="read", description="Build the monthly decision template from canonical local evidence and explicit unavailable sections.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def monthly_decision_pack(month: str) -> dict[str, Any]:
    if len(month) != 7 or month[4] != "-":
        raise InvalidArgumentsError("month must use YYYY-MM")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise InvalidArgumentsError("month must use YYYY-MM") from None
    from etf_cockpit.application.headless_session import load_monthly_decision_pack

    return load_monthly_decision_pack(_session().snapshot, month)


@tool(tier="edit", description="Validate and stage a local portfolio import; confirmation is required before durable staging.", idempotent_hint=True, profiles=("full",))
def portfolio_import_preview(
    path: str,
    source_format: str = "canonical",
    locale: str = "en_US",
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    session = _session()
    args = {"path": path, "source_format": source_format, "locale": locale}
    if dry_run:
        source = Path(path)
        try:
            source_stat = source.stat()
            identity = {"size_bytes": source_stat.st_size, "modified_ns": source_stat.st_mtime_ns}
        except OSError:
            identity = {"status": "unavailable", "unavailable_reason": "source_file_unavailable"}
        return {**identity, "status": "confirmation_required", "confirm_token": _issue_token(args), "execution_allowed": False}
    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication

    with session.activity_publication():
        preview = PortfolioImportApplication(session.root).preview(Path(path), source_format=source_format, numeric_locale=locale)
    token = _issue_token({"preview_id": preview.preview_id}) if preview.valid else None
    return {
        "preview_id": preview.preview_id,
        "valid": preview.valid,
        "rows": preview.rows,
        "columns": list(preview.columns),
        "errors": list(preview.errors),
        "warnings": list(preview.warnings),
        "checksum": preview.checksum,
        "confirm_token": token,
        "execution_allowed": False,
    }


@tool(tier="edit", description="Commit one durable portfolio import staging preview to the canonical ledger.", profiles=("full",))
def portfolio_import_commit(preview_id: str, dry_run: bool = True, confirm_token: str | None = None) -> dict[str, Any]:
    session = _session()
    if dry_run:
        return {"preview_id": preview_id, "status": "confirmation_required", "confirm_token": _issue_token({"preview_id": preview_id}), "execution_allowed": False}
    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication

    with session.activity_publication():
        result = PortfolioImportApplication(session.root).commit(preview_id)
    return {**result.__dict__, "execution_allowed": False}


@tool(tier="edit", description="Reverse one committed portfolio import batch with a recorded reason.", profiles=("full",))
def portfolio_import_rollback(batch_id: str, reason: str, dry_run: bool = True, confirm_token: str | None = None) -> dict[str, Any]:
    session = _session()
    if not reason.strip():
        raise InvalidArgumentsError("reason must not be empty")
    if dry_run:
        args = {"batch_id": batch_id, "reason": reason.strip()}
        return {"batch_id": batch_id, "status": "confirmation_required", "confirm_token": _issue_token(args), "execution_allowed": False}
    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication

    with session.activity_publication():
        rolled_back = PortfolioImportApplication(session.root).rollback(batch_id, reason=reason.strip())
    return {"batch_id": batch_id, "rolled_back": rolled_back, "execution_allowed": False}


@tool(tier="read", description="Read verified decision-journal entries with integrity status and a signed cursor.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def journal_entries(instrument_id: str | None = None, since: str | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    from etf_cockpit.application.ui_facade import DecisionJournal

    root = _session().root
    entries = DecisionJournal().list_entries(root=root)
    selected = [entry for entry in entries if (instrument_id is None or instrument_id in entry.instrument_ids) and (since is None or entry.created_at >= since)]
    return _page(selected, cursor=cursor, limit=limit, filters={"instrument_id": instrument_id, "since": since}, key="entries")


@tool(tier="edit", description="Write one checksummed decision-journal entry linked to supplied evidence.", profiles=("full",))
def journal_record(
    thesis: str,
    decision: str,
    evidence_refs: list[str],
    alternatives: list[str] | None = None,
    confidence: float | None = None,
    invalidation_rules: list[str] | None = None,
    review_date: str | None = None,
    instrument_ids: list[str] | None = None,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    session = _session()
    if not thesis.strip() or not decision.strip():
        raise InvalidArgumentsError("thesis and decision must not be empty")
    args = {
        "thesis": thesis, "decision": decision, "evidence_refs": evidence_refs,
        "alternatives": alternatives or [], "confidence": confidence,
        "invalidation_rules": invalidation_rules or [], "review_date": review_date,
        "instrument_ids": instrument_ids or [],
    }
    if dry_run:
        return {"status": "confirmation_required", "confirm_token": _issue_token(args), "execution_allowed": False}
    from etf_cockpit.application.ui_facade import DecisionJournal, JournalEntry

    entry_id = "mcp_" + hashlib.sha256(str(args).encode("utf-8")).hexdigest()[:24]
    entry = JournalEntry(
        journal_entry_id=entry_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        thesis=thesis.strip(), decision=decision.strip(), outcome="pending",
        evidence_refs=list(evidence_refs), alternatives=alternatives or [], confidence=confidence,
        invalidation_rules=invalidation_rules or [], review_date=review_date,
        instrument_ids=instrument_ids or [],
    )
    with session.activity_publication():
        stored = DecisionJournal().create(entry, root=session.root)
    return {"entry_id": stored.journal_entry_id, "checksum": stored.checksum, "execution_allowed": False}


__all__ = [
    "journal_entries", "journal_record", "monthly_decision_pack", "portfolio_candidate_analyse",
    "portfolio_import_commit", "portfolio_import_preview", "portfolio_import_rollback", "portfolio_optimise",
    "portfolio_overview", "portfolio_reconcile", "portfolio_risk",
]
