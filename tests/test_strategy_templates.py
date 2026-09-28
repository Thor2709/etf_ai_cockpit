from __future__ import annotations

from types import SimpleNamespace

import pytest

from etf_cockpit.app.pages import strategy_builder
from etf_cockpit.application.strategy_templates import StrategyTemplateFacade
from etf_cockpit.signals.strategy_templates import (
    TEMPLATE_IDS,
    compute_template_matches,
    load_strategy_templates,
    validate_strategy_authority,
)


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
        {"instrument_id": "ETF-1", "asset_type": "etf", "momentum": 0.2, "trend": 0.1, "news_context": "source-linked note"},
        {"instrument_id": "STOCK-1", "asset_type": "stock", "quality": 0.8, "value": 0.7, "momentum": 0.3},
    ]
    first = compute_template_matches(snapshot)
    second = compute_template_matches(snapshot)
    assert first == second
    context_matches = [item for item in first if item.template_id == "news_context_watchlist"]
    assert context_matches and all(item.actions == () and item.execution_allowed is False for item in context_matches)


def test_strategy_builder_page_renders_registry_and_matches_from_facade(tmp_path, monkeypatch) -> None:
    facade = StrategyTemplateFacade(state_path=tmp_path / "state.json")
    monkeypatch.setattr(strategy_builder, "StrategyTemplateFacade", lambda: facade)
    state = SimpleNamespace(snapshot=SimpleNamespace(signals=[{"instrument_id": "ETF-1", "asset_type": "etf", "trend": 0.2}]))
    page = SimpleNamespace(update=lambda: None)
    rendered = strategy_builder.strategy_builder_page(page, state)
    rendered_text = " ".join(_texts(rendered))
    assert "Strategy builder" in rendered_text
    assert "ETF dual momentum" in rendered_text
    assert "execution_allowed=false" in rendered_text
