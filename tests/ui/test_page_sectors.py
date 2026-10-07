"""Sectors & Countries page: view-model rules and rendered cards (FINAL_UI_SPEC 6.7)."""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import sectors as page_module
from etf_cockpit.app.pages.sectors import sectors_page
from etf_cockpit.application.ui_views import sectors as view
from tests.ui._p2_fixtures import reference_view


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


def _page(monkeypatch, data: view.SectorsView):
    monkeypatch.setattr(view, "load", lambda _snapshot, window="1Y", **_kw: data if data.window == window else reference_view(window))
    return sectors_page(SimpleNamespace(width=1920, height=1200, update=lambda: None), SimpleNamespace(snapshot=None))


def test_headline_follows_the_spec_thresholds() -> None:
    one = [view.Weight("United States", 62.0), view.Weight("Japan", 5.5)]
    assert view.headline(one, "Country") == ("United States concentration is high", "62% of the portfolio sits in one country")
    even = [view.Weight(f"C{i}", 10.0) for i in range(9)]
    assert view.headline(even, "Country")[0] == "Exposure is diversified"
    concentrated = [view.Weight("A", 45.0), view.Weight("B", 40.0), view.Weight("C", 15.0)]
    assert view.headline(concentrated, "Sector") == ("Exposure is concentrated", f"HHI {view.concentration(concentrated)[0]:.2f} across 3 sectors")
    assert view.headline([], "Country") == (None, None)


def test_histogram_bins_count_negative_returns_and_never_zero_fill() -> None:
    counts, negatives, total = view.histogram_counts([-35.0, -5.0, 0.0, 12.0, 45.0, None, float("nan")])
    assert counts == [1, 0, 1, 1, 1, 0, 0, 1] and negatives == 2 and total == 5
    assert view.histogram_counts([None, None]) == ([0] * 8, 0, 0)
    assert view.histogram_insight([0] * 8, 0, 0) is None


def test_geography_maps_names_codes_and_regions() -> None:
    assert view.iso3_of("USA") == "USA" and view.iso3_of("United Kingdom") == "GBR" and view.iso3_of("uk") == "GBR"
    assert view.iso3_of("Atlantis") is None
    assert view.country_short("FRA", "France") == "FR" and view.region_of("JPN") == "Asia-Pacific" and view.region_of("DEU") == "Europe"
    shares = view.region_shares([view.Weight("USA", 60.0, code="USA"), view.Weight("Japan", 20.0, code="JPN"), view.Weight("France", 20.0, code="FRA")])
    assert [(name, round(share)) for name, share in shares] == [("N. America", 60), ("Asia-Pacific", 20), ("Europe", 20)]


def test_load_without_holdings_gives_reasons_not_zeros() -> None:
    snapshot = SimpleNamespace(holdings=pd.DataFrame({"etf_id": ["A"], "current_weight": [0.0]}))
    data = view.load(snapshot, "1Y")
    assert data.countries == [] and data.sectors == [] and "No current holdings" in (data.exposure_reason or "")
    assert view.bubbles_from_holdings(pd.DataFrame(), "1Y")[0] == []
    points, reason = view.bubbles_from_holdings(pd.DataFrame({"security": ["X"], "pe_ratio": [12.0], "return_on_equity": [20.0], "market_cap": [1e9], "sector": ["Software"], "return_1y": [5.0]}))
    assert reason is None and points[0].group == "Tech" and points[0].roe == 20.0 and points[0].ret == 5.0


def test_page_renders_the_six_reference_cards_and_segments(monkeypatch) -> None:
    result = _page(monkeypatch, reference_view())
    text = _texts(result.body)
    for title in ("Headline", "Top-1 country", "Concentration (HHI)", "World exposure", "Sector overview", "Benchmark vs. analysed companies", "Country exposure vs. return", "Distribution of 1Y returns"):
        assert title.casefold() in text.casefold()
    assert result.chrome.title == "Sectors & Countries"
    assert [list(group.items) for group in result.chrome.segment_groups] == [["Sector", "Country", "Company"], ["P/E", "P/B", "ROE"], ["1M", "3M", "1Y", "5Y"]]
    assert [group.selected for group in result.chrome.segment_groups] == ["Country", "P/E", "1Y"]
    assert "USA concentration is high" in text and "Traceback" not in text


def test_segments_rebuild_in_place(monkeypatch) -> None:
    result = _page(monkeypatch, reference_view())
    result.chrome.segment_groups[2].on_change("5Y")
    assert "Distribution of 5Y returns" in _texts(result.body)
    result.chrome.segment_groups[0].on_change("Sector")
    assert "top-1 sector" in _texts(result.body).casefold()
    result.chrome.segment_groups[1].on_change("ROE")
    assert "ROE vs. P/E" in _texts(result.body)


def test_treemap_click_drills_into_a_sector_and_back(monkeypatch) -> None:
    data = reference_view()
    result = _page(monkeypatch, data)
    items = page_module._treemap_items(data.sectors)
    tile = page_module._tile_at(items, 60.0, 60.0, 800.0, 360.0)
    assert tile is not None and tile.name == "Technology"  # the largest tile starts at the top-left inset
    assert page_module._tile_at(items, 799.0, 1.0, 800.0, 360.0) is None  # inside the legend margin, no tile
    detectors = [c for c in _walk(result.body) if isinstance(c, ft.GestureDetector) and c.on_tap_down]
    assert detectors
    detectors[0].on_tap_down(SimpleNamespace(local_position=SimpleNamespace(x=60.0, y=60.0)))
    text = _texts(result.body)
    assert "All sectors › Technology" in text
    crumb = next(c for c in _walk(result.body) if isinstance(c, ft.Container) and c.on_click and "All sectors" in _texts(c))
    crumb.on_click(None)
    assert "All sectors ›" not in _texts(result.body)


def test_missing_evidence_shows_reasons_not_zeros(monkeypatch) -> None:
    empty = view.SectorsView(exposure_reason="No current holdings are available in the selected portfolio snapshot.", sector_reason="No sector exposure is available.", bubbles_reason="Import benchmark holdings and fundamentals to compare companies.")
    text = _texts(_page(monkeypatch, empty).body)
    for expected in ("Unavailable", "Exposure unavailable", "Sector exposure unavailable", "No constituent fundamentals", "No constituent returns"):
        assert expected in text
    region = reference_view()
    region.region_only = True
    assert "Region level only · ETF holdings evidence missing" in _texts(_page(monkeypatch, region).body)
