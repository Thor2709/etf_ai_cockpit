from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.audit import local_llm
from etf_cockpit.audit.local_llm import (
    LocalLLMSettings,
    build_local_audit_context,
    check_local_llm_status,
    generate_local_audit_commentary,
    parse_local_llm_response,
    save_local_audit_commentary,
)
import etf_cockpit.audit.thesis_diary as thesis_diary
from etf_cockpit.audit.thesis_diary import ThesisDiaryStore, build_thesis_entry, reproduce_thesis_from_packet
from etf_cockpit.core.atomic_io import atomic_write_group as real_atomic_write_group
from etf_cockpit.services import build_snapshot


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_disabled_local_llm_status_does_not_call_network(monkeypatch) -> None:
    def fail_get(*_args, **_kwargs):
        raise AssertionError("network should not be called when local LLM is disabled")

    monkeypatch.setattr(local_llm.requests, "get", fail_get)

    status = check_local_llm_status(LocalLLMSettings(enabled=False))

    assert status.status == "disabled"
    assert status.model is None


def test_local_llm_status_discovers_first_model(monkeypatch) -> None:
    monkeypatch.setattr(local_llm.requests, "get", lambda *_args, **_kwargs: _Response({"data": [{"id": "local-test-model"}]}))

    status = check_local_llm_status(LocalLLMSettings(enabled=True, api_key="secret-token"))

    assert status.status == "ok"
    assert status.model == "local-test-model"


def test_local_llm_unavailable_status_is_user_safe(monkeypatch) -> None:
    def fail_get(*_args, **_kwargs):
        raise local_llm.requests.exceptions.ConnectionError("raw connection details")

    monkeypatch.setattr(local_llm.requests, "get", fail_get)

    status = check_local_llm_status(LocalLLMSettings(enabled=True))

    assert status.status == "unavailable"
    assert "raw connection details" not in status.message
    assert "Start the LM Studio local server" in status.message


def test_local_llm_response_rejects_executable_authority() -> None:
    payload = '{"summary":"Looks coherent.","blocked_trade_explanations":[],"contradictions":[],"external_review_questions":[],"confidence":0.4,"executable_authority":true}'

    with pytest.raises(ValueError, match="schema validation"):
        parse_local_llm_response(payload)


def test_local_llm_response_accepts_commentary_only_schema() -> None:
    payload = """```json
{"summary":"Risk gates block all trades.","blocked_trade_explanations":["WORLD_CORE is over policy cap."],"contradictions":[],"external_review_questions":["Should the policy cap be changed?"],"confidence":0.6,"executable_authority":false}
```"""

    commentary = parse_local_llm_response(payload)

    assert commentary.executable_authority is False
    assert commentary.blocked_trade_explanations


def test_local_llm_context_contains_only_deterministic_snapshot_outputs() -> None:
    context = build_local_audit_context(build_snapshot())

    assert context["authority"] == "commentary_only_no_trade_execution"
    assert isinstance(context["signals"], list)
    assert "validation_issues" in context
    assert "backtest" in context


def test_generation_repeated_with_same_context_is_fresh_and_does_not_mutate_prompt_input(monkeypatch) -> None:
    context = {
        "as_of_date": "2026-08-03",
        "generation_time": "2000-01-01T00:00:00+00:00",
        "signals": [{"etf_id": "VWCE"}],
    }
    response_payload = {
        "model": "exact-model",
        "choices": [{"message": {"content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'}}],
    }
    prompts: list[str] = []

    monkeypatch.setattr(local_llm.requests, "get", lambda *_args, **_kwargs: _Response({"data": [{"id": "exact-model"}]}))

    def post(_url, *, json, **_kwargs):
        prompts.append(json["messages"][1]["content"])
        return _Response(response_payload)

    monkeypatch.setattr(local_llm.requests, "post", post)
    original = json.loads(json.dumps(context))
    first_status, _ = generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))
    second_status, _ = generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))

    assert context == original
    assert "2000-01-01T00:00:00+00:00" not in prompts[0]
    assert prompts[1] == prompts[0]
    assert first_status.generation_time != second_status.generation_time


def test_generation_failure_then_success_does_not_backdate_or_mutate_context(monkeypatch) -> None:
    context = {"as_of_date": "2026-08-03", "signals": [{"etf_id": "VWCE"}]}
    response_payload = {
        "model": "exact-model",
        "choices": [{"message": {"content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'}}],
    }
    responses = iter((
        _Response({"model": "exact-model", "choices": [{"message": {"content": "not json"}}]}),
        _Response(response_payload),
    ))
    monkeypatch.setattr(local_llm.requests, "get", lambda *_args, **_kwargs: _Response({"data": [{"id": "exact-model"}]}))
    monkeypatch.setattr(local_llm.requests, "post", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(ValueError, match="did not contain a JSON object"):
        generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))
    assert "generation_time" not in context
    status, _ = generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))
    assert status.generation_time is not None
    assert "generation_time" not in context


def test_generation_persists_the_exact_request_and_response_binding(
    monkeypatch, tmp_path
) -> None:
    context = {
        "as_of_date": "2026-08-03",
        "authority": "commentary_only_no_trade_execution",
        "generation_time": "2026-08-03T12:00:00Z",
        "signals": [{"etf_id": "VWCE", "input_sources": ["scoreboard"]}],
    }
    response_payload = {
        "id": "completion-1",
        "model": "exact-model",
        "choices": [{
            "message": {
                "content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'
            }
        }],
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(local_llm.requests, "get", lambda *_args, **_kwargs: _Response({"data": [{"id": "exact-model"}]}))

    def post(_url, *, json, **_kwargs):
        captured["body"] = json
        return _Response(response_payload)

    monkeypatch.setattr(local_llm.requests, "post", post)
    original_context = json.loads(json.dumps(context))
    status, commentary = generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))
    assert commentary is not None
    assert status.request_envelope == captured["body"]
    assert status.response_payload == response_payload
    assert status.generation_time is not None
    assert context == original_context

    save_local_audit_commentary(
        commentary,
        model=status.model,
        context=context,
        request_envelope=status.request_envelope,
        response_payload=status.response_payload,
        generation_time=status.generation_time,
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    entry = ThesisDiaryStore(tmp_path / "data").list_entries()[0]
    assert entry.prompt == captured["body"]["messages"][1]["content"]  # type: ignore[index]
    assert entry.created_at == status.generation_time
    assert entry.decision_time == entry.created_at
    assert entry.evidence_snapshot["as_of_date"] == "2026-08-03"
    with pytest.raises(ValueError, match="precedes thesis decision time"):
        ThesisDiaryStore(tmp_path / "data").replay(entry.thesis_id, at="2026-08-03T11:59:59+00:00")
    with pytest.raises(ValueError, match="precedes thesis decision time"):
        reproduce_thesis_from_packet(
            ThesisDiaryStore(tmp_path / "data").export_packet(),
            entry.thesis_id,
            at="2026-08-03T11:59:59+00:00",
        )
    assert entry.generation_record["generation_time"] == entry.created_at
    assert entry.generation_record["request"] == captured["body"]  # type: ignore[index]
    assert entry.generation_record["response"] == response_payload


def test_exact_generation_rejects_mutated_save_context_and_retries_same_status(
    monkeypatch, tmp_path
) -> None:
    context = {
        "as_of_date": "2026-08-03",
        "authority": "commentary_only_no_trade_execution",
        "signals": [{"etf_id": "VWCE", "input_sources": ["scoreboard"]}],
    }
    response_payload = {
        "model": "exact-model",
        "choices": [{"message": {"content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'}}],
    }
    monkeypatch.setattr(local_llm.requests, "get", lambda *_args, **_kwargs: _Response({"data": [{"id": "exact-model"}]}))
    monkeypatch.setattr(local_llm.requests, "post", lambda *_args, **_kwargs: _Response(response_payload))

    status, commentary = generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))
    assert commentary is not None
    assert status.context_snapshot is not None
    context["signals"][0]["input_sources"] = ["mutated-after-generation"]

    with pytest.raises(ValueError, match="contradicts save context"):
        save_local_audit_commentary(
            commentary,
            model=status.model,
            context=context,
            request_envelope=status.request_envelope,
            response_payload=status.response_payload,
            generation_time=status.generation_time,
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )

    first = save_local_audit_commentary(
        commentary,
        model=status.model,
        context=status.context_snapshot,
        request_envelope=status.request_envelope,
        response_payload=status.response_payload,
        generation_time=status.generation_time,
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    second = save_local_audit_commentary(
        commentary,
        model=status.model,
        context=status.context_snapshot,
        request_envelope=status.request_envelope,
        response_payload=status.response_payload,
        generation_time=status.generation_time,
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    assert second == first
    assert second.read_bytes() == first.read_bytes()
    assert len(ThesisDiaryStore(tmp_path / "data").list_entries()) == 1


def test_exact_generation_requires_stable_generation_time(tmp_path: Path) -> None:
    commentary = local_llm.LocalAuditCommentary(summary="Review only", confidence=0.5)
    context = {"as_of_date": "2026-08-03", "signals": [{"etf_id": "VWCE"}]}
    envelope = {
        "model": "exact-model",
        "messages": [{"role": "user", "content": local_llm.build_local_audit_prompt(context)}],
    }
    response = {
        "model": "exact-model",
        "choices": [{"message": {"content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'}}],
    }

    with pytest.raises(ValueError, match="immutable availability timestamp"):
        local_llm.save_local_audit_commentary(
            commentary,
            model="exact-model",
            context=context,
            request_envelope=envelope,
            response_payload=response,
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )


def test_exact_generation_rejects_request_without_immutable_context(tmp_path: Path) -> None:
    commentary = local_llm.LocalAuditCommentary(summary="Review only", confidence=0.5)
    with pytest.raises(ValueError, match="prompt context is invalid"):
        local_llm.save_local_audit_commentary(
            commentary,
            model="exact-model",
            context={"as_of_date": "2026-08-03", "signals": [{"etf_id": "VWCE"}]},
            request_envelope={
                "model": "exact-model",
                "messages": [{"role": "user", "content": "legacy prompt without immutable context"}],
            },
            response_payload={
                "model": "exact-model",
                "choices": [{
                    "message": {
                        "content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'
                    }
                }],
            },
            generation_time="2026-08-03T12:00:00+00:00",
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )


def test_exact_generation_rejects_availability_before_snapshot_date(tmp_path: Path) -> None:
    context = {"as_of_date": "2026-08-03", "signals": [{"etf_id": "VWCE"}]}
    commentary = local_llm.LocalAuditCommentary(summary="Review only", confidence=0.5)
    with pytest.raises(ValueError, match="postdates thesis decision time"):
        local_llm.save_local_audit_commentary(
            commentary,
            model="exact-model",
            context=context,
            request_envelope={
                "model": "exact-model",
                "messages": [{"role": "user", "content": local_llm.build_local_audit_prompt(context)}],
            },
            response_payload={
                "model": "exact-model",
                "choices": [{
                    "message": {
                        "content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'
                    }
                }],
            },
            generation_time="1970-01-01T00:00:00+00:00",
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )
    assert not (tmp_path / "data" / "thesis_diary").exists()
    assert not list((tmp_path / "reports").glob("*.json"))


def test_immutable_entry_rejects_self_consistent_but_semantically_inconsistent_exact_generation() -> None:
    commentary = local_llm.LocalAuditCommentary(summary="Stored commentary", confidence=0.5)
    prompt = "immutable prompt"
    generation = {
        "provenance": "exact_generation",
        "synthetic": False,
        "generation_time": "2026-08-03T12:00:00+00:00",
        "request": {"model": "exact-model", "messages": [{"role": "user", "content": prompt}]},
        "response": {
            "model": "exact-model",
            "choices": [{"message": {"content": '{"summary":"Different commentary","confidence":0.5,"executable_authority":false}'}}],
        },
    }

    with pytest.raises(ValueError, match="immutable entry commentary"):
        build_thesis_entry(
            prompt=prompt,
            model="exact-model",
            source_snapshot={"source": "test"},
            retrieval_snapshot={"retrieval": "test"},
            evidence_snapshot={"as_of_date": "2026-08-03"},
            llm_output=commentary.model_dump(mode="json"),
            generation_record=generation,
            decision_time="2026-08-03T12:00:00+00:00",
            created_at="2026-08-03T12:00:00+00:00",
        )


def test_exact_generation_rejects_model_and_response_commentary_contradictions(tmp_path: Path) -> None:
    commentary = local_llm.LocalAuditCommentary(summary="Review only", confidence=0.5)
    context = {"as_of_date": "2026-08-03", "signals": [{"etf_id": "VWCE"}]}
    envelope = {
        "model": "exact-model",
        "messages": [{"role": "user", "content": local_llm.build_local_audit_prompt(context)}],
    }
    response = {
        "model": "exact-model",
        "choices": [{"message": {"content": '{"summary":"Different","confidence":0.5,"executable_authority":false}'}}]
    }

    with pytest.raises(ValueError, match="does not parse"):
        local_llm.save_local_audit_commentary(
            commentary,
            model="exact-model",
            context=context,
            request_envelope=envelope,
            response_payload=response,
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )
    with pytest.raises(ValueError, match="contradicts"):
        local_llm.save_local_audit_commentary(
            commentary,
            model="other-model",
            context=context,
            request_envelope=envelope,
            response_payload={"choices": [{"message": {"content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'}}]},
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )
    assert not (tmp_path / "data" / "thesis_diary" / "index.json").exists()


def test_synthetic_fallback_is_explicitly_non_exact(tmp_path: Path) -> None:
    report = local_llm.save_local_audit_commentary(
        local_llm.LocalAuditCommentary(summary="Synthetic review", confidence=0.5),
        model="local-test-model",
        context={"as_of_date": "2026-08-03", "signals": [{"etf_id": "VWCE"}]},
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    entry = ThesisDiaryStore(tmp_path / "data").list_entries()[0]
    assert entry.generation_record["provenance"] == "synthetic_fallback"
    assert entry.generation_record["synthetic"] is True
    assert json.loads(report.read_text(encoding="utf-8"))["batch_id"].startswith("batch-")


def test_invalid_later_signal_writes_no_batch_entries_or_report(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="instrument id"):
        local_llm.save_local_audit_commentary(
            local_llm.LocalAuditCommentary(summary="Review only", confidence=0.5),
            model="local-test-model",
            context={
                "as_of_date": "2026-08-03",
                "signals": [{"etf_id": "VWCE"}, {"etf_id": "not safe"}],
            },
            directory=tmp_path / "reports",
            diary_root=tmp_path / "data",
        )
    assert ThesisDiaryStore(tmp_path / "data").list_entries() == []
    assert not list((tmp_path / "reports").glob("*.json"))


def test_exact_batch_retry_is_idempotent_and_interruption_leaves_zero_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = {
        "as_of_date": "2026-08-03",
        "generation_time": "2026-08-03T12:00:00+00:00",
        "signals": [{"etf_id": "VWCE"}, {"etf_id": "XDWU"}],
    }
    commentary = local_llm.LocalAuditCommentary(summary="Review only", confidence=0.5)
    envelope = {
        "model": "local-test-model",
        "messages": [{"role": "user", "content": local_llm.build_local_audit_prompt(context)}],
    }
    response = {
        "model": "local-test-model",
        "choices": [{"message": {"content": '{"summary":"Review only","confidence":0.5,"executable_authority":false}'}}],
    }
    generation_time = "2026-08-03T12:00:00+00:00"
    first = local_llm.save_local_audit_commentary(
        commentary,
        model="local-test-model",
        context=context,
        request_envelope=envelope,
        response_payload=response,
        generation_time=generation_time,
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    first_bytes = first.read_bytes()
    second = local_llm.save_local_audit_commentary(
        commentary,
        model="local-test-model",
        context=context,
        request_envelope=envelope,
        response_payload=response,
        generation_time=generation_time,
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    assert second == first
    assert second.read_bytes() == first_bytes
    assert len(ThesisDiaryStore(tmp_path / "data").list_entries()) == 2

    interrupted = tmp_path / "interrupted"

    def interrupting_write(requests, **_kwargs):
        def hook(state: str, _journal: Path) -> None:
            if state == "memory":
                raise RuntimeError("batch interruption")

        return real_atomic_write_group(requests, lifecycle_hook=hook)

    monkeypatch.setattr(thesis_diary, "atomic_write_group", interrupting_write)
    with pytest.raises(RuntimeError, match="batch interruption"):
        local_llm.save_local_audit_commentary(
            commentary,
            model="local-test-model",
            context=context,
            request_envelope=envelope,
            response_payload=response,
            generation_time=generation_time,
            directory=interrupted / "reports",
            diary_root=interrupted / "data",
        )
    assert ThesisDiaryStore(interrupted / "data").list_entries() == []
    assert not list((interrupted / "reports").glob("*.json"))
