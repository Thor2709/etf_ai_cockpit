from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import risk as risk_module
from etf_cockpit.app.pages.risk import risk_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    if getattr(control, "content", None) is not None:
        yield from _walk(control.content)


def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _text(view) -> str:
    return "\n".join(str(item.value) for item in _walk(view.body) if isinstance(item, ft.Text))


def test_renders_with_sample_data() -> None:
    view = risk_page(None, _state())
    assert isinstance(view, PageView)
    original_body = view.body
    content = []
    view_group, dimension_group = view.chrome.segment_groups
    for item in view_group.items:
        view_group.on_change(item)
        if item == "Exposure":
            for dimension in dimension_group.items:
                dimension_group.on_change(dimension)
                content.append(_text(view))
        else:
            content.append(_text(view))
    rendered = "\n".join(content)
    assert view.body is original_body
    assert all(
        title in rendered
        for title in (
            "Asset class exposure vs. target",
            "Region exposure vs. target",
            "Currency exposure vs. target",
            "Sector exposure vs. target",
            "Theme exposure vs. target",
            "Portfolio guardrail context",
            "Correlation",
            "Regimes, tail dependence and liquidity",
            "Factor exposure and contribution",
            "Historical factor returns",
            "Multi-factor risk model",
            "Robust risk model",
            "Performance and decision attribution",
            "Regimes",
            "Tail evidence",
            "ETF holdings evidence",
            "ETF direct overlap",
            "Underlying holdings context",
        )
    )
    assert "Traceback" not in rendered


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        risk_module,
        "allocation_frame",
        lambda *_args: pd.DataFrame(columns=["etf_id", "current_weight", "target_weight"]),
    )
    monkeypatch.setattr(risk_module, "exposure_limit_report", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(risk_module, "return_correlation_matrix", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        risk_module,
        "build_factor_risk_report",
        lambda *_args, **_kwargs: {
            "status": "unavailable",
            "diagnostics": {},
            "portfolio_contributions": pd.DataFrame(),
            "factor_returns": pd.DataFrame(),
        },
    )
    monkeypatch.setattr(
        risk_module,
        "build_performance_attribution",
        lambda *_args, **_kwargs: {"status": "unavailable", "asset_contributions": pd.DataFrame(), "warnings": []},
    )
    view = risk_page(None, _state())
    content = _text(view)
    assert isinstance(view, PageView)
    assert "Unavailable" in content or "unavailable" in content
    for control in _walk(view.body):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(str(value) != "0" for row in data.get("rows", ()) for value in row.values())
