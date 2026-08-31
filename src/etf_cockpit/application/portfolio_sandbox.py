"""Application facade and persistence boundary for local portfolio candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
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
    unavailable_reference_projection,
    project_profile_relative_analysis,
    resolve_vwce_anchor,
)
from etf_cockpit.application.overlap import build_direct_overlap_view, direct_overlap_payload
from etf_cockpit.application.portfolio_optimiser import build_portfolio_optimiser
from etf_cockpit.application.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
)
from etf_cockpit.portfolio.attribution import build_performance_attribution
from etf_cockpit.portfolio.factor_risk import build_factor_risk_report
from etf_cockpit.portfolio.optimiser import OptimiserConstraints
from etf_cockpit.portfolio.optimiser import METHODS as OPTIMISER_METHODS
from etf_cockpit.portfolio.optimiser import returns_from_adjusted_prices
from etf_cockpit.portfolio.rebalancing import RebalanceConstraints, build_rebalance_report
from etf_cockpit.portfolio.robust_risk import build_robust_risk_report
from etf_cockpit.portfolio.stress_testing import StressScenario, StressScenarioError, run_stress_scenario
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
    reference_portfolio_ids: tuple[str, ...] | None = None,
    vwce_anchor: VwceAnchorEvidence | None = None,
    vwce_listing_id: str | None = None,
    vwce_conversion_evidence: Mapping[str, object] | None = None,
) -> PortfolioAnalysis:
    reference_registry = reference_registry if reference_registry is not None else getattr(snapshot, "benchmark_reference_registry", None)
    if reference_registry is None:
        reference_registry = CanonicalBenchmarkRegistry()
    reference_instrument = reference_instrument if reference_instrument is not None else getattr(snapshot, "benchmark_reference_instrument", None)
    reference_currency = reference_currency if reference_currency is not None else getattr(snapshot, "benchmark_reference_currency", None)
    reference_horizon_years = reference_horizon_years if reference_horizon_years is not None else getattr(snapshot, "benchmark_reference_horizon_years", None)
    reference_start_date = reference_start_date if reference_start_date is not None else getattr(snapshot, "benchmark_reference_start_date", None)
    reference_end_date = reference_end_date if reference_end_date is not None else getattr(snapshot, "benchmark_reference_end_date", None)
    reference_decision_time = reference_decision_time if reference_decision_time is not None else getattr(snapshot, "benchmark_reference_decision_time", None)
    if reference_portfolio_ids is None:
        reference_portfolio_ids = tuple(getattr(snapshot, "benchmark_reference_portfolio_ids", ()))
    vwce_anchor = vwce_anchor if vwce_anchor is not None else getattr(snapshot, "vwce_anchor_evidence", None)
    vwce_listing_id = vwce_listing_id if vwce_listing_id is not None else getattr(snapshot, "vwce_listing_id", None)
    vwce_conversion_evidence = vwce_conversion_evidence if vwce_conversion_evidence is not None else getattr(snapshot, "vwce_conversion_evidence", None)
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
    reference_resolution: AnalysisResolution | None = None
    selected_vwce_anchor_digest = None if vwce_anchor is None else vwce_anchor.digest()
    benchmark_reference: dict[str, object]
    if reference_registry is not None:
        benchmark_reference, reference_resolution = _resolve_reference_evidence(
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
            selected_vwce_anchor_digest=selected_vwce_anchor_digest,
        )
    else:
        benchmark_reference = unavailable_reference_projection(blocker="reference_registry_unavailable")
    reference_context = _reference_context_from_resolution(reference_registry, reference_resolution, benchmark_reference)
    binding = replace(binding, price_source_checksum=_service_input_checksum(snapshot, binding, reference_context))
    analysis = replace(analysis, snapshot_binding=binding)
    services = _service_evidence(snapshot, analysis, reference_context=reference_context)
    services["capability_matrix"] = _capability_matrix_evidence(governed_holdings, target_capabilities)
    services["benchmark_reference"] = benchmark_reference
    if vwce_anchor is not None:
        anchor_digest = vwce_anchor.digest()
        registry_anchor_matches = sum(
            item.digest() == anchor_digest and item.status == "available"
            for item in reference_registry.vwce_anchors
        )
        registry_anchor_bound = registry_anchor_matches == 1
        if not registry_anchor_bound and isinstance(benchmark_reference, dict):
            blockers = list(benchmark_reference.get("blockers", ()))
            blockers.append("vwce_anchor:registry_membership_unavailable")
            benchmark_reference["blockers"] = list(dict.fromkeys(blockers))
            benchmark_reference["status"] = "unavailable"
        anchor_resolution = _resolve_profile_anchor(
            vwce_anchor,
            listing_id=vwce_listing_id,
            currency=reference_currency,
            horizon_years=reference_horizon_years,
            effective_date=reference_start_date,
            decision_time=reference_decision_time,
            conversion_evidence=vwce_conversion_evidence,
        )
        if (
            reference_resolution is None
            or reference_resolution.blockers
            or not registry_anchor_bound
        ):
            reason = (
                "registry_anchor_membership_unavailable"
                if not registry_anchor_bound
                else "reference_resolution_incomplete"
            )
            anchor_resolution = replace(anchor_resolution, status="unavailable", reason=reason)
        services["profile_relative"] = project_profile_relative_analysis(
            {"analysis_id": candidate.candidate_id, "analysis_status": "available"},
            anchor_resolution,
            anchor=vwce_anchor,
            registry=reference_registry,
            conversion_evidence=vwce_conversion_evidence,
        )
    else:
        services["profile_relative"] = project_profile_relative_analysis(
            {"analysis_id": candidate.candidate_id, "analysis_status": "available"},
            VwceAnchorResolution(
                "unavailable",
                None,
                vwce_listing_id,
                "vwce_anchor_unavailable",
                output_currency=reference_currency,
                horizon_years=reference_horizon_years,
            ),
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
    selected_vwce_anchor_digest: str | None,
) -> tuple[dict[str, object], AnalysisResolution | None]:
    registry_hash = str(registry.as_payload()["registry_hash"])
    selected_records = (
        {}
        if selected_vwce_anchor_digest is None
        else {"vwce_anchor": selected_vwce_anchor_digest}
    )

    def unavailable(blocker: str) -> tuple[dict[str, object], AnalysisResolution | None]:
        return (
            {
                **unavailable_reference_projection(registry_hash=registry_hash, blocker=blocker),
                "provenance": {
                    "registry_hash": registry_hash,
                    "selected_records": selected_records,
                    "selected_vwce_anchor_digest": selected_vwce_anchor_digest,
                },
            },
            None,
        )

    if (
        instrument is None
        or currency is None
        or horizon_years is None
        or start_date is None
        or end_date is None
        or decision_time is None
    ):
        return unavailable("reference_resolution_inputs_unavailable")
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
        return unavailable(f"reference_resolution_invalid:{type(exc).__name__}")
    try:
        projection = registry.ui_projection(
            resolution,
            selected_vwce_anchor_digest=selected_vwce_anchor_digest,
        )
    except BenchmarkReferenceError as exc:
        return unavailable(f"reference_projection_invalid:{type(exc).__name__}")
    projection["status"] = "available" if not resolution.blockers else "unavailable"
    projection["benchmark_data_id"] = _benchmark_data_id(registry, resolution)
    return projection, resolution


def _benchmark_data_id(
    registry: CanonicalBenchmarkRegistry,
    resolution: AnalysisResolution,
) -> str | None:
    if resolution.benchmark.status != "available" or resolution.cash.status != "available":
        return None
    selected = resolution.benchmark
    matches = [
        item for item in registry.benchmarks
        if item.benchmark_id == selected.selected_id
        and item.version == selected.version
        and item.digest() == selected.content_hash
    ]
    if len(matches) != 1:
        return None
    constituents = tuple(matches[0].constituents)
    if selected.selected_id in constituents:
        return selected.selected_id
    return constituents[0] if len(constituents) == 1 else None


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
    normalized_listing_id = listing_id.strip() if isinstance(listing_id, str) and listing_id.strip() else None
    if (
        normalized_listing_id is None
        or currency is None
        or horizon_years is None
        or effective_date is None
        or decision_time is None
    ):
        return replace(
            VwceAnchorResolution(
                "unavailable",
                anchor.canonical_share_class_id,
                normalized_listing_id,
                "listing_unavailable_at_cutoff" if normalized_listing_id is None else "profile_alignment_inputs_unavailable",
                anchor_digest=anchor.digest(),
            ),
            output_currency=currency,
            horizon_years=horizon_years,
        )
    try:
        return resolve_vwce_anchor(
            anchor,
            listing_id=normalized_listing_id,
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
            normalized_listing_id,
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
    _assert_no_execution(analysis.service_evidence)
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


def _service_evidence(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    reference_context: CanonicalReferenceContext | None = None,
) -> dict[str, object]:
    """Compose canonical portfolio services for one snapshot-bound what-if.

    This function is deliberately an orchestration boundary.  It does not
    calculate risk, optimisation, stress or attribution metrics itself; each
    producer receives the same target allocation and its own explicit
    unavailable state is retained when an input is missing.
    """

    prices = _bound_service_prices(snapshot, analysis, reference_context)
    benchmark_prices = _bound_service_prices(snapshot, analysis, reference_context, investable_only=False)
    allocation = _service_allocation(snapshot, analysis)
    target = _target_allocation(allocation)
    current_weights = {row.instrument_id: row.current_weight for row in analysis.allocations}
    target_weights = {row.instrument_id: row.target_weight for row in analysis.allocations}
    usable_returns = returns_from_adjusted_prices(prices)
    # A price row alone is not return coverage.  Keep only instruments with
    # at least one finite adjusted return before any producer is invoked;
    # otherwise one-row instruments can be silently retained and filled as
    # zero-risk by downstream covariance code.
    usable_ids = {
        str(column)
        for column in usable_returns.columns
        if usable_returns[column].notna().any()
    }
    missing_target_ids = tuple(sorted(identifier for identifier, weight in target_weights.items() if weight > 0 and identifier not in usable_ids))
    missing_current_exit_ids = tuple(
        sorted(identifier for identifier, weight in current_weights.items() if weight > 0 and target_weights.get(identifier, 0.0) <= 0 and identifier not in usable_ids)
    )
    missing_optimizer_ids = tuple(sorted(set(missing_target_ids) | set(missing_current_exit_ids)))
    has_target_exposure = any(weight > 0 for weight in target_weights.values())
    complete_target_returns = has_target_exposure and not missing_target_ids
    limits = getattr(getattr(snapshot, "config"), "risks").portfolio_limits
    constraints = OptimiserConstraints(
        cash_weight=analysis.candidate.cash_weight,
        max_weight=float(getattr(limits, "max_single_etf_weight", 1.0)),
        turnover_limit=float(getattr(limits, "max_monthly_turnover", 1.0)),
    )
    evidence: dict[str, object] = {
        "cost": {
            "model_id": analysis.cost.model_id,
            "status": "available",
            "total_order_value_eur": analysis.cost.total_order_value_eur,
            "total_cost_eur": analysis.cost.total_cost_eur,
            "weighted_cost_bps": analysis.cost.weighted_cost_bps,
            "execution_allowed": False,
        },
        "optimiser": _unavailable_service("adjusted-price returns unavailable"),
        "optimiser_comparison": _unavailable_service("adjusted-price returns unavailable"),
        "factor_risk": _unavailable_service("adjusted-price returns or factor descriptors unavailable"),
        "risk": _unavailable_service("adjusted-price returns unavailable"),
        "rebalancing": _unavailable_service("rebalance inputs unavailable"),
        "scenarios": _unavailable_service("no explicit scenario is bound to this snapshot"),
        "attribution": _unavailable_service("adjusted-price returns unavailable"),
    }

    # Factor risk is a direct input to robust covariance.  Use the complete
    # bound allocation and selected holdings lineage, not an arbitrary subset
    # of the price universe.
    factor_report: dict[str, object] | None = None
    try:
        factor_report = build_factor_risk_report(
            prices if complete_target_returns else pd.DataFrame(),
            target,
            _bound_service_features(snapshot, analysis, reference_context),
            _bound_holdings(snapshot, analysis),
        )
        evidence["factor_risk"] = _add_missing_price_evidence(
            _report_projection(factor_report, coverage_keys=("coverage",)), missing_target_ids
        )
    except (ArithmeticError, KeyError, TypeError, ValueError):
        evidence["factor_risk"] = _unavailable_service("factor risk service evidence unavailable")

    try:
        if not has_target_exposure:
            raise ValueError("no invested target exposure")
        if missing_optimizer_ids:
            raise ValueError(f"required instruments missing usable adjusted returns: {', '.join(missing_optimizer_ids)}")
        optimiser, returns = build_portfolio_optimiser(prices)
        comparison = optimiser.compare(
            tuple(OPTIMISER_METHODS),
            constraints=constraints,
            current_weights=current_weights,
        )
        comparison_rows = _comparison_rows(comparison, analysis, constraints)
        equal_weight = next(
            (row for row in comparison_rows if row.get("method") == "equal_weight"),
            _unavailable_service("equal-weight baseline unavailable"),
        )
        current_baseline = _current_baseline(current_weights, analysis, constraints)
        evidence["optimiser_comparison"] = {
            "status": "available" if comparison_rows else "unavailable",
            "methods": comparison_rows,
            "baseline": {"equal_weight": equal_weight, "current": current_baseline},
            "constraints": _optimiser_constraint_projection(constraints),
            "cost_assumptions": {
                "model_id": analysis.cost.model_id,
                "candidate_cost_eur": analysis.cost.total_cost_eur,
                "candidate_cost_bps": analysis.cost.weighted_cost_bps,
                "turnover_limit": constraints.turnover_limit,
                "execution_allowed": False,
            },
            "returns_observations": int(len(returns)),
            "execution_allowed": False,
        }
        # Keep the single-solution projection for existing consumers.  The
        # comparison is authoritative for method availability and feasibility.
        selected = next((row for row in comparison_rows if row.get("method") == "minimum_variance"), None)
        try:
            # Retain the established single-solution projection for existing
            # consumers; comparison remains the source of method coverage.
            solution = optimiser.solve(
                "minimum_variance",
                constraints=constraints,
                current_weights=current_weights,
            )
            evidence["optimiser"] = _solution_projection(solution)
        except (ArithmeticError, KeyError, TypeError, ValueError, AttributeError):
            evidence["optimiser"] = selected or _unavailable_service("minimum_variance solution unavailable")
    except AttributeError:
        # Older test doubles may only implement solve; retain compatibility
        # while production uses the complete comparison contract above.
        try:
            if not has_target_exposure:
                raise ValueError("no invested target exposure")
            if missing_optimizer_ids:
                raise ValueError(f"required instruments missing usable adjusted returns: {', '.join(missing_optimizer_ids)}")
            optimiser, returns = build_portfolio_optimiser(prices)
            solution = optimiser.solve("minimum_variance", constraints=constraints, current_weights=current_weights)
            evidence["optimiser"] = _solution_projection(solution)
            evidence["optimiser_comparison"] = {
                "status": "partial",
                "methods": [_solution_projection(solution)],
                "baseline": {"equal_weight": "unavailable", "current": _current_baseline(current_weights, analysis, constraints)},
                "constraints": _optimiser_constraint_projection(constraints),
                "cost_assumptions": {
                    "model_id": analysis.cost.model_id,
                    "candidate_cost_eur": analysis.cost.total_cost_eur,
                    "candidate_cost_bps": analysis.cost.weighted_cost_bps,
                    "turnover_limit": constraints.turnover_limit,
                    "execution_allowed": False,
                },
                "returns_observations": int(len(returns)),
                "execution_allowed": False,
            }
        except (ArithmeticError, KeyError, TypeError, ValueError, AttributeError):
            evidence["optimiser"] = _unavailable_service(
                f"required instruments missing usable adjusted returns: {', '.join(missing_optimizer_ids)}"
                if missing_optimizer_ids
                else "no invested target exposure" if not has_target_exposure else "portfolio optimiser service evidence unavailable"
            )
    except (ArithmeticError, KeyError, TypeError, ValueError):
        evidence["optimiser"] = _unavailable_service(
            f"required instruments missing usable adjusted returns: {', '.join(missing_optimizer_ids)}"
            if missing_optimizer_ids
            else "no invested target exposure" if not has_target_exposure else "portfolio optimiser service evidence unavailable"
        )

    try:
        risk = build_robust_risk_report(
            prices if complete_target_returns else pd.DataFrame(),
            target,
            factor_report=factor_report,
            bootstrap_reps=0,
        )
        evidence["risk"] = _add_missing_price_evidence(
            _report_projection(risk, coverage_keys=("diagnostics", "coverage")), missing_target_ids
        )
    except (ArithmeticError, KeyError, TypeError, ValueError):
        evidence["risk"] = _unavailable_service("robust risk service evidence unavailable")

    inapplicable = rebalance_inapplicable_instruments(
        snapshot, _bound_holdings(snapshot, analysis), set(target_weights)
    )
    if inapplicable:
        evidence["rebalancing"] = _unavailable_service(
            f"ETF-only rebalance is inapplicable: {', '.join(inapplicable)}"
        )
    else:
        try:
            rebalance = build_rebalance_report(
                getattr(snapshot, "config"),
                _bound_holdings(snapshot, analysis),
                target_weights,
                target_cash_weight=analysis.candidate.cash_weight,
                portfolio_value_eur=analysis.candidate.analysis_notional_eur,
                constraints=RebalanceConstraints(
                    cash_buffer_weight=float(getattr(limits, "cash_min_weight", 0.0)),
                    min_trade_eur=float(getattr(limits, "min_trade_value_eur", 0.0)),
                ),
                tax_lots=_optional_frame(snapshot, "tax_lots"),
            )
            evidence["rebalancing"] = {
                "status": "available" if rebalance.feasible else "partial",
                "model_version": rebalance.model_version,
                "feasible": rebalance.feasible,
                "trade_count": len(rebalance.trades),
                "turnover_limit": float(getattr(limits, "max_monthly_turnover", 1.0)),
                "tax_status": rebalance.tax_status,
                "tax_jurisdiction": rebalance.tax_jurisdiction,
                "warnings": list(rebalance.warnings),
                "assumptions": dict(rebalance.assumptions),
                "execution_allowed": False,
            }
        except (ArithmeticError, KeyError, TypeError, ValueError):
            evidence["rebalancing"] = _unavailable_service("rebalance service evidence unavailable")

    try:
        attribution = build_performance_attribution(
            benchmark_prices if complete_target_returns else pd.DataFrame(),
            target,
            factor_returns=_frame_value(factor_report, "factor_returns"),
            factor_exposures=_frame_value(factor_report, "exposure_matrix"),
            costs=_bound_optional_frame(snapshot, "costs", analysis, reference_context),
            cashflows=_bound_optional_frame(snapshot, "cashflows", analysis, reference_context),
            decisions=_bound_optional_frame(snapshot, "decisions", analysis, reference_context),
            reference_context=reference_context,
        )
        evidence["attribution"] = _add_missing_price_evidence(
            _report_projection(attribution, coverage_keys=("coverage",)), missing_target_ids
        )
    except (ArithmeticError, KeyError, TypeError, ValueError):
        evidence["attribution"] = _unavailable_service("portfolio attribution service evidence unavailable")

    evidence["scenarios"] = _scenario_evidence(
        snapshot,
        _target_allocation(_service_allocation(snapshot, analysis, include_unsupported=True)),
        factor_report,
        analysis,
    )
    evidence["execution_allowed"] = False
    return evidence


def _unavailable_service(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "reason": reason, "execution_allowed": False}


def _service_allocation(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    include_unsupported: bool = False,
) -> pd.DataFrame:
    """Build one target-bound allocation frame for all portfolio producers."""

    configured = getattr(snapshot, "config").universe.by_id()
    rows: list[dict[str, object]] = []
    for item in analysis.allocations:
        if item.capability_status != "supported" and not include_unsupported:
            continue
        instrument = configured.get(item.instrument_id)
        rows.append(
            {
                "etf_id": item.instrument_id,
                "instrument_id": item.instrument_id,
                "weight": item.target_weight,
                "current_weight": item.current_weight,
                "target_weight": item.target_weight,
                "market_value_eur": item.target_weight * analysis.candidate.analysis_notional_eur,
                "asset_class": getattr(instrument, "asset_class", item.asset_type),
                "asset_type": item.asset_type,
                "sector": getattr(instrument, "sector", None),
                "region": getattr(instrument, "region", None),
                "currency": getattr(instrument, "currency", None),
                "capability_status": item.capability_status,
            }
        )
    return pd.DataFrame(rows)


def _target_allocation(allocation: pd.DataFrame) -> pd.DataFrame:
    """Adapt the target to producers whose legacy weight column is current_weight."""

    if allocation.empty:
        return allocation.copy()
    result = allocation.loc[allocation["target_weight"] > 0].copy(deep=True)
    if result.empty:
        return result
    if "weight" in result.columns:
        result = result.drop(columns=["weight"])
    result["current_weight"] = result["target_weight"]
    return result


def _bound_service_prices(
    snapshot: object,
    analysis: PortfolioAnalysis,
    reference_context: CanonicalReferenceContext | None,
    *,
    investable_only: bool = True,
) -> pd.DataFrame:
    prices = getattr(snapshot, "prices", pd.DataFrame())
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.DataFrame()
    result = prices.copy(deep=True)
    declaration = None if reference_context is None else reference_context.resolution
    if declaration is not None:
        window = declaration.declaration
        result = clip_to_decision_window(
            result,
            start_date=window.start_date,
            end_date=window.end_date,
            decision_time=window.decision_time,
        )
    if analysis.snapshot_binding is not None and analysis.snapshot_binding.as_of:
        cutoff = pd.to_datetime(analysis.snapshot_binding.as_of, errors="coerce", utc=True)
        if pd.notna(cutoff) and "date" in result.columns:
            if len(str(analysis.snapshot_binding.as_of)) == 10:
                cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            dates = pd.to_datetime(result["date"], errors="coerce", utc=True, format="mixed")
            result = result.loc[dates <= cutoff].copy()
    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce", utc=True, format="mixed")
    universe = set(_service_allocation(snapshot, analysis).get("etf_id", pd.Series(dtype=str)).astype(str))
    if investable_only and "etf_id" in result.columns:
        result = result.loc[result["etf_id"].astype(str).isin(universe)].copy()
    return result


def _bound_service_features(
    snapshot: object,
    analysis: PortfolioAnalysis,
    reference_context: CanonicalReferenceContext | None,
) -> pd.DataFrame | None:
    features = getattr(snapshot, "latest_features", None)
    if not isinstance(features, pd.DataFrame):
        features = getattr(snapshot, "features", None)
    if not isinstance(features, pd.DataFrame):
        return None
    result = features.copy(deep=True)
    resolution = None if reference_context is None else reference_context.resolution
    date_column = "date" if "date" in result.columns else "as_of_date" if "as_of_date" in result.columns else None
    if resolution is not None and date_column is not None:
        window = resolution.declaration
        if date_column != "date":
            result = result.rename(columns={date_column: "date"})
        result = clip_to_decision_window(
            result,
            start_date=window.start_date,
            end_date=window.end_date,
            decision_time=window.decision_time,
        )
        if date_column != "date":
            result = result.rename(columns={"date": date_column})
    if analysis.snapshot_binding is not None and analysis.snapshot_binding.as_of and date_column is not None:
        cutoff = pd.to_datetime(analysis.snapshot_binding.as_of, errors="coerce", utc=True)
        if pd.notna(cutoff):
            if len(str(analysis.snapshot_binding.as_of)) == 10:
                cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            dates = pd.to_datetime(result[date_column], errors="coerce", utc=True, format="mixed")
            result = result.loc[dates <= cutoff].copy()
    if date_column is not None:
        result[date_column] = pd.to_datetime(result[date_column], errors="coerce", utc=True, format="mixed")
    knowledge_column = next((column for column in ("known_at", "available_at", "imported_at") if column in result.columns), None)
    if knowledge_column is not None:
        cutoff = _reference_cutoff(reference_context, analysis.snapshot_binding)
        known = pd.to_datetime(result[knowledge_column], errors="coerce", utc=True, format="mixed")
        result = result.loc[known <= cutoff].copy()
    return result


def _add_missing_price_evidence(projection: dict[str, object], missing: tuple[str, ...]) -> dict[str, object]:
    if not missing:
        return projection
    result = dict(projection)
    warnings = [str(item) for item in result.get("warnings", ())]
    warnings.append("positive_target_missing_adjusted_price:" + ",".join(missing))
    result["warnings"] = list(dict.fromkeys(warnings))
    result["status"] = "partial" if result.get("status") == "available" else result.get("status", "unavailable")
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        coverage = dict(coverage)
        coverage["missing_target_instruments"] = list(missing)
        result["coverage"] = coverage
    return result


def _bound_holdings(snapshot: object, analysis: PortfolioAnalysis) -> pd.DataFrame:
    holdings = getattr(snapshot, "holdings", pd.DataFrame())
    view = "combined" if analysis.snapshot_binding is None else analysis.snapshot_binding.holdings_view
    try:
        return select_holdings_view(holdings, view)
    except (TypeError, ValueError):
        return pd.DataFrame()


def _optional_frame(snapshot: object, name: str) -> pd.DataFrame | None:
    value = getattr(snapshot, name, None)
    return value.copy(deep=True) if isinstance(value, pd.DataFrame) else None


def _bound_optional_frame(
    snapshot: object,
    name: str,
    analysis: PortfolioAnalysis,
    reference_context: CanonicalReferenceContext | None,
) -> pd.DataFrame | None:
    frame = _optional_frame(snapshot, name)
    if frame is None:
        return None
    resolution = None if reference_context is None else reference_context.resolution
    date_column = "date" if "date" in frame.columns else "as_of_date" if "as_of_date" in frame.columns else None
    if resolution is not None and date_column is not None:
        window = resolution.declaration
        if date_column != "date":
            frame = frame.rename(columns={date_column: "date"})
        frame = clip_to_decision_window(
            frame,
            start_date=window.start_date,
            end_date=window.end_date,
            decision_time=window.decision_time,
        )
        if date_column != "date":
            frame = frame.rename(columns={"date": date_column})
    if analysis.snapshot_binding is not None and analysis.snapshot_binding.as_of and date_column is not None:
        cutoff = _snapshot_cutoff(analysis.snapshot_binding.as_of)
        dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True, format="mixed")
        frame = frame.loc[dates <= cutoff].copy()
    knowledge_column = next((column for column in ("known_at", "available_at", "imported_at") if column in frame.columns), None)
    if knowledge_column is not None:
        cutoff = _reference_cutoff(reference_context, analysis.snapshot_binding)
        known = pd.to_datetime(frame[knowledge_column], errors="coerce", utc=True, format="mixed")
        frame = frame.loc[known <= cutoff].copy()
    return frame


def _snapshot_cutoff(value: object) -> pd.Timestamp:
    cutoff = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.notna(cutoff) and len(str(value)) == 10:
        cutoff = cutoff + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return cutoff


def _reference_cutoff(
    reference_context: CanonicalReferenceContext | None,
    binding: PortfolioSnapshotBinding | None,
) -> pd.Timestamp:
    snapshot_cutoff = _snapshot_cutoff(binding.as_of if binding is not None else "")
    if reference_context is not None and reference_context.resolution is not None:
        reference_cutoff = pd.to_datetime(reference_context.resolution.declaration.decision_time, utc=True)
        if pd.isna(snapshot_cutoff):
            return reference_cutoff
        if pd.isna(reference_cutoff):
            return snapshot_cutoff
        return min(reference_cutoff, snapshot_cutoff)
    return snapshot_cutoff


def _frame_value(report: Mapping[str, object] | None, key: str) -> pd.DataFrame | None:
    value = None if report is None else report.get(key)
    return value if isinstance(value, pd.DataFrame) else None


def _report_projection(report: Mapping[str, object], *, coverage_keys: tuple[str, ...]) -> dict[str, object]:
    """Retain canonical report fields while making status/coverage explicit."""

    result = {str(key): _projection_value(value) for key, value in report.items()}
    result["status"] = str(result.get("status", "unavailable"))
    result["warnings"] = [str(item) for item in result.get("warnings", ())]
    if "coverage" in result:
        result["coverage"] = _projection_value(result["coverage"])
    else:
        result["coverage"] = {
            key: result[key]
            for key in coverage_keys
            if key in result
        }
        result["coverage"] = {
            "status": result["status"],
            **result["coverage"],
        }
    result["execution_allowed"] = False
    return result


def _projection_value(value: object) -> object:
    """Detach dataframe/numpy values so repeated analysis remains comparable."""

    if isinstance(value, pd.DataFrame):
        return {
            "columns": [str(column) for column in value.columns],
            "index_name": None if value.index.name is None else str(value.index.name),
            "index": [_projection_value(item) for item in value.index.tolist()],
            "data": [
                [_projection_value(item) for item in row]
                for row in value.itertuples(index=False, name=None)
            ],
        }
    if isinstance(value, pd.Series):
        return {str(key): _projection_value(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _projection_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_projection_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _solution_projection(solution: object) -> dict[str, object]:
    return {
        "status": str(getattr(solution, "status", "unavailable")),
        "method": str(getattr(solution, "method", "unavailable")),
        "feasible": bool(getattr(solution, "feasible", False)),
        "weights": {
            str(key): float(value)
            for key, value in getattr(solution, "weights", pd.Series(dtype=float)).items()
        },
        "warnings": [str(item) for item in getattr(solution, "warnings", ())],
        "model_version": str(getattr(solution, "model_version", "portfolio-optimiser.v1")),
        "execution_allowed": False,
    }


def _comparison_rows(
    comparison: object,
    analysis: PortfolioAnalysis,
    constraints: OptimiserConstraints,
) -> list[dict[str, object]]:
    if not isinstance(comparison, pd.DataFrame) or comparison.empty:
        return []
    rows: list[dict[str, object]] = []
    for raw in comparison.to_dict("records"):
        row: dict[str, object] = {}
        for key, value in raw.items():
            if isinstance(value, float) and pd.isna(value):
                row[key] = None
            elif isinstance(value, (str, int, float, bool)) or value is None:
                row[key] = value
            else:
                row[key] = str(value)
        row["candidate_cost_eur"] = analysis.cost.total_cost_eur
        row["candidate_cost_bps"] = analysis.cost.weighted_cost_bps
        row["turnover_limit"] = constraints.turnover_limit
        row["execution_allowed"] = False
        rows.append(row)
    return rows


def _current_baseline(
    current_weights: Mapping[str, float],
    analysis: PortfolioAnalysis,
    constraints: OptimiserConstraints,
) -> dict[str, object]:
    values = {str(key): float(value) for key, value in sorted(current_weights.items())}
    total = sum(values.values())
    expected_invested = 1.0 - constraints.cash_weight
    warnings: list[str] = []
    if not math.isclose(total, expected_invested, abs_tol=0.000_001):
        warnings.append("current_weight_sum_does_not_match_cash_constraint")
    if any(value < constraints.min_weight - 0.000_001 for value in values.values()):
        warnings.append("current_weight_below_min_constraint")
    if any(value > constraints.max_weight + 0.000_001 for value in values.values()):
        warnings.append("current_weight_above_max_constraint")
    return {
        "method": "current",
        "status": "available",
        "feasible": not warnings and all(value >= 0 for value in values.values()),
        "weights": values,
        "turnover": 0.0,
        "cost_eur": 0.0,
        "cost_bps": 0.0,
        "cash_weight": max(0.0, 1.0 - total),
        "source_id": analysis.candidate.source_as_of or "current_snapshot",
        "constraints": _optimiser_constraint_projection(constraints),
        "warnings": warnings,
        "execution_allowed": False,
    }


def _optimiser_constraint_projection(constraints: OptimiserConstraints) -> dict[str, object]:
    return {
        "cash_weight": float(constraints.cash_weight),
        "min_weight": float(constraints.min_weight),
        "max_weight": float(constraints.max_weight),
        "turnover_limit": constraints.turnover_limit,
        "execution_allowed": False,
    }


def _reference_context_from_resolution(
    registry: CanonicalBenchmarkRegistry | None,
    resolution: AnalysisResolution | None,
    projection: Mapping[str, object],
) -> CanonicalReferenceContext | None:
    if not isinstance(registry, CanonicalBenchmarkRegistry):
        return None
    if resolution is not None:
        return CanonicalReferenceContext(registry, resolution)
    return CanonicalReferenceContext(registry, None, legacy_projection=projection)


def _service_input_checksum(
    snapshot: object,
    binding: PortfolioSnapshotBinding,
    reference_context: CanonicalReferenceContext | None,
) -> str:
    optional_frames = {
        name: _frame_checksum(getattr(snapshot, name, None))
        for name in ("features", "latest_features", "tax_lots", "costs", "cashflows", "decisions")
    }
    scenario_payload = {
        name: _jsonable(getattr(snapshot, name, None))
        for name in ("portfolio_scenarios", "stress_scenarios", "scenarios", "scenario")
        if getattr(snapshot, name, None) is not None
    }
    payload = {
        "base_price_checksum": _prices_checksum(getattr(snapshot, "prices", pd.DataFrame())),
        "price_source_revision": binding.price_source_revision,
        "optional_frames": optional_frames,
        "scenarios": scenario_payload,
        "reference_identity": None if reference_context is None else reference_context.identity,
        "holdings_view": binding.holdings_view,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, allow_nan=False).encode("utf-8")).hexdigest()


def _frame_checksum(value: object) -> str | None:
    if not isinstance(value, pd.DataFrame):
        return None
    return hashlib.sha256(
        value.to_json(orient="split", date_format="iso", date_unit="ns", double_precision=15, default_handler=str).encode("utf-8")
    ).hexdigest()


def _scenario_evidence(
    snapshot: object,
    allocation: pd.DataFrame,
    factor_report: Mapping[str, object] | None,
    analysis: PortfolioAnalysis,
) -> dict[str, object]:
    raw = next(
        (
            getattr(snapshot, name, None)
            for name in ("portfolio_scenarios", "stress_scenarios", "scenarios", "scenario")
            if getattr(snapshot, name, None) is not None
        ),
        None,
    )
    if raw is None:
        return _unavailable_service("no explicit scenario is bound to this snapshot")
    values = raw if isinstance(raw, (list, tuple)) else (raw,)
    results: list[dict[str, object]] = []
    exposures = _frame_value(factor_report, "factor_exposures")
    missing_exposure = []
    if "capability_status" in allocation.columns:
        missing_exposure = [
            {"instrument_id": str(row["instrument_id"]), "weight": float(row["current_weight"]), "reason": str(row["capability_status"])}
            for row in allocation.to_dict("records")
            if float(row.get("current_weight", 0.0)) > 0 and str(row.get("capability_status")) != "supported"
        ]
    scenario_input = (
        allocation.loc[allocation["capability_status"].eq("supported")].copy()
        if "capability_status" in allocation.columns
        else allocation
    )
    for item in values:
        scenario = item
        if isinstance(item, Mapping):
            try:
                scenario = StressScenario(**dict(item))
            except (StressScenarioError, TypeError, ValueError):
                results.append({"status": "unavailable", "reason": "scenario input is invalid", "execution_allowed": False})
                continue
        if not isinstance(scenario, StressScenario):
            results.append({"status": "unavailable", "reason": "scenario input is not canonical", "execution_allowed": False})
            continue
        try:
            scenario_allocation = scenario_input.copy()
            if "instrument_id" not in scenario_allocation.columns and "etf_id" in scenario_allocation.columns:
                scenario_allocation = scenario_allocation.rename(columns={"etf_id": "instrument_id"})
            elif "instrument_id" in scenario_allocation.columns and "etf_id" in scenario_allocation.columns:
                scenario_allocation = scenario_allocation.drop(columns=["etf_id"])
            result = run_stress_scenario(
                scenario,
                scenario_allocation,
                factor_exposures=exposures,
                notional=analysis.candidate.analysis_notional_eur,
            )
            payload = result.to_payload()
            if missing_exposure:
                payload["status"] = "partial" if payload.get("status") != "unavailable" else "unavailable"
                coverage = dict(payload.get("coverage", {}))
                coverage["candidate_instrument_count"] = int(len(allocation))
                coverage["missing_exposure"] = missing_exposure
                payload["coverage"] = coverage
                limitations = list(payload.get("limitations", ()))
                limitations.append("Some candidate exposure is unsupported by the scenario producer.")
                payload["limitations"] = limitations
            results.append({**payload, "execution_allowed": False})
        except (ArithmeticError, KeyError, TypeError, ValueError, StressScenarioError):
            results.append({"scenario_id": scenario.scenario_id, "status": "unavailable", "reason": "scenario service evidence unavailable", "execution_allowed": False})
    if not results:
        return _unavailable_service("no valid scenario is bound to this snapshot")
    return {
        "status": "partial" if missing_exposure else "available" if any(item.get("status") == "available" for item in results) else "partial",
        "results": results,
        "source_snapshot": analysis.snapshot_binding.snapshot_id if analysis.snapshot_binding else None,
        "execution_allowed": False,
    }


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
