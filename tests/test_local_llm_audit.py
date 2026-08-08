from __future__ import annotations

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
from etf_cockpit.audit.thesis_diary import ThesisDiaryStore
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


def test_generation_persists_the_exact_request_and_response_binding(
    monkeypatch, tmp_path
) -> None:
    context = {
        "as_of_date": "2026-08-03",
        "authority": "commentary_only_no_trade_execution",
        "signals": [{"etf_id": "VWCE", "input_sources": ["scoreboard"]}],
    }
    response_payload = {
        "id": "completion-1",
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
    status, commentary = generate_local_audit_commentary(context, LocalLLMSettings(model="exact-model"))
    assert commentary is not None
    assert status.request_envelope == captured["body"]
    assert status.response_payload == response_payload

    save_local_audit_commentary(
        commentary,
        model=status.model,
        context=context,
        request_envelope=status.request_envelope,
        response_payload=status.response_payload,
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )
    entry = ThesisDiaryStore(tmp_path / "data").list_entries()[0]
    assert entry.prompt == captured["body"]["messages"][1]["content"]  # type: ignore[index]
    assert entry.generation_record["request"] == captured["body"]  # type: ignore[index]
    assert entry.generation_record["response"] == response_payload
