from __future__ import annotations

import json
import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import etf_cockpit.audit.thesis_diary as thesis_diary
from etf_cockpit.audit.local_llm import LocalAuditCommentary, save_local_audit_commentary
from etf_cockpit.app.pages.chatgpt_audit import _thesis_diary_text
from etf_cockpit.app.selectors.instrument_detail import _backtest_panel, _thesis_diary_panel
from etf_cockpit.services import build_snapshot
from etf_cockpit.audit.thesis_diary import (
    ThesisDiaryConflictError,
    ThesisDiaryIntegrityError,
    ThesisDiaryStore,
    build_thesis_entry,
    reproduce_thesis_from_packet,
    sha256_value,
)
from etf_cockpit.chatgpt_bridge import export_pack
from etf_cockpit.core.atomic_io import atomic_write_group as real_atomic_write_group
from etf_cockpit.core.types import DataQualityReport, SignalResult, ComponentScores
from etf_cockpit.portfolio.optimiser import OptimiserConstraints, PortfolioOptimiser
from etf_cockpit.portfolio.proposals import create_manual_trade_proposal_report
from etf_cockpit.signals.actions import preliminary_action
from etf_cockpit.signals.gates import evaluate_risk_gates
from etf_cockpit.core.config import load_config


def _entry(
    *,
    thesis_id: str | None = "thesis-1",
    prompt: str = "Review the evidence",
    decision_time: str | None = "2026-08-03T00:00:00+00:00",
    created_at: str | None = "2026-08-03T00:00:00+00:00",
    expires_at: str | None = None,
    instrument_id: str = "VWCE",
    backtest_validity: str = "unknown",
    generation_record: dict | None = None,
    source_snapshot: dict | None = None,
    retrieval_snapshot: dict | None = None,
    evidence_snapshot: dict | None = None,
):
    return build_thesis_entry(
        thesis_id=thesis_id,
        prompt=prompt,
        model="local-test-model",
        source_snapshot=source_snapshot if source_snapshot is not None else {"source_id": "snapshot-1", "source_checksum": "source-checksum"},
        retrieval_snapshot=retrieval_snapshot if retrieval_snapshot is not None else {"retrieval_id": "retrieval-1", "retrieved_at": "2026-08-03T00:00:00+00:00"},
        evidence_snapshot=evidence_snapshot if evidence_snapshot is not None else {"etf_id": "VWCE", "as_of_date": "2026-08-01", "status": "valid"},
        llm_output={"summary": "Commentary only", "executable_authority": False},
        instrument_id=instrument_id,
        input_sources=["cockpit_snapshot", "signal:VWCE"],
        thesis_summary="Commentary only",
        risk_summary="No trade authority",
        contradiction_summary="No contradiction supplied",
        uncertainty=0.5,
        evidence_score=7.5,
        evidence_quality=6.5,
        risk_friction=5.5,
        final_advisory_label="manual_review",
        backtest_validity=backtest_validity,
        decision_time=decision_time,
        created_at=created_at,
        expires_at=expires_at,
        generation_record=generation_record,
    )


def _create_diary_worker(root: str, index: int) -> None:
    ThesisDiaryStore(Path(root)).create(_entry(thesis_id=f"thesis-{index}"))


def _append_diary_worker(root: str, index: int) -> None:
    ThesisDiaryStore(Path(root)).append_review(
        "thesis-0",
        status="approved",
        reviewer=f"worker-{index}",
        notes="concurrent review",
        decision_time="2026-08-03T01:00:00+00:00",
        event_id=f"review-worker-{index}",
    )


def _read_export_worker(root: str) -> None:
    store = ThesisDiaryStore(Path(root))
    store.list_entries()
    store.replay("thesis-0")
    store.export_packet()


def test_thesis_persistence_is_immutable_and_idempotent(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = _entry()

    assert store.create(entry) == entry
    assert store.create(entry) == entry
    with pytest.raises(ThesisDiaryConflictError):
        store.create(_entry(prompt="Different immutable thesis content"))
    assert len(store.list_entries()) == 1


def test_hash_bindings_replay_lifecycle_and_packet_reproduction(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    store.append_review(entry.thesis_id, status="approved", reviewer="human", notes="Checked sources", decision_time="2026-08-03T01:00:00+00:00")
    store.append_redaction(entry.thesis_id, state="redacted", reason="Personal note", decision_time="2026-08-03T02:00:00+00:00")
    store.append_expiry(entry.thesis_id, expires_at="2026-08-03T04:00:00+00:00", decision_time="2026-08-03T03:00:00+00:00")
    store.append_outcome(entry.thesis_id, outcome="held", observed_at="2026-08-03T05:00:00+00:00", decision_time="2026-08-03T05:00:00+00:00", details={"return": "not_used"})

    before_redaction = store.replay(entry.thesis_id, at="2026-08-03T01:30:00+00:00")
    assert before_redaction.redaction_state == "unredacted"
    assert before_redaction.human_review["status"] == "approved"
    assert before_redaction.outcomes == ()

    current = store.replay(entry.thesis_id, at="2026-08-03T06:00:00+00:00")
    assert current.redaction_state == "redacted"
    assert current.expired is True
    assert current.outcomes[0]["outcome"] == "held"
    assert current.execution_allowed is False

    packet = store.export_packet()
    reproduced = reproduce_thesis_from_packet(packet, entry.thesis_id, at="2026-08-03T06:00:00+00:00")
    assert reproduced.model_dump(mode="json") == current.model_dump(mode="json")


def test_initial_outcomes_and_observation_bounds_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="initial thesis outcomes"):
        build_thesis_entry(
            prompt="Review the evidence",
            model="local-test-model",
            source_snapshot={"source": "test"},
            retrieval_snapshot={"retrieval": "test"},
            evidence_snapshot={"evidence": "test"},
            llm_output={"summary": "commentary"},
            outcomes={"20": {"return": 0.1}, "60": None, "120": None},
        )

    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    with pytest.raises(ValueError, match="bounds"):
        store.append_outcome(
            entry.thesis_id,
            outcome="too early",
            observed_at="2026-08-02T23:59:59+00:00",
            decision_time="2026-08-03T01:00:00+00:00",
        )
    with pytest.raises(ValueError, match="bounds"):
        store.append_outcome(
            entry.thesis_id,
            outcome="observed too late",
            observed_at="2026-08-03T02:00:01+00:00",
            decision_time="2026-08-03T02:00:00+00:00",
        )

    store.append_outcome(
        entry.thesis_id,
        outcome="held",
        observed_at="2026-08-03T02:00:00+00:00",
        decision_time="2026-08-03T02:00:00+00:00",
        event_id="outcome-boundary",
    )
    assert store.replay(entry.thesis_id, at="2026-08-03T01:59:59+00:00").outcomes == ()
    assert len(store.replay(entry.thesis_id, at="2026-08-03T02:00:00+00:00").outcomes) == 1


def test_nested_outcome_detail_timestamps_cannot_postdate_event_decision(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())

    with pytest.raises(ValueError, match="outcome_details.*postdates thesis decision time"):
        store.append_outcome(
            entry.thesis_id,
            outcome="held",
            observed_at="2026-08-03T02:00:00+00:00",
            decision_time="2026-08-03T02:00:00+00:00",
            details={"observations": [{"metadata": {"timestamp": "2026-08-03T02:00:01+00:00"}}]},
        )


def test_snapshot_observation_times_cannot_postdate_decision() -> None:
    with pytest.raises(ValueError, match="evidence_snapshot.as_of_date postdates"):
        _entry(evidence_snapshot={"as_of_date": "2099-01-01"})
    with pytest.raises(ValueError, match="retrieval_snapshot.retrieved_at must be"):
        _entry(retrieval_snapshot={"retrieved_at": "not-a-timestamp"})
    with pytest.raises(ValueError, match="source_snapshot.timestamp postdates"):
        _entry(source_snapshot={"timestamp": "2099-01-01T00:00:00+00:00"})
    with pytest.raises(ValueError, match=r"evidence_snapshot.metadata\[0\].retrieved_at postdates"):
        _entry(
            evidence_snapshot={
                "as_of_date": "2026-08-03",
                "metadata": [{"retrieved_at": "2099-01-01T00:00:00+00:00"}],
            }
        )

    valid = _entry(
        source_snapshot={"timestamp": "2026-08-03T00:00:00+00:00"},
        retrieval_snapshot={"retrieved_at": "2026-08-02T23:59:59+00:00"},
        evidence_snapshot={"as_of_date": "2026-08-03"},
    )
    assert valid.evidence_snapshot["as_of_date"] == "2026-08-03"


def test_expiry_event_cannot_backdate_expiry_before_event(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    with pytest.raises(ThesisDiaryIntegrityError, match="expiry is backdated"):
        store.append_expiry(
            entry.thesis_id,
            expires_at="2026-08-02T00:00:00+00:00",
            reason="invalid retroactive expiry",
            decision_time="2026-08-04T00:00:00+00:00",
        )
    assert len(store.export_packet()["events"]) == 1


def test_multiprocess_create_append_read_and_export_are_serialized(tmp_path: Path) -> None:
    context = mp.get_context("spawn")
    creators = [context.Process(target=_create_diary_worker, args=(str(tmp_path), index)) for index in range(4)]
    for process in creators:
        process.start()
    for process in creators:
        process.join(timeout=20)
        assert process.exitcode == 0

    store = ThesisDiaryStore(tmp_path)
    assert len(store.list_entries()) == 4

    appenders = [context.Process(target=_append_diary_worker, args=(str(tmp_path), index)) for index in range(4)]
    for process in appenders:
        process.start()
    for process in appenders:
        process.join(timeout=20)
        assert process.exitcode == 0

    readers = [context.Process(target=_read_export_worker, args=(str(tmp_path),)) for _ in range(3)]
    for process in readers:
        process.start()
    for process in readers:
        process.join(timeout=20)
        assert process.exitcode == 0

    packet = store.export_packet()
    assert len(packet["entries"]) == 4
    assert len([event for event in packet["events"] if event["operation"] == "review"]) == 4


def test_event_commitment_detects_truncation_and_interrupted_group_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    store.append_review(
        entry.thesis_id,
        status="approved",
        reviewer="human",
        decision_time="2026-08-03T01:00:00+00:00",
    )
    lines = store.events_path.read_text(encoding="utf-8").splitlines()
    store.events_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ThesisDiaryIntegrityError, match="commitment"):
        store.export_packet()

    interrupted_root = tmp_path / "interrupted"
    interrupted_store = ThesisDiaryStore(interrupted_root)

    def interrupting_write(requests, **_kwargs):
        def hook(state: str, _journal: Path) -> None:
            if state == "memory":
                raise RuntimeError("bounded interruption")

        return real_atomic_write_group(requests, lifecycle_hook=hook)

    monkeypatch.setattr(thesis_diary, "atomic_write_group", interrupting_write)
    with pytest.raises(RuntimeError, match="bounded interruption"):
        interrupted_store.create(_entry())
    assert not interrupted_store.index_path.exists()
    assert interrupted_store.list_entries() == []


def test_diary_lifecycle_does_not_change_canonical_financial_outputs(tmp_path: Path) -> None:
    config = load_config()
    row = pd.Series(
        {
            "etf_id": "WORLD_CORE",
            "trend_200": 1.0,
            "drawdown_60d_max": -0.03,
            "expected_edge_60d": 0.0001,
            "cost_bps": 13.0,
            "current_weight": 0.10,
        }
    )

    def canonical_outputs() -> dict[str, object]:
        score = preliminary_action(
            config,
            total_score=0.62,
            confidence=0.70,
            current_weight=0.10,
            drift=-0.02,
            hard_band=0.05,
            trend_200=1,
        )
        risk = evaluate_risk_gates(
            config,
            row,
            DataQualityReport(as_of_date=pd.Timestamp("2026-06-26").date(), issues=[]),
            candidate_action="add",
            projected_weight=0.12,
            cash_weight=0.10,
        )
        returns = pd.DataFrame(
            {
                "WORLD_CORE": [100.0, 101.0, 100.5, 102.0, 101.5, 103.0],
                "WORLD_BOND": [100.0, 100.2, 100.1, 100.4, 100.3, 100.5],
            },
            index=pd.date_range("2026-01-01", periods=6),
        )
        optimiser = PortfolioOptimiser(returns)
        solution = optimiser.solve("equal_weight", constraints=OptimiserConstraints())
        signal = SignalResult(
            run_id="test-run",
            signal_date=pd.Timestamp("2026-06-26").date(),
            etf_id="WORLD_CORE",
            action="add_candidate",
            confidence=0.7,
            total_score=0.6,
            components=ComponentScores(
                momentum=0.0, trend=0.0, risk=0.0, rebalance=0.0,
                relative_strength=0.0, toto=0.0, timesfm=0.0, baseline_ml=0.0,
                chatgpt_thesis=0.0, cost_penalty=0.0, turnover_penalty=0.0,
                concentration_penalty=0.0,
            ),
            blocked_by=[],
            warnings=[],
            reason_short="test",
            reason_long="test reason",
            horizon_primary="1-3 months",
            supporting_metrics={"reason_full": "test reason"},
            suggested_trade_value_eur=250.0,
            suggested_new_weight=0.12,
        )
        proposal = create_manual_trade_proposal_report(
            [signal],
            DataQualityReport(as_of_date=pd.Timestamp("2026-06-26").date(), issues=[]),
            run_id="test-run",
            report_dir=tmp_path / "proposals",
        )
        return {
            "score": score,
            "optimizer": {
                "weights": solution.weights.round(12).to_dict(),
                "status": solution.status,
                "objective": solution.objective,
            },
            "risk_gate": risk,
            "trade_proposal": {
                "status": proposal["status"],
                "proposals": proposal["proposals"],
                "blocked_or_no_trade_summary": proposal["blocked_or_no_trade_summary"],
            },
        }

    before = canonical_outputs()
    store = ThesisDiaryStore(tmp_path / "diary")
    entry = store.create(_entry())
    store.append_review(
        entry.thesis_id,
        status="approved",
        reviewer="human",
        decision_time="2026-08-03T01:00:00+00:00",
    )
    store.append_redaction(
        entry.thesis_id,
        state="redacted",
        reason="safe export",
        decision_time="2026-08-03T02:00:00+00:00",
    )
    store.append_expiry(
        entry.thesis_id,
        expires_at="2026-08-03T04:00:00+00:00",
        decision_time="2026-08-03T03:00:00+00:00",
    )
    store.append_outcome(
        entry.thesis_id,
        outcome="held",
        observed_at="2026-08-03T05:00:00+00:00",
        decision_time="2026-08-03T05:00:00+00:00",
        details={"return": "not_used"},
    )
    assert canonical_outputs() == before


def test_event_retry_after_later_event_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    first = store.append_redaction(
        entry.thesis_id,
        state="redacted",
        reason="Personal note",
        decision_time="2026-08-03T01:00:00+00:00",
        event_id="event-retry",
    )
    store.append_review(
        entry.thesis_id,
        status="approved",
        reviewer="human",
        decision_time="2026-08-03T02:00:00+00:00",
    )

    assert (
        store.append_redaction(
            entry.thesis_id,
            state="redacted",
            reason="Personal note",
            decision_time="2026-08-03T01:00:00+00:00",
            event_id="event-retry",
        )
        == first
    )
    with pytest.raises(ThesisDiaryConflictError):
        store.append_redaction(
            entry.thesis_id,
            state="redacted",
            reason="Changed note",
            decision_time="2026-08-03T03:00:00+00:00",
            event_id="event-retry",
        )
    with pytest.raises(ThesisDiaryConflictError):
        store.append_review(
            entry.thesis_id,
            status="approved",
            reviewer="human",
            decision_time="2026-08-03T03:00:00+00:00",
            event_id="event-retry",
        )
    other = store.create(
        _entry(
            thesis_id="thesis-2",
            decision_time="2026-08-03T03:00:00+00:00",
            created_at="2026-08-03T03:00:00+00:00",
        )
    )
    with pytest.raises(ThesisDiaryConflictError):
        store.append_redaction(
            other.thesis_id,
            state="redacted",
            reason="Personal note",
            decision_time="2026-08-03T01:00:00+00:00",
            event_id="event-retry",
        )


def test_default_thesis_identity_includes_normalized_generation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 8, 3, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr(thesis_diary, "datetime", ControlledDateTime)
    first = _entry(thesis_id=None, decision_time=None, created_at=None)
    retry = _entry(thesis_id=None, decision_time=first.decision_time, created_at=first.created_at)
    ControlledDateTime.current = datetime(2026, 8, 3, 0, 1, tzinfo=timezone.utc)
    second = _entry(thesis_id=None, decision_time=None, created_at=None)

    assert retry.thesis_id == first.thesis_id
    assert second.thesis_id != first.thesis_id


def test_replay_without_cutoff_uses_current_time_for_expiry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 8, 3, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr(thesis_diary, "datetime", ControlledDateTime)
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry(expires_at="2026-08-03T02:00:00+00:00"))

    assert store.replay(entry.thesis_id).expired is False
    assert store.replay(entry.thesis_id, at="2026-08-03T01:30:00+00:00").expired is False
    ControlledDateTime.current = datetime(2026, 8, 3, 3, tzinfo=timezone.utc)
    assert store.replay(entry.thesis_id).expired is True


def test_omitted_cutoff_excludes_future_events_in_store_and_packet(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 8, 3, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr(thesis_diary, "datetime", ControlledDateTime)
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    store.append_review(
        entry.thesis_id,
        status="approved",
        reviewer="future-reviewer",
        decision_time="2099-01-01T00:00:00+00:00",
    )

    current = store.replay(entry.thesis_id)
    assert current.human_review["status"] == "pending"
    assert current.replayed_at == "2026-08-03T01:00:00+00:00"
    packet_state = reproduce_thesis_from_packet(store.export_packet(), entry.thesis_id)
    assert packet_state.human_review["status"] == "pending"
    assert packet_state.applied_event_ids == current.applied_event_ids


def test_disclosure_safe_export_at_cutoff_drops_future_payloads_and_replays(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry(prompt="protected prompt"))
    store.append_review(
        entry.thesis_id,
        status="approved",
        reviewer="future reviewer secret",
        notes="future review secret",
        decision_time="2099-01-01T00:00:00+00:00",
    )
    store.append_redaction(
        entry.thesis_id,
        state="redacted",
        reason="future redaction secret",
        decision_time="2099-01-01T01:00:00+00:00",
    )
    store.append_expiry(
        entry.thesis_id,
        expires_at="2099-01-02T00:00:00+00:00",
        reason="future expiry secret",
        decision_time="2099-01-01T02:00:00+00:00",
    )
    store.append_outcome(
        entry.thesis_id,
        outcome="future outcome secret",
        observed_at="2099-01-01T03:00:00+00:00",
        decision_time="2099-01-01T03:00:00+00:00",
        details={"future_detail": "secret"},
    )

    cutoff = "2026-08-03T01:00:00+00:00"
    packet = store.export_packet(disclosure_safe=True, at=cutoff)
    encoded = json.dumps(packet, sort_keys=True)
    assert len(packet["events"]) == 1
    assert packet["events"][0]["operation"] == "created"
    assert packet["events"][0]["sequence"] == 1
    assert packet["checksums"]["events"] == sha256_value(packet["events"])
    for secret in ("future reviewer secret", "future review secret", "future redaction secret", "future expiry secret", "future outcome secret", "future_detail"):
        assert secret not in encoded

    reproduced = reproduce_thesis_from_packet(packet, entry.thesis_id, at=cutoff)
    assert reproduced.human_review["status"] == "pending"
    assert reproduced.redaction_state == "unredacted"
    assert reproduced.outcomes == ()
    assert reproduced.applied_event_ids == (packet["events"][0]["event_id"],)


def test_current_redaction_cannot_be_reversed_by_future_unredaction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 8, 3, 3, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr(thesis_diary, "datetime", ControlledDateTime)
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry(prompt="private prompt"))
    store.append_redaction(entry.thesis_id, state="redacted", reason="private reason", decision_time="2026-08-03T02:00:00+00:00")
    store.append_redaction(entry.thesis_id, state="unredacted", reason="future release", decision_time="2099-01-01T00:00:00+00:00")

    packet = store.export_packet(disclosure_safe=True)
    exported = packet["entries"][0]
    assert exported["redaction_state"] == "redacted"
    assert exported["content_redacted"] is True
    assert "private prompt" not in json.dumps(packet)
    assert "private reason" not in json.dumps(packet)
    assert "future release" not in json.dumps(packet)


def test_redacted_instrument_and_chat_projections_scrub_protected_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path / "data")
    entry = store.create(build_thesis_entry(
        thesis_id="thesis-secret",
        prompt="secret prompt",
        model="secret-model",
        source_snapshot={"secret_source": "source-value"},
        retrieval_snapshot={"secret_retrieval": "retrieval-value"},
        evidence_snapshot={"secret_evidence": "evidence-value"},
        llm_output={"secret_output": "output-value"},
        generation_record={"provenance": "synthetic_fallback", "synthetic": True, "secret_generation": "generation-value"},
        instrument_id="VWCE",
        input_sources=["secret-source"],
        thesis_summary="secret thesis",
        risk_summary="secret risk",
        contradiction_summary="secret contradiction",
        decision_time="2026-08-03T00:00:00+00:00",
        created_at="2026-08-03T00:00:00+00:00",
    ))
    store.append_redaction(entry.thesis_id, state="redacted", reason="private reason", decision_time="2026-08-03T01:00:00+00:00")
    store.append_review(entry.thesis_id, status="approved", reviewer="secret reviewer", notes="secret notes", decision_time="2026-08-03T02:00:00+00:00")
    store.append_outcome(entry.thesis_id, outcome="secret outcome", observed_at="2026-08-03T03:00:00+00:00", decision_time="2026-08-03T03:00:00+00:00", details={"secret_detail": "detail-value"})

    panel = _thesis_diary_panel("VWCE", root=tmp_path / "data")
    rendered = json.dumps(panel)
    assert panel["entries"][0]["content_redacted"] is True
    assert panel["entries"][0]["human_review"]["reviewer"] == "[REDACTED]"
    assert panel["entries"][0]["outcome_events"][0]["details"] == {"redacted": True}
    for secret in ("secret prompt", "secret-model", "source-value", "retrieval-value", "evidence-value", "output-value", "generation-value", "secret-source", "secret thesis", "secret risk", "secret contradiction", "secret reviewer", "secret notes", "secret outcome", "detail-value"):
        assert secret not in rendered

    monkeypatch.setattr("etf_cockpit.app.pages.chatgpt_audit.ThesisDiaryStore", lambda: store)
    audit_text = _thesis_diary_text()
    for secret in ("secret prompt", "secret-model", "secret-source", "secret thesis", "secret risk", "secret contradiction", "secret reviewer", "secret notes", "secret outcome", "detail-value"):
        assert secret not in audit_text
    assert "redaction=redacted" in audit_text


def test_review_rejects_empty_reviewer(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())

    with pytest.raises(ValueError, match="non-empty reviewer"):
        store.append_review(
            entry.thesis_id,
            status="approved",
            reviewer="   ",
            decision_time="2026-08-03T01:00:00+00:00",
        )


def test_corrupt_store_and_inconsistent_packet_fail_closed(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    entry_path = store.entry_path(entry.thesis_id)
    payload = json.loads(entry_path.read_text(encoding="utf-8"))
    payload["evidence_snapshot"]["status"] = "tampered"
    entry_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ThesisDiaryIntegrityError):
        store.export_packet()

    valid_packet = {
        "schema_version": "thesis-diary.v1",
        "execution_allowed": False,
        "entries": [],
        "events": [],
        "checksums": {"entries": {"unexpected": "0" * 64}, "events": "0" * 64},
    }
    with pytest.raises(ThesisDiaryIntegrityError):
        reproduce_thesis_from_packet(valid_packet, "thesis-1")


def test_packet_reproduction_rejects_self_consistent_exact_provenance_mismatch(tmp_path: Path) -> None:
    commentary = {
        "summary": "Stored commentary",
        "blocked_trade_explanations": [],
        "contradictions": [],
        "external_review_questions": [],
        "confidence": 0.5,
        "executable_authority": False,
    }
    prompt = "immutable prompt"
    generation = {
        "provenance": "exact_generation",
        "synthetic": False,
        "generation_time": "2026-08-03T12:00:00+00:00",
        "request": {"model": "exact-model", "messages": [{"role": "user", "content": prompt}]},
        "response": {
            "model": "exact-model",
            "choices": [{"message": {"content": json.dumps(commentary, sort_keys=True)}}],
        },
    }
    entry = ThesisDiaryStore(tmp_path).create(
        build_thesis_entry(
            thesis_id="exact-thesis",
            prompt=prompt,
            model="exact-model",
            source_snapshot={"source": "test"},
            retrieval_snapshot={"retrieval": "test"},
            evidence_snapshot={"as_of_date": "2026-08-03"},
            llm_output=commentary,
            generation_record=generation,
            decision_time="2026-08-03T12:00:00+00:00",
            created_at="2026-08-03T12:00:00+00:00",
        )
    )
    packet = ThesisDiaryStore(tmp_path).export_packet()
    record = packet["entries"][0]
    record["generation_record"]["response"]["choices"][0]["message"]["content"] = json.dumps(
        {**commentary, "summary": "Tampered commentary"}, sort_keys=True
    )
    record["generation_record_hash"] = sha256_value(record["generation_record"])
    checksum_values = dict(record)
    checksum_values.pop("checksum")
    record["checksum"] = sha256_value(checksum_values)
    packet["checksums"]["entries"][entry.thesis_id] = record["checksum"]
    created = packet["events"][0]
    created["payload"] = {"entry_checksum": record["checksum"]}
    created_without_hash = dict(created)
    created_without_hash.pop("event_hash")
    created["event_hash"] = sha256_value(created_without_hash)
    packet["checksums"]["events"] = sha256_value(packet["events"])

    with pytest.raises(ThesisDiaryIntegrityError, match="packet entry is malformed"):
        reproduce_thesis_from_packet(packet, entry.thesis_id, at="2026-08-03T12:00:00+00:00")


@pytest.mark.parametrize(
    "generation_record",
    [
        {"synthetic": True},
        {"provenance": "unknown", "synthetic": True},
        {"provenance": "synthetic_fallback", "synthetic": False},
        {
            "provenance": "synthetic_fallback",
            "synthetic": True,
            "request": {"model": "local-test-model"},
            "response": {"model": "local-test-model"},
        },
    ],
)
def test_generation_provenance_is_required_and_synthetic_cannot_claim_exact_records(generation_record: dict) -> None:
    with pytest.raises(ValueError, match="provenance|synthetic"):
        _entry(generation_record=generation_record)


def test_packet_rejects_missing_generation_provenance_after_rehash(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    packet = store.export_packet()
    record = packet["entries"][0]
    record["generation_record"] = {"synthetic": True}
    record["generation_record_hash"] = sha256_value(record["generation_record"])
    checksum_values = dict(record)
    checksum_values.pop("checksum")
    record["checksum"] = sha256_value(checksum_values)
    packet["checksums"]["entries"][entry.thesis_id] = record["checksum"]
    _rehash_packet_events(packet, packet["events"])
    packet["events"][0]["payload"] = {"entry_checksum": record["checksum"]}
    _rehash_packet_events(packet, packet["events"])

    with pytest.raises(ThesisDiaryIntegrityError, match="packet entry is malformed"):
        reproduce_thesis_from_packet(packet, entry.thesis_id)


def test_inconsistent_redaction_markers_and_checksum_valid_content_fail_closed(tmp_path: Path) -> None:
    entry = ThesisDiaryStore(tmp_path).create(_entry())
    raw = entry.model_dump(mode="json")
    raw["redaction_state"] = "redacted"
    with pytest.raises(ValueError, match="redacted content"):
        type(entry).model_validate(raw)

    raw["content_redacted"] = True
    raw["redaction_state"] = "unredacted"
    with pytest.raises(ValueError, match="redacted state"):
        type(entry).model_validate(raw)

    packet = ThesisDiaryStore(tmp_path).export_packet()
    record = packet["entries"][0]
    record.update(
        {
            "content_redacted": True,
            "redaction_state": "redacted",
            "prompt": "protected prompt",
            "llm_output": {"secret": "protected output"},
            "generation_record": {"provenance": "redacted_content", "content_redacted": True},
        }
    )
    checksum_values = dict(record)
    checksum_values.pop("checksum")
    record["checksum"] = sha256_value(checksum_values)
    packet["checksums"]["entries"][entry.thesis_id] = record["checksum"]
    created = packet["events"][0]
    created["payload"] = {"entry_checksum": record["checksum"]}
    created_without_hash = dict(created)
    created_without_hash.pop("event_hash")
    created["event_hash"] = sha256_value(created_without_hash)
    packet["checksums"]["events"] = sha256_value(packet["events"])

    with pytest.raises(ThesisDiaryIntegrityError, match="packet entry is malformed"):
        reproduce_thesis_from_packet(packet, entry.thesis_id)


def _rehash_packet_events(packet: dict, events: list[dict]) -> None:
    previous = None
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["previous_event_hash"] = previous
        values = dict(event)
        values.pop("event_hash")
        event["event_hash"] = sha256_value(values)
        previous = event["event_hash"]
    packet["events"] = events
    packet["checksums"]["events"] = sha256_value(events)


def test_packet_reproduction_reuses_store_chronology_and_unique_event_invariants(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    store.append_review(entry.thesis_id, status="approved", reviewer="one", decision_time="2026-08-03T01:00:00+00:00", event_id="review-one")
    store.append_review(entry.thesis_id, status="approved", reviewer="two", decision_time="2026-08-03T02:00:00+00:00", event_id="review-two")

    backdated = store.export_packet()
    backdated_events = json.loads(json.dumps(backdated["events"]))
    backdated_events[2]["decision_time"] = "2026-08-03T00:30:00+00:00"
    _rehash_packet_events(backdated, backdated_events)
    with pytest.raises(ThesisDiaryIntegrityError, match="history is backdated"):
        reproduce_thesis_from_packet(backdated, entry.thesis_id)

    duplicated = store.export_packet()
    duplicated_events = json.loads(json.dumps(duplicated["events"]))
    duplicate = dict(duplicated_events[2])
    duplicated_events.append(duplicate)
    _rehash_packet_events(duplicated, duplicated_events)
    with pytest.raises(ThesisDiaryIntegrityError, match="event identity is duplicated"):
        reproduce_thesis_from_packet(duplicated, entry.thesis_id)


def test_local_llm_save_creates_non_executable_diary_record(tmp_path: Path) -> None:
    commentary = LocalAuditCommentary(summary="No trade authority", confidence=0.5)
    report_path = save_local_audit_commentary(
        commentary,
        model="local-test-model",
        context={"as_of_date": "2026-08-03", "signals": [], "authority": "commentary_only_no_trade_execution"},
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )

    assert report_path.is_file()
    entries = ThesisDiaryStore(tmp_path / "data").list_entries()
    assert len(entries) == 1
    assert entries[0].execution_allowed is False
    assert entries[0].prompt_hash
    assert entries[0].evidence_snapshot_hash
    assert json.loads(report_path.read_text(encoding="utf-8"))["executable_authority"] is False


def test_audit_export_contains_reproducible_diary_records(tmp_path: Path) -> None:
    entry = ThesisDiaryStore(tmp_path / "data").create(_entry())
    destination = tmp_path / "evidence_export" / "thesis_diary.json"

    export_pack._export_thesis_diary(destination, root=tmp_path / "data")

    packet = json.loads(destination.read_text(encoding="utf-8"))
    reproduced = reproduce_thesis_from_packet(packet, entry.thesis_id)
    assert reproduced.entry.evidence_snapshot == entry.evidence_snapshot
    assert packet["execution_allowed"] is False
    assert packet["executable_authority"] is False


def test_redacted_export_hides_content_and_retains_commitments(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path / "data")
    entry = store.create(_entry(prompt="secret prompt that must not leave local storage"))
    store.append_redaction(
        entry.thesis_id,
        state="redacted",
        reason="private reason",
        decision_time="2026-08-03T01:00:00+00:00",
    )
    destination = tmp_path / "evidence_export" / "thesis_diary.json"
    export_pack._export_thesis_diary(destination, root=tmp_path / "data")

    packet = json.loads(destination.read_text(encoding="utf-8"))
    exported = packet["entries"][0]
    assert exported["prompt"] == "[REDACTED]"
    assert "secret prompt" not in json.dumps(packet)
    assert packet["local_commitments"]["entries"][entry.thesis_id] == entry.checksum
    reproduced = reproduce_thesis_from_packet(packet, entry.thesis_id, at="2026-08-03T02:00:00+00:00")
    assert reproduced.redaction_state == "redacted"
    assert reproduced.entry.content_redacted is True


def test_structured_fields_and_forward_only_backtest_guard_are_explicit() -> None:
    entry = _entry()

    assert entry.instrument_id == "VWCE"
    assert entry.executable_authority is False
    assert entry.prompt_hash
    assert entry.input_sources == ["cockpit_snapshot", "signal:VWCE"]
    assert entry.thesis_summary and entry.risk_summary and entry.contradiction_summary
    assert entry.uncertainty == 0.5
    assert entry.human_review_status == "pending"
    assert entry.evidence_score == 7.5
    assert entry.evidence_quality == 6.5
    assert entry.risk_friction == 5.5
    assert entry.final_advisory_label == "manual_review"
    assert set(entry.outcomes) == {"20", "60", "120"}
    assert entry.backtest_validity == "unknown"

    with pytest.raises(ValueError, match="forward-only"):
        _entry(backtest_validity="forward_only")


def test_local_llm_save_scopes_records_and_keeps_diary_non_authoritative(tmp_path: Path) -> None:
    commentary = LocalAuditCommentary(summary="Review only", confidence=0.75)
    context = {
        "as_of_date": "2026-08-03",
        "authority": "commentary_only_no_trade_execution",
        "signals": [
            {"etf_id": "VWCE", "input_sources": ["scoreboard"], "evidence_score": 8.0, "evidence_quality": 7.0, "risk_friction": 6.0, "final_advisory_label": "watch"},
            {"etf_id": "XDWU", "input_sources": ["scoreboard"], "evidence_score": 5.0, "evidence_quality": 4.0, "risk_friction": 3.0, "final_advisory_label": "manual_review"},
        ],
    }
    original = json.loads(json.dumps(context))

    report_path = save_local_audit_commentary(commentary, model="local-test-model", context=context, directory=tmp_path / "reports", diary_root=tmp_path / "data")
    entries = ThesisDiaryStore(tmp_path / "data").list_entries()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert context == original
    assert {entry.instrument_id for entry in entries} == {"VWCE", "XDWU"}
    assert all(entry.execution_allowed is False for entry in entries)
    assert all(entry.backtest_validity == "unknown" for entry in entries)
    assert all(entry.evidence_score is not None for entry in entries)
    assert report["executable_authority"] is False
    assert len(report["thesis_ids"]) == 2


def test_instrument_and_audit_projections_are_context_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ThesisDiaryStore(tmp_path / "data")
    entry = store.create(_entry())
    store.append_outcome(entry.thesis_id, outcome="positive", horizon="20", observed_at="2026-08-04T00:00:00+00:00", decision_time="2026-08-04T00:00:00+00:00", details={"return": 0.1})

    panel = _thesis_diary_panel("VWCE", root=tmp_path / "data")
    assert panel["status"] == "available"
    assert panel["execution_allowed"] is False
    assert panel["executable_authority"] is False
    assert panel["score_eligible"] is False
    assert panel["action_authority"] is False
    assert panel["risk_gate_authority"] is False
    assert panel["entries"][0]["redaction_state"] == "unredacted"
    assert panel["entries"][0]["expired"] is False
    assert panel["entries"][0]["human_review"]["status"] == "pending"
    assert panel["entries"][0]["outcomes"]["20"]["outcome"] == "positive"

    monkeypatch.setattr("etf_cockpit.app.pages.chatgpt_audit.ThesisDiaryStore", lambda: store)
    audit_text = _thesis_diary_text()
    assert "VWCE" in audit_text
    assert "execution_allowed=false" in audit_text


def test_llm_backtest_panel_is_unknown_and_excluded_from_trust() -> None:
    panel = _backtest_panel(build_snapshot(), "VWCE", {})

    assert panel["llm_backtest_validity"] == "unknown"
    assert panel["llm_output_authority"] == "excluded_from_backtest"
    assert panel["execution_allowed"] is False
