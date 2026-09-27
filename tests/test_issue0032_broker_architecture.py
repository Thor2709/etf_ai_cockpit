"""Acceptance evidence for ISSUE-0032's future-only execution boundary."""

from __future__ import annotations

from pathlib import Path

from etf_cockpit.app.pages.system_map import system_map_page
from etf_cockpit.app.state import AppState
from etf_cockpit.governance.product_scope import load_strategy_scope
from etf_cockpit.services import build_snapshot


ROOT = Path(__file__).resolve().parents[1]
FUTURE_DOCS = ROOT / "docs" / "architecture" / "future"


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(
        str(getattr(item, "value", "") or getattr(item, "text", ""))
        for item in _walk(control)
    )


def test_future_architecture_documents_cover_issue_requirements() -> None:
    documents = {
        path.name: path.read_text(encoding="utf-8").casefold()
        for path in sorted(FUTURE_DOCS.glob("*.md"))
    }
    assert set(documents) == {
        "broker_adapter_contract.md",
        "execution_scope_and_approval.md",
        "source_of_truth_and_reconciliation.md",
    }
    text = "\n".join(documents.values())
    for phrase in (
        "future-only",
        "paper mode first",
        "order preview",
        "explicitly confirm",
        "maximum order value",
        "position size",
        "daily turnover",
        "daily loss",
        "drawdown kill switch",
        "cooldown",
        "market-hours",
        "stale-data",
        "news/event",
        "audit log",
        "emergency disable",
        "llm",
        "model-only",
        "same id",
        "identical immutable payload",
        "payload or checksum difference",
        "official broker api",
        "block new submission",
        "local ledger owns local intents",
        "official broker api owns external account",
        "divergence",
        "automated retries",
        "execution_allowed=false",
        "executable_authority=false",
    ):
        assert phrase in text, phrase

    contract = documents["broker_adapter_contract.md"]
    numbered_stages = tuple(
        contract.index(f"{index}. **`{stage}`**")
        for index, stage in enumerate(
            ("paper", "broker_read_only", "draft_order", "capped_automatic"),
            start=1,
        )
    )
    assert numbered_stages == tuple(sorted(numbered_stages))


def test_system_map_exposes_future_only_architecture_without_action_control() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    text = _text(system_map_page(None, state)).casefold()

    for phrase in (
        "future execution",
        "not installed",
        "paper mode first",
        "research · shadow_proposal · paper · broker_read_only · draft_order · capped_automatic · disabled",
        "order previews",
        "max order value",
        "position size",
        "daily turnover",
        "daily loss",
        "drawdown kill switch",
        "cooldowns",
        "market-hours checks",
        "stale-data block",
        "news/event block",
        "explicit human confirmation",
        "immutable audit log",
        "emergency disable",
        "llm or model-only authority is prohibited",
        "execution_allowed=false",
        "order_submission=disabled",
    ):
        assert phrase in text, phrase
    assert "enable trading" not in text


def test_strategy_scope_rejects_future_execution_stages() -> None:
    loaded = load_strategy_scope()
    assert loaded.policy is not None
    policy = loaded.policy
    assert policy.execution_allowed is False
    assert policy.executable_authority is False

    for profile in policy.capability_profiles:
        for stage in ("draft_order", "canary", "bounded_automatic"):
            assert profile.cells[stage].state in {"unavailable", "rejected"}
            assert profile.cells[stage].execution_allowed is False

    future = next(item for item in policy.entries if item.strategy_id == "future_broker_architecture")
    assert future.lifecycle == "future_only"
    assert future.execution_authority == "none"
    assert future.execution_allowed is False


def test_current_production_static_execution_boundary_is_clean() -> None:
    from etf_cockpit.governance.static_checks import run_static_execution_boundary_check

    report = run_static_execution_boundary_check(ROOT)
    assert report.result == "pass"
    assert report.execution_allowed is False
    assert report.executable_authority is False
    assert not report.violations
