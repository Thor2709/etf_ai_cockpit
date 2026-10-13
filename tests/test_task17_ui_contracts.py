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
        {"run_id": "old", "run_completed_at": "2026-07-09T12:00:00+00:00", "instrument_id": "A", "final_combined_score_10": 5.0, "final_action": "watchlist"},
        {"run_id": "new", "run_completed_at": "2026-07-10T12:00:00+00:00", "instrument_id": "A", "final_combined_score_10": 7.0, "final_action": "watchlist"},
    ]))
    rendered = module.what_changed_page(None, SimpleNamespace())
    controls = list(_walk(rendered))
    labels = {str(getattr(item, "label", "")) for item in controls}
    labels.update(str(item.value) for item in controls if isinstance(item, ft.Text))
    assert "search instrument" in {label.casefold() for label in labels}
    assert rendered.chrome.segment_groups[0].selected == "All dimensions"
    assert callable(rendered.chrome.segment_groups[0].on_change)
    assert any(isinstance(item, ft.Switch) and item.key == "what-changed.filter.changed-only" and callable(item.on_change) for item in controls)


def test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table(monkeypatch) -> None:
    import etf_cockpit.app.pages.what_changed as module

    monkeypatch.setattr(
        module,
        "score_history_frame",
        lambda: pd.DataFrame(
            [
                {
                    "run_id": "old",
                    "run_completed_at": "2026-07-09T12:00:00+00:00",
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
                    "run_completed_at": "2026-07-10T12:00:00+00:00",
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

    # No natively scrolling table: the kit table lays its columns out with flex sizes inside the card width.
    assert not any(isinstance(item, ft.DataTable) for item in controls)
    assert not any(
        isinstance(item, ft.Row) and getattr(item, "scroll", None) not in (None, ft.ScrollMode.HIDDEN)
        for item in controls
    )
    tables = [item for item in controls if isinstance(getattr(item, "data", None), dict) and item.data.get("kit") == "DataTable"]
    changes = [
        item for item in tables
        if item.data["columns"] == ["instrument", "score", "rank", "freshness", "model", "forecasts", "news", "backtest", "risk"]
    ]
    assert len({id(item) for item in changes}) == 1
    assert changes[0].data["rows"] >= 1
    # The first row is selected and its causal path card is shown next to the table.
    selected_rows = [
        item for item in controls
        if isinstance(getattr(item, "data", None), dict) and item.data.get("kit") == "DataTableRow" and item.data.get("selected")
    ]
    assert [row.data["index"] for row in selected_rows] == [0]
    titles = {str(item.value).casefold() for item in controls if isinstance(item, ft.Text)}
    assert "changes by instrument" in titles
    assert any(title.startswith("causal path: a") for title in titles)


def test_dashboard_digest_surfaces_deterministic_run_changes(monkeypatch) -> None:
    import etf_cockpit.app.pages.dashboard as module

    monkeypatch.setattr(module, "score_history_frame", lambda: pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-07-09T12:00:00+00:00", "instrument_id": "A", "final_combined_score_10": 5.0, "final_action": "watchlist"},
        {"run_id": "new", "run_completed_at": "2026-07-10T12:00:00+00:00", "instrument_id": "A", "final_combined_score_10": 7.0, "final_action": "watchlist"},
    ]))
    state = SimpleNamespace(snapshot=SimpleNamespace(data_report=SimpleNamespace(as_of_date="2026-07-10")))
    rendered = module._run_changes_digest(None, state)
    texts = [str(getattr(item, "value", "")) for item in _walk(rendered) if hasattr(item, "value")]
    assert any("Compared run new with old" in value for value in texts)
    assert any("A" in value for value in texts)
