from __future__ import annotations

from etf_cockpit.app.pages.system_map import system_map_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(control))


def _strategy_row(control, strategy_id: str):
    rows = [
        item
        for item in _walk(control)
        if strategy_id in str(getattr(item, "value", "") or getattr(item, "text", ""))
    ]
    assert len(rows) == 1, f"expected one dynamic strategy row for {strategy_id}, got {len(rows)}"
    return rows[0]


def test_system_map_exposes_both_research_only_boundaries() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = system_map_page(None, state)
    text = _text(page).casefold()

    pair_row = str(getattr(_strategy_row(page, "pair_trading"), "value", "")).casefold()
    triple_row = str(getattr(_strategy_row(page, "triple_barrier_research"), "value", "")).casefold()
    for row in (pair_row, triple_row):
        assert "research_only" in row
        assert "authority=none" in row
        assert "score_authority=false" in row
        assert "paper_authority=false" in row
        assert "live_authority=false" in row
        assert "draft_order=unavailable" in row
        assert "canary=unavailable" in row
        assert "bounded_automatic=unavailable" in row

    assert "research-only strategy boundaries" in text
    assert "pair trading / cointegration" in text
    assert "point-in-time pair selection" in text
    assert "borrow availability and borrow-cost evidence" in text
    assert "multiple-testing budget" in text
    assert "triple-barrier labels / purged validation" in text
    assert "upper, lower and vertical barriers" in text
    assert "minimum event/sample" in text
    assert "purged folds" in text
    assert "embargo" in text
    assert "leakage canaries" in text
    assert "issue-0120" in text
    assert "execution_authority=none" in text
