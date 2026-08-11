"""Application facade and persistence boundary for local portfolio candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import sqlite3
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
from etf_cockpit.application.overlap import build_direct_overlap_view, direct_overlap_payload
from etf_cockpit.application.portfolio_optimiser import build_portfolio_optimiser
from etf_cockpit.portfolio.optimiser import OptimiserConstraints
from etf_cockpit.portfolio.robust_risk import build_robust_risk_report
from etf_cockpit.governance.capability_scope import InstrumentDescriptor, resolve_instrument_capability
from etf_cockpit.governance.product_scope import load_strategy_scope


PORTFOLIO_SANDBOX_ENTITY = "portfolio_sandbox"
PORTFOLIO_SANDBOX_RESULT_ENTITY = "portfolio_sandbox_result"
_RESULT_FIELDS = frozenset({
    "schema_version", "candidate_id", "source_snapshot", "before_after", "allocations", "holdings",
    "constraints", "marginal_effects", "why_not", "overlap", "warnings", "cost", "service_evidence",
    "proposal_boundary", "execution_allowed", "payload_checksum",
})
_SOURCE_FIELDS = frozenset({"account_id", "portfolio_id", "snapshot_id", "source_revision", "source_checksum", "as_of", "holdings_view", "execution_allowed"})


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
    return create_candidate(
        getattr(snapshot, "config"),
        holdings,
        name=name,
        analysis_notional_eur=analysis_notional_eur,
        target_weights=dict(target_weights),
        cash_weight=cash_weight,
        source_revision=str(getattr(snapshot, "universe_revision", "") or "unknown"),
        source_as_of=_source_as_of(snapshot),
    )


def analyse_portfolio_candidate(
    snapshot: object,
    candidate: PortfolioCandidate,
    *,
    account_id: str | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    holdings_view: str = "combined",
) -> PortfolioAnalysis:
    holdings = select_holdings_view(getattr(snapshot, "holdings"), holdings_view)
    governed_holdings = _governed_holdings(snapshot, holdings)
    selected_checksum = holdings_checksum(holdings)
    source_stale = (
        candidate.source_revision != str(getattr(snapshot, "universe_revision", "") or "unknown")
        or candidate.source_checksum != selected_checksum
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
    )
    analysis_candidate = replace(candidate, source_checksum=holdings_checksum(holdings))
    analysis = analyse_candidate(
        getattr(snapshot, "config"),
        governed_holdings,
        analysis_candidate,
        current_revision=str(getattr(snapshot, "universe_revision", "") or "unknown"),
        overlap=overlap,
    )
    if source_stale:
        analysis = replace(
            analysis,
            source_stale=True,
            warnings=tuple(dict.fromkeys(("Saved source binding changed; all derived values were re-evaluated from the current snapshot.", *analysis.warnings))),
        )
    binding = portfolio_snapshot_binding(
        snapshot,
        account_id=account_id,
        portfolio_id=portfolio_id,
        snapshot_id=snapshot_id,
        holdings_view=holdings_view,
    )
    services = _service_evidence(snapshot, analysis)
    services["capability_matrix"] = _capability_matrix_evidence(governed_holdings)
    return replace(analysis, snapshot_binding=binding, service_evidence=services)


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
    result_payload = portfolio_analysis_payload(analysis)
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
            record = store.get(PORTFOLIO_SANDBOX_ENTITY, identity)
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
    result_payload = None
    try:
        with TransactionalStore(root) as store:
            result = store.get(PORTFOLIO_SANDBOX_RESULT_ENTITY, identity)
            result_payload = None if result is None else dict(result.payload)
    except (OSError, sqlite3.Error, StorageSchemaError) as exc:
        raise PortfolioSandboxPersistenceError(f"local portfolio result storage is unavailable: {exc}") from exc
    result_payload = _validate_loaded_result(result_payload, candidate, analysis)
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
    selected_account = str(account_id or getattr(snapshot, "account_id", "default") or "default")
    selected_portfolio = str(portfolio_id or getattr(snapshot, "portfolio_id", "default") or "default")
    selected_snapshot = str(snapshot_id or getattr(snapshot, "snapshot_id", "") or f"{selected_portfolio}:{revision}:{checksum[:12]}")
    return PortfolioSnapshotBinding(
        account_id=selected_account,
        portfolio_id=selected_portfolio,
        snapshot_id=selected_snapshot,
        source_revision=revision,
        source_checksum=checksum,
        as_of=_source_as_of(snapshot),
        holdings_view=str(holdings_view or "combined"),
    )


def portfolio_analysis_payload(analysis: PortfolioAnalysis) -> dict[str, object]:
    """Build the sandbox-specific deterministic result/export contract."""

    binding = analysis.snapshot_binding
    if binding is None:
        raise ValueError("portfolio sandbox result requires a source snapshot binding")
    body: dict[str, object] = {
        "schema_version": "portfolio_sandbox_result.v1",
        "candidate_id": analysis.candidate.candidate_id,
        "source_snapshot": None if binding is None else asdict(binding),
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
    violated = {
        item.name.removeprefix("instrument:")
        for item in analysis.constraints
        if item.status != "pass" and item.name.startswith("instrument:")
    }
    changes = []
    rejected = []
    for row in analysis.allocations:
        if abs(row.drift) <= 0 or row.marginal_effect not in {"increase", "decrease"}:
            rejected.append({"instrument_id": row.instrument_id, "reason": row.why_not or "no_trade"})
        elif row.capability_status != "supported":
            rejected.append({"instrument_id": row.instrument_id, "reason": row.capability_reason})
        elif row.instrument_id in violated:
            rejected.append({"instrument_id": row.instrument_id, "reason": "constraint_violation"})
        else:
            changes.append({"instrument_id": row.instrument_id, "weight_delta": row.drift})
    material = {
        "candidate_id": analysis.candidate.candidate_id,
        "candidate_source_checksum": analysis.candidate.source_checksum,
        "result_checksum": result["payload_checksum"],
        "source_snapshot": asdict(binding),
        "service_evidence": _jsonable(analysis.service_evidence),
    }
    return {
        "schema_version": "portfolio_sandbox_draft_handoff.v1",
        "boundary": "ISSUE-0130",
        "status": "pre_issue_0130_draft",
        "proposal_policy_evaluated": False,
        "candidate_id": analysis.candidate.candidate_id,
        "account_id": binding.account_id,
        "portfolio_id": binding.portfolio_id,
        "portfolio_revision": binding.source_revision,
        "source_snapshot_id": binding.snapshot_id,
        "source_snapshot": asdict(binding),
        "changes": changes,
        "rejected": rejected,
        "why_not": [{"instrument_id": key, "reason": value} for key, value in analysis.why_not],
        "evidence_checksum": _payload_checksum(material),
        "evidence": material,
        "proposal_allowed": False,
        "execution_allowed": False,
    }


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
    validated = build_portfolio_candidate(
        snapshot,
        name=str(payload.get("name", "")),
        analysis_notional_eur=payload.get("analysis_notional_eur"),
        target_weights=dict(target_pairs),
        cash_weight=payload.get("cash_weight"),
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


def _governed_holdings(snapshot: object, frame: pd.DataFrame) -> pd.DataFrame:
    """Annotate rows from the canonical resolver; never trust row assertions."""

    if not isinstance(frame, pd.DataFrame):
        raise ValueError("holdings evidence is unavailable")
    loaded = load_strategy_scope()
    if loaded.policy is None:
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
        descriptor_values = _descriptor_values(values, configured, loaded.policy)
        decision = None
        if descriptor_values is not None:
            try:
                decision = resolve_instrument_capability(
                    loaded.policy,
                    InstrumentDescriptor(**descriptor_values),
                    stage="portfolio",
                    horizon="1M",
                )
            except (TypeError, ValueError):
                decision = None
        statuses.append(_capability_status(decision))
        reasons.append(str(getattr(decision, "reason_code", "CLASSIFICATION_EVIDENCE_INCOMPLETE")))
    result["capability_status"] = statuses
    result["capability_reason"] = reasons
    return result


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
    return {
        "asset_type": asset_type,
        "security_type": security_type,
        "cfi_code": cfi_code,
        "exchange": _text_value(values.get("exchange")),
        "leveraged": _bool_flag(values.get("leveraged")),
        "inverse": _bool_flag(values.get("inverse")),
        "derivative": _bool_flag(values.get("derivative")),
        "crypto": _bool_flag(values.get("crypto")),
        "otc": _bool_flag(values.get("otc")),
        "complex_structured": _bool_flag(values.get("complex_structured")),
        "market_cap_usd": _optional_float(values.get("market_cap_usd")),
        "average_daily_value_usd": _optional_float(values.get("average_daily_value_usd")),
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


def _capability_matrix_evidence(frame: pd.DataFrame) -> list[dict[str, object]]:
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
    return rows


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
    if payload.get("execution_allowed") is not False:
        raise ValueError("saved portfolio sandbox result violates the no-execution contract")
    source = payload.get("source_snapshot")
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS or source.get("execution_allowed") is not False:
        raise ValueError("saved portfolio sandbox result source binding is malformed")
    current_source = None if analysis.snapshot_binding is None else asdict(analysis.snapshot_binding)
    if source != current_source:
        return None
    _assert_no_execution(payload)
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
    "load_portfolio_candidate",
    "save_portfolio_candidate",
]
