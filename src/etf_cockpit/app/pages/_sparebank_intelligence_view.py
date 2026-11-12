"""Presentation of the Sparebank specialist-intelligence audit (#719).

Presentation only: every value comes from ``application.sparebank_intelligence_audit`` (the audit dict, which is also what the
export packet stores, so render == export == reload).  Specialist science and Cockpit evidence stay in separately labelled
cards; probability and confidence stay separate; nothing here averages, reconciles or recalculates.  No button here can
create execution, release or broker authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import flet as ft

from etf_cockpit.app.components.kit import DataTable, Disclosure, EmptyState, GlassCard, Note, TableColumn, Tag

_STATE_KIND = {
    "VALID": "ok", "OK": "ok", "HOLDING": "ok", "reached": "ok",
    "DEGRADED": "warn", "STALE": "warn", "LOW_CONFIDENCE": "warn", "UNOBSERVED": "warn", "NOT_EVALUATED": "mute", "UNEVALUABLE": "warn",
    "INVALID": "bad", "QUARANTINED": "bad", "UNREADABLE": "bad", "BREACHED": "bad", "EXPIRED": "mute", "not_reported": "mute",
}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _seq(value: object) -> Sequence[object]:
    return value if isinstance(value, (list, tuple)) else ()


def _s(value: object, empty: str = "unavailable") -> str:
    if value is None or value == "":
        return empty
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _table(columns: Sequence[tuple[str, str]], rows: Sequence[Mapping[str, object]]) -> ft.Control:
    return DataTable([TableColumn(k, label, sortable=False) for k, label in columns], [{k: _s(r.get(k)) for k, _ in columns} for r in rows], row_height=40)


def _unavailable(title: str, section: object) -> ft.Control:
    return Note(f"{title}: unavailable ({_s(_mapping(section).get('reason'), 'no evidence recorded')}). Nothing is substituted.")


def _tag(state: object) -> ft.Control:
    return Tag(_s(state), _STATE_KIND.get(str(state), "mute"), dense=True)


def _card(title: str, note: str, body: Sequence[ft.Control], key: str) -> ft.Control:
    return GlassCard(title, note=note, body=list(body), key=f"sparebank-intelligence.{key}")


# --------------------------------------------------------------------------- 1. run inventory


def render_run_inventory(inventory: object) -> ft.Control:
    data = _mapping(inventory)
    if data.get("status") != "available":
        return _card("Intelligence runs", "specialist engine", [_unavailable("Run inventory", data)], "inventory")
    rows = []
    for run in [*_seq(data.get("runs")), *_seq(data.get("quarantined"))]:
        r = _mapping(run)
        rows.append({
            "run": r.get("run_id"), "state": r.get("state"), "producer": _mapping(r.get("producer")).get("id"),
            "versions": " / ".join(_s(r.get(k), "-") for k in ("schema_version", "model_version", "code_revision")) if r.get("model_version") else None,
            "known": r.get("known_at_cutoff"), "hash": _s(r.get("content_hash") or r.get("raw_sha256"))[:16],
            "usable": "recommendation evidence" if r.get("usable_as_recommendation_evidence") else "NOT usable: " + ", ".join(_s(x) for x in _seq(r.get("reasons"))),
            "lineage": f"prev {_s(r.get('previous_run_id'), '-')} / next {_s(r.get('superseded_by_run_id'), '-')}",
        })
    body: list[ft.Control] = [_table([("run", "Run"), ("state", "State"), ("producer", "Producer"), ("versions", "Schema/model/code"), ("known", "Known at"),
                                      ("hash", "Hash"), ("usable", "Use"), ("lineage", "Lineage")], rows)]
    if not rows:
        body = [Note("No run has been imported.")]
    return _card("Intelligence runs", "accepted and quarantined; old runs are never changed", body, "inventory")


# --------------------------------------------------------------------------- 2. five layers


def _evidence_table(items: Sequence[object]) -> ft.Control:
    rows = []
    for item in items:
        i = _mapping(item)
        rows.append({"id": i.get("metric_id") or i.get("driver_id"), "cls": i.get("epistemic_class"), "value": i.get("display") if i.get("display") is not None else i.get("value"),
                     "unit": i.get("unit"), "conf": i.get("confidence_class"), "miss": i.get("missingness"), "known": i.get("known_at"), "scope": i.get("scope")})
    return _table([("id", "Item"), ("cls", "Epistemic class"), ("value", "Value"), ("unit", "Unit"), ("conf", "Confidence"), ("miss", "Missingness"), ("known", "Known at"), ("scope", "Scope")], rows)


def _layer_fact(audit: Mapping[str, object]) -> ft.Control:
    layer = _mapping(_mapping(audit.get("layers")).get("fact_base"))
    body = [_evidence_table(_seq(layer.get("items"))) if layer.get("items") else _unavailable("Fact base", layer)]
    return _card("1 Fact base / observed evidence", "OBSERVED only; availability times shown", body, "layer-fact")


def _layer_state(audit: Mapping[str, object]) -> ft.Control:
    layer = _mapping(_mapping(audit.get("layers")).get("current_state"))
    body = [_evidence_table(_seq(layer.get("items"))) if layer.get("items") else _unavailable("Current-state reconstruction", layer)]
    return _card("2 Current-state reconstruction", "CALCULATED and NORMALISED are kept apart from OBSERVED", body, "layer-state")


def _bridge(audit: Mapping[str, object]) -> ft.Control:
    b = _mapping(audit.get("owner_claim_bridge"))
    if b.get("status") != "available":
        return _card("Owner-claim bridge", "who owns what", [Note("Owner valuation and portfolio use are blocked: owner claim not supplied.")], "claim")
    body: list[ft.Control] = []
    if b.get("owner_valuation_blocked"):
        body.append(Note("OWNER VALUATION BLOCKED - portfolio use blocked. No whole-bank multiple is shown. Reasons: " + ", ".join(_s(x) for x in _seq(b.get("block_reasons")))))
    cap, counts, hold = _mapping(b.get("capital")), _mapping(b.get("ec_counts")), _mapping(b.get("holdings"))
    rows = [
        {"k": "Bank legal entity / class", "v": f"{_s(b.get('bank_legal_entity'))} / {_s(b.get('share_class'))}"},
        {"k": "Eierandelskapital", "v": _s(_mapping(cap.get("eierandelskapital")).get("value"))},
        {"k": "Grunnfondskapital", "v": _s(_mapping(cap.get("grunnfondskapital")).get("value"))},
        {"k": "Eierbrok (effective / known)", "v": f"{_s(_mapping(cap.get('eierbrok')).get('value'))} ({_s(_mapping(cap.get('eierbrok')).get('effective_at'))} / {_s(_mapping(cap.get('eierbrok')).get('known_at'))})"},
        {"k": "EC count current / fully diluted / treasury", "v": f"{_s(counts.get('current'))} / {_s(counts.get('fully_diluted'))} / {_s(counts.get('treasury'))}"},
        {"k": "Foundation / strategic / effective free float", "v": f"{_s(hold.get('foundation_share'))} / {_s(hold.get('strategic_share'))} / {_s(hold.get('effective_free_float'))}"},
        {"k": "Voting share (governance only)", "v": _s(hold.get("voting_share"))},
        {"k": "Payout symmetry", "v": _s(b.get("payout_symmetry") if not isinstance(b.get("payout_symmetry"), Mapping) else _mapping(b.get("payout_symmetry")).get("reason") or b.get("payout_symmetry"))},
        {"k": "Claimant allocation / projection", "v": f"{_s(b.get('claimant_allocation_status'))} / {_s(b.get('claimant_projection_status'))} ({_s(b.get('claimant_state'))})"},
        {"k": "Pre-event -> post-event state", "v": f"{_s(b.get('pre_event_state'), 'none')} -> {_s(b.get('post_event_state'), 'none')}"},
    ]
    ov = _mapping(b.get("owner_valuation"))
    if ov.get("status") == "available":
        rows += [{"k": "Owner-attributable book", "v": _s(ov.get("owner_attributable_book"))}, {"k": "Owner-attributable earnings", "v": _s(ov.get("owner_attributable_earnings"))},
                 {"k": "Denominator basis", "v": _s(ov.get("denominator_basis"))}]
    body.append(_table([("k", "Field"), ("v", "Value")], rows))
    return _card("Owner-claim bridge", "specialist claim data; unresolved allocation blocks owner valuation", body, "claim")


def _event(audit: Mapping[str, object]) -> ft.Control:
    e = _mapping(_mapping(audit.get("layers")).get("transition_model"))
    if e.get("status") != "available":
        return _card("3 Transition model / structural event", "mechanism and event state", [_unavailable("Structural event", e)], "layer-transition")
    body: list[ft.Control] = [Note(f"{_s(e.get('event_type'))} {_s(e.get('event_id'))} - milestone: {_s(e.get('milestone'))}")]
    ledgers = _mapping(e.get("ledgers"))
    body.append(_table([("k", "Ledger"), ("v", "Reference")], [{"k": k, "v": v} for k, v in ledgers.items()]))
    ratios = _mapping(e.get("four_ratios"))
    if ratios.get("status") == "available":
        body.append(_table([("label", "Merger ratio (distinct quantity)"), ("value", "Value")], [_mapping(r) for r in _seq(ratios.get("ratios"))]))
        if ratios.get("coincident_values"):
            body.append(Note("Some ratios carry equal numbers: " + ", ".join(_s(x) for x in _seq(ratios.get("coincident_values"))) + ". They remain separate quantities."))
    groups = _mapping(e.get("recipient_groups"))
    body.append(_table([("claimant", "Recipient group"), ("kind", "Consideration"), ("source", "Source"), ("legal_bridge_ref", "Legal bridge")], [_mapping(g) for g in _seq(groups.get("groups"))])
                if groups.get("groups") else _unavailable("Recipient groups", groups))
    pp = _mapping(e.get("pre_post"))
    body.append(_table([("k", "Pre / post"), ("v", "Value")], [
        {"k": "Pre-event EC count", "v": _s(pp.get("pre_ec_count"))}, {"k": "Post-event EC count", "v": _s(pp.get("post_ec_count"))},
        {"k": "Owner value per legacy EC (specialist model)", "v": _s(pp.get("owner_value_per_legacy_ec"))}]))
    syn = [_mapping(s) for s in _seq(e.get("synergies"))]
    if syn:
        body.append(_table([("component", "Synergy / cost component"), ("state", "State (target -> seasoned)"), ("value", "Value")], syn))
    approvals = _mapping(e.get("approvals"))
    body.append(Note("Unresolved approvals: " + (", ".join(_s(a) for a in _seq(approvals.get("items"))) or "none reported") if approvals.get("status") == "available" else "Unresolved approvals: not supplied."))
    body.append(_clocks(_mapping(e.get("clocks"))))
    return _card("3 Transition model / structural event", "pre/post owner bridge, four ratios, recipients and clocks", body, "layer-transition")


def _clocks(clocks: Mapping[str, object]) -> ft.Control:
    if clocks.get("status") != "available":
        return Note("Clocks: unavailable.")
    c = _mapping(clocks.get("clocks"))
    rows = [{"clock": name, "status": _mapping(c.get(name)).get("status"), "detail": _clock_detail(name, _mapping(c.get(name)))} for name in ("economic", "accounting", "market", "institutional")]
    body: list[ft.Control] = [_table([("clock", "Clock"), ("status", "Status"), ("detail", "Detail")], rows)]
    stages = clocks.get("merger_stages")
    if stages:
        body.append(_table([("stage", "Merger stage"), ("status", "Status"), ("at", "At")], [_mapping(s) for s in _seq(stages)]))
    body.append(Note(_s(clocks.get("economic_maturity_note"))))
    return ft.Column(body, spacing=8)


def _clock_detail(name: str, clock: Mapping[str, object]) -> str:
    if clock.get("status") != "available":
        return "no dated evidence"
    if name == "institutional":
        return f"milestone {_s(clock.get('current_milestone'))}; integration {_s(clock.get('integration_state'))}"
    if name == "economic":
        return ", ".join(f"{_s(s.get('component'))}:{_s(s.get('state'))}" for s in map(_mapping, _seq(clock.get("synergy_states")))) or "supplied clock"
    if name == "accounting":
        return f"ledger {_s(clock.get('ledger_ref'))}"
    return f"price time {_s(clock.get('price_time'))}"


def _scenarios(audit: Mapping[str, object]) -> ft.Control:
    v = _mapping(_mapping(_mapping(audit.get("layers")).get("valuation_expectations")).get("scenarios"))
    if v.get("status") != "available":
        return _card("4 Valuation and expectations", "scenarios", [_unavailable("Scenarios", v)], "layer-valuation")
    rows = [{**_mapping(s), "value": _mapping(s).get("value_display"), "probability": _mapping(s).get("probability_display")} for s in _seq(v.get("scenarios"))]
    body: list[ft.Control] = [_table([("name", "Scenario"), ("value", "Value"), ("probability", "State probability"), ("probability_confidence", "Probability confidence"), ("evidence_state", "Evidence state")], rows)]
    body.append(Row_tags([_mapping(s) for s in _seq(v.get("scenarios"))]))
    dist = _mapping(v.get("distribution"))
    body.append(Note(f"Distribution ({_s(dist.get('horizon'))}): " + ", ".join(f"{k}={_s(x)}" for k, x in _mapping(dist.get("quantiles")).items())) if dist.get("quantiles") else Note("Distribution: unavailable."))
    body.append(Note(f"Reference price (Cockpit): {_s(v.get('reference_price'))}. No weighted average is shown; probability and confidence are separate fields."))
    expect = _mapping(_mapping(_mapping(audit.get("layers")).get("valuation_expectations")).get("evidence"))
    for cls, items in _mapping(expect.get("by_class")).items():
        body.append(Note(f"{cls}:"))
        body.append(_evidence_table(_seq(items)))
    return _card("4 Valuation and expectations", "specialist model output, labelled by epistemic class", body, "layer-valuation")


def Row_tags(scenarios: Sequence[Mapping[str, object]]) -> ft.Control:  # noqa: N802
    return ft.Row([ft.Row([ft.Text(_s(s.get("name")), size=12), _tag(s.get("evidence_state"))], spacing=6) for s in scenarios], spacing=14, wrap=True)


def _falsifiers(audit: Mapping[str, object]) -> ft.Control:
    f = _mapping(_mapping(_mapping(audit.get("layers")).get("valuation_expectations")).get("assumption_burden"))
    rows = [_mapping(k) for k in _seq(f.get("kill_variables"))]
    body: list[ft.Control] = [_table([("variable", "Review/kill variable"), ("comparator", "Rule"), ("threshold", "Threshold"), ("observed", "Observed"), ("expires_at", "Expires"), ("state", "State")], rows)
                              if rows else Note("No falsification variables were supplied.")]
    body.append(Row_tags([{"name": _s(r.get("variable")), "evidence_state": r.get("state")} for r in rows]))
    if f.get("re_underwrite_required"):
        body.append(Note("A falsifier is BREACHED: re-underwrite on a new run. Expired falsifiers are shown separately and are not treated as breaches."))
    body.append(Note("Drivers: " + (", ".join(_s(x) for x in _seq(f.get("drivers"))) or "none") + ". Legitimate outcomes: no action, watch, re-underwrite."))
    return _card("Assumption burden and falsification", "drivers, review and kill variables", body, "falsifiers")


def _comparison(audit: Mapping[str, object]) -> ft.Control:
    c = _mapping(audit.get("independent_comparison"))
    if c.get("status") != "available":
        return _card("Independent-evidence comparison", "specialist vs generic Cockpit", [_unavailable("Comparison", c)], "comparison")
    sv = _mapping(c.get("standalone_value"))
    generic = _mapping(sv.get("generic"))
    rows = [{"metric": "standalone value", "specialist": sv.get("specialist_standalone_value"), "generic": generic.get("standalone_value"),
             "diff": f"gap {_s(sv.get('relative_gap'))} ({_s(sv.get('status'))}); definition: {_s(generic.get('definition'))}"}]
    for r in map(_mapping, _seq(c.get("rows"))):
        rows.append({"metric": r.get("metric_id"), "specialist": _mapping(r.get("specialist")).get("value"), "generic": _mapping(r.get("generic")).get("value"),
                     "diff": ", ".join(_s(d) for d in _seq(r.get("differences"))) or _s(r.get("reason"), "no definitional difference reported")})
    treatment = _mapping(c.get("cockpit_policy_treatment"))
    body = [_table([("metric", "Metric"), ("specialist", "Specialist engine"), ("generic", "Generic Cockpit"), ("diff", "Differences")], rows),
            Note(f"Not averaged and not reconciled. Cockpit policy treatment: {_s(treatment.get('action'))} {', '.join(_s(x) for x in _seq(treatment.get('reason_codes')))}. " + _s(c.get("note")))]
    return _card("Independent-evidence comparison", "side by side, neither certifies the other", body, "comparison")


def _decision(audit: Mapping[str, object]) -> ft.Control:
    d = _mapping(_mapping(audit.get("layers")).get("cockpit_decision"))
    if d.get("status") != "available":
        return _card("5 Cockpit decision", "Cockpit evidence, not specialist science", [_unavailable("Cockpit decision", d)], "layer-decision")
    gates = [{"gate": g.get("gate_id"), "result": "passed" if g.get("passed") else "FAILED", "detail": g.get("detail")} for g in map(_mapping, _seq(d.get("gates")))]
    sizing = _mapping(d.get("cockpit_weight_result"))
    body: list[ft.Control] = [
        Note(f"Decision {_s(d.get('decision_id'))}: {_s(d.get('action'))} - reasons: {', '.join(_s(x) for x in _seq(d.get('reason_codes'))) or 'none'}"),
        Note(f"Cockpit-owned sizing result: {_s(sizing.get('result'))} (ceiling {_s(sizing.get('ceiling'))}, binding {', '.join(_s(x) for x in _seq(sizing.get('ceiling_binding'))) or 'none'}). Paper proposal only; execution_allowed=false."),
        _table([("gate", "Gate"), ("result", "Result"), ("detail", "Detail")], gates) if gates else Note("No gate evidence recorded."),
    ]
    return _card("5 Cockpit decision", "Cockpit evidence, labelled separately from the specialist engine", body, "layer-decision")


def _marketability(audit: Mapping[str, object]) -> ft.Control:
    m = _mapping(audit.get("marketability"))
    if m.get("status") != "available":
        return _card("Marketability and implementation context", "Cockpit side", [_unavailable("Marketability", m)], "market")
    price, mv, liq, pf = _mapping(m.get("price")), _mapping(m.get("market_value")), _mapping(m.get("liquidity")), _mapping(m.get("portfolio"))
    rows = [
        {"k": "Price (Cockpit)", "v": f"{_s(price.get('value'))} {_s(price.get('currency'), '')} at {_s(price.get('price_time'))}"},
        {"k": "Headline vs effective free-float market value", "v": f"{_s(mv.get('headline'))} vs {_s(mv.get('effective_free_float'))}"},
        {"k": "ADV / spread bps / commission bps", "v": f"{_s(liq.get('adv_value'))} / {_s(liq.get('spread_bps'))} / {_s(liq.get('commission_bps'))}"},
        {"k": "Current weight / sector exposure", "v": f"{_s(pf.get('current_weight'))} / {_s(pf.get('sector_exposure_excluding_candidate'))} ({_s(pf.get('revision'))})"},
        {"k": "Binding size ceilings", "v": ", ".join(_s(x) for x in _seq(_mapping(m.get("size_ceilings")).get("binding"))) or "none"},
        {"k": "Implementation-adjusted net annual return", "v": _s(_mapping(m.get("implementation_adjusted")).get("net_annual_return"))},
    ]
    return _card("Marketability and implementation context", "Cockpit market/portfolio evidence, not friend-engine science; timestamped", [_table([("k", "Item"), ("v", "Value")], rows)], "market")


def _chain(audit: Mapping[str, object]) -> ft.Control:
    chain = _mapping(audit.get("causal_chain"))
    replay = _mapping(audit.get("replay"))
    rows = [{"stage": n.get("stage"), "status": n.get("status"), "hashes": "; ".join(f"{k}={_s(v)[:16]}" for k, v in _mapping(n.get("hashes")).items()) or _s(n.get("reason"))}
            for n in map(_mapping, _seq(chain.get("nodes")))]
    body: list[ft.Control] = [_table([("stage", "Stage"), ("status", "Status"), ("hashes", "Hashes / versions")], rows) if rows else _unavailable("Causal chain", chain),
                              Note(f"Chain hash {_s(chain.get('chain_hash'))[:16]}; replay reproduced: {_s(replay.get('reproduced'), _s(replay.get('reason')))}. New runs never rewrite old evidence.")]
    return _card("Causal audit chain", "source -> run -> resolution -> scenarios -> Cockpit context -> gates -> paper decision", body, "chain")


# --------------------------------------------------------------------------- public


def render_intelligence_audit(audit: object, *, inventory: object = None) -> ft.Control:
    """Audit view for one EC; an empty container when no audit is supplied (nothing is invented)."""

    data = _mapping(audit)
    if not data and not _mapping(inventory):
        return ft.Container()
    body: list[ft.Control] = []
    if _mapping(inventory):
        body.append(render_run_inventory(inventory))
    if data and data.get("status") != "available":
        body.append(EmptyState("Specialist audit unavailable", _s(data.get("reason"), "no evidence recorded")))
    elif data:
        run = _mapping(data.get("run"))
        body.append(Note("Specialist engine output is shown as supplied and kept apart from Cockpit's independent evidence and decision. "
                         "Observed, calculated, normalised, model-estimate, assumption, management-target, thesis and speculation labels are never merged."))
        body.append(ft.Row([_tag(run.get("state")), ft.Text(f"run {_s(run.get('run_id'))}  known at {_s(run.get('known_at_cutoff'))}", size=12)], spacing=8))
        if not run.get("usable_as_recommendation_evidence"):
            body.append(Note("This run is NOT usable as recommendation evidence: " + ", ".join(_s(x) for x in _seq(run.get("usability_reasons")))))
        body += [_layer_fact(data), _layer_state(data), _bridge(data), _event(data), _scenarios(data), _falsifiers(data), _comparison(data), _decision(data),
                 _marketability(data), _chain(data), Disclosure("Audit: complete stored audit packet body", _pretty(data), expanded=False)]
    return ft.ExpansionTile(
        title=ft.Text("Specialist intelligence audit"),
        subtitle=ft.Text("owner claim, transition and decision audit | execution_allowed=false"),
        controls=[ft.Column(body, spacing=10)], expanded=False, key="instrument-detail.sparebank-intelligence-audit",
    )


def _pretty(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)


__all__ = ["render_intelligence_audit", "render_run_inventory"]
