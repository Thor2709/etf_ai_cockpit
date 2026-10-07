"""Universe page: view-model rules and rendered cards (FINAL_UI_SPEC 6.2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flet as ft

import etf_cockpit.app.pages.universe_manager as manager
from etf_cockpit.app.pages.universe_manager import universe_manager_page
from etf_cockpit.application.ui_views import universe as view
from etf_cockpit.core.config import AppConfig, CostConfig, ModelSettings, PortfolioTargets, RiskLimits, UISettings, UniverseConfig
from etf_cockpit.data.universe_store import UniverseRecord, UniverseStoreSnapshot


class _Page:
    width, height = 1920, 1200

    def __init__(self) -> None:
        self.overlay: list[ft.Control] = []

    def update(self) -> None:
        return None


def _walk(control):
    if not isinstance(control, ft.Control):
        return
    yield control
    for attr in ("controls", "items"):
        for child in getattr(control, attr, None) or []:
            yield from _walk(child)
    yield from _walk(getattr(control, "content", None))


def _texts(root) -> str:
    return "\n".join(str(c.value) for c in _walk(root) if isinstance(c, ft.Text) and c.value)


def _state() -> SimpleNamespace:
    config = AppConfig(universe=UniverseConfig(etfs=[]), targets=PortfolioTargets(), risks=RiskLimits(), costs=CostConfig(), models=ModelSettings(), ui=UISettings(), chatgpt_schema={})
    return SimpleNamespace(snapshot=SimpleNamespace(config=config))


def _records() -> tuple[UniverseRecord, ...]:
    return (
        UniverseRecord("VWCE", "Vanguard All-World", "IE00BK5BQT80", "verified", "VWCE.DE", "etf", "primary", "", True, "daily", "EUR", "World", "", "Global equity"),
        UniverseRecord("ASML", "ASML Holding", "NL0010273215", "verified", "ASML", "stock", "secondary", "", True, "daily", "EUR", "Netherlands", "Technology", ""),
        UniverseRecord("TQQQ", "UltraPro QQQ", "US74347X8314", "needs_verification", "TQQQ", "etf", "secondary", "", False, "daily", "USD", "US", "", "", leveraged=True),
    )


def _load(monkeypatch, records) -> None:
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot(tuple(records), "revision", Path("store.json")))


def test_review_and_tier_tags_follow_the_spec_priorities() -> None:
    plain, _, leveraged = _records()
    assert view.review_tag(plain, "current", "ok").text is None
    assert view.review_tag(leveraged, "unavailable", "x").text == "Manual review"
    assert view.review_tag(plain, "manual_review", "tampered").text == "Manual review"
    assert view.review_tag(plain, "stale", "old").text == "Pending refresh"
    assert view.tier_tag(leveraged) == ("Leveraged", "warn") and view.tier_tag(plain) == ("Primary", "mute")
    assert view.tier_tag(UniverseRecord("S", "Short", tier="primary", inverse=True)) == ("Inverse", "warn")


def test_composition_and_enabled_by_tier_count_the_shown_records() -> None:
    records = _records()
    slices = {item.name: item.count for item in view.composition(records, {"VWCE": "equity", "ASML": "equity", "TQQQ": "equity"})}
    assert slices == {"Equity ETFs": 1, "Stocks": 1, "Leveraged / inverse": 1}
    bars, disabled = view.enabled_by_tier(records, {})
    assert [(bar.label, bar.count) for bar in bars] == [("Primary", 1), ("Secondary", 1), ("Sparebanken", 0), ("Manual review", 1)]
    assert disabled == 1
    insight = view.composition_insight(view.composition(records, {}), 1) or ""
    assert insight.startswith("Equity ETFs make up 33%") and "1 leveraged or inverse" in insight


def test_page_renders_the_four_reference_cards_and_segments(monkeypatch) -> None:
    _load(monkeypatch, _records())
    result = universe_manager_page(_Page(), _state())
    text = _texts(result.body)
    for title in ("Instrument universe", "Add instruments", "Universe composition", "Enabled by tier", "Preview import", "Validate only"):
        assert title.casefold() in text.casefold()
    assert result.chrome.title == "Universe"
    assert "3 candidates · 2 enabled" in result.chrome.subtitle
    assert [list(group.items) for group in result.chrome.segment_groups] == [["All", "Primary", "Secondary", "Sparebanken"], ["All", "ETF", "Stock"]]
    assert "Traceback" not in text and "Leveraged" in text


def test_segments_filter_the_table_in_place(monkeypatch) -> None:
    _load(monkeypatch, _records())
    result = universe_manager_page(_Page(), _state())
    keys = lambda: {str(c.key) for c in _walk(result.body) if c.key}  # noqa: E731
    assert {"universe.enabled.VWCE", "universe.enabled.ASML", "universe.enabled.TQQQ"} <= keys()
    result.chrome.segment_groups[0].on_change("Primary")
    assert "universe.enabled.VWCE" in keys() and "universe.enabled.ASML" not in keys()
    result.chrome.segment_groups[0].on_change("All")
    result.chrome.segment_groups[1].on_change("Stock")
    assert "universe.enabled.ASML" in keys() and "universe.enabled.VWCE" not in keys()


def test_empty_universe_shows_empty_states_never_zeros(monkeypatch) -> None:
    _load(monkeypatch, ())
    result = universe_manager_page(_Page(), _state())
    text = _texts(result.body)
    assert "No instruments match" in text and "No instruments" in text
    assert "0 candidates" in result.chrome.subtitle
