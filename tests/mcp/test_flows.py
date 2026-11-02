"""End-to-end MCP flow checks against the registry and an isolated fixture root.

Open defaults: fixture calls use a 25-row page and cap each response at 8,000
tokens (approximately 32,000 JSON characters). Network refresh and live execution
are disabled; external web research is represented by owner-supplied evidence.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext

import pytest

from etf_cockpit.application import mcp_universe_ops
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.errors import ConfirmationError, MCPToolError
from etf_cockpit.mcp.registry import CallContext, RateLimiter, invoke_tool


class FixtureSession:
    """Minimal headless session rooted in a test-owned directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=())))
        self.jobs: dict[str, dict[str, object]] = {}

    def submit_workflow(self, workflow_type: str, **kwargs: object) -> object:
        job_id = f"fixture-{len(self.jobs) + 1}"
        self.jobs[job_id] = {"job_id": job_id, "workflow_type": workflow_type, "status": "completed", **kwargs}
        return SimpleNamespace(resource_id=job_id)

    def get_workflow(self, job_id: str):
        return self.jobs.get(job_id)

    def activity_publication(self):
        return nullcontext()


@pytest.fixture
def flow_context(tmp_path: Path) -> CallContext:
    root = tmp_path / "fixture-root"
    root.mkdir()
    (root / "fixture.json").write_text(
        (Path(__file__).parent / "fixtures" / "flow_root.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return CallContext(
        enabled_tiers=frozenset({"read", "edit", "read_job", "research", "paper"}),
        profile="full", client_id="flow-test", session=FixtureSession(root),
        confirmation_store=ConfirmationStore(b"c" * 32),
        audit=AuditRecorder(sink=lambda _record: None),
        rate_limiter=RateLimiter(path=root / "rate-limits.sqlite3"),
    )


def _compact(result: object) -> None:
    assert len(json.dumps(result, default=str, separators=(",", ":"))) <= 32_000
    assert "execution_allowed" not in result or result["execution_allowed"] is False  # type: ignore[operator]


def test_flow_1_add_instrument_refresh_and_explain(flow_context: CallContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import api as api_module, forecast_run, score_explain as score_explain_module
    from etf_cockpit.mcp import tools_forecast, tools_scores
    monkeypatch.setattr(tools_forecast, "ROOT", flow_context.session.root)
    monkeypatch.setattr(tools_scores, "ROOT", flow_context.session.root)
    calls: list[str] = []
    monkeypatch.setattr(mcp_universe_ops, "lookup_instrument_view", lambda _identifier: calls.append("lookup") or {"chosen": {"instrument_id": "FIXTURE1"}, "in_universe": False, "proposed_fields": {}})
    monkeypatch.setattr(mcp_universe_ops, "preview_universe_change", lambda *_a, **_k: calls.append("preview") or {"valid": True, "expected_revision": "R1"})
    monkeypatch.setattr(mcp_universe_ops, "commit_universe_change", lambda *_a, **_k: calls.append("commit") or {"revision": "R2", "execution_allowed": False})

    lookup = invoke_tool("instrument_lookup", {"identifier": "Fixture One"}, context=flow_context)
    staged = invoke_tool("universe_change_preview", {"action": "add", "instrument_id": "FIXTURE1", "fields": {"instrument_id": "FIXTURE1"}}, context=flow_context)
    assert staged["confirm_token"]
    commit_args = {"action": "add", "instrument_id": "FIXTURE1", "fields": {"instrument_id": "FIXTURE1"}, "expected_revision": "R1"}
    with pytest.raises(ConfirmationError):
        invoke_tool("universe_change_commit", {**commit_args, "confirm_token": "invalid"}, context=flow_context)
    preview = invoke_tool("universe_change_commit", commit_args, context=flow_context)
    committed = invoke_tool("universe_change_commit", {**commit_args, "confirm_token": preview["confirm_token"]}, context=flow_context)
    assert lookup["in_universe"] is False and committed["revision"] == "R2"
    assert calls == ["lookup", "preview", "preview", "commit"]

    refresh_args = {"source": "prices", "years": 1, "rescore": False}
    refresh_preview = invoke_tool("data_refresh", refresh_args, context=flow_context)
    with pytest.raises(ConfirmationError):
        invoke_tool("data_refresh", {**refresh_args, "confirm_token": "invalid"}, context=flow_context)
    refresh = invoke_tool("data_refresh", {**refresh_args, "confirm_token": refresh_preview["confirm_token"]}, context=flow_context)
    job = invoke_tool("job_status", {"job_id": refresh["job_id"]}, context=flow_context)

    class FakeApi:
        def __init__(self, *_args, **_kwargs): pass
        def execute(self, _command): return SimpleNamespace(status=api_module.ApiStatus.ACCEPTED, resource_id="fixture-pipeline")
        def run_next_job(self, _handler, *, workflow_id): return SimpleNamespace(status="completed", outputs={"steps": ["scores"], "execution_allowed": False})

    monkeypatch.setattr(api_module, "LocalApplicationApi", FakeApi)
    monkeypatch.setattr(forecast_run, "pipeline_request_payload", lambda *_args: {"fixture": True})
    monkeypatch.setattr(forecast_run, "run_pipeline_steps", lambda *_args, **_kwargs: {"steps": ["scores"], "execution_allowed": False})
    pipeline = invoke_tool("pipeline_run", {"steps": ["scores"], "live_optional_models": False}, context=flow_context)
    monkeypatch.setattr(score_explain_module, "explain_score", lambda *_args: {"instrument_id": "FIXTURE1", "score": None, "coverage": "unavailable"})
    explained = invoke_tool("score_explain", {"instrument_id": "FIXTURE1"}, context=flow_context)
    for result in (lookup, staged, preview, committed, refresh_preview, refresh, job, pipeline, explained): _compact(result)


def test_flow_2_rank_research_and_store_confirmed_findings(flow_context: CallContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import research_evidence, score_views
    from etf_cockpit.mcp import tools_forecast, tools_research, tools_scores
    from etf_cockpit.application import instrument_detail_loader, score_explain as score_explain_module

    monkeypatch.setattr(tools_scores, "ROOT", flow_context.session.root)
    monkeypatch.setattr(tools_forecast, "ROOT", flow_context.session.root)
    monkeypatch.setattr(tools_research, "ROOT", flow_context.session.root)
    monkeypatch.setattr(score_explain_module, "explain_score", lambda *_args: {"instrument_id": "FIXTURE1", "score": None, "coverage": "unavailable"})
    monkeypatch.setattr(instrument_detail_loader, "load_instrument_detail", lambda *_args: {"instrument_id": "FIXTURE1", "sections": {"overview": {"status": "available"}, "score": {"status": "unavailable", "value": None}}})

    score = SimpleNamespace(display_id="FIXTURE1", rank=1, final_score_10=None, final_label="unavailable", final_action="unavailable", name="Fixture One", asset_type="STOCK", one_line_reason="score evidence unavailable")
    monkeypatch.setattr(score_views, "published_scores", lambda *_a, **_k: [score])
    monkeypatch.setattr(score_views, "_rank_sort_key", lambda _score: 1)
    monkeypatch.setattr(research_evidence, "research_revision", lambda _root: "R1", raising=False)
    monkeypatch.setattr(research_evidence, "research_revision", lambda _root: "R1")
    writes: list[object] = []
    monkeypatch.setattr(research_evidence, "record_research_findings", lambda items, **_k: writes.extend(items) or ["finding-1"])

    ranked = invoke_tool("scores_ranked", {"top_n": 5, "include_gated": True}, context=flow_context)
    explained = invoke_tool("score_explain", {"instrument_id": "FIXTURE1"}, context=flow_context)
    detail = invoke_tool("instrument_detail", {"instrument_id": "FIXTURE1", "sections": ["overview", "score"]}, context=flow_context)
    forecasts = invoke_tool("forecast_get", {"instrument_ids": ["FIXTURE1"], "horizons": [30]}, context=flow_context)
    item = {"subject": "FIXTURE1", "kind": "web", "claim": "Fixture claim", "stance": 0.1, "confidence": 0.5, "source_url": "https://example.invalid/fixture", "source_title": "Fixture", "published_at": "2026-11-01T00:00:00Z", "retrieved_at": "2026-11-02T00:00:00Z", "excerpt": "Fixture evidence"}
    preview = invoke_tool("research_findings", {"prepare_items": [item]}, context=flow_context)
    with pytest.raises(ConfirmationError):
        invoke_tool("research_record_findings", {"items": [item], "expected_revision": "R1", "confirm_token": "invalid"}, context=flow_context)
    stored = invoke_tool("research_record_findings", {"items": [item], "expected_revision": "R1", "confirm_token": preview["confirm_token"]}, context=flow_context)
    assert ranked["rows"][0]["score_10"] is None
    assert stored["ids"] == ["finding-1"] and len(writes) == 1
    for result in (ranked, explained, detail, forecasts, preview, stored): _compact(result)


def test_flow_3_candidate_assessment_is_provisional_and_local(flow_context: CallContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.mcp import tools_scores
    monkeypatch.setattr(tools_scores, "ROOT", flow_context.session.root)
    monkeypatch.setattr(mcp_universe_ops, "lookup_instrument_view", lambda _identifier: {"chosen": None, "in_universe": False, "proposed_fields": {}})

    class Service:
        def __init__(self, _config: object) -> None: pass
        def run_stored_candidate_analysis(self, **_kwargs: object) -> dict[str, object]:
            return {"status": "unavailable", "price": None, "label": "provisional, not ranked"}

    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (flow_context.session, flow_context.session.snapshot))
    monkeypatch.setattr("etf_cockpit.application.data_service.DataService", Service)
    monkeypatch.setattr(tools_scores, "_job", lambda _root, _name, _label, _payload, run, **_kwargs: {"result": run(None), "execution_allowed": False})
    lookup = invoke_tool("instrument_lookup", {"identifier": "UNLISTED"}, context=flow_context)
    candidate = invoke_tool("candidate_analyse", {"identifiers": ["UNLISTED"], "years": 1, "allow_network": False}, context=flow_context)
    assert lookup["in_universe"] is False
    assert candidate["result"]["status"] == "unavailable" and candidate["result"]["price"] is None
    _compact(lookup); _compact(candidate)


@pytest.mark.xfail(strict=True, reason="paper_order_preview is a write-tier tool without a registry preview callback, so invoke_tool refuses the intended preview before its handler (tools_paper.py:255)")
def test_flow_4_paper_order_requires_confirmation_and_stays_paper(flow_context: CallContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import paper_manual_order

    writes: list[str] = []
    monkeypatch.setattr(paper_manual_order, "preview_manual_paper_order", lambda **_kwargs: {"status": "proposal_ready", "proposal_id": "proposal-fixture", "quantity": 1.0, "price": None, "execution_allowed": False})
    monkeypatch.setattr(paper_manual_order, "persist_manual_paper_proposal", lambda _preview, **_kwargs: {"status": "proposal_ready", "proposal_id": "proposal-fixture", "quantity": 1.0, "price": None, "execution_allowed": False})
    monkeypatch.setattr(paper_manual_order, "accept_manual_paper_proposal", lambda **_kwargs: writes.append("place") or {"order_id": "paper-order-fixture"})
    preview_args = {"account_id": "fixture-account", "instrument_id": "FIXTURE1", "side": "buy", "quantity": 1.0, "rationale": "fixture evidence"}
    preview = invoke_tool("paper_order_preview", preview_args, context=flow_context)
    tokenized = invoke_tool("paper_order_place", {"proposal_id": "proposal-fixture", "instrument_id": "FIXTURE1", "quantity": 1.0}, context=flow_context)
    with pytest.raises(ConfirmationError):
        invoke_tool("paper_order_place", {"proposal_id": "proposal-fixture", "instrument_id": "FIXTURE1", "quantity": 1.0, "confirm_token": "invalid"}, context=flow_context)
    assert tokenized["preview"]["status"] == "confirmation_required" and writes == []
    placed = invoke_tool("paper_order_place", {"proposal_id": "proposal-fixture", "instrument_id": "FIXTURE1", "quantity": 1.0, "confirm_token": tokenized["confirm_token"]}, context=flow_context)
    assert placed["execution_allowed"] is False and writes == ["place"]
    _compact(preview); _compact(tokenized); _compact(placed)


@pytest.mark.xfail(strict=True, reason="tools_data.data_health reads DataHealthReport.as_of, while the canonical report exposes as_of_date; flow 5 stops at freshness lookup (tools_data.py:85, mcp_data_views.py:27)")
def test_flow_5_status_gates_and_alerts_are_compact(flow_context: CallContext, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import status_views
    from etf_cockpit.mcp import tools_ops

    monkeypatch.setattr(status_views, "build_cockpit_status", lambda **_kwargs: {"freshness": "unavailable", "execution_allowed": False})
    monkeypatch.setattr(status_views, "build_gate_status", lambda **_kwargs: {"status": "unavailable", "checks": []})
    for name, args in (("cockpit_status", {}), ("paper_bots_status", {}), ("data_health", {"limit": 5}), ("data_readiness", {"start": date(2026, 11, 1), "end": date(2026, 11, 2)}), ("gates_status", {}), ("alerts_list", {"limit": 5})):
        result = invoke_tool(name, args, context=flow_context)
        _compact(result)


@pytest.mark.xfail(strict=True, reason="section 6 flow 6 requires ticket_preview, ticket_export and fill_record_preview/fill_record_commit, which are absent from the MCP registry; owner ADR-gated ticket/fill lane is unimplemented")
def test_flow_6_owner_ticket_export_and_fill_record(flow_context: CallContext) -> None:
    preview = invoke_tool("ticket_preview", {"instrument_id": "FIXTURE1"}, context=flow_context)
    exported = invoke_tool("ticket_export", {"confirm_token": preview["confirm_token"]}, context=flow_context)
    fill = invoke_tool("fill_record_preview", {"instrument_id": "FIXTURE1"}, context=flow_context)
    invoke_tool("fill_record_commit", {"confirm_token": fill["confirm_token"]}, context=flow_context)
    reconciled = invoke_tool("portfolio_reconcile", {"as_of": date(2026, 11, 2), "known_at": date(2026, 11, 2)}, context=flow_context)
    for result in (preview, exported, fill, reconciled): _compact(result)
