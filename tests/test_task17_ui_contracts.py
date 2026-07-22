from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_what_changed_exposes_instrument_search_and_dimension_filters(monkeypatch) -> None:
    import etf_cockpit.app.pages.what_changed as module

    monkeypatch.setattr(module, "score_history_frame", lambda: pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-07-09", "instrument_id": "A", "final_combined_score_10": 5.0, "final_action": "watchlist"},
        {"run_id": "new", "run_completed_at": "2026-07-10", "instrument_id": "A", "final_combined_score_10": 7.0, "final_action": "watchlist"},
    ]))
    rendered = module.what_changed_page(None, SimpleNamespace())
    controls = list(_walk(rendered))
    labels = {str(getattr(item, "label", "")) for item in controls}
    assert "Search instrument" in labels
    assert "Filter dimension" in labels
    assert any(isinstance(item, ft.Checkbox) and item.label == "Changed only" for item in controls)


def test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table(monkeypatch) -> None:
    import etf_cockpit.app.pages.what_changed as module

    monkeypatch.setattr(
        module,
        "score_history_frame",
        lambda: pd.DataFrame(
            [
                {
                    "run_id": "old",
                    "run_completed_at": "2026-07-09",
                    "instrument_id": "A",
                    "final_combined_score_10": 5.0,
                    "rank": 4,
                    "final_action": "watchlist",
                    "warnings": "stale_prices",
                    "freshness_status": "stale",
                    "model_available": False,
                    "forecast_status": "unavailable",
                    "news_inventory": 1,
                    "backtest_trust": "weak",
                    "portfolio_risk": "low",
                },
                {
                    "run_id": "new",
                    "run_completed_at": "2026-07-10",
                    "instrument_id": "A",
                    "final_combined_score_10": 7.0,
                    "rank": 2,
                    "final_action": "add_candidate",
                    "warnings": "",
                    "freshness_status": "ok",
                    "model_available": True,
                    "forecast_status": "available",
                    "news_inventory": 3,
                    "backtest_trust": "usable",
                    "portfolio_risk": "review",
                },
            ]
        ),
    )

    rendered = module.what_changed_page(None, SimpleNamespace())
    controls = list(_walk(rendered))
    texts = {str(getattr(item, "value", "")) for item in controls if hasattr(item, "value")}

    assert not any(isinstance(item, ft.DataTable) for item in controls)
    assert any(isinstance(item, ft.ResponsiveRow) for item in controls)
    assert {"Warnings", "Freshness", "Model availability", "Forecasts", "News inventory", "Backtest trust", "Portfolio risk", "Current action"} <= texts


def test_dashboard_digest_surfaces_deterministic_run_changes(monkeypatch) -> None:
    import etf_cockpit.app.pages.dashboard as module

    monkeypatch.setattr(module, "score_history_frame", lambda: pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-07-09", "instrument_id": "A", "final_combined_score_10": 5.0, "final_action": "watchlist"},
        {"run_id": "new", "run_completed_at": "2026-07-10", "instrument_id": "A", "final_combined_score_10": 7.0, "final_action": "watchlist"},
    ]))
    rendered = module._run_changes_digest(None, SimpleNamespace())
    texts = [str(getattr(item, "value", "")) for item in _walk(rendered) if hasattr(item, "value")]
    assert any("Compared run new with old" in value for value in texts)
    assert any("A" in value for value in texts)
