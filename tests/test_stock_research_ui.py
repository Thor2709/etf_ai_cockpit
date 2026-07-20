from __future__ import annotations

import inspect

import flet as ft

from etf_cockpit.app.pages.stock_research import (
    _expectations_panel,
    _growth_panel,
    _valuation_panel,
    stock_research_page,
)


def test_stock_research_page_exposes_required_evidence_panels() -> None:
    source = (
        inspect.getsource(stock_research_page)
        + inspect.getsource(_growth_panel)
        + inspect.getsource(_expectations_panel)
        + inspect.getsource(_valuation_panel)
    )

    assert "Profitability" in source
    assert "Earnings quality" in source
    assert "Balance sheet" in source
    assert "Solvency" in source
    assert "Valuation Lab" in source
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
    control = _expectations_panel(
        {
            "guidance": {
                "status": "available",
                "items": [
                    {
                        "metric": "revenue",
                        "period_key": "FY2026",
                        "lower": 118.0,
                        "upper": 123.0,
                        "review_status": "structured",
                        "source_id": "issuer-release",
                    },
                ],
                "rejected_records": [],
            },
            "consensus": {
                "status": "available",
                "metrics": {
                    "revenue": {
                        "FY2026": {
                            "latest_value": 121.0,
                            "revision": {"value": 3.0},
                            "dispersion": {"value": 1.5},
                            "surprise": {"value": -1.0},
                            "staleness": {"days": 2},
                            "source_ids": ["licensed-import"],
                        }
                    }
                },
                "rejected_records": [],
            },
        }
    )

    visible = "\n".join(
        str(item.value) for item in _walk(control) if isinstance(item, ft.Text)
    )
    assert "Management guidance (available)" in visible
    assert "118 to 123" in visible
    assert "review=structured" in visible
    assert "Optional consensus (available)" in visible
    assert "revision=3" in visible
    assert "dispersion=1.5" in visible
    assert "surprise=-1" in visible
    assert "staleness=2 days" in visible
    assert "execution_allowed=false" in visible
