from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.research_surface import (
    decision_tag,
    distribution_range,
    metric_card,
    panel,
    unavailable_card,
)
from etf_cockpit.app.components.valuation_lab import _research_number, _research_value


def _texts(control: object) -> list[str]:
    found: list[str] = []
    stack = [control]
    while stack:
        item = stack.pop()
        if isinstance(item, ft.Text) and item.value is not None:
            found.append(str(item.value))
        stack.extend(getattr(item, "controls", None) or [])
        content = getattr(item, "content", None)
        if content is not None:
            stack.append(content)
    return found


def test_panel_and_metric_card_use_keyed_glass_surfaces() -> None:
    first = panel(ft.Text("Heading"))
    second = panel(ft.Text("Heading"))
    assert first.key and second.key and first.key != second.key
    assert first.tooltip == "Heading"
    tile = metric_card("Vol 60d", "12.3%", "detail")
    assert tile.key.startswith("research.kpi.") and tile.expand is True


def test_missing_metric_values_read_na_never_zero() -> None:
    assert "N/A" in _texts(metric_card("Growth", "n/a"))
    assert "N/A" in _texts(metric_card("Growth", ""))
    assert _research_number(None) == "N/A" and _research_value(None) == "N/A"


def test_distribution_range_renders_when_complete() -> None:
    view = distribution_range(
        {"q10_expected_return": -0.05, "q50_expected_return": 0.02, "q90_expected_return": 0.09, "expected_return_horizon_days": 60},
        key="t.range",
    )
    texts = " ".join(_texts(view))
    assert "q10 -5.0%" in texts and "q50 +2.0%" in texts and "q90 +9.0%" in texts and "60d" in texts
    assert "Unavailable" not in texts


def test_distribution_range_unavailable_with_reason_when_incomplete() -> None:
    for payload in ({}, {"q10_expected_return": 0.1, "q50_expected_return": None, "q90_expected_return": 0.2}, {"q10_expected_return": 0.3, "q50_expected_return": 0.2, "q90_expected_return": 0.1}):
        view = distribution_range(payload, key="t.range")
        texts = _texts(view)
        assert "Unavailable" in texts and any("never filled" in t for t in texts)


def test_decision_tag_and_unavailable_card_carry_text() -> None:
    assert _texts(decision_tag("Hold", None, key="t.tag")) == ["Hold"]
    assert "reason text" in _texts(unavailable_card("Fan", "reason text", key="t.un"))
