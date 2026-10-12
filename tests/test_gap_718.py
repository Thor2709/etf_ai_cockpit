from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import etf_cockpit.portfolio.proposal_policy as proposal_policy
from etf_cockpit.application.sparebank_intelligence_workflow import build_resolution_projection
from etf_cockpit.application.sparebank_opportunity import (
    DecisionContext,
    DecisionStore,
    OpportunityPolicy,
    ProposalAuthority,
    advisory_input,
    decide,
    emit_paper_proposal,
    replay_decision,
    reprice,
    returns_payload,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityClaim
from etf_cockpit.data.sparebank_intelligence import seal_envelope
from etf_cockpit.data.sparebank_run_store import SparebankRunStore
from etf_cockpit.portfolio.sparebank_constraints import CeilingInputs, CeilingPolicy, compute_ceilings

FIXTURE = Path(__file__).parent / "fixtures" / "sparebank_intelligence" / "rich_v1.json"
ATTACHMENT = b'{"posterior":"synthetic"}'
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
CANDIDATE = "SYNTH-EC-1"
DECISION_TIME = "2026-09-10T12:00:00+00:00"
POLICY = OpportunityPolicy()


@pytest.fixture(autouse=True)
def _authority_matrix(monkeypatch):
    caps = tuple(
        SimpleNamespace(capability_id=cid, authority_stage="paper", availability="mandatory",
                        required_approvals=("paper_simulation_review",), max_quantity_delta=1_000_000.0)
        for cid in ("strategy:paper_portfolio", "model:paper", "broker:paper_portfolio")
    )
    result = SimpleNamespace(diagnostic_mode=False, diagnostics=(), checksum="a" * 64, policy=SimpleNamespace(capabilities=caps))
    monkeypatch.setattr(proposal_policy, "load_authority_matrix", lambda: result)


AUTHORITY = ProposalAuthority("strategy:paper_portfolio", "paper", "model:paper", "paper", "broker:paper_portfolio", "paper", "a" * 64,
                              ("paper_simulation_review",))


def _claim(iid: str, field: str, value: str) -> IdentityClaim:
    return IdentityClaim(iid, field, value, "fixture", SourceAuthority.OFFICIAL, f"{iid}:{field}", valid_from="2025-01-01T00:00:00Z",
                         available_at="2026-01-01T00:00:00Z")


def _identity(tmp_path: Path, ids=("SYNTH-EC-1", "SYNTH-EC-2")) -> IdentityMasterStore:
    store = IdentityMasterStore(tmp_path / "identity")
    store.append_claims([_claim(iid, f, v) for n, iid in enumerate(ids, 1) for f, v in (
        ("ticker", f"SB{n}"), ("isin", f"NO000000000{n}"), ("name", f"Synth {n}"), ("exchange", "XOSL"), ("currency", "NOK"),
        ("asset_type", "equity"), ("mic", "XOSL"))])
    return store


def _envelope(**advisory_extra) -> dict:
    env = json.loads(FIXTURE.read_text(encoding="utf-8"))
    env["advisory"][0].update(maximum_allowed=0.03, **advisory_extra)
    return env


def _bundle(tmp_path: Path, env: dict | None = None, ids=("SYNTH-EC-1", "SYNTH-EC-2")) -> tuple[dict, dict]:
    runs = SparebankRunStore(tmp_path / "runs")
    env = env or _envelope()
    raw = json.dumps(seal_envelope(env), sort_keys=True).encode("utf-8")
    assert runs.import_bytes(raw, source="t", attachments={"posterior-summary": ATTACHMENT}, now=NOW).status == "IMPORTED"
    run = runs.get_run(env["run_id"])
    return run, build_resolution_projection(run, _identity(tmp_path, ids), raw_sha256="r" * 64)


def _returns() -> dict:
    rng = np.random.default_rng(718)
    index = pd.bdate_range("2026-03-02", periods=120)
    frame = pd.DataFrame({CANDIDATE: rng.normal(0.0004, 0.012, 120), "ETF-A": rng.normal(0.0002, 0.006, 120)}, index=index)
    return returns_payload(frame)


def _context(**changes) -> DecisionContext:
    values = dict(
        instrument_id=CANDIDATE, decision_time=DECISION_TIME, knowledge_cutoff=DECISION_TIME, price=90.0, price_time="2026-09-10T10:00:00+00:00",
        price_currency="NOK", base_currency="NOK", fx_rate=1.0, fx_time="2026-09-10T10:00:00+00:00", spread_bps=40.0, commission_bps=5.0,
        adv_value=5_000_000.0, market_cap=10_000_000_000.0, portfolio_id="paper-1", portfolio_revision="rev-1", portfolio_value=1_000_000.0,
        current_weight=0.0, sector_exposure_excluding_candidate=0.05, cash_return=0.03,
        alternatives=({"id": "ETF-A", "expected_return": 0.04, "switching_cost_bps": 10.0},), returns=_returns(),
        generic_evidence={"version": "generic-bank.v1", "standalone_value": 108.0, "definition": "generic residual income"},
    )
    values.update(changes)
    return DecisionContext(**values)


def test_advisory_input_repricing_and_unchanged_run(tmp_path: Path) -> None:
    run, _ = _bundle(tmp_path)
    before = copy.deepcopy(run)
    advisory = advisory_input(run, CANDIDATE)
    assert advisory["layer"] == "SPECIALIST_ADVISORY" and advisory["specialist_maximum"] == 0.03
    assert "never copied into target weight" in advisory["transformation"]
    advisory["raw_scenarios"] = run["valuations"][0]["scenarios"]

    cheap, dear = reprice(advisory, _context(price=90.0), POLICY), reprice(advisory, _context(price=130.0), POLICY)
    assert cheap["layer"] == "COCKPIT_DECISION" and cheap["horizon_source"] == "specialist_distribution_horizon" and cheap["horizon_years"] == 3
    assert cheap["no_catalyst_coverage"] == pytest.approx(110 / 90)
    assert cheap["price_implied_transition_probability"]["value"] == pytest.approx((90 - 110) / 30)  # below standalone: out of range
    assert cheap["price_implied_transition_probability"]["in_range"] is False
    assert cheap["net_annual_return"] > 0 > dear["net_annual_return"]
    assert run == before  # a price move never touches the specialist run

    expired = copy.deepcopy(advisory)
    expired["raw_scenarios"][2]["expires_at"] = "2026-09-01T00:00:00+00:00"
    assert [s["value"] for s in reprice(expired, _context(), POLICY)["scenarios_used"]] == [80.0, 110.0, 110.0]  # stale optionality removed
    no_price = reprice(advisory, _context(price=None), POLICY)
    assert no_price["status"] == "unavailable" and "net_annual_return" not in no_price  # unavailable, not a value


def test_cockpit_owns_weight_inside_ceilings_and_replays(tmp_path: Path) -> None:
    run, resolution = _bundle(tmp_path)
    result = decide(run, resolution, _context(), POLICY, AUTHORITY, attachments_verified=True)
    assert result.action == "PROPOSE", result.payload["reason_codes"]
    sizing, ceilings = result.payload["sizing"], result.payload["ceilings"]
    advisory_range = run["advisory"][0]["suggested_exposure_range"]
    assert 0 < sizing["target_weight"] <= ceilings["ceiling"] < advisory_range["high"] + 1  # Cockpit output, inside every ceiling
    assert all(sizing["target_weight"] <= v + 1e-12 for v in ceilings["components"].values())
    assert ceilings["components"]["specialist_maximum"] == 0.03 and "specialist_maximum" not in ceilings["binding"]
    assert result.payload["comparison"]["best_alternative"] == "ETF-A" and result.payload["execution_allowed"] is False

    tight = _envelope()
    tight["advisory"][0]["maximum_allowed"] = 0.005
    run2, res2 = _bundle(tmp_path / "t", tight)
    capped = decide(run2, res2, _context(), POLICY, AUTHORITY, attachments_verified=True)
    assert capped.payload["sizing"]["target_weight"] <= 0.005 and "specialist_maximum" in capped.payload["ceilings"]["binding"]
    loose = _envelope()
    loose["advisory"][0]["maximum_allowed"] = 0.9
    run3, res3 = _bundle(tmp_path / "l", loose)
    assert decide(run3, res3, _context(), POLICY, AUTHORITY, attachments_verified=True).payload["sizing"]["target_weight"] == sizing["target_weight"]

    store = DecisionStore(tmp_path / "decisions")
    store.save(result)
    store.save(result)  # idempotent
    proposals = tmp_path / "proposals"
    first = emit_paper_proposal(result, proposals)
    assert first == emit_paper_proposal(result, proposals) and len(list(proposals.glob("proposal_*.json"))) == 1
    assert json.loads(first.read_text(encoding="utf-8"))["execution_allowed"] is False

    restarted = DecisionStore(tmp_path / "decisions").load(result.decision_id)  # restart: reload from disk, recompute
    assert replay_decision(restarted, run, resolution).payload == restarted

    later = decide(run, resolution, _context(price=100.0, price_time="2026-09-11T10:00:00+00:00", fx_time="2026-09-11T10:00:00+00:00",
                                              decision_time="2026-09-11T12:00:00+00:00", knowledge_cutoff="2026-09-11T12:00:00+00:00"),
                   POLICY, AUTHORITY, attachments_verified=True)
    store.save(later)
    assert later.decision_id != result.decision_id and len(store.decisions_for_instrument(CANDIDATE)) == 2  # both preserved
    assert later.payload["frozen"]["run"] == result.payload["frozen"]["run"]


@pytest.mark.parametrize(
    ("code", "action", "mutate"),
    [
        ("run_stale", "BLOCK", lambda env, ctx, kw: ctx.update(decision_time="2026-12-30T00:00:00+00:00", knowledge_cutoff="2026-12-30T00:00:00+00:00",
                                                                price_time="2026-12-30T00:00:00+00:00", fx_time="2026-12-30T00:00:00+00:00")),
        ("attachment_unverified_or_invalid", "BLOCK", lambda env, ctx, kw: kw.update(attachments_verified=False)),
        ("conflicting_duplicate_run", "BLOCK", lambda env, ctx, kw: kw.update(lineage_conflict=True)),
        ("context_missing", "BLOCK", lambda env, ctx, kw: ctx.update(price=None)),
        ("context_missing", "BLOCK", lambda env, ctx, kw: ctx.update(portfolio_value=None, fx_rate=None)),
        ("falsifier_breached_re_underwrite", "BLOCK", lambda env, ctx, kw: ctx.update(observed_kill_variables={"cet1_ratio": 0.10})),
        ("specialist_generic_disagreement", "REVIEW", lambda env, ctx, kw: ctx.update(generic_evidence={"version": "g", "standalone_value": 60.0, "definition": "d"})),
        ("run_degraded", "REVIEW", lambda env, ctx, kw: env.update(status="DEGRADED", critical_missing=["x"])),
    ],
)
def test_fail_closed_gates_with_stable_reasons(tmp_path: Path, code: str, action: str, mutate) -> None:
    env, ctx, kw = _envelope(), {}, {"attachments_verified": True}
    mutate(env, ctx, kw)
    run, resolution = _bundle(tmp_path, env)
    result = decide(run, resolution, _context(**ctx), POLICY, AUTHORITY, **kw)
    assert result.action == action and code in result.payload["reason_codes"]
    assert result.proposal is None and emit_paper_proposal(result, tmp_path / "p") is None and not (tmp_path / "p").exists()  # no side effect
    if action == "BLOCK":
        assert result.payload["sizing"]["target_weight"] is None  # unavailable, never a guessed weight
    if code == "specialist_generic_disagreement":
        d = result.payload["disagreement"]
        assert d["specialist_standalone_value"] == 110.0 and d["generic"]["standalone_value"] == 60.0 and d["averaged"] is False


def test_claim_identity_and_poor_price_gates(tmp_path: Path) -> None:
    run, resolution = _bundle(tmp_path)
    unresolved = decide(run, resolution, _context(instrument_id="SYNTH-EC-3"), POLICY, AUTHORITY, attachments_verified=True)
    assert unresolved.action == "BLOCK" and "identity_unresolved" in unresolved.payload["reason_codes"]

    bad = copy.deepcopy(run)
    bad["owner_claims"][0]["claimant_allocation_status"] = "UNRESOLVED"
    bad["owner_claims"][0].pop("owner_valuation")
    assert {"claimant_allocation_unresolved", "owner_valuation_missing"} <= set(decide(bad, resolution, _context(), POLICY, AUTHORITY, attachments_verified=True).payload["reason_codes"])

    state = next(s for s in resolution["claimant_states"] if s["instrument_id"] == CANDIDATE)
    pre_merger = copy.deepcopy(resolution)
    next(s for s in pre_merger["claimant_states"] if s["instrument_id"] == CANDIDATE).update(status="REJECTED", reason="pre_event_economics_on_post_event_instrument")
    assert state["status"] == "RESOLVED"
    mismatch = decide(run, pre_merger, _context(), POLICY, AUTHORITY, attachments_verified=True)
    assert mismatch.action == "BLOCK" and "denominator_mismatch" in mismatch.payload["reason_codes"]

    dear = decide(run, resolution, _context(price=150.0, price_time="2026-09-10T10:00:00+00:00"), POLICY, AUTHORITY, attachments_verified=True)
    assert dear.action == "BLOCK" and dear.payload["sizing"]["target_weight"] == 0.0  # high specialist rank, poor price: no allocation
    assert emit_paper_proposal(dear, tmp_path / "p2") is None


def test_ceilings_liquidity_loss_confidence_and_fail_closed() -> None:
    base = dict(portfolio_value=1_000_000.0, bear_case_loss_fraction=0.50, adv_value=5_000_000.0, market_cap=10e9, effective_free_float=0.6,
                sector_exposure_excluding_candidate=0.0, scenario_confidences=((0.5, "HIGH"), (0.5, "HIGH")))
    policy = CeilingPolicy()
    free = compute_ceilings(CeilingInputs(**base), policy)
    assert free.status == "available" and free.binding == ("loss_budget",) and free.ceiling == pytest.approx(0.01 / 0.50)

    # a large foundation/strategic block leaves a thin effective float despite a huge headline market cap
    thin = compute_ceilings(CeilingInputs(**{**base, "effective_free_float": 0.0005, "market_cap": 1e9, "adv_value": 50_000_000.0}), policy)
    assert thin.binding == ("free_float_capacity",) and thin.ceiling < free.ceiling

    low = compute_ceilings(CeilingInputs(**{**base, "scenario_confidences": ((0.5, "LOW"), (0.5, "LOW"))}), policy)
    assert low.confidence_factor == 0.25 and low.ceiling < free.ceiling

    event = compute_ceilings(CeilingInputs(**base, event_relevant=True, event_failure_loss_fraction=0.9), policy)
    assert "event_failure" in event.components and event.ceiling == pytest.approx(0.0075 / 0.9) and event.binding == ("event_failure",)

    missing = compute_ceilings(CeilingInputs(**{**base, "adv_value": None}), policy)
    assert missing.status == "unavailable" and missing.ceiling is None and "liquidity_adv_missing" in missing.reasons
