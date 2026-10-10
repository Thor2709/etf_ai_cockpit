from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.pages import dashboard, onboarding


def _walk(node):
    yield node
    for child in list(getattr(node, "controls", None) or []):
        if isinstance(child, ft.Control):
            yield from _walk(child)
    content = getattr(node, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)


def _texts(node) -> str:
    return " ".join(str(c.value) for c in _walk(node) if isinstance(c, ft.Text))


def test_as_of_strip_shows_snapshot_date_and_price_basis() -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(data_report=SimpleNamespace(as_of_date="2026-07-01")))
    strip = dashboard.as_of_strip(state, key="dashboard.as-of")
    text = _texts(strip)
    assert "As of: 2026-07-01" in text and "Price basis: adjusted" in text
    assert {c.key for c in _walk(strip) if c.key} >= {"dashboard.as-of.date", "dashboard.as-of.basis"}


def test_as_of_strip_missing_date_is_unavailable_with_reason_not_zero() -> None:
    strip = dashboard.as_of_strip(SimpleNamespace(snapshot=None), key="dashboard.as-of")
    assert "As of: Unavailable" in _texts(strip)
    date = next(c for c in _walk(strip) if c.key == "dashboard.as-of.date")
    assert date.tooltip and "no snapshot as-of date" in date.tooltip.lower()


def test_disclosure_is_collapsed_by_default_and_wraps_content() -> None:
    tile = dashboard.disclosure("Title", "Sub", ft.Text("body"), key="k.details")
    assert isinstance(tile, ft.ExpansionTile)
    assert tile.expanded is False and tile.key == "k.details"
    assert "body" in _texts(tile)


def test_summary_kpis_have_stable_keys_and_no_inline_as_of() -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-01")))
    cards = dashboard._summary_cards(state, None, 1, 2, 3, 0, narrow=False)
    keys = {c.key for c in cards.controls}
    assert keys == {f"dashboard.kpi.{n}" for n in ("primary-instruments", "secondary-candidates", "sparebanken-scorecards", "top-score", "data-health", "model-rows", "regime", "final-mode")}
    assert "N/A" in _texts(cards) and "as of 2026" not in _texts(cards)


def test_onboarding_leads_with_setup_and_discloses_details() -> None:
    page = onboarding.onboarding_page(SimpleNamespace(update=lambda: None), SimpleNamespace(snapshot=None))

    def keyed(key: str):
        return next((c for c in _walk(page) if getattr(c, "key", None) == key), None)

    # Setup comes first: a four-step flow opens on Preferences with Next; saving is only offered on the last step.
    assert {f"onboarding.step.{n}" for n in range(4)} <= {c.key for c in _walk(page) if getattr(c, "key", None)}
    steps = [c for c in _walk(page) if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == "Stepper"]
    assert len(steps) == 1
    text = _texts(page)
    for name in ("Preferences", "Data source", "Watchlist", "Review & save"):
        assert name in text
    assert "Current step" in text
    assert keyed("onboarding.next") is not None and keyed("onboarding.save") is None
    for _ in range(3):
        keyed("onboarding.next").on_click(None)
    assert keyed("onboarding.save") is not None and keyed("onboarding.next") is None

    # Details stay disclosed on demand: every disclosure starts collapsed and is not an expanded tile.
    disclosures = [c for c in _walk(page) if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == "Disclosure"]
    assert {c.data["label"] for c in disclosures} >= {
        "Save status",
        "Raw authority flags",
        "Full profile table and diagnostics",
        "Policy and terms details",
    }
    assert all(c.controls[1].visible is False for c in disclosures)
    assert not any(isinstance(c, ft.ExpansionTile) and c.expanded for c in _walk(page))
    assert "execution_allowed=false" in _texts(page)
