from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import (
    ApiStatus,
    CancelWorkflowCommand,
    PaperAccountOpenRequest,
    PaperPositionMarkRequest,
    PageRequest,
    ProposalReviewRequest,
    QueryRequest,
    RefreshDataCommand,
    SubmitWorkflowCommand,
)
from etf_cockpit.app import state as state_module


def _snapshot() -> SimpleNamespace:
    records = [
        SimpleNamespace(id="ETF1", name="One", ticker="ONE", asset_class="equity", region="EU", currency="EUR", enabled=True),
        SimpleNamespace(id="ETF2", name="Two", ticker="TWO", asset_class="bond", region="US", currency="USD", enabled=False),
    ]
    universe = SimpleNamespace(etfs=records)
    config = SimpleNamespace(universe=universe)
    signal = SimpleNamespace(etf_id="ETF1", signal_date="2026-07-01", total_score=0.75, research_state="manual_review", confidence=0.8, status="ok")
    return SimpleNamespace(
        config=config,
        prices=pd.DataFrame({"etf_id": ["ETF1"], "adjusted_close": [100.0]}),
        holdings=pd.DataFrame({"etf_id": ["ETF1"], "current_weight": [1.0], "target_weight": [1.0], "market_value_eur": [1000.0]}),
        forecasts=pd.DataFrame({"etf_id": ["ETF1"], "model_name": ["baseline"], "horizon_days": [20], "expected_return": [0.02], "status": ["ok"]}),
        signals=[signal],
        universe_revision="revision-1",
    )


def test_queries_return_immutable_paginated_view_models_without_domain_frames() -> None:
    api = LocalApplicationApi(_snapshot)

    universe = api.query(QueryRequest(resource="universe", page=PageRequest(limit=1)))
    assert universe.total == 2
    assert len(universe.items) == 1
    assert universe.next_offset == 1
    assert universe.items[0].instrument_id == "ETF1"
    assert api.get_scores().items[0].state == "manual_review"
    assert api.get_forecasts().items[0].expected_return == pytest.approx(0.02)
    assert api.get_portfolios().items[0].market_value == pytest.approx(1000.0)
    assert api.query(QueryRequest(resource="proposals")).total == 0

    with pytest.raises(ValidationError):
        universe.items = ()


def test_typed_paper_account_exposes_provenanced_marks_and_orders(tmp_path: Path) -> None:
    api = LocalApplicationApi(_snapshot, root=tmp_path)

    opened = api.open_paper_account(PaperAccountOpenRequest(initial_cash=1_000))
    marked = api.mark_paper_position(
        PaperPositionMarkRequest(
            instrument_id="ETF1",
            adjusted_close=101,
            as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
            source_authority="test-adjusted-close",
            source_checksum="a" * 64,
        )
    )

    assert opened.status == "ready"
    assert marked.reconciliation_status == "ready"
    assert marked.execution_allowed is False
    assert api.get_paper_orders().total == 0


def test_typed_proposal_review_stays_inside_application_boundary(tmp_path, monkeypatch) -> None:
    import etf_cockpit.portfolio.proposal_policy as proposal_policy

    capabilities = tuple(
        SimpleNamespace(capability_id=capability_id, authority_stage=stage, availability="mandatory")
        for capability_id, stage in (
            ("strategy:manual_review", "research"),
            ("model:baseline", "research"),
            ("broker:paper_portfolio", "paper"),
        )
    )
    matrix = SimpleNamespace(
        diagnostic_mode=False,
        diagnostics=(),
        checksum="a" * 64,
        policy=SimpleNamespace(capabilities=capabilities),
    )
    monkeypatch.setattr(proposal_policy, "load_authority_matrix", lambda: matrix)
    api = LocalApplicationApi(_snapshot, root=tmp_path)

    view = api.review_proposal(
        ProposalReviewRequest(
            instrument_id="ETF1",
            current_quantity=0,
            target_quantity=1,
            strategy_id="strategy:manual_review",
            strategy_stage="research",
            model_id="model:baseline",
            model_stage="research",
            account_id="broker:paper_portfolio",
            account_stage="paper",
            as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
            expires_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            authority_policy_checksum="a" * 64,
        )
    )

    assert view.outcome == "manual_review"
    assert view.execution_allowed is False
    assert view.failed_gate_count == 9
    assert api.query(QueryRequest(resource="proposals")).total == 1


def test_paper_account_is_exposed_through_typed_application_boundary(tmp_path) -> None:
    api = LocalApplicationApi(_snapshot, root=tmp_path)

    opened = api.open_paper_account(PaperAccountOpenRequest(initial_cash=10_000))
    queried = api.query(QueryRequest(resource="paper"))

    assert opened.status == "ready"
    assert opened.execution_allowed is False
    assert opened.cash == pytest.approx(10_000)
    assert opened.reconciliation_status == "ready"
    assert queried.items[0].account_id == "local-paper"
    assert queried.items[0].equity == pytest.approx(10_000)


def test_typed_paper_boundary_keeps_named_accounts_separate(tmp_path: Path) -> None:
    api = LocalApplicationApi(_snapshot, root=tmp_path)

    opened = api.open_paper_account(PaperAccountOpenRequest(account_id="research-a", initial_cash=2_000))
    queried = api.get_paper(account_id="research-a")

    assert opened.account_id == "research-a"
    assert queried.items[0].account_id == "research-a"
    assert queried.items[0].cash == pytest.approx(2_000)
    assert api.get_paper(account_id="research-b").items[0].status == "unavailable"


def test_commands_are_idempotent_and_reject_stale_revisions() -> None:
    calls: list[str] = []

    def refresh(_command: object) -> dict[str, object]:
        calls.append("refresh")
        return {"message": "accepted"}

    api = LocalApplicationApi(_snapshot, revision_provider=lambda: "revision-1", command_handlers={"refresh_data": refresh})
    command = RefreshDataCommand(idempotency_key="refresh-001", expected_revision="revision-1")
    first = api.execute(command)
    replay = api.execute(command)

    assert first.status is ApiStatus.ACCEPTED
    assert replay.status is ApiStatus.REPLAYED
    assert replay.replayed is True
    assert calls == ["refresh"]

    reused = api.execute(RefreshDataCommand(idempotency_key="refresh-001", force_sample=True))
    assert reused.status is ApiStatus.CONFLICT
    assert reused.error_code == "idempotency_key_reused"

    stale = api.execute(RefreshDataCommand(idempotency_key="refresh-002", expected_revision="old"))
    assert stale.status is ApiStatus.CONFLICT
    assert stale.error_code == "revision_conflict"
    assert calls == ["refresh"]


def test_workflow_commands_use_the_single_local_scheduler_and_are_cancelable(tmp_path) -> None:
    api = LocalApplicationApi(_snapshot, root=tmp_path)
    submitted = api.execute(
        SubmitWorkflowCommand(
            idempotency_key="workflow-001",
            workflow_type="local_check",
            label="Local check",
            job_keys=("check",),
        )
    )

    assert submitted.status is ApiStatus.ACCEPTED
    assert submitted.resource_id
    details = dict(submitted.details)
    assert details["profile"]
    assert int(details["memory_mb"]) > 0
    assert int(details["disk_mb"]) > 0
    jobs = api.get_jobs()
    assert jobs.total == 1
    assert jobs.items[0].workflow_id == submitted.resource_id

    cancelled = api.execute(CancelWorkflowCommand(idempotency_key="cancel-001", workflow_id=submitted.resource_id))
    assert cancelled.status is ApiStatus.ACCEPTED
    assert api.get_jobs().items[0].status == "cancelled"


def test_app_state_runtime_uses_persisted_profile_for_submission_and_claim(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import onboarding as onboarding_module
    from etf_cockpit.app.state import AppState

    monkeypatch.setattr(state_module, "ROOT", tmp_path)
    monkeypatch.setattr(
        onboarding_module,
        "load_onboarding",
        lambda _root=None: SimpleNamespace(hardware_profile="minimum"),
    )

    state = AppState(snapshot=_snapshot(), selected_etf="ETF1")
    scheduler = state.application_api._scheduler
    assert scheduler.root == tmp_path.resolve()
    assert scheduler.resource_policy.requested_profile == "minimum"

    submitted = state.application_api.execute(
        SubmitWorkflowCommand(
            idempotency_key="state-workflow-001",
            workflow_type="local_check",
            label="State local check",
            job_keys=("check",),
        )
    )
    assert submitted.status is ApiStatus.ACCEPTED
    claimed = scheduler.claim_next()
    assert claimed is not None
    assert claimed.resources["profile"] == "minimum"


def test_jobs_page_consumes_application_api_view_models() -> None:
    from etf_cockpit.app.pages.jobs import jobs_page

    source = inspect.getsource(jobs_page)
    assert "state.application_api" in source
    assert "get_jobs" in source
    assert "SubmitWorkflowCommand" in source


def test_generated_application_api_schema_is_present_and_non_executable() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs" / "architecture" / "application-api-schema.json").read_text(encoding="utf-8"))

    assert schema["schema_version"] == "application_api.v1"
    assert schema["transport"] == "in_process"
    assert schema["execution_allowed"] is False
    assert {"PageRequest", "PageView", "SubmitWorkflowCommand", "JobViewModel"}.issubset(schema["models"])
