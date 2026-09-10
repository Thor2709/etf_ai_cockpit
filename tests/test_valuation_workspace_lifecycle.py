"""Scenario ownership follows real shell renders, not viewport relayout."""
import asyncio
import weakref
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.pages import instrument_detail as detail
from etf_cockpit.app.selectors.instrument_detail import InstrumentDetailViewModel


def _walk(node):
    yield node
    for child in getattr(node, "controls", []) or []:
        yield from _walk(child)
    if getattr(node, "content", None) is not None:
        yield from _walk(node.content)


@pytest.mark.parametrize("target", ["/instrument/NEW", "/instrument/OLD"])
def test_real_shell_render_discards_only_owned_workspace(monkeypatch, target):
    class Session:
        index = {}
        async def after_event(self, control):
            pass
    session = Session()
    page = ft.Page(session)
    # The renderer normally attaches this root; updates are stubbed below.
    page._dialogs._parent = weakref.ref(page)
    page.width = 1280
    page.route = "/instrument/OLD"
    monkeypatch.setattr(ft.Page, "update", lambda *_: None)
    monkeypatch.setattr(type(page._dialogs), "update", lambda *_: None)
    focused = []
    async def focus(control):
        focused.append(control)
    monkeypatch.setattr(ft.OutlinedButton, "focus", focus)
    computed = []
    def preview(*args):
        computed.append(args)
        return {"status": "unavailable", "execution_allowed": False}
    monkeypatch.setattr(detail, "_valuation_panel", preview)
    def builder(page, state):
        instrument = page.route.rsplit("/", 1)[-1]
        model = InstrumentDetailViewModel(instrument, instrument, "available", {"asset_type": "stock"}, {"valuation": {"status": "unavailable"}})
        return detail._valuation_workspace(page, model, "2026-07-01")
    monkeypatch.setitem(router.PAGES, "/instrument", ("Instrument", builder))
    state = SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(ui=SimpleNamespace(window_width=1280)),
        data_report=SimpleNamespace(as_of_date="2026-07-01")), evidence_mode="simple", current_activity=None, last_message="Ready")
    router.render_shell(page, state, page.route)
    opener = next(control for control in _walk(page.views[0]) if getattr(control, "key", None) == "instrument-detail.open-valuation")
    opener.on_click(None)
    old = page._dialogs.controls[-1]
    fields = [control for control in _walk(old.content) if isinstance(control, ft.TextField)]
    fields[0].value = "5"
    preview_control = next(control for control in _walk(old.content) if getattr(control, "key", None) == "instrument-detail.preview-valuation")
    router.relayout_shell(page, state, 390)
    assert old.open and fields[0].value == "5"
    assert page._dialogs.controls[-1] is old
    preview_control.on_click(None)
    assert len(computed) == 1 and computed[0][0] == "OLD"
    unrelated = ft.AlertDialog(title="Unrelated workspace")
    page.show_dialog(unrelated)
    page.route = target
    router.render_shell(page, state, target)
    assert old.open is False and old.content is None
    assert unrelated.open is True
    preview_control.on_click(None)
    assert len(computed) == 1
    asyncio.run(old.actions[0].on_click(None))
    assert unrelated.open is True and focused == []
    # Exercise Flet's managed post-animation cleanup, including its original
    # dismissal callback: detached route ownership must suppress focus return.
    asyncio.run(old.on_dismiss(SimpleNamespace(data=None)))
    assert old not in page._dialogs.controls
    assert unrelated in page._dialogs.controls and unrelated.open
    assert focused == []
    new_opener = next(control for control in _walk(page.views[0]) if getattr(control, "key", None) == "instrument-detail.open-valuation")
    assert new_opener is not opener
    new_opener.on_click(None)
    fresh = page._dialogs.controls[-1]
    assert all(control.value == "" for control in _walk(fresh.content) if isinstance(control, ft.TextField))
