from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import chatgpt_audit


def _texts(control: object) -> list[str]:
    values = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.extend(_texts(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_texts(content))
    body = getattr(control, "body", None)
    if body is not None:
        values.extend(_texts(body))
    return values


def _visible_texts(control: object) -> list[str]:
    data = getattr(control, "data", None)
    if isinstance(data, dict) and data.get("kit") == "Disclosure":
        controls = getattr(control, "controls", ()) or ()
        return _visible_texts(controls[0]) if controls else []
    values = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.extend(_visible_texts(child))
    for name in ("content", "body"):
        child = getattr(control, name, None)
        if child is not None:
            values.extend(_visible_texts(child))
    return values


def _state():
    return SimpleNamespace(last_message="", last_export_path=None, local_audit_output=None, recent_activity=[], current_activity=None)


def test_renders_with_sample_data() -> None:
    result = chatgpt_audit.chatgpt_audit_page(SimpleNamespace(), _state())
    text = "\n".join(_texts(result))
    assert isinstance(result, PageView)
    assert all(title in text for title in ("Active product authority", "LLM thesis diary", "Manual note credibility", "Audit timeline", "External audit packet", "Import audit commentary", "Local LLM commentary"))
    assert "Traceback" not in text
    assert "executable_authority=false" not in "\n".join(_visible_texts(result))


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(chatgpt_audit, "_thesis_diary_rows", lambda: [])
    monkeypatch.setattr(chatgpt_audit, "_manual_note_credibility_text", lambda: "Unavailable: no manual notes are available.")
    monkeypatch.setattr(chatgpt_audit, "load_authority_matrix", lambda: SimpleNamespace(policy=None, checksum=None))
    result = chatgpt_audit.chatgpt_audit_page(SimpleNamespace(), _state())
    texts = _texts(result)
    assert isinstance(result, PageView)
    assert any("Unavailable" in value or "No persisted" in value or "No audit activity" in value for value in texts)
    assert "0" not in texts


def test_audit_timeline_is_bounded_dot_chart_when_empty() -> None:
    result = chatgpt_audit.chatgpt_audit_page(SimpleNamespace(), _state())
    controls = list(_walk(result))
    chart_handles = [getattr(control, "data", None) for control in controls]
    timeline = next(handle for handle in chart_handles if hasattr(handle, "scene") and handle.scene.title == "No audit activity")
    card = next(control for control in controls if isinstance(getattr(control, "data", None), dict) and control.data.get("kit") == "GlassCard" and control.data.get("title") == "Audit timeline")
    assert timeline.scene.empty
    assert "No dated local audit exports or imports" in timeline.scene.reason
    assert card.expand is True
    assert any(getattr(control, "scroll", None) == ft.ScrollMode.AUTO and control.expand is True for control in _walk(card))
    assert not any(type(control).__name__ == "ListView" for control in controls)


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for name in ("content", "body"):
        child = getattr(control, name, None)
        if child is not None:
            yield from _walk(child)
