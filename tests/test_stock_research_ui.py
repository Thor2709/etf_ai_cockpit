from __future__ import annotations

import inspect

from etf_cockpit.app.pages.stock_research import _valuation_panel, stock_research_page


def test_stock_research_page_exposes_required_evidence_panels() -> None:
    source = inspect.getsource(stock_research_page) + inspect.getsource(_valuation_panel)

    assert "Profitability" in source
    assert "Earnings quality" in source
    assert "Balance sheet" in source
    assert "Solvency" in source
    assert "Valuation Lab" in source
    assert "execution_allowed" in source
