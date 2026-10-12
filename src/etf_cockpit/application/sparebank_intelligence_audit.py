"""Read model for the Sparebank specialist owner-claim / transition / decision audit (#719).

Pure and presentation-neutral: it only *arranges* what the frozen specialist run (#716), the claimant/PIT projection (#717)
and the stored Cockpit decision (#718) already say.  It never recalculates specialist science, never averages the
specialist and the generic Cockpit evidence, never promotes an epistemic label, and returns ``status: unavailable`` with a
reason whenever evidence is missing.  Every structure is JSON-round-trippable so render == export == reload.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from numpy import format_float_positional

from etf_cockpit.application.sparebank_opportunity import DecisionConflict, DecisionResult, replay_decision
from etf_cockpit.data.sparebank_intelligence import EPISTEMIC_CLASSES, FORBIDDEN_AUTHORITY_KEYS, FOUR_RATIOS, canonical_json
from etf_cockpit.data.sparebank_run_store import SparebankRunStore

AUDIT_SCHEMA = "sparebank-intelligence-audit.v1"
PACKET_SCHEMA = "sparebank-audit-packet.v1"
MAX_RUN_AGE_DAYS = 45.0  # same default as OpportunityPolicy.max_run_age_days; display classification only
EXECUTION_ALLOWED = False

LAYER_BY_CLASS = {
    "OBSERVED": "fact_base",
    "CALCULATED": "current_state",
    "NORMALISED": "current_state",
    "MODEL_ESTIMATE": "valuation_expectations",
    "ASSUMPTION": "valuation_expectations",
    "MANAGEMENT_TARGET": "valuation_expectations",
    "THESIS": "valuation_expectations",
    "SPECULATION": "valuation_expectations",
}
SIGNIFICANT_DIGITS = {"OBSERVED": 4, "HIGH": 4, "MEDIUM": 3, "LOW": 2}  # display precision never exceeds source confidence
RATIO_LABELS = {
    "bank_value_split": "Bank-level value split",
    "target_ec_conversion_ratio": "Target EC conversion ratio",
    "post_merger_ec_class_split": "Post-merger EC ownership split",
    "post_merger_eierbrok": "Post-merger eierbrøk",
}
MERGER_STAGES = (
    ("signed_plan", ("signed_plan", "plan_signed", "merger_plan_signed")),
    ("owner_approval", ("owner_approval", "owners_approved", "approved_by_owners", "general_meeting_approval")),
    ("regulatory_clearance", ("regulatory_clearance", "regulatory_approval", "regulator_cleared")),
    ("legal_completion", ("legal_completion", "legally_completed", "completed_legally")),
    ("organisational_integration", ("organisational_integration", "organizational_integration")),
    ("technical_customer_integration", ("technical_customer_integration", "technical_integration", "customer_migration")),
    ("economic_maturity", ("economic_maturity", "synergies_seasoned")),
)
CLOCK_NAMES = ("economic", "accounting", "market", "institutional")
SYNERGY_ORDER = ("ANNOUNCED", "TARGET", "IMPLEMENTED", "FINANCIALLY_VISIBLE", "SEASONED")
FALSIFIER_CODES = {"falsifier_breached_re_underwrite": "BREACHED", "kill_variable_unobserved": "UNOBSERVED", "kill_variable_unevaluable": "UNEVALUABLE"}


class AuditPacketError(RuntimeError):
    """A packet failed its integrity or authority check."""


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _scrub(value: Any) -> Any:
    """Ledger rows from the continuity projection carry recorded EC counts under authority-looking names; rename, never drop."""

    if isinstance(value, Mapping):
        return {(f"recorded_{k}" if str(k).lower() in FORBIDDEN_AUTHORITY_KEYS else k): _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, **extra}


def _pick(row: Mapping[str, Any] | None, keys: Sequence[str]) -> dict[str, Any]:
    return {k: row[k] for k in keys if row is not None and k in row}


def display_value(value: object, confidence: object) -> str | None:
    """Rounded text whose precision follows the confidence class; ``None`` for non-numbers."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rounded = float(f"{value:.{SIGNIFICANT_DIGITS.get(str(confidence), 2)}g}")
    return format_float_positional(rounded, trim="-")


# ------------------------------------------------------------------------------------------------ run inventory


def _read_meta(store: SparebankRunStore, run_id: str) -> dict[str, Any]:
    try:
        return json.loads((Path(store.root) / "runs" / run_id / "meta.json").read_bytes())
    except (OSError, ValueError):
        return {}


def evidence_usability(run: Mapping[str, Any], as_of: str | None, max_age_days: float = MAX_RUN_AGE_DAYS) -> dict[str, Any]:
    """Whether a run may be shown as recommendation evidence.  Missing information is never usable."""

    reasons: list[str] = []
    status = str(run.get("status"))
    if status == "INVALID":
        reasons.append("run_invalid")
    elif status == "DEGRADED":
        reasons.append("run_degraded")
    elif status != "VALID":
        reasons.append("run_status_unknown")
    known, now = _time(run.get("known_at_cutoff")), _time(as_of)
    if known is None or now is None:
        reasons.append("freshness_unverifiable")
    elif known > now:
        reasons.append("run_not_known_at_as_of")
    elif now - known > timedelta(days=max_age_days):
        reasons.append("run_stale")
    return {"usable": not reasons and status == "VALID", "state": "STALE" if "run_stale" in reasons and status == "VALID" else status, "reasons": reasons}


def run_inventory(
    store: SparebankRunStore,
    *,
    resolutions: Mapping[str, Mapping[str, Any]] | None = None,
    as_of: str | None = None,
    max_age_days: float = MAX_RUN_AGE_DAYS,
) -> dict[str, Any]:
    """Accepted and quarantined runs with lineage; reads only, so old runs are never mutated."""

    resolutions = resolutions or {}
    rows: list[dict[str, Any]] = []
    for run_id in store.run_ids():
        run = store.get_run(run_id)
        if run is None:
            rows.append({"run_id": run_id, "state": "UNREADABLE", "usable_as_recommendation_evidence": False, "reasons": ["stored_bytes_failed_verification"]})
            continue
        meta = _read_meta(store, run_id)
        usable = evidence_usability(run, as_of, max_age_days)
        resolution = resolutions.get(run_id)
        if resolution is None:
            unresolved: dict[str, Any] = _unavailable("no_claimant_resolution_projection")
        else:
            unresolved = {
                "status": "available", "projection_hash": resolution.get("projection_hash"),
                "identities": sorted(i for i, a in resolution.get("assets", {}).items() if a.get("status") != "RESOLVED"),
                "claimants": sorted(s["instrument_id"] for s in resolution.get("claimant_states", ()) if s.get("status") != "RESOLVED"),
            }
        rows.append({
            "run_id": run_id, "state": usable["state"], "usable_as_recommendation_evidence": usable["usable"], "reasons": usable["reasons"],
            "producer": run.get("producer"), "schema_version": run.get("schema_version"), "model_version": run.get("model_version"),
            "science_version": run.get("science_version"), "code_revision": run.get("code_revision"),
            "as_of": run.get("as_of"), "known_at_cutoff": run.get("known_at_cutoff"), "generated_at": run.get("generated_at"),
            "status": run.get("status"), "content_hash": run.get("content_hash"), "raw_sha256": meta.get("raw_sha256"),
            "attachments": [_pick(a, ("attachment_id", "sha256", "size_bytes", "required")) for a in run.get("attachments", ())],
            "coverage": run.get("coverage"), "critical_missing": run.get("critical_missing", []),
            "assets": sorted(c["instrument_id"] for c in run.get("owner_claims", ())), "unresolved": unresolved,
            "previous_run_id": None, "superseded_by_run_id": None,
        })
    live = sorted((r for r in rows if r.get("known_at_cutoff")), key=lambda r: (r["known_at_cutoff"], r["run_id"]))
    for index, row in enumerate(live):  # lineage by overlapping assets, derived read-only
        assets = set(row["assets"])
        for earlier in reversed(live[:index]):
            if assets & set(earlier["assets"]):
                row["previous_run_id"] = earlier["run_id"]
                earlier["superseded_by_run_id"] = earlier["superseded_by_run_id"] or row["run_id"]
                break
    quarantined = [
        {"run_id": q.get("run_id"), "state": "QUARANTINED", "usable_as_recommendation_evidence": False,
         "raw_sha256": q.get("raw_sha256"), "source": q.get("source"), "reasons": [r.get("code") for r in q.get("reasons", ())]}
        for q in store.quarantine_reasons()
    ]
    return {"schema": AUDIT_SCHEMA, "status": "available" if rows or quarantined else "unavailable",
            "reason": None if rows or quarantined else "no_runs_imported", "as_of": as_of, "runs": rows, "quarantined": quarantined,
            "execution_allowed": EXECUTION_ALLOWED}


# ------------------------------------------------------------------------------------------------ evidence layers


def _evidence_row(row: Mapping[str, Any], scope: str, kind: str) -> dict[str, Any]:
    confidence = row.get("confidence_class")
    value = row.get("value")
    out = _pick(row, ("metric_id", "driver_id", "layer", "definition_id", "epistemic_class", "confidence_class", "missingness", "period", "unit",
                      "known_at", "source_ref", "source_hash", "value", "value_range", "reported_value", "adjustment", "mechanism",
                      "evidence_ref", "persistence_assumption"))
    out.update(kind=kind, scope=scope, display=display_value(value, confidence),
               low_confidence=confidence == "LOW", value_available=row.get("missingness") != "MISSING")
    return out


def evidence_layers(run: Mapping[str, Any], instrument_id: str) -> dict[str, Any]:
    """Fact base, current-state and expectation evidence; labels are copied from the run, never changed."""

    layers: dict[str, list[dict[str, Any]]] = {"fact_base": [], "current_state": [], "valuation_expectations": []}
    for kind, key in (("metric", "metrics"), ("bank_state", "bank_state")):
        for row in run.get(key, ()):
            owner = row.get("instrument_id")
            if owner not in (None, instrument_id):
                continue
            label = row.get("epistemic_class")
            layer = LAYER_BY_CLASS.get(str(label))
            if layer is None or label not in EPISTEMIC_CLASSES:
                continue
            layers[layer].append(_evidence_row(row, "instrument" if owner else "run_level", kind))
    expectations = layers["valuation_expectations"]
    return {
        "fact_base": {"status": "available" if layers["fact_base"] else "unavailable", "reason": None if layers["fact_base"] else "no_observed_evidence",
                      "items": layers["fact_base"], "attachments": [_pick(a, ("attachment_id", "sha256", "required")) for a in run.get("attachments", ())]},
        "current_state": {"status": "available" if layers["current_state"] else "unavailable",
                          "reason": None if layers["current_state"] else "no_calculated_or_normalised_evidence", "items": layers["current_state"]},
        "valuation_expectations_evidence": {
            "status": "available" if expectations else "unavailable", "reason": None if expectations else "no_model_or_assumption_evidence",
            "by_class": {c: [i for i in expectations if i["epistemic_class"] == c] for c in sorted({i["epistemic_class"] for i in expectations})}},
    }


def verify_epistemic_labels(layers: Mapping[str, Any], run: Mapping[str, Any]) -> list[str]:
    """Violations (empty = every shown label equals the run's label for that id)."""

    source = {r.get("metric_id") or r.get("driver_id"): r.get("epistemic_class") for key in ("metrics", "bank_state") for r in run.get(key, ())}
    shown = [*layers["fact_base"]["items"], *layers["current_state"]["items"],
             *[i for items in layers["valuation_expectations_evidence"]["by_class"].values() for i in items]]
    problems = [f"{i.get('metric_id') or i.get('driver_id')}:{i['epistemic_class']}!={source.get(i.get('metric_id') or i.get('driver_id'))}"
                for i in shown if source.get(i.get("metric_id") or i.get("driver_id")) != i["epistemic_class"]]
    expected = {"fact_base": {"OBSERVED"}, "current_state": {"CALCULATED", "NORMALISED"}}
    for layer, allowed in expected.items():
        problems += [f"{layer}:{i['epistemic_class']}" for i in layers[layer]["items"] if i["epistemic_class"] not in allowed]
    return problems


# ------------------------------------------------------------------------------------------------ owner claim, events, clocks


def _claim(run: Mapping[str, Any], instrument_id: str) -> Mapping[str, Any] | None:
    return next((c for c in run.get("owner_claims", ()) if c.get("instrument_id") == instrument_id), None)


def _state(resolution: Mapping[str, Any] | None, instrument_id: str) -> Mapping[str, Any] | None:
    return next((s for s in (resolution or {}).get("claimant_states", ()) if s.get("instrument_id") == instrument_id), None)


def owner_claim_bridge(run: Mapping[str, Any], resolution: Mapping[str, Any] | None, instrument_id: str) -> dict[str, Any]:
    claim = _claim(run, instrument_id)
    if claim is None:
        return _unavailable("owner_claim_not_supplied", owner_valuation_blocked=True, portfolio_use_blocked=True)
    state = _state(resolution, instrument_id)
    reasons: list[str] = []
    if claim.get("claimant_allocation_status") != "RESOLVED":
        reasons.append("claimant_allocation_unresolved")
    if state is None:
        reasons.append("claimant_projection_missing")
    elif state.get("status") != "RESOLVED":
        reasons.append(str(state.get("reason") or "claimant_state_" + str(state.get("status")).lower()))
    if "owner_valuation" not in claim:
        reasons.append("owner_valuation_missing")
    blocked = bool(reasons)
    holdings = claim.get("holdings") or {}
    bridge = {
        "status": "available", "instrument_id": instrument_id, "bank_legal_entity": claim.get("bank_legal_entity"), "share_class": claim.get("share_class"),
        "listing_identity": _pick((resolution or {}).get("assets", {}).get(instrument_id), ("status", "selected_instrument_id", "reason")),
        "capital": {"eierandelskapital": claim.get("eierandelskapital"), "grunnfondskapital": claim.get("grunnfondskapital"), "eierbrok": claim.get("eierbrok")},
        "ec_counts": {"current": claim.get("ec_count_current"), "fully_diluted": claim.get("ec_count_fully_diluted"), "treasury": claim.get("treasury_ec_count")},
        "holdings": {"foundation_share": holdings.get("foundation_share"), "strategic_share": holdings.get("strategic_share"),
                     "effective_free_float": holdings.get("effective_free_float"), "voting_share": claim.get("voting_share")},
        "payout_symmetry": claim["payout_symmetry"] if "payout_symmetry" in claim else _unavailable("payout_symmetry_not_supplied"),
        "claimant_allocation_status": claim.get("claimant_allocation_status"),
        "claimant_projection_status": (state or {}).get("status", "unavailable"), "claimant_state": (state or {}).get("state"),
        "pre_event_state": claim.get("pre_event_state"), "post_event_state": claim.get("post_event_state"), "event_id": claim.get("event_id"),
        "owner_valuation_blocked": blocked, "portfolio_use_blocked": blocked, "block_reasons": reasons,
    }
    if blocked:
        bridge["owner_valuation"] = _unavailable("owner valuation and portfolio use are blocked: " + ", ".join(reasons))
        bridge["whole_bank_multiples"] = "not_shown"
    else:
        bridge["owner_valuation"] = {"status": "available", **dict(claim["owner_valuation"])}
    return bridge


def _stage_of(milestone: object) -> str | None:
    text = str(milestone or "").strip().lower().replace(" ", "_").replace("-", "_")
    return next((stage for stage, aliases in MERGER_STAGES if text in aliases), None)


def event_clocks(event: Mapping[str, Any] | None, link: Mapping[str, Any] | None, claim: Mapping[str, Any] | None, *, price_time: str | None = None) -> dict[str, Any]:
    """Four separate dated clocks; legal completion never fills the economic clock."""

    if event is None:
        return _unavailable("no_structural_event")
    history = [(str(h.get("milestone")), h.get("at")) for h in event.get("history", ())]
    reached: dict[str, Any] = {}
    unmapped = []
    for milestone, at in history:
        stage = _stage_of(milestone)
        if stage is None:
            unmapped.append({"milestone": milestone, "at": at})
        else:
            reached[stage] = at
    state_stage = _stage_of(event.get("integration_state"))
    if state_stage and state_stage not in reached:
        reached[state_stage] = None  # reached, but the run gave no date
    seasoned = [s for s in event.get("synergies", ()) if s.get("state") == "SEASONED"]
    if seasoned and "economic_maturity" not in reached:
        reached["economic_maturity"] = None
    stages = [{"stage": stage, "status": "reached" if stage in reached else "not_reported", "at": reached.get(stage)} for stage, _ in MERGER_STAGES]
    supplied = event.get("clocks") if isinstance(event.get("clocks"), Mapping) else {}
    maturity = next(s for s in stages if s["stage"] == "economic_maturity")
    clocks = {
        "institutional": {"status": "available" if history or state_stage else "unavailable", "current_milestone": event.get("milestone"),
                          "integration_state": event.get("integration_state"), "history": [{"milestone": m, "at": a} for m, a in history]},
        "economic": {"status": "available" if supplied.get("economic") or any(s.get("state") for s in event.get("synergies", ())) else "unavailable",
                     "synergy_states": [_pick(s, ("component", "state", "value")) for s in event.get("synergies", ())],
                     "supplied": supplied.get("economic")},
        "accounting": {"status": "available" if supplied.get("accounting") or event.get("ledger_refs", {}).get("accounting") else "unavailable",
                       "ledger_ref": event.get("ledger_refs", {}).get("accounting"), "supplied": supplied.get("accounting")},
        "market": {"status": "available" if price_time or supplied.get("market") else "unavailable", "price_time": price_time, "supplied": supplied.get("market")},
    }
    return {"status": "available", "event_id": event.get("event_id"), "clocks": clocks, "merger_stages": stages if event.get("event_type") == "MERGER" else None,
            "unmapped_milestones": unmapped,
            "economic_maturity_note": "legal completion is not economic maturity" if maturity["status"] != "reached" else "economic maturity reported by the run",
            "legal_completion_reached": "legal_completion" in reached}


def structural_event_audit(run: Mapping[str, Any], resolution: Mapping[str, Any] | None, instrument_id: str, *, price_time: str | None = None) -> dict[str, Any]:
    claim = _claim(run, instrument_id)
    links = [l for l in (resolution or {}).get("continuity", {}).get("links", ())
             if instrument_id in (l.get("predecessor_instrument_id"), l.get("successor_instrument_id"))]
    event_id = (claim or {}).get("event_id") or (links[0].get("event_id") if links else None)
    event = next((e for e in run.get("structural_events", ()) if e.get("event_id") == event_id), None) if event_id else None
    if event is None:
        return _unavailable("no_structural_event_for_instrument")
    link = next((l for l in links if l.get("event_id") == event_id), None)
    ratios = event.get("four_ratios")
    if event.get("event_type") == "MERGER" and isinstance(ratios, Mapping):
        values = [ratios.get(n) for n in FOUR_RATIOS]
        four = {"status": "available", "ratios": [{"name": n, "label": RATIO_LABELS[n], "value": ratios.get(n)} for n in FOUR_RATIOS],
                "coincident_values": sorted({n for n in FOUR_RATIOS if values.count(ratios.get(n)) > 1}),
                "note": "four distinct quantities; none is derived from another"}
    else:
        four = _unavailable("not_a_merger_or_ratios_missing")
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in (link or {}).get("allocations", ()):
        key = (str(row.get("claimant")), str(row.get("kind")), str(row.get("source")))
        groups[key] = {"claimant": key[0], "kind": key[1], "source": key[2], "legal_bridge_ref": row.get("legal_bridge_ref")}
    recipients = {"status": "available" if groups else "unavailable", "reason": None if groups else "no_recipient_allocation_supplied",
                  "groups": list(groups.values()), "ledger": _scrub(list(((link or {}).get("conversion") or {}).get("recipient_ledger", ())))}
    synergies = []
    for s in event.get("synergies", ()):
        synergies.append({**_pick(s, ("component", "state", "value")), "stage_index": SYNERGY_ORDER.index(s["state"]) if s.get("state") in SYNERGY_ORDER else None,
                          "is_cost": s.get("component") == "INTEGRATION_COST"})
    return {
        "status": "available", "event_id": event_id, "event_type": event.get("event_type"), "milestone": event.get("milestone"),
        "continuity": _pick(link, ("status", "reason", "kind", "predecessor_instrument_id", "successor_instrument_id", "effective_at", "known_at")) if link else _unavailable("continuity_bridge_missing"),
        "ledgers": dict(event.get("ledger_refs") or {}), "four_ratios": four, "recipient_groups": recipients,
        "pre_post": {"pre_state": event.get("pre_state"), "post_state": event.get("post_state"),
                     "pre_ec_count": ((claim or {}).get("pre_event_state") or {}).get("ec_count_current"),
                     "post_ec_count": ((claim or {}).get("post_event_state") or {}).get("ec_count_current"),
                     "owner_value_per_legacy_ec": event.get("owner_value_per_legacy_ec")},
        "synergies": synergies,
        "approvals": {"status": "available", "items": list(event["unresolved_approvals"])} if "unresolved_approvals" in event else _unavailable("approvals_not_supplied"),
        "clocks": event_clocks(event, link, claim, price_time=price_time),
    }


# ------------------------------------------------------------------------------------------------ scenarios, falsifiers


def scenario_view(run: Mapping[str, Any], instrument_id: str, *, as_of: str | None, reference_price: float | None = None) -> dict[str, Any]:
    valuation = next((v for v in run.get("valuations", ()) if v.get("instrument_id") == instrument_id), None)
    if valuation is None:
        return _unavailable("no_valuation_for_instrument")
    now = _time(as_of)
    rows = []
    for s in valuation.get("scenarios", ()):
        expiry = _time(s.get("expires_at"))
        state = "EXPIRED" if expiry is not None and now is not None and expiry <= now else "LOW_CONFIDENCE" if s.get("probability_confidence") == "LOW" else "OK"
        rows.append({**_pick(s, ("name", "value", "probability", "probability_confidence", "expires_at")), "evidence_state": state,
                     "value_display": display_value(s.get("value"), s.get("probability_confidence")),
                     "probability_display": display_value(s.get("probability"), s.get("probability_confidence"))})
    distribution = next((d for d in run.get("distributions", ()) if d.get("instrument_id") == instrument_id), None)
    return {"status": "available", "model_id": valuation.get("model_id"), "scenarios": rows,
            "distribution": _pick(distribution, ("horizon", "quantiles", "p_cet1_breach", "p_value_exceeds_price", "simulation_id")) if distribution else _unavailable("no_distribution"),
            "reference_price": reference_price, "weighted_average": "not_shown_by_design",
            "note": "probability and probability confidence are separate fields"}


def falsifier_view(run: Mapping[str, Any], decision: Mapping[str, Any] | None, *, as_of: str | None) -> dict[str, Any]:
    monitoring = run.get("monitoring") or {}
    now = _time(as_of)
    issues = {(i["code"], i.get("detail")): i for i in (decision or {}).get("issues", ())}
    kills = []
    for kill in monitoring.get("kill_variables", ()):
        expiry = _time(kill.get("expires_at"))
        if expiry is not None and now is not None and expiry <= now:
            state = "EXPIRED"
        elif decision is None:
            state = "NOT_EVALUATED"
        else:
            state = next((label for code, label in FALSIFIER_CODES.items() if (code, kill.get("variable")) in issues), "HOLDING")
        observed = ((decision or {}).get("inputs", {}).get("context", {}).get("observed_kill_variables") or {}).get(kill.get("variable"))
        kills.append({**_pick(kill, ("variable", "comparator", "threshold", "expires_at")), "state": state, "observed": observed})
    return {"status": "available", "kill_variables": kills, "drivers": list(monitoring.get("drivers", ())),
            "weakening_observations": list(monitoring.get("weakening_observations", ())), "limitations": list(monitoring.get("limitations", ())),
            "outcomes": ["no_action", "watch", "re_underwrite"],
            "re_underwrite_required": any(k["state"] == "BREACHED" for k in kills)}


# ------------------------------------------------------------------------------------------------ independent comparison


def independent_comparison(run: Mapping[str, Any], instrument_id: str, decision: Mapping[str, Any] | None,
                           generic_rows: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Specialist and generic Cockpit evidence side by side.  Never averaged, never reconciled, neither certifies the other."""

    specialist = {(m.get("metric_id")): m for m in run.get("metrics", ()) if m.get("instrument_id") in (None, instrument_id)}
    treatment = _pick(decision, ("action",)) | {"reason_codes": [c for c in (decision or {}).get("reason_codes", ()) if "disagreement" in c or "generic" in c]}
    rows = []
    for generic in generic_rows:
        key = generic.get("metric_id")
        spec = specialist.get(key)
        if spec is None or spec.get("missingness") == "MISSING" or generic.get("value") is None:
            rows.append({"metric_id": key, "status": "unavailable", "reason": "one_side_missing", "specialist": _pick(spec, ("value", "definition_id")) or None,
                         "generic": dict(generic), "averaged": False})
            continue
        spec_side = _pick(spec, ("value", "unit", "period", "definition_id", "source_ref", "known_at", "confidence_class", "epistemic_class"))
        differences = [f for f, s_key in (("definition", "definition_id"), ("period", "period"), ("unit", "unit"), ("source", "source_ref"), ("known_at", "known_at"))
                       if generic.get(f) != spec.get(s_key)]
        if generic.get("claimant_denominator") != spec.get("claimant_denominator", "specialist_owner_attributable_ec"):
            differences.append("claimant_denominator")
        rows.append({"metric_id": key, "status": "available", "specialist": spec_side, "generic": dict(generic), "differences": differences,
                     "averaged": False, "reconciled": False})
    disagreement = (decision or {}).get("disagreement") or _unavailable("no_cockpit_decision_recorded")
    return {"status": "available" if rows or decision else "unavailable", "reason": None if rows or decision else "no_generic_evidence_supplied",
            "rows": rows, "standalone_value": disagreement, "cockpit_policy_treatment": treatment, "averaged": False,
            "note": "the generic Cockpit result does not certify the specialist model and vice versa"}


# ------------------------------------------------------------------------------------------------ Cockpit context, decision, chain


def marketability_context(decision: Mapping[str, Any] | None, claim: Mapping[str, Any] | None) -> dict[str, Any]:
    if decision is None:
        return _unavailable("no_cockpit_decision_recorded", side="COCKPIT")
    ctx = decision["inputs"]["context"]
    float_share = ((claim or {}).get("holdings") or {}).get("effective_free_float")
    cap = ctx.get("market_cap")
    effective = cap * float_share if isinstance(cap, (int, float)) and isinstance(float_share, (int, float)) else None
    ceilings = decision.get("ceilings") or {}
    return {
        "status": "available", "side": "COCKPIT", "source": "Cockpit market/portfolio evidence, not friend-engine science",
        "price": {"value": ctx.get("price"), "currency": ctx.get("price_currency"), "price_time": ctx.get("price_time")},
        "fx": {"rate": ctx.get("fx_rate"), "time": ctx.get("fx_time"), "base_currency": ctx.get("base_currency")},
        "market_value": {"headline": cap, "effective_free_float": effective, "effective_free_float_share": float_share,
                         "derivation": "headline market cap x specialist effective free-float share (display only)"},
        "liquidity": {"adv_value": ctx.get("adv_value"), "spread_bps": ctx.get("spread_bps"), "commission_bps": ctx.get("commission_bps")},
        "portfolio": {"portfolio_id": ctx.get("portfolio_id"), "revision": ctx.get("portfolio_revision"), "current_weight": ctx.get("current_weight"),
                      "sector_exposure_excluding_candidate": ctx.get("sector_exposure_excluding_candidate")},
        "size_ceilings": {"status": ceilings.get("status"), "ceiling": ceilings.get("ceiling"), "binding": list(ceilings.get("binding", ())),
                          "components": dict(ceilings.get("components", {}))},
        "implementation_adjusted": _pick(decision.get("economics"), ("net_annual_return", "net_total_return", "implementation_cost_fraction", "horizon_years")),
        "decision_time": ctx.get("decision_time"),
    }


def cockpit_decision_layer(decision: Mapping[str, Any] | None) -> dict[str, Any]:
    if decision is None:
        return _unavailable("no_cockpit_decision_recorded")
    sizing = decision.get("sizing") or {}
    proposal = decision.get("proposal")
    return {
        "status": "available", "decision_id": decision["decision_id"], "decision_hash": decision["decision_hash"], "action": decision["action"],
        "reason_codes": list(decision.get("reason_codes", ())), "issues": [dict(i) for i in decision.get("issues", ())],
        "gates": [dict(g) for g in decision.get("gates", ())], "comparison": _pick(decision.get("comparison"), ("status", "best_alternative", "attractive", "reasons")),
        "economics": _pick(decision.get("economics"), ("status", "reasons", "net_annual_return", "no_catalyst_coverage", "price_implied_transition_probability",
                                                       "expired_scenarios", "horizon_years")),
        "cockpit_weight_result": _pick(sizing, ("status", "desired_weight", "released_to_cash", "ceiling", "ceiling_binding")) | {"result": sizing.get("target_weight")},
        "paper_proposal": {"present": bool(proposal), "proposal_id": (proposal or {}).get("proposal_id"), "outcome": (proposal or {}).get("outcome")},
        "layer": "COCKPIT_DECISION", "execution_allowed": EXECUTION_ALLOWED,
    }


def causal_chain(run: Mapping[str, Any] | None, resolution: Mapping[str, Any] | None, decision: Mapping[str, Any] | None, instrument_id: str,
                 *, paper_refs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """source -> run -> resolution -> scenarios -> Cockpit context -> comparison -> gates -> decision -> paper evidence, with hashes per edge."""

    frozen = (decision or {}).get("frozen") or {}

    def node(stage: str, hashes: Mapping[str, Any], reason: str | None = None) -> dict[str, Any]:
        present = bool(hashes) and all(v not in (None, "") for v in hashes.values())
        return {"stage": stage, "status": "available" if present else "unavailable", "reason": None if present else reason or "evidence_not_recorded", "hashes": dict(hashes)}

    nodes = [
        node("source_evidence", {"attachment_set": frozen.get("attachment_set") or (_sha(sorted((a["attachment_id"], a["sha256"]) for a in run.get("attachments", ()))) if run else None)}),
        node("specialist_run", {"run_id": (run or {}).get("run_id"), "content_hash": (run or {}).get("content_hash"),
                                "raw_sha256": (resolution or {}).get("raw_sha256"), "model_version": (run or {}).get("model_version"),
                                "science_version": (run or {}).get("science_version"), "code_revision": (run or {}).get("code_revision")}),
        node("claimant_pit_resolution", {"projection_hash": (resolution or {}).get("projection_hash"), "policy_version": (resolution or {}).get("policy_version"),
                                         "identity_versions": ",".join((resolution or {}).get("identity_versions", ())) or None}),
        node("specialist_opportunity_scenarios", {"asset_fingerprint": ((resolution or {}).get("asset_fingerprints") or {}).get(instrument_id),
                                                  "claim_event_state": frozen.get("owner_claim_event_state")}),
        node("cockpit_context", {k: _sha(frozen[k]) if isinstance(frozen.get(k), Mapping) else frozen.get(k) for k in ("portfolio", "price", "fx", "cost_snapshot")}),
        node("comparative_return_optimiser_input", {"alternatives": frozen.get("alternatives"), "returns": frozen.get("returns"), "optimiser": _sha(frozen["optimiser"]) if frozen.get("optimiser") else None}),
        node("constraints_gates", {"policy": _sha(frozen["policy"]) if frozen.get("policy") else None, "gates": _sha((decision or {}).get("gates")) if decision else None}),
        node("paper_proposal_or_no_action", {"decision_id": (decision or {}).get("decision_id"), "decision_hash": (decision or {}).get("decision_hash"),
                                             "action": (decision or {}).get("action")}),
        node("paper_fill_replay", dict(paper_refs or {}), "no_paper_fill_or_replay_recorded"),
    ]
    return {"status": "available" if decision else "unavailable", "reason": None if decision else "no_cockpit_decision_recorded",
            "nodes": nodes, "chain_hash": _sha(nodes)}


def replay_check(decision: Mapping[str, Any] | None, run: Mapping[str, Any] | None, resolution: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recompute the stored decision from its frozen inputs (#718 ``replay_decision``) and compare."""

    if decision is None or run is None:
        return _unavailable("decision_or_run_missing")
    frozen_run = decision["frozen"]["run"]
    if frozen_run.get("content_hash") != run.get("content_hash"):
        return {"status": "available", "reproduced": False, "reason": "run_content_hash_differs_from_frozen_reference"}
    try:
        replayed: DecisionResult = replay_decision(decision, run, resolution)
    except (KeyError, TypeError, ValueError, DecisionConflict) as exc:
        return {"status": "available", "reproduced": False, "reason": f"replay_failed:{type(exc).__name__}"}
    same = replayed.payload == dict(decision)
    return {"status": "available", "reproduced": same, "reason": None if same else "replayed_payload_differs", "decision_hash": decision["decision_hash"]}


# ------------------------------------------------------------------------------------------------ audit + packet


def assert_no_authority(value: Any, path: str = "$") -> None:
    """Fail closed: no key that could carry an order/weight/quantity/execute instruction may appear in an audit or packet."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_AUTHORITY_KEYS:
                raise AuditPacketError(f"forbidden authority key {key!r} at {path}")
            if key == "execution_allowed" and item is not False:
                raise AuditPacketError(f"execution_allowed must be false at {path}")
            assert_no_authority(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_authority(item, f"{path}[{index}]")


def build_instrument_audit(
    run: Mapping[str, Any] | None,
    resolution: Mapping[str, Any] | None,
    instrument_id: str,
    *,
    decision: Mapping[str, Any] | None = None,
    generic_rows: Sequence[Mapping[str, Any]] = (),
    as_of: str | None = None,
    paper_refs: Mapping[str, Any] | None = None,
    max_age_days: float = MAX_RUN_AGE_DAYS,
) -> dict[str, Any]:
    """Five-layer audit for one EC.  ``as_of`` defaults to the decision time; a missing run gives ``unavailable``."""

    if run is None:
        return {"schema": AUDIT_SCHEMA, "status": "unavailable", "reason": "run_missing_or_unverifiable", "instrument_id": instrument_id, "execution_allowed": EXECUTION_ALLOWED}
    when = as_of or ((decision or {}).get("inputs", {}).get("context", {}).get("decision_time")) or None
    ctx = (decision or {}).get("inputs", {}).get("context", {})
    claim = _claim(run, instrument_id)
    usable = evidence_usability(run, when, max_age_days)
    layers = evidence_layers(run, instrument_id)
    audit = {
        "schema": AUDIT_SCHEMA, "status": "available", "instrument_id": instrument_id, "as_of": when,
        "run": {**_pick(run, ("run_id", "content_hash", "status", "model_version", "science_version", "code_revision", "as_of", "known_at_cutoff", "generated_at", "coverage", "critical_missing")),
                "producer": run.get("producer"), "usable_as_recommendation_evidence": usable["usable"], "usability_reasons": usable["reasons"], "state": usable["state"],
                "attachments": [_pick(a, ("attachment_id", "sha256", "size_bytes", "required")) for a in run.get("attachments", ())]},
        "labels": {"observed": ["OBSERVED"], "specialist_science": sorted(EPISTEMIC_CLASSES - {"OBSERVED"}), "cockpit": ["COCKPIT_DECISION"]},
        "layers": {
            "fact_base": layers["fact_base"], "current_state": layers["current_state"],
            "transition_model": structural_event_audit(run, resolution, instrument_id, price_time=ctx.get("price_time")),
            "valuation_expectations": {"evidence": layers["valuation_expectations_evidence"],
                                       "scenarios": scenario_view(run, instrument_id, as_of=when, reference_price=ctx.get("price")),
                                       "assumption_burden": falsifier_view(run, decision, as_of=when)},
            "cockpit_decision": cockpit_decision_layer(decision),
        },
        "owner_claim_bridge": owner_claim_bridge(run, resolution, instrument_id),
        "independent_comparison": independent_comparison(run, instrument_id, decision, generic_rows),
        "marketability": marketability_context(decision, claim),
        "causal_chain": causal_chain(run, resolution, decision, instrument_id, paper_refs=paper_refs),
        "replay": replay_check(decision, run, resolution),
        "authority": {"execution_allowed": EXECUTION_ALLOWED, "proposal_authority": False, "release_authority": False, "broker_authority": False},
        "execution_allowed": EXECUTION_ALLOWED,
    }
    audit["label_violations"] = verify_epistemic_labels(layers, run)
    assert_no_authority(audit)
    return json.loads(canonical_json(audit))


def build_audit_packet(
    run: Mapping[str, Any] | None,
    resolution: Mapping[str, Any] | None,
    instrument_id: str,
    *,
    decision: Mapping[str, Any] | None = None,
    generic_rows: Sequence[Mapping[str, Any]] = (),
    as_of: str | None = None,
    paper_refs: Mapping[str, Any] | None = None,
    inventory_row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured local export for one decision/run; hashed, local-only, ``execution_allowed=false``."""

    audit = build_instrument_audit(run, resolution, instrument_id, decision=decision, generic_rows=generic_rows, as_of=as_of, paper_refs=paper_refs)
    body = {
        "schema": PACKET_SCHEMA, "instrument_id": instrument_id,
        "envelope": {"run_id": (run or {}).get("run_id"), "content_hash": (run or {}).get("content_hash"), "raw_sha256": (resolution or {}).get("raw_sha256"),
                     "attachments": audit.get("run", {}).get("attachments", []), "inventory": dict(inventory_row) if inventory_row else None},
        "claimant_identity_event_projection": _scrub(_pick(resolution, ("projection_hash", "policy_version", "identity_versions", "claimant_states", "continuity", "unresolved_exposure"))),
        "evidence_provenance": {"fact_base": audit.get("layers", {}).get("fact_base"), "current_state": audit.get("layers", {}).get("current_state")},
        "scenario_probability_confidence": audit.get("layers", {}).get("valuation_expectations"),
        "independent_comparison": audit.get("independent_comparison"),
        "frozen_context": {"marketability": audit.get("marketability"), "policy": ((decision or {}).get("frozen") or {}).get("policy")},
        "decision": audit.get("layers", {}).get("cockpit_decision"),
        "falsification_monitoring": audit.get("layers", {}).get("valuation_expectations", {}).get("assumption_burden"),
        "audit": audit, "execution_allowed": EXECUTION_ALLOWED,
    }
    assert_no_authority(body)
    packet = json.loads(canonical_json(body))
    return {**packet, "packet_hash": _sha(packet)}


def write_audit_packet(packet: Mapping[str, Any], directory: Path) -> Path:
    """Immutable, content-addressed local file; rewriting identical content is a no-op, differing content is refused."""

    body = {k: v for k, v in packet.items() if k != "packet_hash"}
    if _sha(body) != packet.get("packet_hash"):
        raise AuditPacketError("packet hash does not match its content")
    assert_no_authority(body)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"sap_{packet['packet_hash'][:24]}.json"
    data = canonical_json(dict(packet))
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise AuditPacketError("a different packet is already stored under this hash") from None
    return path


def load_audit_packet(path: Path) -> dict[str, Any]:
    packet = json.loads(Path(path).read_bytes())
    body = {k: v for k, v in packet.items() if k != "packet_hash"}
    if _sha(body) != packet.get("packet_hash"):
        raise AuditPacketError("packet failed its integrity check")
    if packet.get("execution_allowed") is not False:
        raise AuditPacketError("packet execution_allowed is not false")
    assert_no_authority(body)
    return packet


__all__ = [
    "AUDIT_SCHEMA",
    "AuditPacketError",
    "PACKET_SCHEMA",
    "assert_no_authority",
    "build_audit_packet",
    "build_instrument_audit",
    "causal_chain",
    "display_value",
    "event_clocks",
    "evidence_layers",
    "evidence_usability",
    "falsifier_view",
    "independent_comparison",
    "load_audit_packet",
    "marketability_context",
    "owner_claim_bridge",
    "replay_check",
    "run_inventory",
    "scenario_view",
    "structural_event_audit",
    "verify_epistemic_labels",
    "write_audit_packet",
]
