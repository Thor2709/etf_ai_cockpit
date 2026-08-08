from __future__ import annotations

from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.services import build_snapshot


def _text_values(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for child in getattr(control, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    return values


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_issue0010_instrument_detail_exposes_non_executable_thesis_diary() -> None:
    snapshot = build_snapshot()
    state = type("State", (), {"snapshot": snapshot, "selected_etf": "VWCE", "last_export_path": None, "last_message": "Ready"})()

    control = instrument_detail_page(None, state)
    thesis_diary = next(item for item in _walk(control) if getattr(item, "key", "") == "instrument-detail.thesis-diary")
    diary_text = "\n".join(_text_values(thesis_diary))

    assert "LLM thesis diary" in diary_text
    assert "execution_allowed=false" in diary_text
