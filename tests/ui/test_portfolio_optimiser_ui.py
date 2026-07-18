from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import portfolio_optimiser
from etf_cockpit.app.router import PAGES
from etf_cockpit.core.config import load_config


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(root) -> str:
    return "\n".join(str(control.value) for control in _walk(root) if isinstance(control, ft.Text))


def _state(with_prices: bool = True):
    dates = pd.date_range("2025-01-01", periods=80)
    prices = pd.DataFrame(
        {
            "date": dates.tolist() * 2,
            "etf_id": ["AAA"] * 80 + ["BBB"] * 80,
            "adjusted_close": [100 + index * 0.1 for index in range(80)] + [90 + index * 0.2 for index in range(80)],
        }
    )
    if not with_prices:
        prices = pd.DataFrame()
    snapshot = SimpleNamespace(config=load_config(), prices=prices)
    return SimpleNamespace(snapshot=snapshot, last_message="Ready")


def test_portfolio_optimiser_lab_exposes_methods_constraints_and_audit_state() -> None:
    root = portfolio_optimiser.portfolio_optimiser_page(None, _state())
    keys = {str(control.key) for control in _walk(root) if getattr(control, "key", None)}
    assert {"portfolio-optimiser.method", "portfolio-optimiser.cash", "portfolio-optimiser.max-weight", "portfolio-optimiser.run"} <= keys
    text = _text(root)
    assert "Portfolio Optimiser Lab" in text
    assert "Equal weight" in text
    assert "execution_allowed=false" in text
    assert "solver_fingerprints=" in text
    assert PAGES["/portfolio-optimiser"] == ("Portfolio Optimiser Lab", portfolio_optimiser.portfolio_optimiser_page)


def test_portfolio_optimiser_lab_reports_unavailable_adjusted_price_state() -> None:
    root = portfolio_optimiser.portfolio_optimiser_page(None, _state(with_prices=False))
    assert "Optimisation unavailable" in _text(root)
    assert "adjusted-price returns" in _text(root)
