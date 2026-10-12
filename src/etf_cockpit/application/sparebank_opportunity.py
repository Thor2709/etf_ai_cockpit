"""Cockpit decision layer for accepted Sparebank intelligence runs (#718).

specialist run -> advisory opportunity input -> Cockpit repricing at a frozen
price -> comparative return -> existing optimiser inside independent ceilings
-> existing deterministic proposal policy -> at most one paper proposal.

Nothing here reconstructs specialist science, mutates a run, or grants order
authority.  Specialist fields (rank, scenarios, exposure range, maximum) are
inputs or ceilings only; final weights come from the Cockpit optimiser.  Every
missing or unverifiable input produces BLOCK/REVIEW with a stable reason code
instead of a guessed value.  ``execution_allowed`` is always False.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.portfolio.optimiser import OPTIMISER_MODEL_VERSION, OptimiserConstraints, PortfolioOptimiser
from etf_cockpit.portfolio.proposal_policy import (
    PROPOSAL_POLICY_VERSION,
    REQUIRED_GATES,
    GateEvidence,
    ProposalDecision,
    ProposalRequest,
    build_proposal_decision,
    save_proposal_decision,
)
from etf_cockpit.portfolio.sparebank_constraints import CeilingInputs, CeilingPolicy, CeilingResult, apply_ceiling, compute_ceilings

OPPORTUNITY_POLICY_VERSION = "sbi-opportunity.v1"
DECISION_SCHEMA = "sparebank-cockpit-decision.v1"
EXECUTION_ALLOWED = False
CANDIDATE_GROUP = "SBI_CANDIDATE"
CASH_ID = "CASH"
BLOCK, REVIEW, WARN = "BLOCK", "REVIEW", "WARN"

# gate -> issue categories feeding it (REQUIRED_GATES of the existing proposal policy plus two Sparebank gates)
_GATE_CATEGORIES = {
    "optimizer_output": ("optimiser",),
    "portfolio_state": ("context",),
    "data_freshness": ("freshness",),
    "model_confidence": ("confidence", "economics"),
    "liquidity": ("sizing",),
    "cost": ("economics",),
    "concentration": ("sizing",),
    "account_authority": ("authority",),
    "sparebank_run_validity": ("run", "lineage"),
    "sparebank_claim_integrity": ("identity", "claim"),
}


class DecisionConflict(RuntimeError):
    """An immutable decision/run record would be overwritten with different content."""


# ---------------------------------------------------------------------------- helpers


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _pos(value: object) -> bool:
    number = _num(value)
    return number is not None and number > 0


# ---------------------------------------------------------------------------- policy and context


@dataclass(frozen=True)
class OpportunityPolicy:
    """Conservative documented defaults (recorded in the gap-718 handoff)."""

    max_run_age_days: float = 45.0
    stale_action: str = BLOCK  # BLOCK | REVIEW, explicit freshness policy
    allow_degraded: bool = False  # False: DEGRADED runs route to REVIEW; True: eligible with tighter ceiling
    max_price_age_hours: float = 72.0
    disagreement_tolerance: float = 0.25  # relative gap, specialist vs generic standalone value
    default_horizon_years: float = 1.0
    min_excess_return: float = 0.02  # annual, net of costs, over the best realistic alternative
    standalone_scenario: str = "standalone"
    transition_scenario: str = "upside"
    accepted_milestones: tuple[str, ...] = ("approved", "completed", "effective", "closed")
    proposal_ttl_hours: float = 24.0
    optimiser_method: str = "robust_mean_risk"
    cash_weight: float = 0.0
    ceilings: CeilingPolicy = field(default_factory=CeilingPolicy)

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": OPPORTUNITY_POLICY_VERSION, "max_run_age_days": self.max_run_age_days, "stale_action": self.stale_action,
            "allow_degraded": self.allow_degraded, "max_price_age_hours": self.max_price_age_hours,
            "disagreement_tolerance": self.disagreement_tolerance, "default_horizon_years": self.default_horizon_years,
            "min_excess_return": self.min_excess_return, "standalone_scenario": self.standalone_scenario,
            "transition_scenario": self.transition_scenario, "accepted_milestones": list(self.accepted_milestones),
            "proposal_ttl_hours": self.proposal_ttl_hours, "optimiser_method": self.optimiser_method,
            "cash_weight": self.cash_weight, "ceilings": self.ceilings.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "OpportunityPolicy":
        c = dict(payload["ceilings"])
        c.pop("version", None)
        data = {k: v for k, v in payload.items() if k not in ("version", "ceilings")}
        data["accepted_milestones"] = tuple(data["accepted_milestones"])
        return cls(**data, ceilings=CeilingPolicy(**c))


@dataclass(frozen=True)
class DecisionContext:
    """The frozen Cockpit market/portfolio context.  None means 'not supplied' and blocks, never defaults."""

    instrument_id: str
    decision_time: str
    knowledge_cutoff: str
    price: float | None = None
    price_time: str | None = None
    price_currency: str | None = None
    base_currency: str | None = None
    fx_rate: float | None = None  # price currency -> base currency (1.0 explicitly when equal)
    fx_time: str | None = None
    spread_bps: float | None = None
    commission_bps: float | None = None
    adv_value: float | None = None  # base currency per day
    market_cap: float | None = None  # base currency
    portfolio_id: str | None = None
    portfolio_revision: str | None = None
    portfolio_value: float | None = None  # base currency
    current_weight: float | None = None
    sector_exposure_excluding_candidate: float | None = None
    cash_return: float | None = None  # annual
    alternatives: tuple[Mapping[str, Any], ...] = ()  # {"id","expected_return"(annual),"switching_cost_bps"}
    returns: Mapping[str, Any] | None = None  # pandas split-orient adjusted returns incl. the candidate column
    generic_evidence: Mapping[str, Any] | None = None  # {"version","standalone_value","definition"}
    observed_kill_variables: Mapping[str, float] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id, "decision_time": self.decision_time, "knowledge_cutoff": self.knowledge_cutoff,
            "price": self.price, "price_time": self.price_time, "price_currency": self.price_currency,
            "base_currency": self.base_currency, "fx_rate": self.fx_rate, "fx_time": self.fx_time,
            "spread_bps": self.spread_bps, "commission_bps": self.commission_bps, "adv_value": self.adv_value,
            "market_cap": self.market_cap, "portfolio_id": self.portfolio_id, "portfolio_revision": self.portfolio_revision,
            "portfolio_value": self.portfolio_value, "current_weight": self.current_weight,
            "sector_exposure_excluding_candidate": self.sector_exposure_excluding_candidate, "cash_return": self.cash_return,
            "alternatives": [dict(a) for a in self.alternatives], "returns": dict(self.returns) if self.returns else None,
            "generic_evidence": dict(self.generic_evidence) if self.generic_evidence else None,
            "observed_kill_variables": dict(sorted(self.observed_kill_variables.items())),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DecisionContext":
        data = dict(payload)
        data["alternatives"] = tuple(data.get("alternatives") or ())
        return cls(**data)


def returns_payload(frame: pd.DataFrame) -> dict[str, Any]:
    """Serialise an adjusted-return matrix losslessly for freezing."""

    return json.loads(frame.to_json(orient="split", date_format="iso", double_precision=15))


def _returns_frame(payload: Mapping[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(payload["data"], columns=payload["columns"], index=pd.to_datetime(payload["index"]))
    return frame.sort_index()


@dataclass(frozen=True)
class ProposalAuthority:
    strategy_id: str
    strategy_stage: str
    model_id: str
    model_stage: str
    account_id: str
    account_stage: str
    authority_policy_checksum: str
    approvals: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class DecisionResult:
    payload: dict[str, Any]
    proposal: ProposalDecision | None

    @property
    def action(self) -> str:
        return self.payload["action"]

    @property
    def decision_id(self) -> str:
        return self.payload["decision_id"]


# ---------------------------------------------------------------------------- advisory input and repricing


def advisory_input(run: Mapping[str, Any], instrument_id: str) -> dict[str, Any]:
    """Inspectable, non-binding mapping of specialist fields (no field becomes a weight)."""

    valuation = next((v for v in run.get("valuations", ()) if v["instrument_id"] == instrument_id), None)
    distribution = next((d for d in run.get("distributions", ()) if d["instrument_id"] == instrument_id), None)
    advisory = next((a for a in run.get("advisory", ()) if a["instrument_id"] == instrument_id), None)
    claim = next((c for c in run.get("owner_claims", ()) if c["instrument_id"] == instrument_id), None)
    return {
        "layer": "SPECIALIST_ADVISORY", "instrument_id": instrument_id, "run_id": run["run_id"], "content_hash": run["content_hash"],
        "scenarios": [{k: s[k] for k in ("name", "value", "probability", "probability_confidence")} for s in (valuation or {}).get("scenarios", ())],
        "distribution": {k: distribution[k] for k in ("horizon", "quantiles") if k in distribution} if distribution else None,
        "specialist_rank": (advisory or {}).get("opportunity_score"), "specialist_state": (advisory or {}).get("state"),
        "specialist_exposure_range": (advisory or {}).get("suggested_exposure_range"),
        "specialist_maximum": (advisory or {}).get("maximum_allowed"),
        "owner_valuation": (claim or {}).get("owner_valuation"),
        "monitoring": run.get("monitoring", {}),
        "transformation": "advisory_only: rank/range/maximum are never copied into target weight; maximum is a ceiling input",
    }


def _horizon_years(distribution: Mapping[str, Any] | None, policy: OpportunityPolicy) -> tuple[float, str]:
    text = str((distribution or {}).get("horizon", ""))
    match = re.fullmatch(r"P(\d+)([YM])", text)
    if match and int(match.group(1)) > 0:
        years = int(match.group(1)) / (12.0 if match.group(2) == "M" else 1.0)
        return years, "specialist_distribution_horizon"
    return policy.default_horizon_years, "policy_default"


def reprice(advisory: Mapping[str, Any], context: DecisionContext, policy: OpportunityPolicy) -> dict[str, Any]:
    """Cockpit decision layer: price-dependent metrics at the frozen price.  Not friend-engine science."""

    out: dict[str, Any] = {"layer": "COCKPIT_DECISION", "status": "unavailable", "reasons": []}
    price = context.price
    scenarios = [dict(s) for s in advisory["scenarios"]]
    if not _pos(price) or len(scenarios) < 2:
        out["reasons"].append("price_or_scenarios_missing")
        return out
    decision_time = _time(context.decision_time)
    standalone = next((s for s in scenarios if s["name"] == policy.standalone_scenario), None)
    expired: list[str] = []
    raw_by_name = {s["name"]: s for s in (advisory.get("raw_scenarios") or scenarios)}
    for scenario in scenarios:
        expiry = _time(raw_by_name.get(scenario["name"], {}).get("expires_at")) if raw_by_name.get(scenario["name"], {}).get("expires_at") else None
        if expiry is not None and decision_time is not None and expiry <= decision_time:
            if standalone is None or standalone is scenario:
                out["reasons"].append("expired_catalyst_without_standalone_value")
                return out
            expired.append(scenario["name"])
            scenario["value"] = min(float(scenario["value"]), float(standalone["value"]))  # no stale optionality
    if any(not _pos(s["value"]) for s in scenarios):
        out["reasons"].append("scenario_value_not_positive")
        return out
    ev = sum(s["probability"] * s["value"] for s in scenarios)
    downside = min(s["value"] for s in scenarios)
    horizon, horizon_source = _horizon_years(advisory.get("distribution"), policy)
    cost_fraction = ((context.spread_bps or 0.0) + 2.0 * (context.commission_bps or 0.0)) / 1e4
    gross_total = ev / price - 1.0
    net_total = gross_total - cost_fraction
    annual_net = (1.0 + net_total) ** (1.0 / horizon) - 1.0 if net_total > -1.0 else -1.0
    result = {
        "layer": "COCKPIT_DECISION", "status": "available", "reasons": [], "price": price, "horizon_years": horizon,
        "horizon_source": horizon_source, "scenarios_used": scenarios, "expired_scenarios": expired,
        "expected_value": ev, "upside_to_expected_value": gross_total, "downside_to_bear_case": downside / price - 1.0,
        "bear_case_loss_fraction": max(0.0, 1.0 - downside / price), "gross_total_return": gross_total,
        "implementation_cost_fraction": cost_fraction, "net_total_return": net_total, "net_annual_return": annual_net,
        "no_catalyst_coverage": None, "price_implied_transition_probability": None,
    }
    if standalone is not None:
        result["no_catalyst_coverage"] = standalone["value"] / price
        transition = next((s for s in scenarios if s["name"] == policy.transition_scenario), None)
        if transition is not None and transition["value"] > standalone["value"]:
            p = (price - standalone["value"]) / (transition["value"] - standalone["value"])
            result["price_implied_transition_probability"] = {"value": p, "in_range": 0.0 <= p <= 1.0}
    return result


def compare_alternatives(net_annual_return: float, context: DecisionContext, horizon: float, policy: OpportunityPolicy) -> dict[str, Any]:
    alts = [{"id": CASH_ID, "expected_return": context.cash_return, "switching_cost_bps": 0.0}, *({"switching_cost_bps": 0.0, **dict(a)} for a in context.alternatives)]
    if any(_num(a.get("expected_return")) is None for a in alts):
        return {"status": "unavailable", "reasons": ["alternative_return_missing"], "alternatives": alts}
    best = max(alts, key=lambda a: (a["expected_return"], a["id"]))
    friction = float(best.get("switching_cost_bps") or 0.0) / 1e4 / horizon
    excess = net_annual_return - best["expected_return"] - friction
    return {"status": "available", "reasons": [], "candidate_net_annual_return": net_annual_return, "alternatives": alts,
            "best_alternative": best["id"], "best_alternative_return": best["expected_return"], "switching_friction_annual": friction,
            "excess_return": excess, "hurdle": policy.min_excess_return, "attractive": excess >= policy.min_excess_return}


# ---------------------------------------------------------------------------- gates


def _issue(issues: list[dict[str, str]], severity: str, category: str, code: str, detail: str = "") -> None:
    issues.append({"severity": severity, "category": category, "code": code, "detail": detail})


def _validity_issues(run: Mapping[str, Any], resolution: Mapping[str, Any] | None, context: DecisionContext, policy: OpportunityPolicy,
                     attachments_verified: bool | None, lineage_conflict: bool) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    iid, decision, cutoff = context.instrument_id, _time(context.decision_time), _time(context.knowledge_cutoff)
    known, generated = _time(run.get("known_at_cutoff")), _time(run.get("generated_at"))
    if decision is None or cutoff is None or known is None or generated is None:
        _issue(issues, BLOCK, "run", "timestamps_unparseable")
        return issues
    if lineage_conflict:
        _issue(issues, BLOCK, "lineage", "conflicting_duplicate_run")
    if not run.get("content_hash") or not run.get("run_id"):
        _issue(issues, BLOCK, "lineage", "provenance_missing")
    if any(a.get("required") for a in run.get("attachments", ())) and attachments_verified is not True:
        _issue(issues, BLOCK, "lineage", "attachment_unverified_or_invalid")
    if resolution is None or resolution.get("run_id") != run.get("run_id") or resolution.get("content_hash") != run.get("content_hash"):
        _issue(issues, BLOCK, "lineage", "resolution_projection_missing_or_mismatched")
    if run.get("status") == "INVALID":
        _issue(issues, BLOCK, "run", "run_invalid")
    elif run.get("status") == "DEGRADED":
        _issue(issues, WARN if policy.allow_degraded else REVIEW, "run", "run_degraded", ",".join(run.get("critical_missing", ())))
    if generated > cutoff or known > decision:
        _issue(issues, BLOCK, "freshness", "run_not_known_at_decision_time")
    elif decision - known > timedelta(days=policy.max_run_age_days):
        _issue(issues, policy.stale_action if policy.stale_action in (BLOCK, REVIEW) else BLOCK, "freshness", "run_stale")

    missing = [name for name in ("price", "price_time", "price_currency", "base_currency", "fx_rate", "fx_time", "spread_bps", "commission_bps",
                                 "adv_value", "market_cap", "portfolio_id", "portfolio_revision", "portfolio_value", "current_weight",
                                 "sector_exposure_excluding_candidate", "cash_return") if getattr(context, name) is None]
    if not context.returns:
        missing.append("returns")
    for name in missing:
        _issue(issues, BLOCK, "context", "context_missing", name)
    if _num(context.price) is not None and not _pos(context.price) or _num(context.fx_rate) is not None and not _pos(context.fx_rate):
        _issue(issues, BLOCK, "context", "context_invalid", "price_or_fx_not_positive")
    for label, stamp in (("price", context.price_time), ("fx", context.fx_time)):
        at = _time(stamp) if stamp else None
        if at is None:
            continue
        if at > decision:
            _issue(issues, BLOCK, "freshness", f"{label}_after_decision_time")
        elif decision - at > timedelta(hours=policy.max_price_age_hours):
            _issue(issues, BLOCK, "freshness", f"{label}_stale")

    asset = (resolution or {}).get("assets", {}).get(iid)
    if asset is None or asset.get("status") != "RESOLVED":
        _issue(issues, BLOCK, "identity", "identity_" + str((asset or {}).get("status", "missing")).lower())
    state = next((s for s in (resolution or {}).get("claimant_states", ()) if s["instrument_id"] == iid), None)
    claim = next((c for c in run.get("owner_claims", ()) if c["instrument_id"] == iid), None)
    if state is None or claim is None:
        _issue(issues, BLOCK, "claim", "owner_claim_state_missing")
    else:
        if state["status"] != "RESOLVED":
            code = "denominator_mismatch" if state["status"] == "REJECTED" else "claimant_state_unresolved"
            _issue(issues, BLOCK, "claim", code, str(state.get("reason")))
        if claim.get("claimant_allocation_status") != "RESOLVED":
            _issue(issues, BLOCK, "claim", "claimant_allocation_unresolved")
        if "owner_valuation" not in claim:
            _issue(issues, BLOCK, "claim", "owner_valuation_missing")
        if claim.get("event_id"):
            event = next((e for e in run.get("structural_events", ()) if e["event_id"] == claim["event_id"]), None)
            if event is None:
                _issue(issues, BLOCK, "claim", "event_state_missing", claim["event_id"])
            else:
                if str(event.get("milestone", "")).lower() not in policy.accepted_milestones:
                    _issue(issues, REVIEW, "claim", "event_not_approved", str(event.get("milestone")))
                ratios = event.get("four_ratios") or {}
                conversion = ratios.get("target_ec_conversion_ratio")
                if event.get("event_type") == "MERGER" and conversion in (ratios.get("bank_value_split"), ratios.get("post_merger_ec_class_split")):
                    _issue(issues, BLOCK, "claim", "merger_ratios_conflated")
    # Falsifiers: an observed breach forces re-underwriting by a new run; expired ones are ignored.
    for kill in run.get("monitoring", {}).get("kill_variables", ()):
        expiry = _time(kill.get("expires_at")) if kill.get("expires_at") else None
        if expiry is not None and expiry <= decision:
            continue
        observed = (context.observed_kill_variables or {}).get(kill["variable"])
        threshold = kill.get("threshold")
        if observed is None:
            _issue(issues, WARN, "run", "kill_variable_unobserved", kill["variable"])
        elif kill["comparator"] == "between" or _num(threshold) is None:
            _issue(issues, REVIEW, "run", "kill_variable_unevaluable", kill["variable"])
        elif {"<": observed < threshold, "<=": observed <= threshold, ">": observed > threshold, ">=": observed >= threshold}[kill["comparator"]]:
            _issue(issues, BLOCK, "run", "falsifier_breached_re_underwrite", kill["variable"])
    return issues


def _disagreement(spec_standalone: float | None, context: DecisionContext, policy: OpportunityPolicy) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    generic = context.generic_evidence
    record = {"specialist_standalone_value": spec_standalone, "generic": dict(generic) if generic else None, "averaged": False}
    value = _num((generic or {}).get("standalone_value"))
    if generic is None or value is None or spec_standalone is None:
        _issue(issues, WARN, "confidence", "generic_evidence_unavailable")
        record["status"] = "unavailable"
    else:
        gap = abs(spec_standalone - value) / max(abs(value), 1e-12)
        record.update(status="disagree" if gap > policy.disagreement_tolerance else "agree", relative_gap=gap)
        if gap > policy.disagreement_tolerance:
            _issue(issues, REVIEW, "confidence", "specialist_generic_disagreement", f"gap={gap:.4f}")
    return record, issues


# ---------------------------------------------------------------------------- decision


def _frozen_refs(run: Mapping[str, Any], resolution: Mapping[str, Any] | None, context: DecisionContext, policy: OpportunityPolicy,
                 attachments_verified: bool | None) -> dict[str, Any]:
    iid = context.instrument_id
    claim = next((c for c in run.get("owner_claims", ()) if c["instrument_id"] == iid), None)
    state = next((s for s in (resolution or {}).get("claimant_states", ()) if s["instrument_id"] == iid), None)
    event = next((e for e in run.get("structural_events", ()) if claim and e["event_id"] == claim.get("event_id")), None)
    payload = context.to_payload()
    return {
        "run": {k: run.get(k) for k in ("run_id", "content_hash", "known_at_cutoff", "generated_at", "status", "model_version", "science_version", "code_revision")}
        | {"raw_sha256": (resolution or {}).get("raw_sha256")},
        "attachment_set": _sha(sorted((a["attachment_id"], a["sha256"], a["size_bytes"]) for a in run.get("attachments", ()))),
        "attachments_verified": attachments_verified,
        "claimant_projection": {k: (resolution or {}).get(k) for k in ("projection_hash", "policy_version", "identity_versions")},
        "owner_claim_event_state": _sha({"claim": claim, "claimant_state": state, "event": event}),
        "portfolio": _sha({k: payload[k] for k in ("portfolio_id", "portfolio_revision", "portfolio_value", "current_weight", "sector_exposure_excluding_candidate")}),
        "price": {"price": context.price, "price_time": context.price_time, "currency": context.price_currency},
        "fx": {"rate": context.fx_rate, "time": context.fx_time, "base_currency": context.base_currency},
        "cost_snapshot": _sha({k: payload[k] for k in ("spread_bps", "commission_bps", "adv_value", "market_cap")}),
        "alternatives": _sha({"cash_return": context.cash_return, "alternatives": payload["alternatives"]}),
        "returns": _sha(context.returns),
        "generic_evidence": _sha(context.generic_evidence) if context.generic_evidence else None,
        "kill_variable_observations": _sha(payload["observed_kill_variables"]),
        "optimiser": {"version": OPTIMISER_MODEL_VERSION, "method": policy.optimiser_method},
        "policy": {"opportunity": _sha(policy.to_payload()), "ceilings": _sha(policy.ceilings.to_payload()), "proposal_policy": PROPOSAL_POLICY_VERSION},
        "decision_time": context.decision_time, "knowledge_cutoff": context.knowledge_cutoff, "instrument_id": iid,
    }


def decide(
    run: Mapping[str, Any],
    resolution: Mapping[str, Any] | None,
    context: DecisionContext,
    policy: OpportunityPolicy,
    authority: ProposalAuthority,
    *,
    attachments_verified: bool | None = None,
    lineage_conflict: bool = False,
) -> DecisionResult:
    """Pure, deterministic Cockpit decision.  The run projection is never modified."""

    frozen = _frozen_refs(run, resolution, context, policy, attachments_verified)
    decision_id = "sbd_" + _sha(frozen)[:24]
    iid = context.instrument_id
    issues = _validity_issues(run, resolution, context, policy, attachments_verified, lineage_conflict)
    advisory = advisory_input(run, iid)
    valuation = next((v for v in run.get("valuations", ()) if v["instrument_id"] == iid), None)
    advisory["raw_scenarios"] = (valuation or {}).get("scenarios", [])
    economics: dict[str, Any] = {"layer": "COCKPIT_DECISION", "status": "unavailable", "reasons": ["blocked_before_economics"]}
    comparison: dict[str, Any] = {"status": "unavailable", "reasons": ["blocked_before_economics"]}
    ceilings = CeilingResult("unavailable", None, {}, (), ("blocked_before_economics",))
    sizing: dict[str, Any] = {"status": "unavailable", "desired_weight": None, "target_weight": None, "optimiser": None}
    disagreement: dict[str, Any] = {"status": "unavailable", "averaged": False}
    proposal: ProposalDecision | None = None

    if not any(i["severity"] == BLOCK for i in issues):
        economics = reprice(advisory, context, policy)
        if economics["status"] != "available":
            for reason in economics["reasons"]:
                _issue(issues, BLOCK, "economics", reason)
        else:
            standalone = next((s["value"] for s in economics["scenarios_used"] if s["name"] == policy.standalone_scenario), None)
            disagreement, extra = _disagreement(standalone, context, policy)
            issues += extra
            comparison = compare_alternatives(economics["net_annual_return"], context, economics["horizon_years"], policy)
            for reason in comparison["reasons"]:
                _issue(issues, BLOCK, "economics", reason)
            claim = next(c for c in run["owner_claims"] if c["instrument_id"] == iid)
            degraded = run.get("status") == "DEGRADED"
            ceilings = compute_ceilings(CeilingInputs(
                portfolio_value=context.portfolio_value, bear_case_loss_fraction=economics["bear_case_loss_fraction"],
                adv_value=context.adv_value, market_cap=context.market_cap, effective_free_float=claim["holdings"]["effective_free_float"],
                sector_exposure_excluding_candidate=context.sector_exposure_excluding_candidate,
                scenario_confidences=tuple((s["probability"], s["probability_confidence"]) for s in economics["scenarios_used"]),
                event_relevant=bool(claim.get("event_id")), event_failure_loss_fraction=max(economics["bear_case_loss_fraction"], policy.ceilings.min_bear_loss_fraction),
                specialist_maximum=_num(advisory["specialist_maximum"]), degraded=degraded and policy.allow_degraded), policy.ceilings)
            for reason in ceilings.reasons:
                _issue(issues, BLOCK, "sizing", reason)
            if comparison["status"] == "available" and ceilings.status == "available":
                sizing = _size(economics, comparison, ceilings, context, policy, issues)

    action = BLOCK if any(i["severity"] == BLOCK for i in issues) else REVIEW if any(i["severity"] == REVIEW for i in issues) else "PROPOSE"
    gates = _gate_evidence(issues)
    reason_codes = sorted({i["code"] for i in issues if i["severity"] in (BLOCK, REVIEW)})
    if action == "PROPOSE" and sizing["status"] == "available":
        proposal, action, extra_codes = _policy_proposal(decision_id, sizing, context, policy, authority, gates, ceilings)
        reason_codes += extra_codes
    elif action == "PROPOSE":
        action, reason_codes = BLOCK, ["sizing_unavailable"]

    body = {
        "schema": DECISION_SCHEMA, "decision_id": decision_id, "action": action, "reason_codes": sorted(set(reason_codes)),
        "issues": issues, "gates": [g.to_payload() for g in gates], "frozen": frozen, "advisory": {k: v for k, v in advisory.items() if k != "raw_scenarios"},
        "economics": economics, "comparison": comparison, "disagreement": disagreement, "ceilings": ceilings.to_payload(), "sizing": sizing,
        "proposal": proposal.to_payload() if proposal else None, "execution_allowed": EXECUTION_ALLOWED,
        "inputs": {"context": context.to_payload(), "policy": policy.to_payload(), "authority": authority.to_payload(),
                   "attachments_verified": attachments_verified, "lineage_conflict": lineage_conflict},
    }
    return DecisionResult({**body, "decision_hash": _sha(body)}, proposal)


def _size(economics: Mapping[str, Any], comparison: Mapping[str, Any], ceilings: CeilingResult, context: DecisionContext,
          policy: OpportunityPolicy, issues: list[dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "unavailable", "desired_weight": None, "target_weight": None, "released_to_cash": None,
                           "ceiling": ceilings.ceiling, "ceiling_binding": list(ceilings.binding), "optimiser": None,
                           "objective_inputs": {"candidate_net_annual_return": economics["net_annual_return"],
                                                "provenance": "COCKPIT_DECISION repriced at frozen price, net of implementation cost"}}
    candidate = context.instrument_id
    if not comparison["attractive"]:
        out.update(status="available", desired_weight=0.0, target_weight=0.0, released_to_cash=0.0, optimiser="skipped_not_attractive")
        return out
    frame = _returns_frame(context.returns)
    expected: dict[str, float] = {candidate: economics["net_annual_return"]}
    by_id = {a["id"]: a for a in comparison["alternatives"]}
    problems = [] if candidate in frame.columns and len(frame.columns) > 1 else ["optimiser_candidate_or_alternative_series_missing"]
    for column in frame.columns:
        if column != candidate:
            value = _num((by_id.get(column) or {}).get("expected_return"))
            if value is None:
                problems.append(f"optimiser_expected_return_missing:{column}")
            else:
                expected[column] = value
    if problems or ceilings.ceiling <= 0:
        for problem in problems:
            _issue(issues, BLOCK, "optimiser", problem)
        if not problems:
            out.update(status="available", desired_weight=0.0, target_weight=0.0, released_to_cash=0.0, optimiser="skipped_zero_ceiling")
        return out
    constraints = OptimiserConstraints(cash_weight=policy.cash_weight, group_labels={candidate: CANDIDATE_GROUP},
                                       group_max_weights={CANDIDATE_GROUP: min(1.0, ceilings.ceiling)})
    solution = PortfolioOptimiser(frame).solve(policy.optimiser_method, constraints=constraints, expected_returns=expected)
    out["optimiser"] = {"method": solution.method, "status": solution.status, "feasible": solution.feasible,
                        "model_version": solution.model_version, "weights": {k: float(v) for k, v in solution.weights.items()},
                        "reason_code": solution.diagnostics.get("reason_code"), "binding": list(solution.diagnostics.get("binding_constraints", ()))}
    if solution.status != "success" or not solution.feasible or candidate not in solution.weights:
        _issue(issues, BLOCK, "optimiser", "optimiser_unavailable_or_infeasible", str(solution.status))
        return out
    desired = float(solution.weights[candidate])
    final, clamped = apply_ceiling(desired, ceilings)
    out.update(status="available", desired_weight=round(desired, 8), target_weight=round(final, 8), clamped_by_ceiling=clamped,
               released_to_cash=round(desired - final, 8))
    return out


def _gate_evidence(issues: list[dict[str, str]]) -> tuple[GateEvidence, ...]:
    gates = []
    for gate_id, categories in _GATE_CATEGORIES.items():
        hits = [i for i in issues if i["category"] in categories and i["severity"] in (BLOCK, REVIEW)]
        if gate_id == "account_authority":
            hits = []
        gates.append(GateEvidence(gate_id, not hits, "passed" if not hits else "; ".join(sorted({i["code"] for i in hits}))))
    return tuple(gates)


def _policy_proposal(decision_id: str, sizing: Mapping[str, Any], context: DecisionContext, policy: OpportunityPolicy,
                     authority: ProposalAuthority, gates: tuple[GateEvidence, ...], ceilings: CeilingResult
                     ) -> tuple[ProposalDecision | None, str, list[str]]:
    price_base = context.price * context.fx_rate
    to_quantity = lambda weight: round(weight * context.portfolio_value / price_base, 8)  # noqa: E731
    as_of = _time(context.decision_time)
    try:
        proposal = build_proposal_decision(ProposalRequest(
            instrument_id=context.instrument_id, current_quantity=to_quantity(context.current_weight),
            target_quantity=to_quantity(sizing["target_weight"]), strategy_id=authority.strategy_id, strategy_stage=authority.strategy_stage,
            model_id=authority.model_id, model_stage=authority.model_stage, account_id=authority.account_id, account_stage=authority.account_stage,
            optimiser_output_id=decision_id, portfolio_revision=context.portfolio_revision, data_revision=decision_id,
            as_of=as_of, expires_at=as_of + timedelta(hours=policy.proposal_ttl_hours),
            authority_policy_checksum=authority.authority_policy_checksum, gate_evidence=tuple(g for g in gates if g.gate_id in {*REQUIRED_GATES, *_GATE_CATEGORIES}),
            rationale="Cockpit-owned target from repriced Sparebank advisory input inside independent ceilings.", approvals=authority.approvals))
    except ValueError as exc:
        return None, "BLOCK", [f"authority_unavailable:{exc}"]
    if proposal.proposal_allowed:
        return proposal, "PROPOSE", []
    return None, ("BLOCK" if proposal.outcome == "no_trade" else "REVIEW"), [f"proposal_policy_{proposal.outcome}"]


# ---------------------------------------------------------------------------- persistence and replay


class DecisionStore:
    """Immutable file store for decisions plus a run-lineage ledger; no second database."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "decisions").mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(parents=True, exist_ok=True)

    def register_run(self, run_id: str, content_hash: str) -> bool:
        """True when this run id carries a different content hash than first seen (conflicting duplicate)."""

        path = self.root / "runs" / f"{hashlib.sha256(run_id.encode()).hexdigest()[:32]}.json"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"run_id": run_id, "content_hash": content_hash}, sort_keys=True))
                handle.flush()
                os.fsync(handle.fileno())
            return False
        except FileExistsError:
            return json.loads(path.read_text(encoding="utf-8")).get("content_hash") != content_hash

    def save(self, result: DecisionResult) -> Path:
        path = self.root / "decisions" / f"{result.decision_id}.json"
        text = json.dumps(result.payload, sort_keys=True, indent=1) + "\n"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if json.loads(path.read_text(encoding="utf-8")) != json.loads(text):
                raise DecisionConflict(f"decision {result.decision_id} already stored with different content") from None
        return path

    def load(self, decision_id: str) -> dict[str, Any]:
        payload = json.loads((self.root / "decisions" / f"{decision_id}.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in payload.items() if k != "decision_hash"}
        if _sha(body) != payload.get("decision_hash"):
            raise DecisionConflict(f"decision {decision_id} failed its integrity check")
        return payload

    def decisions_for_instrument(self, instrument_id: str) -> list[dict[str, Any]]:
        found = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.root / "decisions").glob("sbd_*.json"))]
        return [d for d in found if d["frozen"]["instrument_id"] == instrument_id]


def emit_paper_proposal(result: DecisionResult, directory: Path) -> Path | None:
    """Persist the (single, idempotent) paper proposal of a PROPOSE decision; REVIEW/BLOCK have no side effect."""

    if result.action != "PROPOSE" or result.proposal is None or not result.proposal.proposal_allowed or result.payload["execution_allowed"] is not False:
        return None
    return save_proposal_decision(result.proposal, directory=Path(directory))


def replay_decision(stored: Mapping[str, Any], run: Mapping[str, Any], resolution: Mapping[str, Any] | None) -> DecisionResult:
    """Recompute a stored decision from its frozen inputs and the (unchanged) run/resolution; callers compare payloads."""

    inputs = stored["inputs"]
    return decide(run, resolution, DecisionContext.from_payload(inputs["context"]), OpportunityPolicy.from_payload(inputs["policy"]),
                  ProposalAuthority(**{**inputs["authority"], "approvals": tuple(inputs["authority"]["approvals"])}),
                  attachments_verified=inputs["attachments_verified"], lineage_conflict=inputs["lineage_conflict"])


__all__ = [
    "DECISION_SCHEMA",
    "DecisionConflict",
    "DecisionContext",
    "DecisionResult",
    "DecisionStore",
    "OpportunityPolicy",
    "ProposalAuthority",
    "advisory_input",
    "compare_alternatives",
    "decide",
    "emit_paper_proposal",
    "replay_decision",
    "reprice",
    "returns_payload",
]
