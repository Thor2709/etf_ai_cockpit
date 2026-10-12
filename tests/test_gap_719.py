from __future__ import annotations

import copy
import json
from pathlib import Path

import flet as ft
import pytest

from etf_cockpit.app.pages._sparebank_intelligence_view import render_intelligence_audit
from etf_cockpit.application.sparebank_intelligence_audit import (
    AuditPacketError,
    assert_no_authority,
    build_audit_packet,
    build_instrument_audit,
    display_value,
    load_audit_packet,
    run_inventory,
    write_audit_packet,
)
from etf_cockpit.application.sparebank_intelligence_workflow import build_resolution_projection
from etf_cockpit.application.sparebank_opportunity import DecisionStore, decide, replay_decision
from etf_cockpit.data.sparebank_run_store import SparebankRunStore

from test_gap_717 import _envelope as _env717, _identity as _identity717, _import as _import717, _merger, _run as _run717
from test_gap_718 import (  # noqa: F401 - autouse authority-matrix fixture must be active
    AUTHORITY,
    CANDIDATE,
    NOW,
    POLICY,
    _authority_matrix,
    _bundle,
    _context,
    _envelope,
)

AS_OF = "2026-09-10T12:00:00+00:00"


def _texts(control: object, out: list[str] | None = None) -> list[str]:
    """All visible strings of a Flet control tree (Text values, tab/table cells, titles)."""

    out = [] if out is None else out
    if isinstance(control, str):
        out.append(control)
    elif isinstance(control, (list, tuple)):
        for item in control:
            _texts(item, out)
    elif isinstance(control, ft.Control):
        for name in ("value", "text", "label", "title", "subtitle", "content", "controls", "cells", "rows", "columns", "leading", "trailing"):
            child = getattr(control, name, None)
            if child is not None and child is not control:
                _texts(child, out)
    return out


def _view_text(audit: dict, inventory: dict | None = None) -> str:
    return "\n".join(_texts(render_intelligence_audit(audit, inventory=inventory))).lower()


def _decision(run: dict, resolution: dict, **context) -> dict:
    return decide(run, resolution, _context(**context), POLICY, AUTHORITY, attachments_verified=True).payload


def test_run_inventory_lineage_quarantine_and_usability(tmp_path: Path) -> None:
    runs = SparebankRunStore(tmp_path / "runs")
    env = _envelope()
    first = _import717(runs, env)
    later = copy.deepcopy(env)
    later.update(run_id="run-fixture-rich-0002", known_at_cutoff="2026-09-05T00:00:00+00:00", generated_at="2026-09-06T00:00:00+00:00")
    _import717(runs, later)
    assert runs.import_bytes(b"{not json", source="t", now=NOW).status == "QUARANTINED"

    inventory = run_inventory(runs, as_of="2026-09-30T00:00:00+00:00")
    by_id = {r["run_id"]: r for r in inventory["runs"]}
    assert by_id[first]["superseded_by_run_id"] == "run-fixture-rich-0002" and by_id["run-fixture-rich-0002"]["previous_run_id"] == first
    assert by_id[first]["raw_sha256"] and by_id[first]["content_hash"] and by_id[first]["attachments"][0]["sha256"]
    assert by_id[first]["assets"] == ["SYNTH-EC-1", "SYNTH-EC-2", "SYNTH-EC-3"] and by_id[first]["unresolved"]["status"] == "unavailable"
    assert by_id[first]["usable_as_recommendation_evidence"] is True
    (quarantined,) = inventory["quarantined"]
    assert quarantined["state"] == "QUARANTINED" and quarantined["usable_as_recommendation_evidence"] is False and quarantined["reasons"]

    stale = run_inventory(runs, as_of="2027-03-01T00:00:00+00:00")
    assert all(r["state"] == "STALE" and not r["usable_as_recommendation_evidence"] for r in stale["runs"])  # stale never looks like valid evidence
    assert run_inventory(SparebankRunStore(tmp_path / "empty"), as_of=AS_OF)["status"] == "unavailable"
    text = _view_text({}, inventory)
    assert "QUARANTINED".lower() in text and "NOT usable".lower() in text and first in text


def test_five_layers_keep_labels_and_separate_confidence_through_export_reload(tmp_path: Path) -> None:
    run, resolution = _bundle(tmp_path)
    decision = _decision(run, resolution)
    audit = build_instrument_audit(run, resolution, CANDIDATE, decision=decision)
    assert audit["label_violations"] == [] and audit["execution_allowed"] is False
    layers = audit["layers"]
    assert {i["epistemic_class"] for i in layers["fact_base"]["items"]} == {"OBSERVED"}
    assert {i["epistemic_class"] for i in layers["current_state"]["items"]} == {"CALCULATED", "NORMALISED"}
    by_class = layers["valuation_expectations"]["evidence"]["by_class"]
    assert set(by_class) == {"MODEL_ESTIMATE", "ASSUMPTION", "MANAGEMENT_TARGET", "THESIS", "SPECULATION"}  # never collapsed or promoted
    assert by_class["THESIS"][0]["metric_id"] == "thesis_margin" and by_class["THESIS"][0]["low_confidence"] is True
    assert display_value(0.123456, "HIGH") == "0.1235" and display_value(0.123456, "LOW") == "0.12"  # precision follows confidence
    scenarios = layers["valuation_expectations"]["scenarios"]["scenarios"]
    assert [(s["name"], s["probability"], s["probability_confidence"], s["evidence_state"]) for s in scenarios] == [
        ("downside", 0.25, "LOW", "LOW_CONFIDENCE"), ("standalone", 0.5, "MEDIUM", "OK"), ("upside", 0.25, "LOW", "LOW_CONFIDENCE")]
    assert layers["cockpit_decision"]["layer"] == "COCKPIT_DECISION" and audit["marketability"]["side"] == "COCKPIT"
    assert audit["marketability"]["price"]["price_time"] == "2026-09-10T10:00:00+00:00"  # timestamped Cockpit context

    packet = build_audit_packet(run, resolution, CANDIDATE, decision=decision)
    path = write_audit_packet(packet, tmp_path / "packets")
    assert write_audit_packet(packet, tmp_path / "packets") == path  # idempotent
    reloaded = load_audit_packet(path)
    assert reloaded == packet and reloaded["audit"] == audit and reloaded["execution_allowed"] is False
    assert reloaded["audit"]["layers"]["valuation_expectations"]["scenarios"]["scenarios"] == scenarios  # probability + confidence survive
    assert _view_text(reloaded["audit"]) == _view_text(audit)  # render(reload) == render(original)
    text = _view_text(audit)
    for expected in ("OBSERVED", "NORMALISED", "THESIS", "SPECULATION", "State probability", "Probability confidence", "LOW_CONFIDENCE", "Cockpit decision"):
        assert expected.lower() in text

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["audit"]["instrument_id"] = "OTHER"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(AuditPacketError):
        load_audit_packet(path)


def test_claimant_ambiguity_blocks_owner_valuation_and_merger_audit_keeps_four_ratios(tmp_path: Path) -> None:
    run, resolution = _bundle(tmp_path)
    bad = copy.deepcopy(run)
    bad["owner_claims"][0]["claimant_allocation_status"] = "UNRESOLVED"
    bad["owner_claims"][0].pop("owner_valuation")
    audit = build_instrument_audit(bad, resolution, CANDIDATE, as_of=AS_OF)
    bridge = audit["owner_claim_bridge"]
    assert bridge["owner_valuation_blocked"] and bridge["portfolio_use_blocked"] and bridge["owner_valuation"]["status"] == "unavailable"
    assert {"claimant_allocation_unresolved", "owner_valuation_missing"} <= set(bridge["block_reasons"]) and bridge["whole_bank_multiples"] == "not_shown"
    text = _view_text(audit)
    assert "OWNER VALUATION BLOCKED".lower() in text and "Owner-attributable book".lower() not in text

    runs, merged = _run717(tmp_path / "m")
    projection = build_resolution_projection(merged, _identity717(tmp_path / "m"), raw_sha256="r" * 64)
    audit = build_instrument_audit(merged, projection, "SYNTH-EC-2", as_of=AS_OF)
    event = audit["layers"]["transition_model"]
    ratios = {r["name"]: r["value"] for r in event["four_ratios"]["ratios"]}
    assert ratios == {"bank_value_split": 0.6, "target_ec_conversion_ratio": 1.2, "post_merger_ec_class_split": 0.55, "post_merger_eierbrok": 0.6}
    assert event["four_ratios"]["coincident_values"] == ["bank_value_split", "post_merger_eierbrok"]  # equal numbers stay separate quantities
    groups = {(g["claimant"], g["source"]) for g in event["recipient_groups"]["groups"]}
    assert ("foundation", "FOUNDATION_ISSUED") in groups and ("legacy_private_ec_holders", "BANK_ISSUED") in groups
    assert not any(c == "legacy_private_ec_holders" and s == "FOUNDATION_ISSUED" for c, s in groups)
    assert event["pre_post"]["pre_ec_count"] == merged["owner_claims"][1]["ec_count_current"] and event["pre_post"]["post_ec_count"] == 12_000_000
    assert {s["component"] for s in event["synergies"]} == {"COST", "INTEGRATION_COST"}
    stages = {s["stage"]: s["status"] for s in event["clocks"]["merger_stages"]}
    assert stages["legal_completion"] == "reached" and stages["economic_maturity"] == "not_reported"  # legal != economic
    assert event["clocks"]["economic_maturity_note"] == "legal completion is not economic maturity"
    assert set(event["clocks"]["clocks"]) == {"economic", "accounting", "market", "institutional"}

    packet = build_audit_packet(merged, projection, "SYNTH-EC-2", as_of=AS_OF)
    again = load_audit_packet(write_audit_packet(packet, tmp_path / "p"))
    assert again["audit"]["layers"]["transition_model"]["four_ratios"] == event["four_ratios"]
    text = _view_text(again["audit"])
    for label in ("Bank-level value split", "Target EC conversion ratio", "Post-merger EC ownership split", "Post-merger eierbrøk", "legal completion is not economic maturity"):
        assert label.lower() in text


def test_disagreement_falsifiers_chain_and_replay_survive_restart(tmp_path: Path) -> None:
    env = _envelope()
    env["monitoring"]["kill_variables"].append({"variable": "npl_ratio", "comparator": ">", "threshold": 0.05, "expires_at": "2026-08-01T00:00:00+00:00"})
    env["valuations"][0]["scenarios"][2]["expires_at"] = "2026-09-01T00:00:00+00:00"
    run, resolution = _bundle(tmp_path, env)
    generic = {"version": "generic-bank.v1", "standalone_value": 60.0, "definition": "generic residual income"}
    decision = _decision(run, resolution, generic_evidence=generic, observed_kill_variables={"npl_ratio": 0.2})
    generic_rows = [{"metric_id": "through_cycle_roe", "value": 0.07, "definition": "def.generic_roe", "period": "2026Q2", "unit": "ratio",
                     "source": "generic:fundamentals", "known_at": "2026-08-25T00:00:00+00:00", "claimant_denominator": "whole_bank"}]
    audit = build_instrument_audit(run, resolution, CANDIDATE, decision=decision, generic_rows=generic_rows, paper_refs={"paper_ledger_ref": "ledger-1"})

    comparison = audit["independent_comparison"]
    assert comparison["averaged"] is False and comparison["standalone_value"]["specialist_standalone_value"] == 110.0
    assert comparison["standalone_value"]["generic"]["standalone_value"] == 60.0 and "specialist_generic_disagreement" in comparison["cockpit_policy_treatment"]["reason_codes"]
    (row,) = comparison["rows"]
    assert row["specialist"]["value"] == 0.095 and row["generic"]["value"] == 0.07 and {"definition", "claimant_denominator", "source"} <= set(row["differences"])

    kills = {k["variable"]: k["state"] for k in audit["layers"]["valuation_expectations"]["assumption_burden"]["kill_variables"]}
    assert kills == {"cet1_ratio": "UNOBSERVED", "npl_ratio": "EXPIRED"}
    breached = _decision(run, resolution, observed_kill_variables={"cet1_ratio": 0.10, "npl_ratio": 0.2})
    assert breached["action"] == "BLOCK"
    breached_audit = build_instrument_audit(run, resolution, CANDIDATE, decision=breached)
    burden = breached_audit["layers"]["valuation_expectations"]["assumption_burden"]
    assert {k["variable"]: k["state"] for k in burden["kill_variables"]} == {"cet1_ratio": "BREACHED", "npl_ratio": "EXPIRED"}  # distinct states
    assert burden["re_underwrite_required"] is True
    states = {s["name"]: s["evidence_state"] for s in audit["layers"]["valuation_expectations"]["scenarios"]["scenarios"]}
    assert states == {"downside": "LOW_CONFIDENCE", "standalone": "OK", "upside": "EXPIRED"}
    text = _view_text(audit) + _view_text(breached_audit)
    assert "BREACHED".lower() in text and "EXPIRED".lower() in text and "LOW_CONFIDENCE".lower() in text and "Not averaged and not reconciled".lower() in text

    chain = audit["causal_chain"]
    stages = {n["stage"]: n for n in chain["nodes"]}
    assert stages["specialist_run"]["hashes"]["content_hash"] == run["content_hash"] and stages["paper_proposal_or_no_action"]["hashes"]["decision_hash"] == decision["decision_hash"]
    assert stages["paper_fill_replay"]["hashes"] == {"paper_ledger_ref": "ledger-1"} and stages["claimant_pit_resolution"]["hashes"]["projection_hash"] == resolution["projection_hash"]
    assert audit["replay"]["reproduced"] is True

    store = DecisionStore(tmp_path / "decisions")
    result = decide(run, resolution, _context(generic_evidence=generic, observed_kill_variables={"npl_ratio": 0.2}), POLICY, AUTHORITY, attachments_verified=True)
    store.save(result)
    restarted = DecisionStore(tmp_path / "decisions").load(result.decision_id)
    after = build_instrument_audit(run, resolution, CANDIDATE, decision=restarted, generic_rows=generic_rows, paper_refs={"paper_ledger_ref": "ledger-1"})
    assert after == audit and replay_decision(restarted, run, resolution).payload == restarted  # identical after restart + historical replay

    other = copy.deepcopy(run)
    other["content_hash"] = "f" * 64
    assert build_instrument_audit(other, resolution, CANDIDATE, decision=restarted)["replay"]["reproduced"] is False


def test_missing_or_invalid_evidence_is_unavailable_and_no_authority_can_leak(tmp_path: Path) -> None:
    missing = build_instrument_audit(None, None, CANDIDATE, as_of=AS_OF)
    assert missing["status"] == "unavailable" and missing["reason"] == "run_missing_or_unverifiable"
    assert "unavailable".lower() in _view_text(missing) and "State probability".lower() not in _view_text(missing)

    run, resolution = _bundle(tmp_path)
    bare = build_instrument_audit(run, resolution, CANDIDATE, as_of=AS_OF)  # no Cockpit decision recorded: no values invented
    assert bare["layers"]["cockpit_decision"]["status"] == "unavailable" and bare["marketability"]["status"] == "unavailable"
    assert bare["causal_chain"]["status"] == "unavailable" and bare["replay"]["status"] == "unavailable"
    assert all(k["state"] in {"NOT_EVALUATED", "EXPIRED"} for k in bare["layers"]["valuation_expectations"]["assumption_burden"]["kill_variables"])
    assert bare["independent_comparison"]["status"] == "unavailable"

    invalid = copy.deepcopy(run)
    invalid["status"] = "INVALID"
    shown = build_instrument_audit(invalid, resolution, CANDIDATE, as_of=AS_OF)
    assert shown["run"]["usable_as_recommendation_evidence"] is False and "run_invalid" in shown["run"]["usability_reasons"]
    assert "NOT usable as recommendation evidence".lower() in _view_text(shown)
    unknown_time = build_instrument_audit(run, resolution, CANDIDATE)
    assert unknown_time["run"]["usable_as_recommendation_evidence"] is False and "freshness_unverifiable" in unknown_time["run"]["usability_reasons"]

    for forbidden in ({"target_weight": 0.1}, {"nested": [{"order": "x"}]}, {"execution_allowed": True}):
        with pytest.raises(AuditPacketError):
            assert_no_authority(forbidden)
    packet = build_audit_packet(run, resolution, CANDIDATE, as_of=AS_OF)
    assert packet["execution_allowed"] is False and packet["audit"]["authority"] == {
        "execution_allowed": False, "proposal_authority": False, "release_authority": False, "broker_authority": False}
    forged = {**{k: v for k, v in packet.items() if k != "packet_hash"}, "execution_allowed": True}
    with pytest.raises(AuditPacketError):
        write_audit_packet({**forged, "packet_hash": packet["packet_hash"]}, tmp_path / "forged")
