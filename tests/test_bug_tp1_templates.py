"""Bughunt C (#974): strategy template matching regression tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.application.strategy_templates import StrategyTemplateFacade
from etf_cockpit.core.types import ComponentScores, SignalResult
from etf_cockpit.signals.strategy_templates import (
    TEMPLATE_IDS,
    compute_template_matches,
    load_strategy_templates,
)

_KNOWN = {"known_at": "2026-01-01T00:00:00Z", "available_at": "2026-01-01T00:00:00Z"}
_DECISION = "2026-01-02T00:00:00Z"


def _components(momentum: float = 0.4, trend: float = 0.3) -> ComponentScores:
    return ComponentScores(momentum, trend, 0.1, 0.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _signal(etf_id: str = "ETF-1", *, momentum: float = 0.4, trend: float = 0.3, status: str = "ok", timestamp: datetime | None = datetime(2026, 1, 1, tzinfo=timezone.utc), **metrics: object) -> SignalResult:
    return SignalResult(
        run_id="run-1",
        signal_date=date(2026, 1, 1),
        etf_id=etf_id,
        action="WATCH",
        confidence=0.5,
        total_score=0.6,
        components=_components(momentum, trend),
        blocked_by=[],
        warnings=[],
        reason_short="",
        reason_long="",
        horizon_primary="1M",
        supporting_metrics=dict(metrics),
        status=status,  # type: ignore[arg-type]
        timestamp=timestamp,
    )


def _ids(matches) -> set[tuple[str, str]]:
    return {(item.instrument_id, item.template_id) for item in matches}


# C120-N001 -------------------------------------------------------------------------------------
def test_typed_signal_result_matches() -> None:
    matches = compute_template_matches([_signal()], decision_time=_DECISION)
    templates = {item.template_id for item in matches if item.instrument_id == "ETF-1"}
    assert {"etf_dual_momentum", "trend_following", "manual_custom_score_blend"} <= templates
    assert all(item.execution_allowed is False and item.actions == () for item in matches)


def test_typed_signal_result_fails_closed() -> None:
    assert compute_template_matches([_signal(timestamp=None)], decision_time=_DECISION) == ()
    assert compute_template_matches([_signal(timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc))], decision_time=_DECISION) == ()
    assert compute_template_matches([_signal(status="blocked")], decision_time=_DECISION) == ()
    for weak in (_signal(momentum=float("nan"), trend=float("nan")), _signal(momentum=-0.2, trend=-0.1)):
        found = {item.template_id for item in compute_template_matches([weak], decision_time=_DECISION)}
        assert not found & {"etf_dual_momentum", "trend_following"}


def test_typed_signal_result_matches_through_facade(tmp_path) -> None:
    facade = StrategyTemplateFacade(state_path=tmp_path / "state.json")
    assert ("ETF-1", "etf_dual_momentum") in _ids(facade.matches([_signal()], decision_time=_DECISION))


# C120-N002 -------------------------------------------------------------------------------------
def test_all_disabled_templates_match_nothing(tmp_path) -> None:
    facade = StrategyTemplateFacade(state_path=tmp_path / "state.json")
    snapshot = [{"instrument_id": "ETF-1", "asset_type": "etf", "momentum": 0.2, "momentum_status": "available", "trend": 0.1, "trend_status": "available", "score": 1.0, **_KNOWN}]
    assert facade.matches(snapshot, decision_time=_DECISION)
    for template in facade.templates:
        facade.set_enabled(template.template_id, False)
    assert facade.matches(snapshot, decision_time=_DECISION) == ()
    assert compute_template_matches(snapshot, (), decision_time=_DECISION) == ()


# C120-N003 -------------------------------------------------------------------------------------
def test_every_template_declares_asset_scope() -> None:
    templates = load_strategy_templates()
    assert tuple(template.template_id for template in templates) == TEMPLATE_IDS
    for template in templates:
        scope = template.definition.get("asset_scope")
        assert isinstance(scope, list) and scope and set(scope) <= {"etf", "stock"}, template.template_id


def test_template_without_asset_scope_is_rejected(tmp_path) -> None:
    source = Path(__file__).resolve().parents[1] / "configs" / "strategy_templates_v1.yaml"
    text = source.read_text(encoding="utf-8")
    assert "asset_scope: [etf], rule: momentum_and_trend" in text
    broken = tmp_path / "no-scope.yaml"
    broken.write_text(text.replace("asset_scope: [etf], rule: momentum_and_trend", "rule: momentum_and_trend", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="asset_scope"):
        load_strategy_templates(broken)


# C020-N003 -------------------------------------------------------------------------------------
def _stock(**fields: object) -> dict[str, object]:
    return {"instrument_id": "STK", "asset_type": "stock", **_KNOWN, **fields}


def test_negative_momentum_does_not_match_stock_momentum_templates() -> None:
    evidence = pd.DataFrame({"instrument_id": ["STK"], "status": ["available"], "composite_score": [1.0], "momentum_score": [-0.4]})
    cases = [
        _stock(quality_momentum_evidence=evidence, momentum=-0.4),
        _stock(quality_momentum_evidence=evidence.drop(columns="momentum_score"), momentum=-0.4),
        _stock(quality_momentum_status="available", quality_momentum_score=0.9, quality=0.9, momentum=-0.4),
        _stock(quality_momentum_status="available", quality_momentum_score=0.9, quality=0.9, momentum=0.4, momentum_status="available", momentum_score=-0.4),
        _stock(momentum=-0.4, momentum_status="available", value=0.7),
        _stock(momentum=0.4, momentum_score=-0.4, momentum_status="available", value=0.7),
        _stock(momentum=-0.4, momentum_score=0.4, momentum_status="available", value=0.7),
    ]
    for row in cases:
        found = {item.template_id for item in compute_template_matches([row], decision_time=_DECISION)}
        assert not found & {"stock_quality_momentum", "stock_value_momentum"}, row


def test_positive_momentum_still_matches_stock_momentum_templates() -> None:
    evidence = pd.DataFrame({"instrument_id": ["STK"], "status": ["available"], "composite_score": [1.0], "momentum_score": [0.4]})
    quality = compute_template_matches([_stock(quality_momentum_evidence=evidence, momentum=0.4)], decision_time=_DECISION)
    assert "stock_quality_momentum" in {item.template_id for item in quality}
    value = compute_template_matches([_stock(momentum=0.4, momentum_status="available", value=0.7)], decision_time=_DECISION)
    assert "stock_value_momentum" in {item.template_id for item in value}


# V8 C.C2.S20.N003 ------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_evidence_never_matches(bad: float) -> None:
    row = {"instrument_id": "X", "asset_type": "etf", "score": bad, "volatility": bad, "dividend_yield": bad, "quality": bad, "momentum": bad, "momentum_status": "available", "trend": bad, "trend_status": "available", **_KNOWN}
    assert compute_template_matches([row], decision_time=_DECISION) == ()
