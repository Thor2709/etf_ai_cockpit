from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages.portfolio_optimiser import portfolio_optimiser_page
from etf_cockpit.core.config import load_config


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    if getattr(control, "content", None) is not None:
        yield from _walk(control.content)


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


def _text(view) -> str:
    return "\n".join(str(item.value) for item in _walk(view.body) if isinstance(item, ft.Text))


def test_renders_with_sample_data() -> None:
    view = portfolio_optimiser_page(None, _state())
    content = _text(view)
    assert view.__class__.__name__ == "PageView"
    assert all(title in content for title in ("Constraints and method", "Risk-return frontier and baseline comparison", "Method comparison", "Weights by method", "Audit and limitations"))
    assert "Equal weight" in content
    assert "Traceback" not in content


def test_empty_data_shows_unavailable() -> None:
    view = portfolio_optimiser_page(None, _state(with_prices=False))
    content = _text(view)
    assert "Unavailable" in content or "unavailable" in content
    assert all(line != "0" for line in content.splitlines())
