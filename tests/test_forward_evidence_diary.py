from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from etf_cockpit.data.forward_evidence_diary import (
    ForwardEvidenceDiary,
    ForwardEvidenceIntegrityError,
    ForwardEvidenceObservation,
    ForwardInputManifest,
)


AS_OF = datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc)
HASHES = {
    "data_hash": "d" * 64,
    "formula_hash": "e" * 64,
    "model_hash": "a" * 64,
    "portfolio_hash": "b" * 64,
    "policy_hash": "c" * 64,
    "proposal_hash": "9" * 64,
}


def _manifest() -> ForwardInputManifest:
    return ForwardInputManifest(
        as_of=AS_OF,
        **HASHES,
        source_authority="test-adjusted-price-source",
        source_checksum="f" * 64,
    )


def _observation(observation_id: str = "observation-1", proposal_outcome: str = "observation_only") -> ForwardEvidenceObservation:
    return ForwardEvidenceObservation(
        observation_id=observation_id,
        created_at=AS_OF,
        instrument_ids=("ETF1", "ETF2"),
        manifest=_manifest(),
        proposal_outcome=proposal_outcome,
        proposal_id="proposal-1" if proposal_outcome not in {"not_proposed", "observation_only"} else None,
        paper_order_ids=("paper-order-1",) if proposal_outcome == "paper_accepted" else (),
        decision="manual_review",
        rationale="Evidence is retained for a later, explicit outcome update.",
    )


@pytest.mark.parametrize(
    "proposal_outcome",
    ("not_proposed", "observation_only", "paper_proposed", "paper_accepted", "paper_rejected", "cancelled", "expired"),
)
def test_records_every_observation_and_proposal_outcome_with_full_manifest(tmp_path: Path, proposal_outcome: str) -> None:
    diary = ForwardEvidenceDiary()
    snapshot = diary.record_observation(_observation(f"observation-{proposal_outcome}", proposal_outcome), root=tmp_path)

    assert snapshot.observation.manifest.data_hash == HASHES["data_hash"]
    assert snapshot.observation.manifest.formula_hash == HASHES["formula_hash"]
    assert snapshot.observation.manifest.model_hash == HASHES["model_hash"]
    assert snapshot.observation.manifest.portfolio_hash == HASHES["portfolio_hash"]
    assert snapshot.observation.manifest.policy_hash == HASHES["policy_hash"]
    assert snapshot.observation.manifest.proposal_hash == HASHES["proposal_hash"]
    assert snapshot.observation.proposal_outcome == proposal_outcome
    assert snapshot.outcome.status == "pending"
    assert snapshot.observation.execution_allowed is False

    restarted = ForwardEvidenceDiary().list_entries(root=tmp_path)
    assert restarted[0].observation.observation_id == snapshot.observation.observation_id
    assert restarted[0].observation.checksum == snapshot.observation.checksum


def test_outcome_versions_are_append_only_and_expose_data_quality_states(tmp_path: Path) -> None:
    diary = ForwardEvidenceDiary()
    snapshot = diary.record_observation(_observation(), root=tmp_path)
    observation_path = tmp_path / "forward_evidence_diary" / "observations" / "observation-1.json"
    original_observation = observation_path.read_bytes()

    updated = diary.update_outcome(
        "observation-1",
        status="stale",
        outcome_as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
        source_authority="test-outcome-source",
        source_checksum="a" * 64,
        metrics={"return": -0.01, "coverage": "partial"},
        notes="The adjusted-price observation is stale and requires review.",
        root=tmp_path,
    )

    assert updated.version == 2
    assert updated.status == "stale"
    assert observation_path.read_bytes() == original_observation
    latest = diary.get("observation-1", root=tmp_path)
    assert latest.observation.checksum == snapshot.observation.checksum
    assert latest.outcome.version == 2
    assert latest.outcome.status == "stale"
    assert (tmp_path / "forward_evidence_diary" / "outcomes" / "observation-1-outcome-1.json").is_file()


def test_missing_index_and_tampered_records_fail_closed(tmp_path: Path) -> None:
    diary = ForwardEvidenceDiary()
    diary.record_observation(_observation(), root=tmp_path)
    index_path = tmp_path / "forward_evidence_diary" / "index.json"
    index_path.unlink()
    with pytest.raises(ForwardEvidenceIntegrityError, match="index is missing"):
        diary.list_entries(root=tmp_path)

    tamper_root = tmp_path / "tamper"
    diary.record_observation(_observation("observation-2"), root=tamper_root)
    payload_path = tamper_root / "forward_evidence_diary" / "observations" / "observation-2.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["decision"] = "tampered"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ForwardEvidenceIntegrityError, match="checksum mismatch"):
        diary.list_entries(root=tamper_root)


def test_duplicate_observation_does_not_overwrite_existing_manifest(tmp_path: Path) -> None:
    diary = ForwardEvidenceDiary()
    first = diary.record_observation(_observation(), root=tmp_path)
    with pytest.raises(ValueError, match="duplicate observation id"):
        diary.record_observation(_observation(), root=tmp_path)
    assert diary.get("observation-1", root=tmp_path).observation.checksum == first.observation.checksum


def test_orphaned_outcome_and_stale_lock_are_handled_without_silent_loss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    diary = ForwardEvidenceDiary()
    diary.record_observation(_observation(), root=tmp_path)
    orphan = tmp_path / "forward_evidence_diary" / "outcomes" / "orphan-outcome-1.json"
    orphan.write_text("{}", encoding="utf-8")
    with pytest.raises(ForwardEvidenceIntegrityError, match="outcome is malformed|linkage"):
        diary.list_entries(root=tmp_path)

    clean_root = tmp_path / "stale-lock"
    lock_path = clean_root / "forward_evidence_diary" / ".diary-write.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("999999:stale", encoding="ascii")
    monkeypatch.setattr("etf_cockpit.data.forward_evidence_diary._LOCK_TIMEOUT_SECONDS", 0.0)
    diary.record_observation(_observation("stale-lock-observation"), root=clean_root)
    assert diary.get("stale-lock-observation", root=clean_root).outcome.status == "pending"
