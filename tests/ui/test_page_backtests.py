from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.backtests import backtests_page


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _render(results: pd.DataFrame) -> PageView:
    report = SimpleNamespace(
        results=results,
        quality_label="medium" if not results.empty else None,
        ai_added_value=None,
        equity_curves=pd.DataFrame(),
        operational_evidence=pd.DataFrame(),
        trade_log=pd.DataFrame(),
    )
    state = SimpleNamespace(snapshot=SimpleNamespace(backtest=report, config=None))
    return backtests_page(None, state)


def _text(page: PageView) -> list[str]:
    return [str(item.value) for item in _walk(page.body) if isinstance(item, ft.Text)]


def test_renders_with_sample_data() -> None:
    rendered = _render(pd.DataFrame([{ "strategy_name": "signal_strategy", "cagr": 0.04, "max_drawdown": -0.12, "turnover": 1.1 }]))
    values = _text(rendered)
    assert isinstance(rendered, PageView)
    for title in ("Equity and drawdown", "Strategy diagnostics", "CAGR vs. max drawdown", "Tail-event diagnostics", "Cost/Capacity"):
        assert title in values
    assert not any("Traceback" in value for value in values)


def test_empty_data_shows_unavailable() -> None:
    rendered = _render(pd.DataFrame())
    values = _text(rendered)
    assert "Unavailable" in " ".join(values)
    assert not any(value.strip() == "0" for value in values)
