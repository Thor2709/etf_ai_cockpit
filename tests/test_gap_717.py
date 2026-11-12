from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from etf_cockpit.application.sparebank_intelligence_workflow import (
    SparebankModelUpdateWorkflow,
    WORKFLOW_TYPE,
    ModelUpdateConflict,
    build_resolution_projection,
    proposal_eligible_assets,
    resolve_asset,
    successor_chain,
)
from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobSpec
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityClaim
from etf_cockpit.data.sparebank_intelligence import seal_envelope
from etf_cockpit.data.sparebank_run_store import SparebankRunStore

FIXTURE = Path(__file__).parent / "fixtures" / "sparebank_intelligence" / "rich_v1.json"
ATTACHMENT = b'{"posterior":"synthetic"}'
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
CUTOFF = "2026-09-01T00:00:00+00:00"
MERGER = "evt-merger-0001"


def _claim(iid: str, field: str, value: str, sid: str, *, available: str = "2026-01-01T00:00:00Z", valid: str = "2025-01-01T00:00:00Z") -> IdentityClaim:
    return IdentityClaim(iid, field, value, "fixture", SourceAuthority.OFFICIAL, sid, valid_from=valid, available_at=available)


def _identity(tmp_path: Path, ids=("SYNTH-EC-1", "SYNTH-EC-2", "SYNTH-EC-3")) -> IdentityMasterStore:
    store = IdentityMasterStore(tmp_path / "identity")
    claims = []
    for n, iid in enumerate(ids, start=1):
        for field, value in (("ticker", f"SB{n}"), ("isin", f"NO000000000{n}"), ("name", f"Synth {n}"), ("exchange", "XOSL"),
                             ("currency", "NOK"), ("asset_type", "equity"), ("mic", "XOSL")):
            claims.append(_claim(iid, field, value, f"{iid}:{field}"))
    claims += [_claim("SYNTH-EC-1", "national_id", "999888777", "o1"), _claim("SYNTH-EC-2", "national_id", "999888777", "o2")]
    store.append_claims(claims)
    return store


def _envelope() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _merger(envelope: dict, **overrides) -> dict:
    continuity = {"kind": "MIXED", "predecessor_instrument_id": "SYNTH-EC-2", "successor_instrument_id": "SYNTH-EC-1",
                  "effective_at": "2026-07-01T00:00:00+00:00", "known_at": "2026-06-20T00:00:00+00:00",
                  "conversion_ratio": 1.2, "cash_per_predecessor_ec": 5.0,
                  "allocations": [{"claimant": "legacy_private_ec_holders", "kind": "EC", "source": "BANK_ISSUED"},
                                  {"claimant": "legacy_private_ec_holders", "kind": "CASH", "source": "ACQUIRER"},
                                  {"claimant": "foundation", "kind": "EC", "source": "FOUNDATION_ISSUED"}]}
    continuity.update(overrides)
    envelope["structural_events"][0]["security_continuity"] = continuity
    claim = envelope["owner_claims"][1]
    claim.update(event_id=MERGER, pre_event_state={"ec_count_current": claim["ec_count_current"]},
                 post_event_state={"ec_count_current": 12_000_000})
    return envelope


def _import(store: SparebankRunStore, envelope: dict) -> str:
    raw = json.dumps(seal_envelope(envelope), sort_keys=True).encode("utf-8")
    assert store.import_bytes(raw, source="t", attachments={"posterior-summary": ATTACHMENT}, now=NOW).status == "IMPORTED"
    return envelope["run_id"]


def _later(envelope: dict, run_id: str, cutoff: str, generated: str, *, change_asset: str | None = None) -> dict:
    env = copy.deepcopy(envelope)
    env.update(run_id=run_id, known_at_cutoff=cutoff, generated_at=generated)
    if change_asset:
        for valuation in env["valuations"]:
            if valuation["instrument_id"] == change_asset:
                valuation["scenarios"][0]["value"] += 1.0
    return env


def _workflow(tmp_path: Path, identity: IdentityMasterStore, runs: SparebankRunStore) -> SparebankModelUpdateWorkflow:
    (tmp_path / "jobs").mkdir(exist_ok=True)  # the resource policy reads free disk of an existing directory
    return SparebankModelUpdateWorkflow(runs, identity, DurableJobScheduler(tmp_path / "jobs"))


def _run(tmp_path: Path, envelope: dict | None = None) -> tuple[SparebankRunStore, dict]:
    runs = SparebankRunStore(tmp_path / "runs")
    run_id = _import(runs, _merger(envelope or _envelope()))
    return runs, runs.get_run(run_id)


def test_resolution_order_pit_wall_and_fail_closed_identity(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    identity.append_claims([_claim("SYNTH-EC-1", "ticker", "NEWTK", "future", available="2026-10-05T00:00:00Z", valid="2026-10-01T00:00:00Z")])

    exact = resolve_asset(identity, "SYNTH-EC-1", decision_time=CUTOFF)
    assert exact["status"] == "RESOLVED" and exact["reason"] == "canonical_id"
    assert exact["identity"]["ticker"] == "SB1"  # future ticker change not visible at the decision time
    assert exact["identity_version"]["decision_id"] and exact["decision_time"] == CUTOFF

    by_isin = resolve_asset(identity, "LEGACY-ALIAS", decision_time=CUTOFF, aliases={"isin": "no0000000003"})
    assert by_isin["status"] == "RESOLVED" and by_isin["selected_instrument_id"] == "SYNTH-EC-3" and by_isin["reason"] == "isin"

    assert resolve_asset(identity, "UNKNOWN", decision_time=CUTOFF, aliases={"ticker": "SB1"})["status"] == "UNRESOLVED"  # ticker never a global key
    org = resolve_asset(identity, "UNKNOWN", decision_time=CUTOFF, aliases={"org_number": "999888777"})
    assert org["status"] == "CONFLICT" and org["reason"] == "issuer_maps_to_multiple_instruments" and org["selected_instrument_id"] is None
    clash = resolve_asset(identity, "SYNTH-EC-1", decision_time=CUTOFF, aliases={"isin": "NO0000000002"})
    assert clash["status"] == "CONFLICT" and clash["reason"] == "canonical_id_isin_disagree"
    none = resolve_asset(identity, "SYNTH-EC-9", decision_time=CUTOFF)
    assert none["status"] == "UNRESOLVED" and none["selected_instrument_id"] is None and none["identity"] == {}  # unavailable, not a value


def test_merger_continuity_pre_post_claims_and_foundation_consideration(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    runs, run = _run(tmp_path)
    projection = build_resolution_projection(run, identity, raw_sha256="x")
    (link,) = projection["continuity"]["links"]
    assert link["status"] == "RESOLVED" and link["kind"] == "MIXED"
    assert (link["conversion_ratio"], link["cash_per_predecessor_ec"]) == (1.2, 5.0)
    assert projection["continuity"]["chains"]["SYNTH-EC-2"] == ["SYNTH-EC-2", "SYNTH-EC-1"]  # old EC chained, not dropped
    states = {s["instrument_id"]: s for s in projection["claimant_states"]}
    assert states["SYNTH-EC-2"]["state"] == "PRE" and states["SYNTH-EC-2"]["status"] == "RESOLVED"
    assert states["SYNTH-EC-1"]["bindings"]["foundation_share"] == 0.2  # foundation kept separate from legacy EC state

    bad = copy.deepcopy(run)
    bad["owner_claims"][1]["ec_count_current"] = 12_000_000  # post-event count on the pre-event instrument
    rejected = build_resolution_projection(bad, identity, raw_sha256="x")["claimant_states"][1]
    assert rejected["status"] == "REJECTED" and rejected["reason"] == "post_event_economics_on_pre_event_instrument"

    misattributed = copy.deepcopy(run)
    misattributed["structural_events"][0]["security_continuity"]["allocations"][0]["source"] = "FOUNDATION_ISSUED"
    out = build_resolution_projection(misattributed, identity, raw_sha256="x")
    assert out["continuity"]["links"][0]["reason"] == "foundation_consideration_misattributed"
    assert out["claimant_states"][1]["status"] == "UNRESOLVED"  # no bridge -> no claimant state

    cash = copy.deepcopy(run)
    cash["structural_events"][0]["security_continuity"].update(kind="CASH", successor_instrument_id=None, conversion_ratio=None, delisted=True)
    assert build_resolution_projection(cash, identity, raw_sha256="x")["continuity"]["links"][0]["status"] == "RESOLVED"
    future = copy.deepcopy(run)
    future["structural_events"][0]["security_continuity"]["known_at"] = "2026-09-20T00:00:00+00:00"
    assert build_resolution_projection(future, identity, raw_sha256="x")["continuity"]["links"][0]["status"] == "NOT_YET_KNOWN"
    assert successor_chain([], "A") == ["A"]


def test_conversion_uses_local_event_math_and_unresolved_exposure_is_not_redistributed(tmp_path: Path) -> None:
    identity = _identity(tmp_path, ids=("SYNTH-EC-1", "SYNTH-EC-2"))  # SYNTH-EC-3 has no identity evidence
    _, run = _run(tmp_path)
    conv = copy.deepcopy(run)
    conv["structural_events"][0]["security_continuity"] = {
        "kind": "CONVERSION", "predecessor_instrument_id": "SYNTH-EC-1", "successor_instrument_id": "SYNTH-EC-1",
        "effective_at": "2026-07-01T00:00:00+00:00", "known_at": "2026-06-20T00:00:00+00:00",
        "conversion": {"pre_ec_count": 10_000_000, "foundation_ec_count": 2_000_000, "post_ec_count": 12_000_000}}
    link = build_resolution_projection(conv, identity, raw_sha256="x")["continuity"]["links"][0]
    assert link["status"] == "RESOLVED"
    assert {r["recipient"]: r.get("quantity") for r in link["conversion"]["recipient_ledger"]}["foundation"] == 2_000_000
    conv["structural_events"][0]["security_continuity"]["conversion"]["post_ec_count"] = 11_000_000
    assert build_resolution_projection(conv, identity, raw_sha256="x")["continuity"]["links"][0]["reason"] == "conversion_post_count_mismatch"

    projection = build_resolution_projection(run, identity, raw_sha256="x")
    assert projection["assets"]["SYNTH-EC-3"]["status"] == "UNRESOLVED"
    assert [u["instrument_id"] for u in projection["unresolved_exposure"]["assets"]] == ["SYNTH-EC-3"]
    assert projection["unresolved_exposure"]["redistributed"] is False
    assert "SYNTH-EC-3" not in proposal_eligible_assets(projection) and "SYNTH-EC-1" in proposal_eligible_assets(projection)
    assert projection["authority"] == {"proposal_authority": False, "execution_allowed": False}


def test_exactly_one_event_across_resubmit_restart_resume_and_race(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    runs, run = _run(tmp_path)
    first = _workflow(tmp_path, identity, runs)
    wf = first.submit(run["run_id"])
    assert first.submit(run["run_id"]).workflow_id == wf.workflow_id  # identical re-import is a no-op

    first.scheduler.run_once(first._stage, workflow_id=wf.workflow_id)  # stage 1 only, then "crash"
    restarted = _workflow(tmp_path, identity, runs)
    restarted.drain(wf.workflow_id)
    restarted.drain(wf.workflow_id)  # repeated scheduler execution
    events = restarted.events()
    assert len(events) == 1 and events[0]["event_type"] == "MODEL_UPDATE_AVAILABLE"
    assert events[0]["execution_allowed"] is False and events[0]["authority"]["proposal_authority"] is False
    assert not any(key in events[0] for key in ("order", "proposal", "target_weight"))

    # A future identity revision (after the cutoff) does not change the mapping, the key or the event count.
    identity.append_claims([_claim("SYNTH-EC-1", "ticker", "NEWTK", "future", available="2026-10-05T00:00:00Z", valid="2026-10-01T00:00:00Z")])
    assert _workflow(tmp_path, identity, runs).submit(run["run_id"]).workflow_id == wf.workflow_id

    projection = build_resolution_projection(run, identity, raw_sha256=first._raw_sha(run["run_id"]))

    def race(_: int) -> str:  # concurrent importers, each with its own scheduler handle (sqlite handles are thread-bound)
        return _workflow(tmp_path, None, runs).submit_projection(run, projection).workflow_id

    with ThreadPoolExecutor(6) as pool:
        ids = set(pool.map(race, range(6)))
    assert ids == {wf.workflow_id} and len(_workflow(tmp_path, identity, runs).events()) == 1


def test_conflicting_binding_fails_closed(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    runs, run = _run(tmp_path)
    flow = _workflow(tmp_path, identity, runs)
    flow.scheduler.submit(WORKFLOW_TYPE, "forged", (JobSpec("x", "x"),), input_payload={"run_id": run["run_id"], "raw_sha256": "0" * 64, "content_hash": "f" * 64})
    with pytest.raises(ModelUpdateConflict):
        flow.submit(run["run_id"])
    with pytest.raises(LookupError):
        flow.submit("run-does-not-exist")  # unverifiable/absent run -> unavailable, never a guessed event
    projection = build_resolution_projection(run, identity, raw_sha256="x" * 64)
    flow.resolutions.persist(projection)
    with pytest.raises(ModelUpdateConflict):
        flow.resolutions.persist(build_resolution_projection(run, identity, raw_sha256="y" * 64))


def test_narrow_invalidation_out_of_order_runs_and_replay(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    runs, run = _run(tmp_path)
    base = _merger(_envelope())
    newer = _later(base, "run-fixture-rich-0002", "2026-09-15T00:00:00+00:00", "2026-09-16T00:00:00+00:00", change_asset="SYNTH-EC-3")
    _import(runs, newer)
    flow = _workflow(tmp_path, identity, runs)
    for run_id in (run["run_id"], "run-fixture-rich-0002"):
        flow.drain(flow.submit(run_id).workflow_id)
    first, second = flow.events()
    assert first["run_id"] == run["run_id"] and second["run_id"] == "run-fixture-rich-0002"
    assert second["affected_assets"] == ["SYNTH-EC-3"]  # unrelated assets are not invalidated
    assert second["downstream_contexts"] == ["decision_context:SYNTH-EC-3"] and second["predecessor_run_id"] == run["run_id"]

    # Out-of-order arrival: an older run imported after a newer one keeps its true chronology.
    older = _later(base, "run-fixture-rich-0000", "2026-08-25T00:00:00+00:00", "2026-08-26T00:00:00+00:00", change_asset="SYNTH-EC-2")
    _import(runs, older)
    flow.drain(flow.submit("run-fixture-rich-0000").workflow_id)
    assert [e["run_id"] for e in flow.events()] == ["run-fixture-rich-0000", run["run_id"], "run-fixture-rich-0002"]

    replay = flow.replay_at("2026-09-10T00:00:00+00:00")
    assert [p["run_id"] for p in replay] == ["run-fixture-rich-0000", run["run_id"]]  # no future run
    assert replay[1]["projection_hash"] == build_resolution_projection(runs.get_run(run["run_id"]), identity, raw_sha256=replay[1]["raw_sha256"])["projection_hash"]
