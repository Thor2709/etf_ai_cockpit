from __future__ import annotations

import inspect

from etf_cockpit.app.pages.macro_factors import macro_factors_page
from etf_cockpit.app.router import PAGES


def test_macro_factors_workspace_is_registered_and_declares_safe_boundaries() -> None:
    assert PAGES["/macro"][0] == "Macro and Factors"
    source = inspect.getsource(macro_factors_page)
    for label in (
        "Decision-time vintages",
        "Execution allowed: false",
        "Latest local observations",
        "Regime and proxy context",
        "Optional FRED: unavailable",
        "Inflation/rates context:",
        "context_only=true",
        "score_eligible=false",
        "Risk-free curves and lawful benchmarks",
        "Interpolation is declared per curve and bounded",
        "Currency+horizon fallbacks are explicit",
        "Issuer-specific credit curves:",
        "decision-time vintage=",
    ):
        assert label in source
    assert "remote fetch" in source
