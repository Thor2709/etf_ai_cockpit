from __future__ import annotations

import inspect

from etf_cockpit.app.pages.stock_research import _expectations_panel, _growth_panel, _valuation_panel, stock_research_page


def test_stock_research_page_exposes_required_evidence_panels() -> None:
    source = inspect.getsource(stock_research_page) + inspect.getsource(_growth_panel) + inspect.getsource(_expectations_panel) + inspect.getsource(_valuation_panel)

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
