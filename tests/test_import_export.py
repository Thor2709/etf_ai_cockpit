from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data import export_tables, import_export
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


@pytest.mark.parametrize(
    ("import_type", "columns"),
    [
        ("broker", {"as_of_date": ["2026-07-10"], "etf_id": ["A"], "units": [1], "market_price": [10], "market_value_eur": [10], "current_weight": [1]}),
        ("candidate", {"instrument_id": ["A"], "ticker": ["AAA"], "name": ["Example"]}),
        ("manual_notes", {"as_of_date": ["2026-07-10"], "note": ["review"]}),
        ("etf_holdings", {"as_of_date": ["2026-07-10"], "etf_id": ["A"], "holding_name": ["Issuer"], "weight": [0.5]}),
        ("news", {"published_at": ["2026-07-10T12:00:00Z"], "headline": ["Headline"], "url": ["https://example.test"]}),
    ],
)
def test_approved_import_shapes_validate_and_commit_only_after_preview(tmp_path: Path, import_type: str, columns: dict[str, list[object]]) -> None:
    source = tmp_path / f"{import_type}.csv"
    pd.DataFrame(columns).to_csv(source, index=False)
    preview = validate_import(import_type, source)
    assert preview.valid is True, preview.errors
    assert preview.preview_id
    assert callable(getattr(import_export, "commit_import", None))
    with pytest.raises(ValueError):
        import_export.commit_import("preview-not-registered")
    service = ImportService(tmp_path)
    service.register(preview)
    result = service.commit(preview.preview_id)
    assert result.status == "committed"
    assert result.destination.exists()
    assert result.execution_allowed is False


def test_export_result_reports_path_and_controlled_failure(tmp_path: Path) -> None:
    destination = tmp_path / "scoreboard.csv"
    result = export_table("scoreboard", pd.DataFrame({"score": [1]}), destination)
    assert isinstance(result, export_tables.ExportResult)
    assert result.ok is True
    assert result.destination == destination
    failed = export_table("scoreboard", None, destination)
    assert failed.ok is False
    assert "unavailable" in failed.error
