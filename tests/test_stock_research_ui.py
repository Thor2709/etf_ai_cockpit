from __future__ import annotations

import inspect
from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.pages.stock_research import _capital_efficiency_panel, _expectations_panel, _growth_panel, _metrics_panel, _valuation_panel, stock_research_page


def test_stock_research_page_exposes_required_evidence_panels() -> None:
    source = inspect.getsource(stock_research_page) + inspect.getsource(_capital_efficiency_panel) + inspect.getsource(_growth_panel) + inspect.getsource(_expectations_panel) + inspect.getsource(_valuation_panel)

    assert "Profitability" in source
    assert "Earnings quality" in source
    assert "Balance sheet" in source
    assert "Solvency" in source
    assert "Valuation Lab" in source
    assert "Capital Efficiency" in source
    assert "Reported" in source
    assert "Adjusted" in source
    assert "cannot override valuation or risk" in source
    assert "Growth" in source
    assert "Management guidance" in source
    assert "Optional consensus" in source
    assert "acquisition_flags" in source
    assert "Period history" in source
    assert "formula" in source
    assert "base_effect" in source
    assert "source lineage" in source
    assert "execution_allowed" in source


def _walk(control: ft.Control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)
    for child in getattr(control, "controls", None) or []:
        if isinstance(child, ft.Control):
            yield from _walk(child)


def test_expectations_panel_renders_guidance_and_consensus_evidence() -> None:
    control = _expectations_panel({
        "guidance": {"status": "available", "items": [{"metric": "revenue", "period_key": "FY2026", "lower": 118.0, "upper": 123.0, "review_status": "structured", "source_id": "issuer-release"}], "rejected_records": []},
        "consensus": {"status": "available", "metrics": {"revenue": {"FY2026": {"latest_value": 121.0, "revision": {"value": 3.0}, "dispersion": {"value": 1.5}, "surprise": {"value": -1.0}, "staleness": {"days": 2}, "source_ids": ["licensed-import"]}}}, "rejected_records": []},
    })

    visible = "\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))
    assert "Management guidance (available)" in visible
    assert "118 to 123" in visible
    assert "review=structured" in visible
    assert "Optional consensus (available)" in visible
    assert "revision=3" in visible
    assert "dispersion=1.5" in visible
    assert "surprise=-1" in visible
    assert "staleness=2 days" in visible
    assert "execution_allowed=false" in visible


def test_expectations_panel_uses_bounded_selection_areas() -> None:
    control = _expectations_panel({"guidance": {}, "consensus": {}})
    descendants = list(_walk(control))

    assert any(isinstance(item, ft.SelectionArea) for item in descendants)
    assert not any(isinstance(item, ft.Text) and item.selectable for item in descendants)


def test_metric_panels_bound_expanding_cards_in_responsive_cells() -> None:
    controls = [
        _metrics_panel("Profitability", "Evidence", {}),
        _growth_panel({}),
    ]

    for control in controls:
        descendants = list(_walk(control))
        assert any(isinstance(item, ft.ResponsiveRow) for item in descendants)


def test_capital_efficiency_toggle_switches_reported_and_adjusted_evidence() -> None:
    class PageStub:
        updates = 0

        def update(self) -> None:
            self.updates += 1

    page = PageStub()
    control = _capital_efficiency_panel(
        {
            "reported": {"status": "available", "metrics": {"roic": {"value": 0.2, "status": "available"}}, "history": [{"period_key": "FY2026", "roic": 0.2}]},
            "adjusted": {"status": "available", "metrics": {"roic": {"value": 0.18, "status": "available"}}, "history": [{"period_key": "FY2026", "roic": 0.18}], "assumptions": {"method": "straight_line"}},
            "business_quality_proxies": {},
            "sector_relative": {},
            "assumption_sensitivity": [{"scenario": "selected"}],
            "proxy_authority": "descriptive_only",
        },
        page,
    )
    descendants = list(_walk(control))
    selector = next(item for item in descendants if isinstance(item, ft.SegmentedButton))
    reported = next(item for item in descendants if isinstance(item, ft.Container) and item.data == "capital-efficiency-reported")
    adjusted = next(item for item in descendants if isinstance(item, ft.Container) and item.data == "capital-efficiency-adjusted")

    assert selector.selected == ["reported"]
    assert reported.visible is True
    assert adjusted.visible is False

    selector.selected = ["adjusted"]
    selector.on_change(SimpleNamespace(control=selector))

    assert reported.visible is False
    assert adjusted.visible is True
    assert page.updates == 1
