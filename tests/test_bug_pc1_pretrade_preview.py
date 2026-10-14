"""Bughunt D/E (#977): pre-trade grants and paper preview/operations records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import ApiStatus, RefreshDataCommand
from etf_cockpit.application.operation_records import (
    build_operation_preview,
    save_operation_record,
    terminal_operation_record,
    validate_operation_record,
)
from etf_cockpit.trading.pre_trade_controls import PreTradeControls
from tests.test_pre_trade_controls import _evaluate_paper, _proposal


def _snapshot_with(holdings: pd.DataFrame) -> object:
    return lambda: SimpleNamespace(holdings=holdings, universe_revision="r1")


def test_e023_n001_failed_command_is_not_recorded_as_replayed() -> None:
    calls: list[int] = []

    def failing(_command: object) -> dict[str, object]:
        calls.append(1)
        raise RuntimeError("boom")

    api = LocalApplicationApi(_snapshot_with(pd.DataFrame()), revision_provider=lambda: "r1", command_handlers={"refresh_data": failing})
    command = RefreshDataCommand(idempotency_key="refresh-fail-001")
    first = api.execute(command)
    second = api.execute(command)

    assert first.status is ApiStatus.FAILED
    assert second.status is ApiStatus.FAILED
    assert second.error_code == first.error_code == "command_failed"
    assert second.replayed is True
    assert calls == [1]


def test_e023_n001_stale_revision_conflict_stays_a_conflict_on_replay() -> None:
    api = LocalApplicationApi(_snapshot_with(pd.DataFrame()), revision_provider=lambda: "r1")
    command = RefreshDataCommand(idempotency_key="refresh-stale-001", expected_revision="old")
    assert api.execute(command).status is ApiStatus.CONFLICT
    assert api.execute(command).status is ApiStatus.CONFLICT


@pytest.mark.parametrize(
    ("holdings", "value", "currency", "status"),
    [
        # E023-N002: a EUR value is labelled EUR even when the holding's native currency differs.
        ({"etf_id": ["A"], "market_value_eur": [1000.0], "currency": ["USD"]}, 1000.0, "EUR", "available"),
        ({"etf_id": ["A"], "market_value": [900.0], "currency": ["USD"]}, 900.0, "USD", "available"),
        # E023-N004: a missing valuation is unavailable, never "available" with no value or label.
        ({"etf_id": ["A"], "market_value_eur": [float("nan")], "currency": ["USD"]}, None, None, "unavailable"),
        ({"etf_id": ["A"], "weight": [0.5]}, None, None, "unavailable"),
        ({"etf_id": ["A"], "market_value": [900.0]}, None, None, "unavailable"),
    ],
)
def test_e023_n002_n004_holding_value_carries_its_own_currency_or_is_unavailable(
    holdings: dict[str, list[object]], value: float | None, currency: str | None, status: str
) -> None:
    api = LocalApplicationApi(_snapshot_with(pd.DataFrame(holdings)))
    row = api.get_portfolios().items[0]
    assert (row.market_value, row.currency, row.status) == (value, currency, status)


def test_e023_n003_repeated_preview_keeps_the_terminal_audit_record(tmp_path: Path) -> None:
    preview = build_operation_preview(environment="paper", instrument_id="vwce", quantity=2)
    path = save_operation_record(preview, directory=tmp_path)
    done = preview.with_update(
        status="completed",
        result={"status": "completed", "message": "done"},
        audit={**preview.audit, "workflow_id": "wf-1"},
    )
    save_operation_record(done, directory=tmp_path)

    again = build_operation_preview(environment="paper", instrument_id="VWCE", quantity=2)
    assert again.operation_id == preview.operation_id
    save_operation_record(again, directory=tmp_path)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["status"] == "completed" and stored["audit"]["workflow_id"] == "wf-1"
    assert terminal_operation_record(preview.operation_id, directory=tmp_path) is not None


def test_e023_n003_non_terminal_record_is_still_updated(tmp_path: Path) -> None:
    preview = build_operation_preview(environment="paper", instrument_id="VWCE", quantity=2)
    save_operation_record(preview, directory=tmp_path)
    queued = preview.with_update(status="queued", result={"status": "queued", "message": "q"})
    path = save_operation_record(queued, directory=tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "queued"
    assert terminal_operation_record(preview.operation_id, directory=tmp_path) is None


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p["preview"].update(quantity=999.0),
        lambda p: p["preview"].update(instrument_id="OTHER"),
        lambda p: p["preview"].update(estimated_notional=1_000_000.0),
        lambda p: p["preview"]["assumptions"].append("A broker fill was requested."),
        lambda p: p["preview"].update(inputs_hash="op_forged"),
        lambda p: (p["preview"].pop("content_hash"), p["preview"].update(quantity=999.0)),
    ],
)
def test_e023_n005_preview_content_is_bound_to_its_inputs_hash(tamper) -> None:
    payload = json.loads(json.dumps(build_operation_preview(environment="paper", instrument_id="VWCE", quantity=2).to_payload()))
    validate_operation_record(payload, for_submission=True)
    tamper(payload)
    with pytest.raises(ValueError):
        validate_operation_record(payload)


def test_d117_n001_grant_is_scoped_to_instrument_time_and_a_single_use(tmp_path: Path) -> None:
    controls = PreTradeControls(tmp_path)
    at = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    proposal = _proposal(quantity_delta=1_001, source="grant-scope")
    proposal_id = str(proposal["proposal_id"])

    def grant(override_id: str, **extra: object) -> None:
        event = controls.grant_override(
            override_id, control="max_order_value", proposal_id=proposal_id, maker="maker", checker="checker",
            reason="one-order review", expires_at=at + timedelta(minutes=5), occurred_at=at, **extra,
        )
        assert event["event_type"] == "override_granted"

    # A grant for another instrument never authorises this order.
    grant("g-other", instrument_id="OTHERETF")
    assert _evaluate_paper(controls, proposal, at=at).allowed is False

    # A grant is not effective before it was recorded.
    grant("g-vwce", instrument_id="vwce")
    assert _evaluate_paper(controls, proposal, at=at - timedelta(minutes=1)).allowed is False

    # Inside its window it works exactly once.
    first = _evaluate_paper(controls, proposal, at=at + timedelta(minutes=1))
    assert first.allowed is True and first.override_id == "g-vwce"
    assert _evaluate_paper(controls, proposal, at=at + timedelta(minutes=2)).allowed is False
    # ... and the expiry instant itself is outside the window.
    grant("g-late", instrument_id="vwce")
    assert _evaluate_paper(controls, proposal, at=at + timedelta(minutes=5)).allowed is False


def test_d117_n001_grant_cannot_be_consumed_twice_by_a_concurrent_evaluation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controls = PreTradeControls(tmp_path)
    at = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    proposal = _proposal(quantity_delta=1_001, source="grant-race")
    controls.grant_override(
        "g-race", control="max_order_value", proposal_id=str(proposal["proposal_id"]), maker="maker",
        checker="checker", reason="one-order review", expires_at=at + timedelta(minutes=5), occurred_at=at,
    )
    original = PreTradeControls._find_override
    state = {"nested": False}

    def racing(self, *args, **kwargs):
        found = original(self, *args, **kwargs)
        if found is not None and not state["nested"]:
            state["nested"] = True  # a second evaluation consumes the grant before the first records its use
            assert _evaluate_paper(controls, proposal, at=at + timedelta(seconds=30)).allowed is True
        return found

    monkeypatch.setattr(PreTradeControls, "_find_override", racing)
    outer = _evaluate_paper(controls, proposal, at=at + timedelta(seconds=40))

    assert outer.allowed is False
    assert sum(event["event_type"] == "override_used" for event in controls.audit_events()) == 1
