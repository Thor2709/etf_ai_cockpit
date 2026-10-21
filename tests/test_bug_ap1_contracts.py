"""Bughunt E (#990): deep-immutable application contracts and E001 N01/N02 (non-UTF-8 upload command)."""

from __future__ import annotations

import copy
import json
import pickle
from types import SimpleNamespace

import pytest

from etf_cockpit.application.api import LocalApplicationApi, _proposal_view_model
from etf_cockpit.application.contracts import (
    ApiStatus,
    BulkAnalysisRun,
    DashboardActionCommand,
    SubmitWorkflowCommand,
)

_KEY = "idem-key-0001"
_BINARY = b"PK\x03\x04\xff\xfe\x00"  # an xlsx-like upload: not valid UTF-8


def _api() -> LocalApplicationApi:
    return LocalApplicationApi(lambda: SimpleNamespace(universe_revision="r1"), revision_provider=lambda: "r1")


def _upload(content: bytes, key: str = _KEY) -> DashboardActionCommand:
    return DashboardActionCommand(idempotency_key=key, action="import_local_upload", file_name="a.xlsx", content=content)


def _mutations(mapping):
    yield lambda: mapping.__setitem__("x", 1)
    yield lambda: mapping.pop(next(iter(mapping)))
    yield lambda: mapping.update({"x": 1})
    yield lambda: mapping.setdefault("x", 1)
    yield lambda: mapping.clear()
    yield lambda: mapping.__delitem__(next(iter(mapping)))


def _assert_frozen(mapping) -> None:
    for mutate in _mutations(mapping):
        with pytest.raises(TypeError):
            mutate()


def test_nested_fields_of_frozen_contracts_cannot_be_mutated():  # E101-N003
    source = {"a": {"b": [1, {"c": 2}]}, "k": "v"}
    command = SubmitWorkflowCommand(idempotency_key=_KEY, workflow_type="t", label="l", input_payload=source)
    source["a"]["b"].append(3)  # later edits of the caller's object must not leak into the contract
    payload = command.input_payload
    _assert_frozen(payload)
    _assert_frozen(payload["a"])
    assert payload["a"]["b"] == [1, {"c": 2}]
    with pytest.raises(TypeError):
        payload["a"]["b"].append(3)
    _assert_frozen(payload["a"]["b"][1])

    proposal = _proposal_view_model({"proposal_id": "p", "input_material": {"event_control": {"status": "ok", "rows": [{"x": 1}]}}})
    _assert_frozen(proposal.event_control)
    _assert_frozen(proposal.event_control["rows"][0])

    run = BulkAnalysisRun(
        run_id="r", analyzer_id="a", status="succeeded", hashes={"E1": "h"}, states={"E1": "done"},
        results={"E1": {"score": [1]}}, failures={}, coverage_completed=1, coverage_total=1,
    )
    for field in (run.hashes, run.states, run.results, run.results["E1"]):
        _assert_frozen(field)

    # Reads, JSON, copies and pickling keep working on the frozen shapes.
    assert json.loads(command.model_dump_json())["input_payload"] == {"a": {"b": [1, {"c": 2}]}, "k": "v"}
    assert dict(payload)["k"] == "v"
    assert copy.deepcopy(command) == command
    assert pickle.loads(pickle.dumps(run)) == run
    assert BulkAnalysisRun.model_validate(run.model_dump()) == run


def test_empty_failures_mapping_is_frozen_too():
    run = BulkAnalysisRun(
        run_id="r", analyzer_id="a", status="queued", hashes={}, states={}, coverage_completed=0, coverage_total=0,
    )
    with pytest.raises(TypeError):
        run.failures["x"] = "y"
    with pytest.raises(TypeError):
        run.results["x"] = "y"


def test_e001_n01_execute_does_not_raise_for_non_utf8_command_content():
    api = _api()
    result = api.execute(_upload(_BINARY))
    assert result.status is not ApiStatus.CONFLICT
    assert result.error_code != "command_unserializable"
    assert result.idempotency_key == _KEY


def test_e001_n01_idempotency_fingerprint_distinguishes_binary_contents():
    api = _api()
    api.execute(_upload(_BINARY))
    replay = api.execute(_upload(_BINARY))
    assert replay.replayed is True
    other = api.execute(_upload(_BINARY + b"\x80"))
    assert other.status is ApiStatus.CONFLICT and other.error_code == "idempotency_key_reused"


def test_e001_n02_dashboard_action_command_serialises_non_utf8_bytes_and_round_trips():
    command = _upload(_BINARY)
    text = command.model_dump_json()
    assert DashboardActionCommand.model_validate_json(text).content == _BINARY
    assert json.loads(text)["content"] != ""


def test_e001_unserialisable_command_is_refused_not_raised():
    class Broken:
        idempotency_key = _KEY
        kind = "broken"

        def model_dump_json(self):
            raise ValueError("boom")

    result = _api().execute(Broken())  # type: ignore[arg-type]
    assert result.status is ApiStatus.FAILED and result.error_code == "command_unserializable"
