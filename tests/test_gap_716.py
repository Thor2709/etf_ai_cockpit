from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from etf_cockpit.data.sparebank_intelligence import (
    EPISTEMIC_CLASSES,
    canonical_json,
    parse_envelope_bytes,
    seal_envelope,
)
from etf_cockpit.data.sparebank_run_store import SparebankRunStore
from etf_cockpit.plugins.registry import PluginRegistry
from etf_cockpit.plugins.sparebank_model import SPAREBANK_MODEL_PLUGIN_ID, SparebankModelAdapter, register_sparebank_model

FIXTURE = Path(__file__).parent / "fixtures" / "sparebank_intelligence"
ATTACHMENT = b'{"posterior":"synthetic"}'
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
RUN_ID = "run-fixture-rich-0001"


def _envelope() -> dict:
    return json.loads((FIXTURE / "rich_v1.json").read_text(encoding="utf-8"))


def _bytes(envelope: dict) -> bytes:
    return json.dumps(seal_envelope(envelope), sort_keys=True).encode("utf-8")


def _codes(raw: bytes) -> tuple[str, ...]:
    result = parse_envelope_bytes(raw, now=NOW)
    assert not result.ok and result.projection is None  # no partial signal on rejection
    return result.reason_codes


def test_rich_envelope_imports_offline_and_survives_restart(tmp_path: Path) -> None:
    raw = (FIXTURE / "rich_v1.json").read_bytes()
    store = SparebankRunStore(tmp_path / "store")
    outcome = store.import_bytes(raw, source="fixture", attachments={"posterior-summary": ATTACHMENT}, now=NOW)
    assert outcome.status == "IMPORTED"

    run = store.get_run(RUN_ID)
    assert run is not None and run["execution_allowed"] is False and run["status"] == "VALID"
    assert len(run["owner_claims"]) == 3 and len(run["valuations"]) == 3
    assert {m["epistemic_class"] for m in run["metrics"]} == EPISTEMIC_CLASSES
    scenario = run["valuations"][0]["scenarios"][0]
    assert "probability" in scenario and "probability_confidence" in scenario  # separate fields
    assert set(run["structural_events"][0]["four_ratios"]) == {
        "bank_value_split", "target_ec_conversion_ratio", "post_merger_ec_class_split", "post_merger_eierbrok",
    }
    assert store.attachment_bytes(run["attachments"][0]["sha256"]) == ATTACHMENT

    stored = tmp_path / "store" / "runs" / RUN_ID
    before = {p.name: p.read_bytes() for p in stored.iterdir()}
    assert before["envelope.json"] == raw
    reopened = SparebankRunStore(tmp_path / "store")  # restart: same record, no reinterpretation
    assert reopened.get_run(RUN_ID) == run
    again = reopened.import_bytes(raw, source="again", attachments={"posterior-summary": ATTACHMENT}, now=NOW)
    assert again.status == "IDEMPOTENT"
    assert {p.name: p.read_bytes() for p in stored.iterdir()} == before


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda e: e.update(schema_version="2.0"), "unsupported_schema_major"),
        (lambda e: e.update(execution_allowed=True), "execution_authority_field"),
        (lambda e: e["advisory"][0].update(target_weight=0.05), "execution_authority_field"),
        (lambda e: e.update(known_at_cutoff="2026-09-10T00:00:00+00:00"), "known_at_cutoff_after_generation"),
        (lambda e: e.update(generated_at="2027-01-01T00:00:00+00:00"), "future_timestamp"),
        (lambda e: e["metrics"][0].update(known_at="2026-09-15T00:00:00+00:00"), "known_after_cutoff"),
        (lambda e: e["metrics"][0].pop("source_ref"), "missing_required_field"),
        (lambda e: e["metrics"][0].update(epistemic_class="GUESS"), "invalid_epistemic_class"),
        (lambda e: e["metrics"][8].update(value=0.0), "missing_with_value"),
        (lambda e: e.update(status="DEGRADED"), "status_missingness_inconsistent"),
        (lambda e: e.update(status="INVALID"), "producer_status_invalid"),
        (lambda e: e["valuations"][0]["scenarios"][0].update(probability=0.6), "probabilities_do_not_sum_to_one"),
        (lambda e: e["valuations"][0]["scenarios"][0].pop("probability_confidence"), "missing_required_field"),
        (lambda e: e["valuations"][0].update(scenarios=e["valuations"][0]["scenarios"][:1]), "valuation_single_point_only"),
        (lambda e: e["owner_claims"][0].update(claimant_allocation_status="UNRESOLVED"), "owner_valuation_unresolved_claimant"),
        (lambda e: e["owner_claims"][0]["owner_valuation"].update(denominator_basis="WHOLE_BANK"), "owner_valuation_denominator_mismatch"),
        (lambda e: e["owner_claims"][0].update(ec_count_fully_diluted=1), "claim_invariant_violated"),
        (lambda e: e["owner_claims"][0]["eierbrok"].update(value=1.4), "probability_out_of_range"),
        (lambda e: e["structural_events"][0]["four_ratios"].pop("post_merger_eierbrok"), "missing_required_field"),
        (lambda e: e["structural_events"][0]["history"].reverse(), "event_history_out_of_order"),
        (lambda e: e["attachments"][0].update(sha256="xyz"), "invalid_attachment_hash"),
    ],
)
def test_adversarial_envelopes_rejected_with_stable_codes(mutate, code: str) -> None:
    envelope = copy.deepcopy(_envelope())
    mutate(envelope)
    assert code in _codes(_bytes(envelope))


def test_malformed_and_hash_tampered_bytes_fail_closed(tmp_path: Path) -> None:
    good = (FIXTURE / "rich_v1.json").read_bytes()
    text = good.decode("utf-8")
    assert _codes(b"{not json") == ("malformed_json",)
    assert _codes(b"\xff\xfe\x00") == ("invalid_utf8",)
    assert _codes(good.replace(b'"run_id"', b'"run_id": "x", "run_id"', 1)) == ("duplicate_key",)
    assert _codes(text.replace('"value": 1200.0', '"value": NaN', 1).encode()) == ("non_finite_number",)
    deep = ('{"a":' * 20 + "1" + "}" * 20).encode()
    assert _codes(deep) == ("depth_exceeded",)
    assert _codes(good + b" " * (2 * 1024 * 1024)) == ("size_exceeded",)
    assert _codes(text.replace("1200.0", "1300.0", 1).encode()) == ("content_hash_mismatch",)

    store = SparebankRunStore(tmp_path)
    assert store.import_bytes(b"{not json", source="x", now=NOW).status == "QUARANTINED"
    # Missing or mismatched required attachment quarantines the run; nothing becomes readable.
    assert store.import_bytes(good, source="x", now=NOW).reasons == ("attachment_missing",)
    mismatch = store.import_bytes(good, source="x", attachments={"posterior-summary": b"tampered"}, now=NOW)
    assert mismatch.reasons == ("attachment_hash_mismatch",)
    assert store.run_ids() == () and store.latest_run() is None  # unavailable, not a value
    assert len(store.quarantine_reasons()) == 3


def test_duplicate_conflict_partial_write_and_concurrent_import(tmp_path: Path) -> None:
    raw = (FIXTURE / "rich_v1.json").read_bytes()
    attachments = {"posterior-summary": ATTACHMENT}
    store = SparebankRunStore(tmp_path / "store")

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(lambda _: store.import_bytes(raw, source="race", attachments=attachments, now=NOW), range(6)))
    assert [o.status for o in outcomes].count("IMPORTED") == 1
    assert {o.status for o in outcomes} <= {"IMPORTED", "IDEMPOTENT"}

    changed = _envelope()
    changed["model_version"] = "synthetic-2"  # same run ID, different bytes/hash
    conflict = store.import_bytes(_bytes(changed), source="conflict", attachments=attachments, now=NOW)
    assert conflict.status == "CONFLICT" and conflict.reasons == ("run_id_conflict",)
    assert store.get_run(RUN_ID)["model_version"] == "synthetic-1"
    assert (tmp_path / "store" / "runs" / RUN_ID / "envelope.json").read_bytes() == raw

    inbox = tmp_path / "inbox"
    (inbox / "attachments").mkdir(parents=True)
    (inbox / ".partial.json").write_bytes(raw[: len(raw) // 2])  # partial publication is invisible
    (inbox / "run.json.tmp").write_bytes(raw[:10])
    fresh = SparebankRunStore(tmp_path / "fresh")
    assert fresh.import_directory(inbox, now=NOW).outcomes == ()
    (inbox / "attachments" / "posterior-summary").write_bytes(ATTACHMENT)
    (inbox / "run.json").write_bytes(raw)
    report = fresh.import_directory(inbox, now=NOW)
    assert report.count("IMPORTED") == 1 and fresh.latest_run()["run_id"] == RUN_ID
    assert fresh.import_directory(tmp_path / "missing-dir").outcomes == ()  # startup valid without a directory


def test_adapter_unavailable_when_engine_absent_and_serves_stored_run(tmp_path: Path) -> None:
    registry = PluginRegistry(allowlist=[SPAREBANK_MODEL_PLUGIN_ID])
    register_sparebank_model(registry, import_dir=tmp_path / "absent", store_root=tmp_path / "store")
    assert registry.health(SPAREBANK_MODEL_PLUGIN_ID).status.value == "unavailable"
    assert registry.invoke(SPAREBANK_MODEL_PLUGIN_ID, "import").status == "unavailable"
    missing = registry.invoke(SPAREBANK_MODEL_PLUGIN_ID, "intelligence")
    assert missing.status == "unavailable" and "run" not in missing.data  # no value without evidence
    assert SparebankModelAdapter().health(None).status.value == "unavailable"

    inbox = tmp_path / "inbox"
    (inbox / "attachments").mkdir(parents=True)
    (inbox / "attachments" / "posterior-summary").write_bytes(ATTACHMENT)
    (inbox / "run.json").write_bytes((FIXTURE / "rich_v1.json").read_bytes())
    (inbox / "bad.json").write_bytes(b"{")
    populated = PluginRegistry(allowlist=[SPAREBANK_MODEL_PLUGIN_ID])
    register_sparebank_model(populated, import_dir=inbox, store_root=tmp_path / "store2")
    imported = populated.invoke(SPAREBANK_MODEL_PLUGIN_ID, "import")
    summary = imported.data["summary"]
    assert imported.status == "degraded" and summary["IMPORTED"] == 1 and summary["QUARANTINED"] == 1
    served = populated.invoke(SPAREBANK_MODEL_PLUGIN_ID, "intelligence", {"run_id": RUN_ID})
    assert served.status == "ok" and served.data["run"]["execution_allowed"] is False
    assert served.executable_authority is False and canonical_json(served.data["run"])
