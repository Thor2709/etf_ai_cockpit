from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.data.privacy import (
    PrivacyDeletionError,
    delete_private_data,
    export_redacted_records,
    redact_private_fields,
)


def test_standard_export_omits_private_fields_recursively(tmp_path: Path) -> None:
    records = [{"decision": "hold", "private_notes": "do not export", "nested": {"password": "secret"}}]

    redacted = redact_private_fields(records)
    assert redacted == [{"decision": "hold", "nested": {}}]
    result = export_redacted_records(records, tmp_path / "export.json")
    assert result.rows == 1
    content = result.path.read_text(encoding="utf-8")
    assert "private_notes" not in content
    assert "do not export" not in content


def test_private_export_requires_explicit_opt_in(tmp_path: Path) -> None:
    records = [{"decision": "hold", "private_notes": "keep"}]
    with pytest.raises(PrivacyDeletionError, match="explicit private export"):
        export_redacted_records(records, tmp_path / "private.json", include_private=True)
    result = export_redacted_records(records, tmp_path / "private.json", include_private=True, confirm_private=True)
    assert json.loads(result.path.read_text(encoding="utf-8"))[0]["private_notes"] == "keep"


def test_private_data_deletion_requires_confirmation_and_is_scoped(tmp_path: Path) -> None:
    private_root = tmp_path / "data" / "private"
    private_root.mkdir(parents=True)
    (private_root / "note.txt").write_text("private", encoding="utf-8")
    with pytest.raises(PrivacyDeletionError, match="confirmation"):
        delete_private_data(tmp_path, confirmation="no")
    deleted = delete_private_data(tmp_path, confirmation="DELETE PRIVATE DATA")
    assert deleted == (private_root / "note.txt",)
    assert not (private_root / "note.txt").exists()
