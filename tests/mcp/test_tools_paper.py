"""Focused MCP portfolio and paper-lane contract checks."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.application import paper_manual_order
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.errors import ConfirmationError
from etf_cockpit.mcp.registry import CallContext, invoke_tool, use_call_context


class _NoSideEffects:
    def acquire(self, _name: str) -> None:
        return None


class _Session:
    def __init__(self, root: Path, snapshot: object | None = None) -> None:
        self.root = root
        self.snapshot = snapshot or SimpleNamespace()
        self.submissions: list[tuple[str, dict[str, object]]] = []

    def activity_publication(self):
        return nullcontext()

    def submit_workflow(self, workflow_type: str, **kwargs: object) -> str:
        self.submissions.append((workflow_type, dict(kwargs)))
        return "wf_fixture"


def _context(tmp_path: Path, session: _Session | None = None) -> CallContext:
    return CallContext(
        enabled_tiers=frozenset({"read", "edit", "paper"}),
        profile="full",
        client_id="test-client",
        confirmation_store=ConfirmationStore(b"c" * 32),
        audit=AuditRecorder(sink=lambda _record: None),
        session=session or _Session(tmp_path),
        rate_limiter=_NoSideEffects(),
    )


def test_every_write_tool_refuses_missing_confirm_token_before_side_effects(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    calls = {
        "portfolio_import_preview": {"path": str(tmp_path / "source.csv"), "dry_run": False},
        "portfolio_import_commit": {"preview_id": "preview_fixture", "dry_run": False},
        "portfolio_import_rollback": {"batch_id": "batch_fixture", "reason": "test", "dry_run": False},
        "journal_record": {"thesis": "test", "decision": "test", "evidence_refs": [], "dry_run": False},
        "paper_bots_run": {"as_of": now, "dry_run": False},
        "paper_replay_run": {"as_of": now, "dry_run": False},
        "paper_account_open": {"name": "test-account", "base_currency": "EUR", "starting_cash": 1000.0, "dry_run": False},
        "paper_order_preview": {"account_id": "test-account", "instrument_id": "ETF1", "side": "buy", "quantity": 1.0, "rationale": "test", "dry_run": False},
        "paper_order_place": {"proposal_id": "proposal_fixture", "instrument_id": "ETF1", "quantity": 1.0, "dry_run": False},
        "paper_order_cancel": {"order_id": "order_fixture", "reason": "test", "dry_run": False},
        "paper_kill_switch_activate": {"reason": "test", "dry_run": False},
    }
    context = _context(tmp_path)

    for name, arguments in calls.items():
        with pytest.raises(ConfirmationError):
            invoke_tool(name, arguments, context=context)

    assert not (tmp_path / "data").exists()


def test_registry_manual_preview_issues_token_and_place_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    calls = []
    writes = []

    def preview(**kwargs):
        calls.append(kwargs["persist"])
        return {"status": "proposal_ready", "proposal_id": "proposal-fixture", "quantity": 1.0, "execution_allowed": False}

    def persist(result, **kwargs):
        writes.append("proposal")
        return dict(result)

    monkeypatch.setattr(paper_manual_order, "preview_manual_paper_order", preview)
    monkeypatch.setattr(paper_manual_order, "persist_manual_paper_proposal", persist)
    monkeypatch.setattr(paper_manual_order, "accept_manual_paper_proposal", lambda **kwargs: writes.append("place") or {"order_id": "paper-fixture"})
    context = _context(tmp_path)
    arguments = {"account_id": "test-account", "instrument_id": "ETF1", "side": "buy", "quantity": 1.0, "rationale": "fixture"}
    staged = invoke_tool("paper_order_preview", arguments, context=context)
    assert isinstance(staged["confirm_token"], str)
    assert staged["preview"]["status"] == "confirmation_required"
    assert calls == [False] and writes == []

    place_args = {"proposal_id": "proposal-fixture", "instrument_id": "ETF1", "quantity": 1.0}
    for name, args in (("paper_order_preview", arguments), ("paper_order_place", place_args)):
        with pytest.raises(ConfirmationError):
            invoke_tool(name, {**args, "dry_run": False}, context=context)
        with pytest.raises(ConfirmationError):
            invoke_tool(name, {**args, "confirm_token": "invalid"}, context=context)
    assert calls == [False] and writes == []

    committed = invoke_tool("paper_order_preview", {**staged["preview"]["confirmation_arguments"], "confirm_token": staged["confirm_token"]}, context=context)
    assert calls == [False, True] and writes == ["proposal"]
    with pytest.raises(ConfirmationError):
        invoke_tool("paper_order_place", {**place_args, "dry_run": True, "confirm_token": committed["confirm_token"]}, context=context)
    assert writes == ["proposal"]
    placed = invoke_tool("paper_order_place", {**place_args, "confirm_token": committed["confirm_token"]}, context=context)
    assert placed["execution_allowed"] is False and writes == ["proposal", "place"]
    with pytest.raises(ConfirmationError):
        invoke_tool("paper_order_place", {**place_args, "confirm_token": committed["confirm_token"]}, context=context)
    assert writes == ["proposal", "place"]


def test_missing_manual_price_remains_unavailable_not_zero(tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_trading import PaperLedger

    PaperLedger(tmp_path, account_id="missing-account").open_account(initial_cash=1000.0)
    result = paper_manual_order.preview_manual_paper_order(
        root=tmp_path,
        snapshot=SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(by_id=lambda: {}))),
        account_id="missing-account",
        instrument_id="ETF1",
        side="buy",
        quantity=1.0,
        rationale="missing-data fixture",
    )

    assert result["status"] == "unavailable"
    assert result["price"] is None
    assert result["fee"] is None
    assert result["fx_rate"] is None
    assert result["unavailable_reason"]


def test_page_output_is_compact_and_has_cursor() -> None:
    from etf_cockpit.mcp.tools_paper import _page

    result = _page(
        [{"bot_id": str(index)} for index in range(40)],
        cursor=None,
        limit=5,
        filters={"as_of": None},
        key="bots",
    )

    assert len(result["bots"]) == 5
    assert result["total"] == 40
    assert isinstance(result["next_cursor"], str)


def test_paper_order_tool_calls_canonical_manual_order_service(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.mcp import tools_paper

    calls: list[dict[str, object]] = []

    def preview(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"status": "unavailable", "price": None, "unavailable_reason": "price_unavailable", "execution_allowed": False}

    monkeypatch.setattr(paper_manual_order, "preview_manual_paper_order", preview)
    session = _Session(tmp_path)
    with use_call_context(_context(tmp_path, session)):
        result = tools_paper.paper_order_preview(
            account_id="test-account", instrument_id="ETF1", side="buy", quantity=1.0,
            rationale="fixture", dry_run=True,
        )

    assert result["status"] == "unavailable"
    assert len(calls) == 1
    assert calls[0]["root"] == tmp_path
    assert calls[0]["persist"] is False


def test_paper_bot_status_pages_bot_rows(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.application import paper_bots_view
    from etf_cockpit.mcp import tools_paper

    monkeypatch.setattr(
        paper_bots_view,
        "load_paper_bots_view",
        lambda *_args, **_kwargs: {"forward": {"status": "available", "bots": [{"bot_id": str(index)} for index in range(35)]}},
    )
    with use_call_context(_context(tmp_path, _Session(tmp_path))):
        result = tools_paper.paper_bots_status(limit=4)

    assert len(result["forward"]["bots"]) == 4
    assert result["forward"]["total"] == 35
    assert result["forward"]["next_cursor"]


def test_paper_bot_run_submits_to_durable_session_service(tmp_path: Path) -> None:
    from etf_cockpit.mcp import tools_paper

    session = _Session(tmp_path)
    with use_call_context(_context(tmp_path, session)):
        result = tools_paper.paper_bots_run(dry_run=False)

    assert result["job_id"] == "wf_fixture"
    assert session.submissions[0][0] == "paper_bots_run"
    assert session.submissions[0][1]["input_payload"]["as_of"].endswith("+00:00")


@pytest.fixture
def manual_evidence(monkeypatch, tmp_path):
    """Real proposal store, ledger and price book; supplied cost capacity evidence."""
    from dataclasses import replace
    from datetime import timedelta
    import shutil
    import pandas as pd
    from etf_cockpit.core.config import load_config
    from etf_cockpit.core.paths import CONFIG_DIR
    from etf_cockpit.portfolio.paper_bots_execution import PRICE_FILE_RELATIVE, PriceBook
    from etf_cockpit.portfolio.paper_trading import PaperLedger
    from etf_cockpit.portfolio.proposal_policy import (
        REQUIRED_GATES, GateEvidence, ProposalRequest, build_proposal_decision,
        current_authority_policy_checksum, save_proposal_decision,
    )
    from etf_cockpit.signals.friction_edge import evaluate_friction_gate

    now = datetime.now(timezone.utc)
    known = now - timedelta(minutes=2)
    price_path = tmp_path / PRICE_FILE_RELATIVE
    price_path.parent.mkdir(parents=True)
    pd.DataFrame([{"instrument_id": "VWCE", "date": known.date().isoformat(),
                   "close": 100.0, "known_at": known.isoformat()}]).to_parquet(price_path)
    config_dir = tmp_path / "configs"
    config_dir.mkdir(exist_ok=True)
    shutil.copyfile(CONFIG_DIR / "paper_bots_execution_v1.yaml", config_dir / "paper_bots_execution_v1.yaml")
    config = load_config()
    snapshot = SimpleNamespace(config=config)
    ledger = PaperLedger(tmp_path, account_id="manual-test")
    ledger.open_account(initial_cash=10000.0)
    original_estimate = paper_manual_order.estimate_execution_cost
    def estimate(*args, **kwargs):
        return replace(original_estimate(*args, **kwargs), capacity_eur=100000.0)
    monkeypatch.setattr(paper_manual_order, "estimate_execution_cost", estimate)
    bar = PriceBook.from_root(tmp_path).last_bar("VWCE", now.date(), known_by=now)
    fingerprint = pd.util.hash_pandas_object(pd.Series([
        "VWCE", str(bar["date"]), str(bar["_known_at"]), 100.0,
    ]), index=False).astype("uint64").to_list()
    price_revision = "price:" + ":".join(str(item) for item in fingerprint)
    def store(**changes):
        values = dict(
            instrument_id="VWCE", current_quantity=0.0, target_quantity=10.0,
            strategy_id="strategy:paper_portfolio", strategy_stage="paper",
            model_id="model:paper", model_stage="paper", account_id="broker:paper_portfolio", account_stage="paper",
            optimiser_output_id="stored-optimiser-run", portfolio_revision=ledger.snapshot().ledger_hash,
            data_revision=price_revision, as_of=now - timedelta(seconds=1), expires_at=now + timedelta(minutes=10),
            authority_policy_checksum=current_authority_policy_checksum(),
            gate_evidence=tuple(GateEvidence(name, True, "Canonical fixture evidence passed.") for name in REQUIRED_GATES),
            approvals=("paper_simulation_review",),
            friction_gate=evaluate_friction_gate(150.0, order_value_eur=1000.0,
                cost_estimate=estimate(config, "VWCE", 1000.0).as_dict(), uncertainty_bps=25.0),
            event_calendar_path=tmp_path / "data" / "clean" / "event_calendar.parquet",
        )
        values.update(changes)
        decision = build_proposal_decision(ProposalRequest(**values))
        save_proposal_decision(decision, directory=tmp_path / "data" / "operations" / "proposals")
        return decision
    return SimpleNamespace(root=tmp_path, snapshot=snapshot, ledger=ledger, store=store, now=now)


def test_manual_preview_through_confirmed_place_uses_stored_policy_evidence(manual_evidence):
    from etf_cockpit.mcp import tools_paper
    fixture = manual_evidence
    source = fixture.store()
    context = _context(fixture.root, _Session(fixture.root, fixture.snapshot))
    args = dict(account_id="manual-test", instrument_id="VWCE", side="buy", quantity=10.0,
                rationale="Stored canonical evidence", evidence_refs=[source.proposal_id])
    with use_call_context(context):
        preview = tools_paper.paper_order_preview(**args)
    assert preview["status"] == "confirmation_required", preview.get("block_reasons", preview)
    committed = invoke_tool("paper_order_preview", {**preview["confirmation_arguments"],
        "confirm_token": preview["confirm_token"]}, context=context)
    data = committed
    assert data["status"] == "proposal_ready", data
    assert all(gate["passed"] for gate in data["gates"])
    assert data["proposal"]["input_material"]["optimiser_output_id"] == "stored-optimiser-run"
    assert (fixture.root / "data" / "operations" / "paper_order_terms" / f"{data['proposal_id']}.json").exists()
    placed = invoke_tool("paper_order_place", dict(proposal_id=data["proposal_id"], instrument_id="VWCE",
        quantity=10.0, dry_run=False, confirm_token=data["confirm_token"]), context=context)
    assert placed["journal_entry_id"]
    assert placed["fill"]["price"] == 100.0
    assert fixture.ledger.snapshot().positions[0].quantity == 10.0
    assert placed["execution_allowed"] is False


@pytest.mark.parametrize("history_kind", ["available", "missing", "future_known", "future_session", "insufficient", "zero"])
def test_manual_liquidity_uses_canonical_point_in_time_volume(manual_evidence, monkeypatch, history_kind):
    from datetime import timedelta
    import pandas as pd
    from etf_cockpit.portfolio.costs import average_daily_value_eur, estimate_execution_cost
    from etf_cockpit.portfolio.paper_bots_execution import PRICE_FILE_RELATIVE

    fixture = manual_evidence
    fixture.store()
    # Use the real cost service, bypassing this older fixture's capacity override.
    monkeypatch.setattr(paper_manual_order, "estimate_execution_cost", estimate_execution_cost)
    price_path = fixture.root / PRICE_FILE_RELATIVE
    current = pd.read_parquet(price_path)
    rows = []
    for offset in range(1, 21):
        # Keep history before the fixture bar even just after UTC midnight.
        day = datetime.fromisoformat(current.iloc[0]["known_at"]) - timedelta(days=offset)
        row = {"instrument_id": "VWCE", "date": day.date().isoformat(), "close": 100.0,
               "known_at": day.isoformat(), "volume": 100000.0}
        if history_kind == "future_known":
            row["known_at"] = (fixture.now + timedelta(days=1)).isoformat()
        if history_kind == "future_session":
            row["date"] = (fixture.now + timedelta(days=offset)).date().isoformat()
        if history_kind == "missing":
            row.pop("volume")
        if history_kind == "zero":
            row["volume"] = 0.0
        if history_kind != "insufficient" or offset <= 8:
            rows.append(row)
    # Other instruments must never supply VWCE's missing liquidity evidence.
    other = [{**row, "instrument_id": "OTHER", "volume": 100000.0} for row in rows]
    pd.concat([pd.DataFrame(rows + other), current], ignore_index=True).to_parquet(price_path)

    preview = paper_manual_order.preview_manual_paper_order(
        root=fixture.root, snapshot=fixture.snapshot, account_id="manual-test", instrument_id="VWCE",
        side="buy", quantity=10.0, rationale="Canonical liquidity regression", as_of=fixture.now,
    )
    liquidity = next(gate for gate in preview["gates"] if gate["gate_id"] == "liquidity")
    if history_kind == "available":
        expected = average_daily_value_eur([100000.0] * 19 + [None], [100.0] * 20)
        expected_cost = estimate_execution_cost(fixture.snapshot.config, "VWCE", 1000.0, adv_eur=expected)
        assert preview["cost_estimate"] == expected_cost.as_dict()
        assert liquidity["passed"] is True
        assert preview["status"] == "proposal_ready"
    else:
        assert liquidity["passed"] is False
        assert preview["status"] == "blocked"
        if history_kind != "zero":
            assert preview["cost_estimate"]["capacity_eur"] is None
            assert preview["cost_estimate"]["capacity_status"] == "unavailable_missing_adv"
    assert not fixture.ledger.orders()


@pytest.mark.parametrize("failure", ["missing", "confidence", "concentration", "quantity", "revision", "future", "expired", "corrupt"])
def test_manual_evidence_fails_closed(manual_evidence, failure):
    from datetime import timedelta
    from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, GateEvidence
    fixture = manual_evidence
    changes = {}
    if failure in {"confidence", "concentration"}:
        failed_id = "model_confidence" if failure == "confidence" else "concentration"
        changes["gate_evidence"] = tuple(GateEvidence(name, name != failed_id, "fixture") for name in REQUIRED_GATES)
    if failure == "quantity":
        changes["target_quantity"] = 20.0
    if failure == "revision":
        changes["portfolio_revision"] = "different-ledger"
    if failure == "future":
        changes["as_of"] = fixture.now + timedelta(minutes=1)
    if failure == "expired":
        changes.update(as_of=fixture.now - timedelta(hours=1), expires_at=fixture.now - timedelta(minutes=1))
    if failure != "missing":
        source = fixture.store(**changes)
        if failure == "corrupt":
            path = fixture.root / "data" / "operations" / "proposals" / f"{source.proposal_id}.json"
            path.write_text(path.read_text().replace("stored-optimiser-run", "forged-run"))
    result = paper_manual_order.preview_manual_paper_order(root=fixture.root, snapshot=fixture.snapshot,
        account_id="manual-test", instrument_id="VWCE", side="buy", quantity=10.0, rationale="fixture")
    assert result["status"] == "unavailable", result
    assert result["proposal"] is None
    assert result["unavailable_reason"] == "matching_canonical_proposal_evidence_unavailable_or_failing"
    assert not fixture.ledger.orders()


def test_lane_catalogue_and_confirmation_contracts_are_discovered():
    """Regression for the previously unverified catalogue and foundation coverage."""
    import inspect
    from etf_cockpit.mcp import tools_paper, tools_portfolio
    from etf_cockpit.mcp.registry import discover_tools
    expected = {
        "portfolio_overview": "read", "portfolio_risk": "read", "portfolio_candidate_analyse": "read",
        "portfolio_optimise": "read", "portfolio_reconcile": "read", "monthly_decision_pack": "read",
        "portfolio_import_preview": "edit", "portfolio_import_commit": "edit", "portfolio_import_rollback": "edit",
        "journal_entries": "read", "journal_record": "edit", "paper_bots_status": "read",
        "paper_bots_run": "paper", "paper_replay_run": "paper", "paper_account_open": "paper",
        "paper_portfolio": "read", "paper_controls_status": "read", "paper_order_preview": "paper",
        "paper_order_place": "paper", "paper_order_cancel": "paper", "paper_kill_switch_activate": "paper",
    }
    parameters = {
        "portfolio_overview": "as_of currency sections cursor limit",
        "portfolio_risk": "profile_id", "portfolio_candidate_analyse": "target_weights cash_weight notional",
        "portfolio_optimise": "objective constraints", "portfolio_reconcile": "as_of known_at",
        "monthly_decision_pack": "month", "portfolio_import_preview": "path source_format locale dry_run confirm_token",
        "portfolio_import_commit": "preview_id dry_run confirm_token",
        "portfolio_import_rollback": "batch_id reason dry_run confirm_token",
        "journal_entries": "instrument_id since cursor limit",
        "journal_record": "thesis decision evidence_refs alternatives confidence invalidation_rules review_date instrument_ids dry_run confirm_token",
        "paper_bots_status": "as_of cursor limit", "paper_bots_run": "as_of dry_run confirm_token",
        "paper_replay_run": "as_of survivorship export dry_run confirm_token",
        "paper_account_open": "name base_currency starting_cash dry_run confirm_token",
        "paper_portfolio": "account_id cursor limit", "paper_controls_status": "account_id",
        "paper_order_preview": "account_id instrument_id side quantity amount_eur target_weight rationale evidence_refs dry_run confirm_token",
        "paper_order_place": "proposal_id instrument_id quantity dry_run confirm_token",
        "paper_order_cancel": "order_id reason dry_run confirm_token",
        "paper_kill_switch_activate": "reason dry_run confirm_token",
    }
    idempotent_writes = {"portfolio_import_preview", "paper_order_preview", "paper_order_place",
                         "paper_order_cancel", "paper_kill_switch_activate"}
    specs = {spec.name: spec for spec in discover_tools()}
    actual = {name for module in (tools_paper, tools_portfolio) for name, value in vars(module).items()
              if hasattr(value, "__mcp_tool_spec__")}
    assert actual == set(expected)
    for name, tier in expected.items():
        spec = specs[name]
        assert spec.tier == tier
        assert list(inspect.signature(spec.function).parameters) == parameters[name].split()
        assert spec.annotations["idempotentHint"] is (tier == "read" or name in idempotent_writes)
        assert spec.annotations["openWorldHint"] is False
        assert spec.annotations["readOnlyHint"] is (tier == "read")
        assert spec.requires_confirmation is (tier != "read")
        if tier != "read":
            signature = inspect.signature(spec.function)
            assert signature.parameters["dry_run"].default is True
            assert signature.parameters["confirm_token"].default is None
            assert spec.annotations["destructiveHint"] is True


@pytest.mark.parametrize("failure", ["extra_gate", "event_policy", "friction"])
def test_manual_preview_keeps_other_canonical_blockers(manual_evidence, failure):
    from etf_cockpit.core.event_policy import EventBlockPolicy
    from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, GateEvidence
    fixture = manual_evidence
    changes = {}
    if failure == "extra_gate":
        changes["gate_evidence"] = (*tuple(GateEvidence(name, True, "fixture") for name in REQUIRED_GATES),
                                    GateEvidence("additional_risk", False, "Explicit additional risk block."))
    if failure == "event_policy":
        changes["event_policy"] = EventBlockPolicy(policy_id="fixture", version="1")
    fixture.store(**changes)
    if failure == "friction":
        path = fixture.root / "configs" / "paper_bots_execution_v1.yaml"
        path.write_text(path.read_text().replace("rule_expected_benefit_bps: 150.0", "rule_expected_benefit_bps: 0.0"))
    result = paper_manual_order.preview_manual_paper_order(root=fixture.root, snapshot=fixture.snapshot,
        account_id="manual-test", instrument_id="VWCE", side="buy", quantity=10.0, rationale="fixture")
    assert result["status"] == "blocked", result
    expected_gate = {"extra_gate": "additional_risk", "event_policy": "event_risk", "friction": "friction_edge"}[failure]
    assert any(gate["gate_id"] == expected_gate and gate["passed"] is False for gate in result["gates"])
    assert not fixture.ledger.orders()



def test_research_references_do_not_hide_available_canonical_manual_evidence(manual_evidence):
    fixture = manual_evidence
    source = fixture.store()
    result = paper_manual_order.preview_manual_paper_order(root=fixture.root, snapshot=fixture.snapshot,
        account_id="manual-test", instrument_id="VWCE", side="buy", quantity=10.0,
        rationale="fixture", evidence_refs=("research:finding-1",))
    assert result["status"] == "proposal_ready", result.get("block_reasons")
    assert result["evidence_refs"] == ["research:finding-1", source.proposal_id]



def test_monthly_tool_delegates_to_canonical_month_service(monkeypatch, tmp_path):
    from etf_cockpit.application import headless_session
    from etf_cockpit.mcp import tools_portfolio
    session = _Session(tmp_path)
    calls = []
    def project(snapshot, month):
        calls.append((snapshot, month))
        return {"month": month, "status": "partial", "execution_allowed": False}
    monkeypatch.setattr(headless_session, "load_monthly_decision_pack", project)
    with use_call_context(_context(tmp_path, session)):
        result = tools_portfolio.monthly_decision_pack("2026-08")
    assert calls == [(session.snapshot, "2026-08")]
    assert result["status"] == "partial"


@pytest.mark.parametrize("change", ["ledger", "friction"])
def test_manual_acceptance_rechecks_current_evidence(manual_evidence, change):
    from etf_cockpit.portfolio.paper_trading import PaperLedgerError
    fixture = manual_evidence
    fixture.store()
    preview = paper_manual_order.preview_manual_paper_order(root=fixture.root, snapshot=fixture.snapshot,
        account_id="manual-test", instrument_id="VWCE", side="buy", quantity=10.0,
        rationale="fixture", persist=True)
    assert preview["status"] == "proposal_ready", preview
    paper_manual_order.persist_manual_paper_proposal(preview, root=fixture.root)
    if change == "ledger":
        from etf_cockpit.trading.pre_trade_controls import PreTradeControls
        PreTradeControls(fixture.root, account_id="manual-test").activate_kill_switch(
            who="fixture", reason="changed account state", paper_ledger=fixture.ledger)
    else:
        path = fixture.root / "configs" / "paper_bots_execution_v1.yaml"
        path.write_text(path.read_text().replace("rule_expected_benefit_bps: 150.0", "rule_expected_benefit_bps: 0.0"))
    with pytest.raises(PaperLedgerError):
        paper_manual_order.accept_manual_paper_proposal(root=fixture.root,
            proposal_id=preview["proposal_id"], instrument_id="VWCE", quantity=10.0)
    assert not fixture.ledger.orders()
