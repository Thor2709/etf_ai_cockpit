from __future__ import annotations

from pathlib import Path
import threading
import time
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app.operations import build_operation_preview, load_operation_records, save_operation_record
from etf_cockpit.app.pages.operations import operations_page
from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.portfolio.proposal_policy import load_proposal_records
from etf_cockpit.services import build_snapshot


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control: object) -> str:
    return "\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))


def _stub_authority_matrix(monkeypatch) -> None:
    import etf_cockpit.portfolio.proposal_policy as proposal_policy

    capabilities = tuple(
        SimpleNamespace(capability_id=capability_id, authority_stage=stage, availability="mandatory")
        for capability_id, stage in (
            ("strategy:manual_review", "research"),
            ("model:baseline", "research"),
            ("broker:paper_portfolio", "paper"),
        )
    )
    result = SimpleNamespace(
        diagnostic_mode=False,
        diagnostics=(),
        checksum="a" * 64,
        policy=SimpleNamespace(capabilities=capabilities),
    )
    monkeypatch.setattr(proposal_policy, "load_authority_matrix", lambda: result)


def test_operation_preview_has_separate_authority_and_result_sections() -> None:
    paper = build_operation_preview(environment="paper", instrument_id=" vwce ", quantity=2)
    live = build_operation_preview(environment="live", instrument_id="VWCE", quantity=2)

    assert paper.status == "preview"
    assert paper.authority["stage"] == "paper_preview"
    assert paper.authority["submission_allowed"] is True
    assert paper.authority["execution_allowed"] is False
    assert paper.result["status"] == "preview"
    assert paper.audit["record_id"] == paper.operation_id
    assert live.status == "blocked"
    assert live.authority["stage"] == "live_disabled"
    assert live.authority["submission_allowed"] is False
    assert "disabled" in str(live.authority["reason"]).casefold()


def test_operation_preview_is_validated_and_deterministically_deduplicated() -> None:
    first = build_operation_preview(environment="paper", instrument_id="VWCE", quantity=1)
    second = build_operation_preview(environment="paper", instrument_id="VWCE", quantity=1)

    assert first.operation_id == second.operation_id
    with pytest.raises(ValueError, match="Quantity"):
        build_operation_preview(environment="paper", instrument_id="VWCE", quantity=0)
    with pytest.raises(ValueError, match="instrument"):
        build_operation_preview(environment="paper", instrument_id="", quantity=1)


def test_operation_records_are_local_versioned_json(tmp_path: Path) -> None:
    record = build_operation_preview(environment="paper", instrument_id="VWCE", quantity=3)
    path = save_operation_record(record, directory=tmp_path)

    assert path.exists()
    records = load_operation_records(directory=tmp_path)
    assert records[0]["schema_version"] == "operations.v1"
    assert records[0]["authority"]["execution_allowed"] is False


def test_operations_workspace_exposes_paper_live_training_and_audit_states() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    rendered = operations_page(None, state)
    text = _text(rendered)

    assert PAGES["/operations"][0] == "Operations Centre"
    assert "Paper environment" in text
    assert "Live environment: disabled" in text
    assert "Training Centre" in text
    assert "execution_allowed=false" in text
    assert "Audit:" in text
    assert any(getattr(item, "key", None) == "operations.preview" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.confirm" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.cancel" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.proposal-review" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-open" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-auto" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-defer" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-outcome" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-incident" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-fill" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-order-cancel" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-mark" for item in _walk(rendered))
    assert any(getattr(item, "key", None) == "operations.paper-corporate-action" for item in _walk(rendered))


def test_proposal_review_records_manual_review_until_immutable_evidence_exists(tmp_path: Path, monkeypatch) -> None:
    import etf_cockpit.app.pages.operations as module

    _stub_authority_matrix(monkeypatch)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.application_api = type(state.application_api)(lambda: state.snapshot, root=tmp_path)
    rendered = module.operations_page(None, state)
    button = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.proposal-review")

    button.on_click(None)
    text = _text(rendered)
    records = load_proposal_records(directory=tmp_path / "data" / "operations" / "proposals")
    assert "Proposal review: manual_review" in text
    assert "execution_allowed=false" in text
    assert "optimizer_output=failed" in text
    assert "alternatives=no_trade" in text
    assert records and records[0]["outcome"] == "manual_review"


def test_operations_workspace_can_open_local_paper_account(tmp_path: Path) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.application_api = type(state.application_api)(lambda: state.snapshot, root=tmp_path)
    rendered = operations_page(None, state)
    open_button = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.paper-open")

    open_button.on_click(None)
    text = _text(rendered)
    assert "Paper account: ready" in text
    assert "execution_allowed=false" in text

    mark_button = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.paper-mark")
    mark_button.on_click(None)
    assert "Adjusted-close mark recorded" in _text(rendered)


def test_paper_preview_starts_once_and_reaches_a_durable_result(tmp_path: Path, monkeypatch) -> None:
    import etf_cockpit.app.pages.operations as module

    monkeypatch.setattr(module, "save_operation_record", lambda record: save_operation_record(record, directory=tmp_path))
    monkeypatch.setattr(module, "load_operation_records", lambda: load_operation_records(directory=tmp_path))
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.application_api = type(state.application_api)(lambda: state.snapshot, root=tmp_path)
    rendered = module.operations_page(None, state)
    preview = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.preview")
    confirm = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.confirm")

    preview.on_click(None)
    preview.on_click(None)
    assert state.application_api.get_jobs().total == 0
    confirm.on_click(None)
    deadline = time.time() + 5
    while time.time() < deadline:
        records = load_operation_records(directory=tmp_path)
        if records and records[0]["status"] == "completed":
            break
        time.sleep(0.02)

    assert len(records) == 1
    assert records[0]["status"] == "completed"
    assert state.application_api.get_jobs().total == 1


def test_cancelled_paper_preview_stays_cancelled(tmp_path: Path, monkeypatch) -> None:
    import etf_cockpit.app.pages.operations as module

    monkeypatch.setattr(module, "save_operation_record", lambda record: save_operation_record(record, directory=tmp_path))
    monkeypatch.setattr(module, "load_operation_records", lambda: load_operation_records(directory=tmp_path))
    started = threading.Event()
    release = threading.Event()
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.application_api = type(state.application_api)(lambda: state.snapshot, root=tmp_path)
    state.application_api.run_next_job = lambda _runner: (started.set(), release.wait(5), object())[-1]  # type: ignore[method-assign]
    rendered = module.operations_page(None, state)
    preview = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.preview")
    confirm = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.confirm")
    cancel = next(item for item in _walk(rendered) if getattr(item, "key", None) == "operations.cancel")

    preview.on_click(None)
    confirm.on_click(None)
    assert started.wait(2)
    cancel.on_click(None)
    release.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        records = load_operation_records(directory=tmp_path)
        if records and records[0]["status"] == "cancelled":
            break
        time.sleep(0.02)

    assert records[0]["status"] == "cancelled"
    assert "no order" in str(records[0]["result"]["message"]).casefold()
