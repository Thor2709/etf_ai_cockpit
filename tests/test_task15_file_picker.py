from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pandas as pd

import etf_cockpit.app.pages.trust_evidence as trust_evidence
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def test_web_file_picker_bytes_are_materialised_and_removed_after_import() -> None:
    """Web FilePicker returns bytes without a filesystem path; imports need a temporary path."""

    selected = SimpleNamespace(path=None, bytes=b"%PDF-1.7 uploaded fixture")
    materialise = getattr(trust_evidence, "_materialise_picker_file")

    with materialise(selected, suffix=".pdf") as path:
        assert path is not None
        assert path.read_bytes() == selected.bytes
        temporary_path = path

    assert not temporary_path.exists()


def test_web_file_picker_source_is_retained_at_durable_raw_path(tmp_path, monkeypatch) -> None:
    selected = SimpleNamespace(path=None, bytes=b"%PDF-1.7 uploaded fixture")
    monkeypatch.setattr(trust_evidence, "RAW_DIR", tmp_path / "raw")

    with trust_evidence._materialise_picker_file(selected, suffix=".pdf") as path:
        retained = trust_evidence._retain_picker_source(path, "priips_kids")

    assert retained.is_file()
    assert retained.parent == tmp_path / "raw" / "priips_kids"
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == hashlib.sha256(selected.bytes).hexdigest()


def test_latest_document_row_uses_newest_version_and_real_checksum() -> None:
    registry = pd.DataFrame(
        [
            {"document_type": "kid", "document_date": "2026-07-15", "source_id": "new", "sha256": "new-checksum"},
            {"document_type": "kid", "document_date": "2026-07-01", "source_id": "old", "sha256": "old-checksum"},
        ]
    )

    row = trust_evidence._latest_document_row(registry, "kid")

    assert row is not None
    assert row["source_id"] == "new"
    assert trust_evidence._document_checksum(row) == "new-checksum"


def test_import_progress_is_visible_and_durable_on_activity_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    result = SimpleNamespace(value="")

    trust_evidence._start_disclosure_import(state, result, "Import PRIIPs KID")

    assert state.current_activity is not None
    assert state.current_activity.status == "running"
    assert state.current_activity.step == "Reading selected document"
    assert "in progress" in result.value.lower()
