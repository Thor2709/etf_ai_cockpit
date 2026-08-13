"""Application facade and persistence boundary for local portfolio candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    StoredRecord,
    TransactionalStore,
)
from etf_cockpit.portfolio.sandbox import (
    PORTFOLIO_SANDBOX_SCHEMA,
    PortfolioAnalysis,
    PortfolioCandidate,
    PortfolioSnapshotBinding,
    analyse_candidate,
    candidate_id,
    create_candidate,
    holdings_checksum,
    select_holdings_view,
)
from etf_cockpit.portfolio.benchmark_reference_contract import (
    AnalysisResolution,
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    VwceAnchorEvidence,
    VwceAnchorResolution,
    project_profile_relative_analysis,
    resolve_vwce_anchor,
)
from etf_cockpit.application.overlap import build_direct_overlap_view, direct_overlap_payload
from etf_cockpit.application.portfolio_optimiser import build_portfolio_optimiser
from etf_cockpit.portfolio.optimiser import OptimiserConstraints
from etf_cockpit.portfolio.robust_risk import build_robust_risk_report
from etf_cockpit.governance.capability_scope import InstrumentDescriptor, resolve_instrument_capability
from etf_cockpit.governance.product_scope import load_strategy_scope


PORTFOLIO_SANDBOX_ENTITY = "portfolio_sandbox"
PORTFOLIO_SANDBOX_RESULT_ENTITY = "portfolio_sandbox_result"
_RESULT_FIELDS = frozenset({
    "schema_version", "candidate_id", "candidate_revision", "candidate_payload_checksum", "source_snapshot", "before_after", "allocations", "holdings",
    "constraints", "marginal_effects", "why_not", "overlap", "warnings", "cost", "service_evidence",
    "proposal_boundary", "execution_allowed", "payload_checksum",
})
_SOURCE_FIELDS = frozenset({"account_id", "portfolio_id", "snapshot_id", "source_revision", "source_checksum", "price_source_revision", "price_source_checksum", "as_of", "holdings_view", "holdings_sources", "execution_allowed"})
_HANDOFF_FIELDS = frozenset({
    "schema_version", "boundary", "status", "proposal_policy_evaluated", "candidate_id", "account_id",
    "portfolio_id", "portfolio_revision", "source_snapshot_id", "source_snapshot", "changes", "rejected",
    "why_not", "evidence", "proposal_allowed", "execution_allowed", "evidence_checksum",
})


class PortfolioSandboxPersistenceError(RuntimeError):
    """Raised when local candidate state cannot be accessed safely."""


@dataclass(frozen=True)
class SavedPortfolioCandidate:
    candidate: PortfolioCandidate
    revision: int
    updated_at: str
    source_stale: bool
    result_payload: dict[str, object] | None = None


def draft_portfolio_candidate(snapshot: object, *, name: str = "Portfolio candidate") -> PortfolioCandidate:
    config = getattr(snapshot, "config")
    targets = {key: float(value.target_weight) for key, value in config.targets.positions.items()}
    return build_portfolio_candidate(
        snapshot,
        name=name,
        analysis_notional_eur=_default_notional(snapshot),
        target_weights=targets,
        cash_weight=float(config.targets.cash_target_weight),
    )


def build_portfolio_candidate(
    snapshot: object,
    *,
    name: str,
    analysis_notional_eur: object,
    target_weights: Mapping[str, object],
    cash_weight: object,
    holdings_view: str = "combined",
) -> PortfolioCandidate:
    holdings = select_holdings_view(getattr(snapshot, "holdings"), holdings_view)
    binding = portfolio_snapshot_binding(snapshot, holdings_view=holdings_view)
    return create_candidate(
        getattr(snapshot, "config"),
        holdings,
        name=name,
        analysis_notional_eur=analysis_notional_eur,
        target_weights=dict(target_weights),
        cash_weight=cash_weight,
        source_revision=str(getattr(snapshot, "universe_revision", "") or "unknown"),
        source_as_of=binding.as_of,
    )


def analyse_portfolio_candidate(
    snapshot: object,
    candidate: PortfolioCandidate,
    *,
    account_id: str | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    holdings_view: str = "combined",
    reference_registry: CanonicalBenchmarkRegistry | None = None,
    reference_instrument: Mapping[str, object] | None = None,
    reference_currency: str | None = None,
    reference_horizon_years: float | None = None,
    reference_start_date: str | None = None,
    reference_end_date: str | None = None,
    reference_decision_time: str | None = None,
    reference_portfolio_ids: tuple[str, ...] = (),
    vwce_anchor: VwceAnchorEvidence | None = None,
    vwce_listing_id: str | None = None,
    vwce_conversion_evidence: Mapping[str, object] | None = None,
) -> PortfolioAnalysis:
    reference_registry = reference_registry or getattr(snapshot, "benchmark_reference_registry", None)
    reference_instrument = reference_instrument or getattr(snapshot, "benchmark_reference_instrument", None)
    reference_currency = reference_currency or getattr(snapshot, "benchmark_reference_currency", None)
    reference_horizon_years = reference_horizon_years if reference_horizon_years is not None else getattr(snapshot, "benchmark_reference_horizon_years", None)
    reference_start_date = reference_start_date or getattr(snapshot, "benchmark_reference_start_date", None)
    reference_end_date = reference_end_date or getattr(snapshot, "benchmark_reference_end_date", None)
    reference_decision_time = reference_decision_time or getattr(snapshot, "benchmark_reference_decision_time", None)
    if not reference_portfolio_ids:
        reference_portfolio_ids = tuple(getattr(snapshot, "benchmark_reference_portfolio_ids", ()))
    vwce_anchor = vwce_anchor or getattr(snapshot, "vwce_anchor_evidence", None)
    vwce_listing_id = vwce_listing_id or getattr(snapshot, "vwce_listing_id", None)
    vwce_conversion_evidence = vwce_conversion_evidence or getattr(snapshot, "vwce_conversion_evidence", None)
    holdings = select_holdings_view(getattr(snapshot, "holdings"), holdings_view)
    binding = portfolio_snapshot_binding(
        snapshot,
        account_id=account_id,
        portfolio_id=portfolio_id,
        snapshot_id=snapshot_id,
        holdings_view=holdings_view,
    )
    policy = load_strategy_scope().policy
    governed_holdings = _governed_holdings(snapshot, holdings, policy=policy)
    holding_ids = {
        str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        for _, row in holdings.iterrows()
    }
    target_capabilities = _governed_target_capabilities(
        snapshot,
        sorted(set(candidate.targets) - holding_ids),
        policy=policy,
    )
    selected_checksum = holdings_checksum(holdings)
    source_stale = (
        candidate.source_revision != str(getattr(snapshot, "universe_revision", "") or "unknown")
        or candidate.source_checksum != selected_checksum
        or candidate.source_as_of != binding.as_of
    )
    current: dict[str, float] = {}
    for _, row in holdings.iterrows():
        instrument_id = str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        if instrument_id:
            current[instrument_id] = current.get(instrument_id, 0.0) + float(row.get("current_weight", 0.0))
    ids = sorted(set(current) | set(candidate.targets))
    overlap = build_direct_overlap_view(
        snapshot,
        ids,
        current_weights=current,
        target_weights=candidate.targets,
        known_at=_overlap_cutoff(binding.as_of),
    )
    analysis_candidate = replace(candidate, source_checksum=holdings_checksum(holdings))
    analysis = analyse_candidate(
        getattr(snapshot, "config"),
        governed_holdings,
        analysis_candidate,
        current_revision=str(getattr(snapshot, "universe_revision", "") or "unknown"),
        overlap=overlap,
        target_capabilities=target_capabilities,
    )
    if source_stale:
        analysis = replace(
            analysis,
            source_stale=True,
            warnings=tuple(dict.fromkeys(("Saved source binding changed; all derived values were re-evaluated from the current snapshot.", *analysis.warnings))),
        )
    services = _service_evidence(snapshot, analysis)
    services["capability_matrix"] = _capability_matrix_evidence(governed_holdings, target_capabilities)
    reference_resolution: AnalysisResolution | None = None
    if reference_registry is not None:
        services["benchmark_reference"], reference_resolution = _resolve_reference_evidence(
            reference_registry,
            analysis_id=candidate.candidate_id,
            instrument_id=candidate.candidate_id,
            instrument=reference_instrument,
            currency=reference_currency,
            horizon_years=reference_horizon_years,
            start_date=reference_start_date,
            end_date=reference_end_date,
            decision_time=reference_decision_time,
            reference_portfolio_ids=reference_portfolio_ids,
        )
    if vwce_anchor is not None:
        anchor_resolution = _resolve_profile_anchor(
            vwce_anchor,
            listing_id=vwce_listing_id,
            currency=reference_currency,
            horizon_years=reference_horizon_years,
            effective_date=reference_start_date,
            decision_time=reference_decision_time,
            conversion_evidence=vwce_conversion_evidence,
        )
        if reference_registry is not None and (
            reference_resolution is None or reference_resolution.blockers
        ):
            anchor_resolution = replace(anchor_resolution, status="unavailable", reason="reference_resolution_incomplete")
        services["profile_relative"] = project_profile_relative_analysis(
            {"analysis_id": candidate.candidate_id, "analysis_status": "available"},
            anchor_resolution,
            anchor=vwce_anchor,
            conversion_evidence=vwce_conversion_evidence,
        )
    return replace(analysis, snapshot_binding=binding, service_evidence=services)


def _resolve_reference_evidence(
    registry: CanonicalBenchmarkRegistry,
    *,
    analysis_id: str,
    instrument_id: str,
    instrument: Mapping[str, object] | None,
    currency: str | None,
    horizon_years: float | None,
    start_date: str | None,
    end_date: str | None,
    decision_time: str | None,
    reference_portfolio_ids: tuple[str, ...],
) -> tuple[dict[str, object], AnalysisResolution | None]:
    if (
        instrument is None
        or currency is None
        or horizon_years is None
        or start_date is None
        or end_date is None
        or decision_time is None
    ):
        return (
            {
                "contract": "benchmark-reference-contract.v1",
                "status": "unavailable",
                "blockers": ["reference_resolution_inputs_unavailable"],
                "execution_allowed": False,
            },
            None,
        )
    try:
        resolution = registry.resolve_analysis(
            analysis_id=analysis_id,
            purpose="comparison",
            instrument_id=instrument_id,
            instrument=instrument,
            currency=currency,
            horizon_years=horizon_years,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
            reference_portfolio_ids=reference_portfolio_ids,
        )
    except (BenchmarkReferenceError, TypeError, ValueError) as exc:
        return (
            {
                "contract": "benchmark-reference-contract.v1",
                "status": "unavailable",
                "blockers": [f"reference_resolution_invalid:{type(exc).__name__}"],
                "execution_allowed": False,
            },
            None,
        )
    projection = registry.ui_projection(resolution)
    projection["status"] = "available" if not resolution.blockers else "unavailable"
    return projection, resolution


def _resolve_profile_anchor(
    anchor: VwceAnchorEvidence,
    *,
    listing_id: str | None,
    currency: str | None,
    horizon_years: float | None,
    effective_date: str | None,
    decision_time: str | None,
    conversion_evidence: Mapping[str, object] | None,
) -> VwceAnchorResolution:
    if (
        listing_id is None
        or currency is None
        or horizon_years is None
        or effective_date is None
        or decision_time is None
    ):
        return replace(
            VwceAnchorResolution(
                "unavailable",
                anchor.canonical_share_class_id,
                listing_id,
                "profile_alignment_inputs_unavailable",
                anchor_digest=anchor.digest(),
            ),
            output_currency=currency,
            horizon_years=horizon_years,
        )
    try:
        return resolve_vwce_anchor(
            anchor,
            listing_id=listing_id,
            effective_date=effective_date,
            decision_time=decision_time,
            currency=currency,
            horizon_years=horizon_years,
            conversion_evidence=None if conversion_evidence is None else _freeze_mapping(conversion_evidence),
        )
    except (BenchmarkReferenceError, TypeError, ValueError):
        return VwceAnchorResolution(
            "unavailable",
            anchor.canonical_share_class_id,
            listing_id,
            "profile_anchor_invalid",
            anchor_digest=anchor.digest(),
        )


def _freeze_mapping(value: object) -> object:
    """Detach conversion evidence before it crosses the resolver boundary."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_mapping(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_mapping(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(_freeze_mapping(item) for item in value)
    return value


def save_portfolio_candidate(
    snapshot: object,
    *,
    name: str,
    analysis_notional_eur: object,
    target_weights: Mapping[str, object],
    cash_weight: object,
    expected_revision: int,
    root: Path = ROOT,
    account_id: str | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    holdings_view: str = "combined",
) -> SavedPortfolioCandidate:
    candidate = build_portfolio_candidate(
        snapshot,
        name=name,
        analysis_notional_eur=analysis_notional_eur,
        target_weights=target_weights,
        cash_weight=cash_weight,
        holdings_view=holdings_view,
    )
    payload = _candidate_payload(candidate)
    analysis = analyse_portfolio_candidate(
        snapshot,
        candidate,
        account_id=account_id,
        portfolio_id=portfolio_id,
        snapshot_id=snapshot_id,
        holdings_view=holdings_view,
    )
    candidate_payload_checksum = str(payload["payload_checksum"])
    result_payload = portfolio_analysis_payload(
        analysis,
        candidate_revision=expected_revision + 1,
        candidate_payload_checksum=candidate_payload_checksum,
    )
    try:
        with TransactionalStore(root) as store:
            existing_result = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, candidate.candidate_id)
            expected_result_revision = existing_result.revision if existing_result is not None else 0
            records = store.put_many_cas(
                [
                    (PORTFOLIO_SANDBOX_ENTITY, candidate.candidate_id, payload),
                    (PORTFOLIO_SANDBOX_RESULT_ENTITY, candidate.candidate_id, result_payload),
                ],
                expected_revisions={
                    (PORTFOLIO_SANDBOX_ENTITY, candidate.candidate_id): expected_revision,
                    (PORTFOLIO_SANDBOX_RESULT_ENTITY, candidate.candidate_id): expected_result_revision,
                },
            )
    except StorageRevisionConflict:
        raise
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        raise PortfolioSandboxPersistenceError(f"local portfolio storage is unavailable: {exc}") from exc
    record, _result_record = records
    return SavedPortfolioCandidate(candidate, record.revision, record.updated_at, source_stale=False, result_payload=result_payload)


def load_portfolio_candidate(
    snapshot: object,
    name: str,
    *,
    root: Path = ROOT,
    account_id: str | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    holdings_view: str = "combined",
) -> SavedPortfolioCandidate:
    identity = candidate_id(name)
    try:
        with TransactionalStore(root) as store:
            with store.read_transaction():
                record = store.get(PORTFOLIO_SANDBOX_ENTITY, identity)
                result = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, identity)
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        raise PortfolioSandboxPersistenceError(f"local portfolio storage is unavailable: {exc}") from exc
    if record is None:
        raise ValueError("no saved portfolio candidate has this name")
    candidate = _candidate_from_record(snapshot, record)
    analysis = analyse_portfolio_candidate(
        snapshot,
        candidate,
        account_id=account_id,
        portfolio_id=portfolio_id,
        snapshot_id=snapshot_id,
        holdings_view=holdings_view,
    )
    result_payload = _validate_loaded_result(
        None if result is None else dict(result.payload),
        candidate,
        analysis,
        candidate_record=record,
    )
    if result is not None and result_payload is None and not analysis.source_stale:
        analysis = replace(
            analysis,
            source_stale=True,
            warnings=tuple(
                dict.fromkeys(
                    (
                        "Saved source binding changed; all derived values were re-evaluated from the current snapshot.",
                        *analysis.warnings,
                    )
                )
            ),
        )
    return SavedPortfolioCandidate(candidate, record.revision, record.updated_at, analysis.source_stale, result_payload)


def portfolio_snapshot_binding(
    snapshot: object,
    *,
    account_id: str | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    holdings_view: str = "combined",
) -> PortfolioSnapshotBinding:
    """Return an explicit, replayable identity for the selected local snapshot."""

    holdings = select_holdings_view(getattr(snapshot, "holdings"), holdings_view)
    revision = str(getattr(snapshot, "universe_revision", "") or "unknown")
    checksum = holdings_checksum(holdings)
    selected_account = _bound_snapshot_identity(snapshot, "account_id", account_id, "default")
    selected_portfolio = _bound_snapshot_identity(snapshot, "portfolio_id", portfolio_id, "default")
    selected_snapshot = _bound_snapshot_identity(snapshot, "snapshot_id", snapshot_id, "current")
    holdings_sources = tuple(
        sorted(
            set(_holding_evidence_values(holdings, "source"))
            | set(_holding_evidence_values(holdings, "holdings_source"))
            | set(_holding_evidence_values(holdings, "source_id"))
        )
    )
    return PortfolioSnapshotBinding(
        account_id=selected_account,
        portfolio_id=selected_portfolio,
        snapshot_id=selected_snapshot,
        source_revision=revision,
        source_checksum=checksum,
        price_source_revision=str(
            getattr(snapshot, "price_revision", None)
            or getattr(snapshot, "prices_revision", None)
            or "unknown"
        ),
        price_source_checksum=_prices_checksum(getattr(snapshot, "prices", pd.DataFrame())),
        as_of=_source_as_of(snapshot),
        holdings_view=str(holdings_view or "combined"),
        holdings_sources=holdings_sources,
    )


def rebalance_inapplicable_instruments(
    snapshot: object,
    holdings: pd.DataFrame,
    instrument_ids: set[str],
) -> tuple[str, ...]:
    """Return instruments that the existing ETF-only preview cannot accept."""

    if not isinstance(holdings, pd.DataFrame):
        return tuple(sorted(instrument_ids))
    policy = load_strategy_scope().policy
    universe = getattr(snapshot, "config").universe.by_id()
    parent_column = next(
        (name for name in ("instrument_id", "etf_id") if name in holdings.columns),
        None,
    )
    inapplicable: list[str] = []
    for instrument_id in sorted(instrument_ids):
        configured = universe.get(instrument_id)
        rows = (
            holdings.loc[holdings[parent_column].astype(str).str.strip().eq(instrument_id)]
            if parent_column is not None
            else pd.DataFrame()
        )
        evidence = [row.to_dict() for _, row in rows.iterrows()] or [
            {"instrument_id": instrument_id}
        ]
        decisions = [
            _resolve_capability_decision(values, configured, policy)[0]
            for values in evidence
        ]
        if any(
            decision is None or str(getattr(decision, "asset_family", "unknown")) != "etf"
            for decision in decisions
        ):
            inapplicable.append(instrument_id)
    return tuple(inapplicable)


def portfolio_analysis_payload(
    analysis: PortfolioAnalysis,
    *,
    candidate_revision: int = 0,
    candidate_payload_checksum: str | None = None,
) -> dict[str, object]:
    """Build the sandbox-specific deterministic result/export contract."""

    binding = analysis.snapshot_binding
    if binding is None:
        raise ValueError("portfolio sandbox result requires a source snapshot binding")
    if isinstance(candidate_revision, bool) or not isinstance(candidate_revision, int) or candidate_revision < 0:
        raise ValueError("candidate revision must be a non-negative integer")
    canonical_candidate_checksum = str(_candidate_payload(analysis.candidate)["payload_checksum"])
    expected_candidate_checksum = str(candidate_payload_checksum or canonical_candidate_checksum)
    if len(expected_candidate_checksum) != 64 or expected_candidate_checksum != canonical_candidate_checksum:
        raise ValueError("candidate payload checksum does not match candidate")
    body: dict[str, object] = {
        "schema_version": "portfolio_sandbox_result.v1",
        "candidate_id": analysis.candidate.candidate_id,
        "candidate_revision": candidate_revision,
        "candidate_payload_checksum": expected_candidate_checksum,
        "source_snapshot": None if binding is None else _jsonable(asdict(binding)),
        "before_after": [
            {"instrument_id": instrument_id, "before_weight": before, "after_weight": after}
            for instrument_id, before, after in analysis.before_after
        ],
        "allocations": [asdict(row) for row in analysis.allocations],
        "holdings": [asdict(row) for row in analysis.holdings],
        "constraints": [asdict(row) for row in analysis.constraints],
        "marginal_effects": [{"instrument_id": key, "weight_delta": value} for key, value in analysis.marginal_effects],
        "why_not": [{"instrument_id": key, "reason": value} for key, value in analysis.why_not],
        "overlap": direct_overlap_payload(analysis.overlap),
        "warnings": list(analysis.warnings),
        "cost": {
            "model_id": analysis.cost.model_id,
            "total_order_value_eur": analysis.cost.total_order_value_eur,
            "total_cost_eur": analysis.cost.total_cost_eur,
            "weighted_cost_bps": analysis.cost.weighted_cost_bps,
            "execution_allowed": False,
        },
        "service_evidence": _jsonable(analysis.service_evidence),
        "proposal_boundary": "ISSUE-0130:draft-only",
        "execution_allowed": False,
    }
    return {**body, "payload_checksum": _payload_checksum(body)}


def export_portfolio_analysis(analysis: PortfolioAnalysis, path: Path) -> Path:
    """Write only the immutable sandbox export; no generic export registry is touched."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(portfolio_analysis_payload(analysis), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    atomic_write_bytes(destination, payload, lambda candidate: json.loads(candidate.read_text(encoding="utf-8")))
    return destination


def draft_portfolio_proposal(snapshot: object, analysis: PortfolioAnalysis) -> dict[str, object]:
    """Create a pre-ISSUE-0130 hand-off envelope without proposal-policy acceptance."""

    binding = analysis.snapshot_binding or portfolio_snapshot_binding(snapshot)
    bound_analysis = analysis if analysis.snapshot_binding is not None else replace(analysis, snapshot_binding=binding)
    result = portfolio_analysis_payload(bound_analysis)
    violated_constraints = tuple(sorted(item.name for item in analysis.constraints if item.status == "violated"))
    changes = []
    rejected = []
    for row in analysis.allocations:
        if abs(row.drift) <= 0 or row.marginal_effect not in {"increase", "decrease"}:
            rejected.append({"instrument_id": row.instrument_id, "reason": row.why_not or "no_trade"})
        elif row.capability_status != "supported":
            rejected.append({"instrument_id": row.instrument_id, "reason": row.capability_reason})
        elif violated_constraints:
            rejected.append({"instrument_id": row.instrument_id, "reason": f"portfolio_constraint_violation:{','.join(violated_constraints)}"})
        else:
            changes.append({"instrument_id": row.instrument_id, "weight_delta": row.drift})
    evidence = {
        "candidate_id": analysis.candidate.candidate_id,
        "candidate_payload_checksum": _candidate_payload(analysis.candidate)["payload_checksum"],
        "candidate_source_checksum": analysis.candidate.source_checksum,
        "result_checksum": result["payload_checksum"],
        "source_snapshot": _jsonable(asdict(binding)),
        "service_evidence": _jsonable(analysis.service_evidence),
    }
    body = {
        "schema_version": "portfolio_sandbox_draft_handoff.v1",
        "boundary": "ISSUE-0130",
        "status": "pre_issue_0130_draft",
        "proposal_policy_evaluated": False,
        "candidate_id": analysis.candidate.candidate_id,
        "account_id": binding.account_id,
        "portfolio_id": binding.portfolio_id,
        "portfolio_revision": binding.source_revision,
        "source_snapshot_id": binding.snapshot_id,
        "source_snapshot": _jsonable(asdict(binding)),
        "changes": changes,
        "rejected": rejected,
        "why_not": [{"instrument_id": key, "reason": value} for key, value in analysis.why_not],
        "evidence": evidence,
        "proposal_allowed": False,
        "execution_allowed": False,
    }
    return {**body, "evidence_checksum": _payload_checksum(body)}


def validate_portfolio_draft_handoff(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate the complete immutable pre-ISSUE-0130 envelope."""

    body_with_checksum = dict(payload)
    if set(body_with_checksum) != _HANDOFF_FIELDS:
        raise ValueError("portfolio draft handoff has an invalid field set")
    checksum = str(body_with_checksum.pop("evidence_checksum", ""))
    if not checksum or checksum != _payload_checksum(body_with_checksum):
        raise ValueError("portfolio draft handoff checksum does not match")
    if (
        body_with_checksum.get("schema_version") != "portfolio_sandbox_draft_handoff.v1"
        or body_with_checksum.get("boundary") != "ISSUE-0130"
        or body_with_checksum.get("status") != "pre_issue_0130_draft"
        or body_with_checksum.get("proposal_policy_evaluated") is not False
        or body_with_checksum.get("proposal_allowed") is not False
        or body_with_checksum.get("execution_allowed") is not False
    ):
        raise ValueError("portfolio draft handoff violates its non-executable boundary")
    _assert_no_execution(body_with_checksum)
    return dict(payload)


def _candidate_payload(candidate: PortfolioCandidate) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": PORTFOLIO_SANDBOX_SCHEMA,
        "candidate_id": candidate.candidate_id,
        "name": candidate.name,
        "analysis_notional_eur": candidate.analysis_notional_eur,
        "target_weights": [[key, value] for key, value in candidate.target_weights],
        "cash_weight": candidate.cash_weight,
        "source_revision": candidate.source_revision,
        "source_checksum": candidate.source_checksum,
        "source_as_of": candidate.source_as_of,
        "execution_allowed": False,
    }
    return {**body, "payload_checksum": _payload_checksum(body)}


def _candidate_from_record(snapshot: object, record: StoredRecord) -> PortfolioCandidate:
    payload = record.payload
    required = {
        "schema_version",
        "candidate_id",
        "name",
        "analysis_notional_eur",
        "target_weights",
        "cash_weight",
        "source_revision",
        "source_checksum",
        "source_as_of",
        "execution_allowed",
        "payload_checksum",
    }
    if set(payload) != required:
        raise ValueError("saved portfolio candidate has an invalid field set")
    if payload.get("schema_version") != PORTFOLIO_SANDBOX_SCHEMA:
        raise ValueError("saved portfolio candidate schema is unsupported")
    checksum = str(payload.get("payload_checksum", ""))
    body = {key: value for key, value in payload.items() if key != "payload_checksum"}
    if not checksum or checksum != _payload_checksum(body):
        raise ValueError("saved portfolio candidate checksum does not match")
    if payload.get("execution_allowed") is not False:
        raise ValueError("saved portfolio candidate violates the no-execution contract")
    raw_targets = payload.get("target_weights")
    if not isinstance(raw_targets, list) or any(not isinstance(item, list) or len(item) != 2 for item in raw_targets):
        raise ValueError("saved portfolio candidate target weights are malformed")
    target_pairs = [(str(item[0]), item[1]) for item in raw_targets]
    if len({item[0] for item in target_pairs}) != len(target_pairs):
        raise ValueError("saved portfolio candidate contains duplicate instruments")
    validation_holdings = pd.DataFrame(
        [
            {"instrument_id": instrument_id, "current_weight": 0.0, "market_value_eur": 0.0}
            for instrument_id, _weight in target_pairs
        ]
    )
    validated = create_candidate(
        getattr(snapshot, "config"),
        validation_holdings,
        name=str(payload.get("name", "")),
        analysis_notional_eur=payload.get("analysis_notional_eur"),
        target_weights=dict(target_pairs),
        cash_weight=payload.get("cash_weight"),
        source_revision=str(payload.get("source_revision", "") or "unknown"),
        source_as_of=str(payload["source_as_of"]).strip() if payload.get("source_as_of") else None,
    )
    if validated.candidate_id != record.entity_id or validated.candidate_id != str(payload.get("candidate_id", "")):
        raise ValueError("saved portfolio candidate identity does not match its name")
    source_checksum = str(payload.get("source_checksum", ""))
    if len(source_checksum) != 64:
        raise ValueError("saved portfolio candidate source checksum is invalid")
    return replace(
        validated,
        source_revision=str(payload.get("source_revision", "") or "unknown"),
        source_checksum=source_checksum,
        source_as_of=str(payload["source_as_of"]).strip() if payload.get("source_as_of") else None,
    )


def _payload_checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_as_of(snapshot: object) -> str | None:
    report = getattr(snapshot, "data_report", None)
    value = getattr(report, "as_of_date", None)
    return str(value) if value is not None else None


def _bound_snapshot_identity(
    snapshot: object,
    field: str,
    requested: str | None,
    fallback: str,
) -> str:
    raw = getattr(snapshot, field, None)
    if isinstance(raw, (list, tuple, set, dict)):
        raise ValueError(f"supplied snapshot {field} must be one immutable identity")
    actual = str(raw or fallback).strip()
    selected = str(requested or actual).strip()
    if not actual or selected != actual:
        raise ValueError(f"selected {field} does not match supplied snapshot")
    return actual


def _overlap_cutoff(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = pd.Timestamp(raw)
    if pd.isna(parsed):
        raise ValueError("portfolio snapshot as-of is invalid")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    if len(raw) == 10 and raw[4:5] == "-" and raw[7:8] == "-":
        parsed = parsed + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return parsed.to_pydatetime()


def _prices_checksum(prices: object) -> str:
    if not isinstance(prices, pd.DataFrame):
        return hashlib.sha256(b"unavailable").hexdigest()
    stable = prices.reset_index(drop=True).sort_index(axis=1)
    payload = stable.to_json(
        orient="split",
        date_format="iso",
        date_unit="ns",
        double_precision=15,
        default_handler=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _holding_evidence_values(holdings: pd.DataFrame, field: str) -> tuple[str, ...]:
    if field not in holdings.columns:
        return ()
    values = {
        text
        for value in holdings[field].tolist()
        if (text := _text_value(value))
    }
    return tuple(sorted(values))


def _default_notional(snapshot: object) -> float:
    holdings = getattr(snapshot, "holdings")
    if "market_value_eur" in holdings:
        value = float(holdings["market_value_eur"].sum())
        if value > 0:
            return value
    return 100_000.0


def _service_evidence(snapshot: object, analysis: PortfolioAnalysis) -> dict[str, object]:
    """Compose existing optimiser/risk/cost services for the what-if target."""

    prices = getattr(snapshot, "prices", pd.DataFrame())
    target = pd.DataFrame(
        [
            {"etf_id": row.instrument_id, "current_weight": row.target_weight, "market_value_eur": row.target_weight * analysis.candidate.analysis_notional_eur}
            for row in analysis.allocations
            if row.target_weight > 0 and row.capability_status == "supported"
        ]
    )
    evidence: dict[str, object] = {
        "cost": {"model_id": analysis.cost.model_id, "status": "available", "execution_allowed": False},
        "optimiser": {"status": "unavailable", "reason": "adjusted-price returns unavailable", "execution_allowed": False},
        "risk": {"status": "unavailable", "reason": "adjusted-price returns unavailable", "execution_allowed": False},
    }
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return evidence
    try:
        optimiser, returns = build_portfolio_optimiser(prices)
        max_weight = float(getattr(getattr(snapshot, "config").risks.portfolio_limits, "max_single_etf_weight", 1.0))
        solution = optimiser.solve(
            "minimum_variance",
            constraints=OptimiserConstraints(cash_weight=analysis.candidate.cash_weight, max_weight=max_weight),
            current_weights={row.instrument_id: row.target_weight for row in analysis.allocations},
        )
        evidence["optimiser"] = {
            "status": solution.status,
            "method": solution.method,
            "feasible": solution.feasible,
            "weights": {str(key): float(value) for key, value in solution.weights.items()},
            "warnings": list(solution.warnings),
            "model_version": solution.model_version,
            "execution_allowed": False,
        }
        risk = build_robust_risk_report(prices, target, bootstrap_reps=0)
        evidence["risk"] = {
            "status": str(risk.get("status", "unavailable")),
            "model_version": str(risk.get("model_version", "robust_risk.v1")),
            "selected_estimator": str(risk.get("selected_estimator", "unavailable")),
            "warnings": [str(item) for item in risk.get("warnings", ())],
            "execution_allowed": False,
        }
        evidence["returns_observations"] = int(len(returns))
    except (ArithmeticError, KeyError, TypeError, ValueError):
        # Existing services already expose their own fail-closed diagnostics;
        # keep a bounded application projection when evidence is incomplete.
        evidence["optimiser"] = {"status": "unavailable", "reason": "portfolio service evidence unavailable", "execution_allowed": False}
    return evidence


def _governed_holdings(snapshot: object, frame: pd.DataFrame, *, policy: object | None = None) -> pd.DataFrame:
    """Annotate rows from the canonical resolver; never trust row assertions."""

    if not isinstance(frame, pd.DataFrame):
        raise ValueError("holdings evidence is unavailable")
    if policy is None:
        result = frame.copy(deep=True)
        result["capability_status"] = "unavailable"
        result["capability_reason"] = "capability_matrix_unavailable"
        return result
    universe = getattr(snapshot, "config").universe.by_id()
    result = frame.copy(deep=True)
    statuses: list[str] = []
    reasons: list[str] = []
    for _, raw in result.iterrows():
        values = raw.to_dict()
        instrument_id = str(values.get("etf_id", values.get("instrument_id", ""))).strip()
        configured = universe.get(instrument_id)
        status, reason, _asset_type = _resolve_capability(values, configured, policy)
        statuses.append(status)
        reasons.append(reason)
    result["capability_status"] = statuses
    result["capability_reason"] = reasons
    return result


def _governed_target_capabilities(
    snapshot: object,
    instrument_ids: list[str],
    *,
    policy: object | None,
) -> dict[str, tuple[str, str, str]]:
    """Resolve configured target-only instruments through the same canonical policy."""

    universe = getattr(snapshot, "config").universe.by_id()
    resolved: dict[str, tuple[str, str, str]] = {}
    for instrument_id in instrument_ids:
        configured = universe.get(instrument_id)
        if policy is None:
            asset_type = str(getattr(configured, "instrument_type", "") or "unknown")
            resolved[instrument_id] = ("unavailable", "capability_matrix_unavailable", asset_type)
            continue
        resolved[instrument_id] = _resolve_capability({"instrument_id": instrument_id}, configured, policy)
    return resolved


def _resolve_capability(
    values: Mapping[str, object],
    configured: object | None,
    policy: object,
) -> tuple[str, str, str]:
    decision, asset_type = _resolve_capability_decision(values, configured, policy)
    return (
        _capability_status(decision),
        str(getattr(decision, "reason_code", "CLASSIFICATION_EVIDENCE_INCOMPLETE")),
        asset_type,
    )


def _resolve_capability_decision(
    values: Mapping[str, object],
    configured: object | None,
    policy: object,
) -> tuple[object | None, str]:
    descriptor_values = _descriptor_values(values, configured, policy)
    asset_type = str(
        (descriptor_values or {}).get("asset_type")
        or getattr(configured, "instrument_type", "")
        or values.get("asset_type")
        or "unknown"
    ).strip()
    decision = None
    if descriptor_values is not None:
        try:
            decision = resolve_instrument_capability(
                policy,
                InstrumentDescriptor(**descriptor_values),
                stage="portfolio",
                horizon="1M",
            )
        except (TypeError, ValueError):
            decision = None
    return decision, asset_type


def _descriptor_values(values: Mapping[str, object], configured: object | None, policy: object) -> dict[str, object] | None:
    explicit = {key: _text_value(values.get(key)) for key in ("asset_type", "security_type", "cfi_code")}
    supplied = [bool(value) for value in explicit.values()]
    if any(supplied):
        if not all(supplied):
            return None
        asset_type, security_type, cfi_code = explicit["asset_type"], explicit["security_type"], explicit["cfi_code"]
    elif configured is not None:
        asset_type = str(getattr(configured, "instrument_type", "") or getattr(configured, "asset_class", "")).strip()
        rule = next((item for item in policy.instrument_rules if asset_type.casefold() in {str(value).casefold() for value in item.match_asset_types}), None)
        if rule is None or not rule.match_security_types or not rule.match_cfi_prefixes:
            return None
        security_type = str(rule.match_security_types[0])
        cfi_code = str(rule.match_cfi_prefixes[0])
    else:
        return None
    rule = next(
        (
            item
            for item in policy.instrument_rules
            if str(asset_type).casefold() in {str(value).casefold() for value in item.match_asset_types}
        ),
        None,
    )
    raw_market_cap = values.get("market_cap_usd", getattr(configured, "market_cap_usd", None))
    raw_average_daily_value = values.get(
        "average_daily_value_usd",
        getattr(configured, "average_daily_value_usd", None),
    )
    market_cap = _optional_float(raw_market_cap)
    average_daily_value = _optional_float(raw_average_daily_value)
    if (_text_value(raw_market_cap) and market_cap is None) or (
        _text_value(raw_average_daily_value) and average_daily_value is None
    ):
        return None
    if configured is not None and rule is not None:
        if market_cap is None and "minimum_market_cap" in rule.prerequisites.liquidity:
            market_cap = float(policy.exclusion_policy.minimum_market_cap_usd)
        if average_daily_value is None and "minimum_average_daily_value" in rule.prerequisites.liquidity:
            average_daily_value = float(policy.exclusion_policy.minimum_average_daily_value_usd)
    return {
        "asset_type": asset_type,
        "security_type": security_type,
        "cfi_code": cfi_code,
        "exchange": _text_value(values.get("exchange")) or _text_value(getattr(configured, "exchange", None)),
        "leveraged": _bool_flag(values.get("leveraged", getattr(configured, "leveraged", False))),
        "inverse": _bool_flag(values.get("inverse", getattr(configured, "inverse", False))),
        "derivative": _bool_flag(values.get("derivative")),
        "crypto": _bool_flag(values.get("crypto")),
        "otc": _bool_flag(values.get("otc")),
        "complex_structured": _bool_flag(values.get("complex_structured")),
        "market_cap_usd": market_cap,
        "average_daily_value_usd": average_daily_value,
        "dealing_frequency": _text_value(values.get("dealing_frequency")) or "unknown",
    }


def _capability_status(decision: object | None) -> str:
    state = str(getattr(decision, "state", "unavailable"))
    return {"supported": "supported", "supported_with_limitations": "partial", "research_only": "partial", "rejected": "unsupported"}.get(state, "unavailable")


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text_value(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _bool_flag(value: object) -> bool:
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def _capability_matrix_evidence(
    frame: pd.DataFrame,
    target_capabilities: Mapping[str, tuple[str, str, str]],
) -> list[dict[str, object]]:
    """Expose the governed resolver projection used by the result."""

    if not isinstance(frame, pd.DataFrame):
        return []
    rows: list[dict[str, object]] = []
    for _, raw in frame.iterrows():
        values = raw.to_dict()
        instrument_id = str(values.get("etf_id", values.get("instrument_id", ""))).strip()
        if not instrument_id:
            continue
        rows.append({"instrument_id": instrument_id, "state": values.get("capability_status", "unavailable"), "reason_code": values.get("capability_reason", "CLASSIFICATION_EVIDENCE_INCOMPLETE"), "execution_allowed": False})
    current_ids = {str(row["instrument_id"]) for row in rows}
    for instrument_id, (status, reason, _asset_type) in sorted(target_capabilities.items()):
        if instrument_id not in current_ids:
            rows.append({"instrument_id": instrument_id, "state": status, "reason_code": reason, "execution_allowed": False})
    return sorted(
        rows,
        key=lambda row: (
            str(row["instrument_id"]),
            str(row["state"]),
            str(row["reason_code"]),
            str(row["execution_allowed"]),
        ),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _validate_loaded_result(
    payload: dict[str, object] | None,
    candidate: PortfolioCandidate,
    analysis: PortfolioAnalysis,
    *,
    candidate_record: StoredRecord,
) -> dict[str, object] | None:
    """Validate a result record and suppress evidence from another snapshot."""

    if payload is None:
        return None
    if set(payload) != _RESULT_FIELDS:
        raise ValueError("saved portfolio sandbox result has an invalid field set")
    checksum = str(payload.get("payload_checksum", ""))
    body = {key: value for key, value in payload.items() if key != "payload_checksum"}
    if not checksum or checksum != _payload_checksum(body):
        raise ValueError("saved portfolio sandbox result checksum does not match")
    if payload.get("schema_version") != "portfolio_sandbox_result.v1":
        raise ValueError("saved portfolio sandbox result schema is unsupported")
    if payload.get("candidate_id") != candidate.candidate_id:
        raise ValueError("saved portfolio sandbox result identity does not match candidate")
    if payload.get("candidate_revision") != candidate_record.revision:
        raise ValueError("saved portfolio sandbox result candidate revision does not match")
    if payload.get("candidate_payload_checksum") != candidate_record.payload.get("payload_checksum"):
        raise ValueError("saved portfolio sandbox result candidate checksum does not match")
    if payload.get("execution_allowed") is not False:
        raise ValueError("saved portfolio sandbox result violates the no-execution contract")
    source = payload.get("source_snapshot")
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS or source.get("execution_allowed") is not False:
        raise ValueError("saved portfolio sandbox result source binding is malformed")
    current_source = None if analysis.snapshot_binding is None else _jsonable(asdict(analysis.snapshot_binding))
    if source.get("as_of") != candidate.source_as_of:
        return None
    if source != current_source:
        return None
    _assert_no_execution(payload)
    canonical = portfolio_analysis_payload(
        analysis,
        candidate_revision=candidate_record.revision,
        candidate_payload_checksum=str(candidate_record.payload.get("payload_checksum", "")),
    )
    if payload != canonical:
        raise ValueError("saved portfolio sandbox result does not match canonical recomputation")
    return dict(payload)


def _assert_no_execution(value: object) -> None:
    if isinstance(value, Mapping):
        if "execution_allowed" in value and value["execution_allowed"] is not False:
            raise ValueError("saved portfolio sandbox result contains execution authority")
        for item in value.values():
            _assert_no_execution(item)
    elif isinstance(value, (tuple, list, set)):
        for item in value:
            _assert_no_execution(item)


__all__ = [
    "PORTFOLIO_SANDBOX_ENTITY",
    "PORTFOLIO_SANDBOX_RESULT_ENTITY",
    "PortfolioAnalysis",
    "PortfolioCandidate",
    "PortfolioSandboxPersistenceError",
    "SavedPortfolioCandidate",
    "analyse_portfolio_candidate",
    "build_portfolio_candidate",
    "candidate_id",
    "draft_portfolio_candidate",
    "draft_portfolio_proposal",
    "export_portfolio_analysis",
    "portfolio_analysis_payload",
    "portfolio_snapshot_binding",
    "rebalance_inapplicable_instruments",
    "load_portfolio_candidate",
    "save_portfolio_candidate",
    "validate_portfolio_draft_handoff",
]
