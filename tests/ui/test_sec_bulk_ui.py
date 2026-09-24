from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from etf_cockpit.app.pages import trust_evidence as ui


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from _walk(content)


@pytest.mark.parametrize("dataset", ["companyfacts", "submissions"])
def test_bulk_callbacks_are_explicit_native_and_guarded(tmp_path, monkeypatch, dataset):
    calls = []
    archive = tmp_path / "local.zip"
    archive.write_bytes(b"fixture")
    async def pick_files(**kwargs):
        assert kwargs["with_data"] is False
        return [SimpleNamespace(path=str(archive))]
    monkeypatch.setattr(ui, "_attach_picker", lambda *_: SimpleNamespace(pick_files=pick_files))
    def action(*args, **kwargs):
        with kwargs["publish_guard"]():
            calls.append((args, kwargs))
        return "partial; execution_allowed=false"
    state = SimpleNamespace(selected_etf="ETF", last_message="Ready", activity_publication=lambda _: nullcontext(),
        import_sec_companyfacts_bulk=action, import_sec_submissions_bulk=action,
        fetch_sec_companyfacts_bulk=action, fetch_sec_submissions_bulk=action)
    monkeypatch.setattr(ui, "_run_picker_activity", lambda page, state, result, label, step, file, suffix, callback: callback(file.path, "action"))
    monkeypatch.setattr(ui, "_run_official_filing_action", lambda page, state, result, label, step, callback: callback("action"))
    controls = {getattr(c, "key", None): c for c in _walk(ui._filing_import_controls(SimpleNamespace(update=lambda: None), state))}
    assert calls == []
    controls["filings.sec-bulk-dataset"].value = dataset
    controls["filings.sec-cik"].value = "1"
    controls["filings.sec-bulk-instrument"].value = "ONE"
    for key in ("filings.import-sec-bulk", "filings.fetch-sec-bulk", "filings.cache-sec-bulk"):
        asyncio.run(controls[key].on_click(None))
    assert len(calls) == 3
    assert calls[0][1]["instrument_id"] == "ONE"
    assert calls[1][1]["cache_only"] is False
    assert calls[2][1]["cache_only"] is True


@pytest.mark.parametrize("files", [[], [SimpleNamespace(path=None)]])
def test_bulk_cancel_or_missing_native_path_does_not_start_action(monkeypatch, files):
    async def pick_files(**kwargs):
        assert kwargs["with_data"] is False
        return files
    monkeypatch.setattr(ui, "_attach_picker", lambda *_: SimpleNamespace(pick_files=pick_files))
    monkeypatch.setattr(ui, "_run_picker_activity", lambda *_: pytest.fail("must not start import"))
    state = SimpleNamespace(selected_etf="ETF", last_message="Ready")
    controls = {getattr(c, "key", None): c for c in _walk(ui._filing_import_controls(SimpleNamespace(update=lambda: None), state))}
    asyncio.run(controls["filings.import-sec-bulk"].on_click(None))
