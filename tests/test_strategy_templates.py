from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.app.pages import strategy_builder
from etf_cockpit.application.strategy_templates import StrategyTemplateFacade
from etf_cockpit.signals import strategy_templates as strategy_templates_module
from etf_cockpit.signals.strategy_templates import (
    TEMPLATE_IDS,
    compute_template_matches,
    load_strategy_templates,
    validate_strategy_authority,
)
from etf_cockpit.portfolio.benchmark_reference_contract import load_canonical_benchmark_registry


def _texts(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for attribute in ("controls", "content"):
        child = getattr(control, attribute, None)
        children = child if isinstance(child, (list, tuple)) else (child,) if child is not None else ()
        for item in children:
            values.extend(_texts(item))
    return values


def test_all_nine_templates_have_version_hash_and_benchmark() -> None:
    templates = load_strategy_templates()
    assert tuple(template.template_id for template in templates) == TEMPLATE_IDS
    assert all(template.version and len(template.definition_hash) == 64 and template.benchmark for template in templates)
    assert all(template.execution_allowed is False for template in templates)
    canonical_ids = {item.benchmark_id for item in load_canonical_benchmark_registry().benchmarks}
    assert {template.benchmark for template in templates} <= canonical_ids
    assert all(set(template.stages) == {"analyse", "portfolio", "backtest", "paper", "draft_order", "canary", "bounded_automatic"} for template in templates)


def test_rejection_boundaries_forbidden_types_and_execution_authority() -> None:
    with pytest.raises(ValueError, match="forbidden strategy type"):
        validate_strategy_authority("martingale")
    with pytest.raises(ValueError, match="execution authority"):
        validate_strategy_authority("trend_following", execution_allowed=True)


def test_enable_disable_persists_across_reload(tmp_path) -> None:
    path = tmp_path / "configs" / "strategy_templates_state.json"
    first = StrategyTemplateFacade(state_path=path)
    first.set_enabled("trend_following", False)
    second = StrategyTemplateFacade(state_path=path)
    assert second.is_enabled("trend_following") is False
    assert second.is_enabled("etf_dual_momentum") is True


def test_fixed_snapshot_matches_are_deterministic_and_context_only_has_no_actions() -> None:
    snapshot = [
        {"instrument_id": "ETF-1", "asset_type": "etf", "momentum": 0.2, "momentum_status": "available", "trend": 0.1, "trend_status": "available", "news_context": "source-linked note", "known_at": "2026-01-01T00:00:00Z", "available_at": "2026-01-01T00:00:00Z"},
        {"instrument_id": "STOCK-1", "asset_type": "stock", "quality": 0.8, "quality_momentum_status": "available", "value": 0.7, "momentum": 0.3, "momentum_status": "available", "known_at": "2026-01-01T00:00:00Z", "available_at": "2026-01-01T00:00:00Z"},
    ]
    first = compute_template_matches(snapshot, decision_time="2026-01-02T00:00:00Z")
    second = compute_template_matches(snapshot, decision_time="2026-01-02T00:00:00Z")
    assert first == second
    context_matches = [item for item in first if item.template_id == "news_context_watchlist"]
    assert context_matches and all(item.actions == () and item.execution_allowed is False for item in context_matches)


def test_missing_malformed_and_future_availability_fail_closed() -> None:
    snapshot = [
        {"instrument_id": "MISSING", "asset_type": "etf", "momentum": 1, "momentum_status": "available", "trend": 1, "trend_status": "available"},
        {"instrument_id": "MALFORMED", "asset_type": "etf", "momentum": 1, "momentum_status": "available", "trend": 1, "trend_status": "available", "known_at": "not-a-time", "available_at": "2026-01-01"},
        {"instrument_id": "FUTURE", "asset_type": "etf", "momentum": 1, "momentum_status": "available", "trend": 1, "trend_status": "available", "known_at": "2026-01-03", "available_at": "2026-01-03"},
    ]
    assert compute_template_matches(snapshot, decision_time="2026-01-02") == ()


def test_zero_valued_canonical_evidence_does_not_match() -> None:
    snapshot = [{"instrument_id": "ZERO", "asset_type": "etf", "momentum": 0, "momentum_status": "available", "trend": 0, "trend_status": "available", "known_at": "2026-01-01", "available_at": "2026-01-01"}]
    assert compute_template_matches(snapshot, decision_time="2026-01-02") == ()


def test_matches_delegate_to_canonical_algorithm_outputs(monkeypatch) -> None:
    calls: list[str] = []

    def momentum(_history, columns):
        calls.append("momentum")
        return pd.Series({columns[0]: 1.0})

    def trend(_config, _history, columns):
        calls.append("trend")
        return pd.Series({columns[0]: 1.0})

    def quality(_evidence, columns, *, mode):
        calls.append(mode)
        return pd.Series({columns[0]: 1.0})

    monkeypatch.setattr(strategy_templates_module, "momentum_weights", momentum)
    monkeypatch.setattr(strategy_templates_module, "trend_weights", trend)
    monkeypatch.setattr(strategy_templates_module, "quality_momentum_weights", quality)
    history = pd.DataFrame({"ALGO": [1.0] * 200})
    evidence = pd.DataFrame({"instrument_id": ["ALGO"], "status": ["available"], "composite_score": [1.0]})
    snapshot = [{"instrument_id": "ALGO", "asset_type": "etf", "price_history": history, "config": object(), "quality_momentum_evidence": evidence, "known_at": "2026-01-01", "available_at": "2026-01-01"}]
    matches = compute_template_matches(snapshot, decision_time="2026-01-02")
    assert {item.template_id for item in matches} >= {"etf_dual_momentum", "trend_following"}
    assert "momentum" in calls and "trend" in calls


def test_invalid_benchmark_and_stage_policy_are_rejected(tmp_path) -> None:
    source = Path(__file__).resolve().parents[1] / "configs" / "strategy_templates_v1.yaml"
    text = source.read_text(encoding="utf-8")
    invalid_benchmark = tmp_path / "invalid-benchmark.yaml"
    invalid_benchmark.write_text(text.replace("benchmark: benchmark:ftse-all-world", "benchmark: benchmark:missing", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown canonical benchmark"):
        load_strategy_templates(invalid_benchmark)
    invalid_stages = tmp_path / "invalid-stages.yaml"
    invalid_stages.write_text(text.replace("stages: {analyse: supported, portfolio: supported", "stages: {analyse: review_only, portfolio: supported", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="stages do not match"):
        load_strategy_templates(invalid_stages)


def test_strategy_builder_page_renders_registry_and_matches_from_facade(tmp_path, monkeypatch) -> None:
    facade = StrategyTemplateFacade(state_path=tmp_path / "state.json")
    monkeypatch.setattr(strategy_builder, "StrategyTemplateFacade", lambda: facade)
    state = SimpleNamespace(snapshot=SimpleNamespace(signals=[{"instrument_id": "ETF-1", "asset_type": "etf", "trend": 0.2}]))
    page = SimpleNamespace(update=lambda: None)
    rendered = strategy_builder.strategy_builder_page(page, state)
    rendered_text = " ".join(_texts(rendered.body))
    assert rendered.chrome.title == "Strategy Builder"
    assert "ETF dual momentum" in rendered_text
    assert "execution_allowed=false" in rendered_text
