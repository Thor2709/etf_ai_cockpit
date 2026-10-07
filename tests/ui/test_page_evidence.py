from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import trust_evidence


def _texts(control: object) -> list[str]:
    values: list[str] = []
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


def test_renders_with_sample_data() -> None:
    result = trust_evidence.evidence_ledger_page(SimpleNamespace(), SimpleNamespace())
    text = "\n".join(_texts(result))
    assert isinstance(result, PageView)
    assert all(title in text for title in ("Evidence tables", "Rows by evidence table", "Boundaries"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(trust_evidence, "_read_frame", lambda _path: pd.DataFrame())
    result = trust_evidence.evidence_ledger_page(SimpleNamespace(), SimpleNamespace())
    texts = _texts(result)
    assert isinstance(result, PageView)
    assert any("Unavailable" in value or "No rows" in value for value in texts)
    body = result.body
    tables = []
    stack = [body]
    while stack:
        control = stack.pop()
        if hasattr(control, "rows"):
            tables.extend(getattr(control, "rows", ()) or ())
        stack.extend(getattr(control, "controls", ()) or ())
        child = getattr(control, "content", None)
        if child is not None:
            stack.append(child)
    assert all(
        getattr(getattr(cell, "content", None), "value", None) != "0"
        for table in tables
        for cell in getattr(table, "cells", ())
    )
