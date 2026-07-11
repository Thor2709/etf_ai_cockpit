from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.export_tables import export_table
from etf_cockpit.data.import_export import ImportService, validate_import


def test_import_requires_preview_before_commit_and_exports_table(tmp_path: Path) -> None:
    source = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2026-07-10"], "etf_id": ["A"], "adjusted_close": [100.0]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    assert preview.valid is True
    service = ImportService(tmp_path)
    service.register(preview)
    result = service.commit(preview.preview_id)
    assert result.rows == 1
    destination = tmp_path / "export.csv"
    export_table("prices", result.frame, destination)
    assert destination.exists()


def test_invalid_import_does_not_commit(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    pd.DataFrame({"bad": [1]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    assert preview.valid is False
    with pytest.raises(ValueError):
        ImportService(tmp_path).commit(preview.preview_id)


def test_import_commit_preserves_previous_parquet_on_locked_replace(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2026-07-10"], "etf_id": ["A"], "adjusted_close": [100.0]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    service = ImportService(tmp_path)
    service.register(preview)
    destination = tmp_path / "data" / "clean" / "prices.parquet"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    real_replace = Path.replace

    def fail_replace(self: Path, target: Path):
        if Path(target) == destination:
            raise PermissionError("destination locked")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError, match="destination locked"):
        service.commit(preview.preview_id)
    assert destination.read_bytes() == b"old"
