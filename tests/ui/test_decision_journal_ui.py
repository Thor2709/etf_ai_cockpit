from __future__ import annotations

from etf_cockpit.app.pages.decision_journal import decision_journal_page
from etf_cockpit.app.state import AppState
from etf_cockpit.data.decision_journal import DecisionJournal
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    yield control
    page_body = getattr(control, "body", None)
    if page_body is not None and page_body is not control:
        yield from _walk(page_body)
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None and content is not page_body:
        yield from _walk(content)


def test_decision_journal_is_local_only_with_one_primary_save_action() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = decision_journal_page(None, state)
    controls = list(_walk(page))
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in controls)
    buttons = [
        item
        for item in controls
        if isinstance(getattr(item, "data", None), dict) and item.data.get("kit") == "Button"
    ]
    assert "user-owned notes" in page.chrome.subtitle.casefold()
    assert "No broker execution" in text
    assert sum(getattr(item, "key", "") == "decision-journal.save" for item in buttons) == 1


def test_decision_journal_read_lock_is_visible_as_partial_state(monkeypatch) -> None:
    def locked(*_args, **_kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(DecisionJournal, "list_entries", locked)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(decision_journal_page(None, state)))
    assert "Partial" in text
    assert "manual review" in text
