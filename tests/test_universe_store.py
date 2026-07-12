from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from etf_cockpit.data.universe_store import (
    UniverseRecord,
    UniverseRevisionConflict,
    add_record,
    disable_record,
    edit_record,
    export_compatibility,
    import_legacy_universe,
    load_universe,
    migrate_legacy_universe,
    remove_record,
    save_universe,
    validate_universe,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.app.pages.universe_manager import filter_records


def _record(instrument_id: str, *, isin: str = "NO0000000001", ticker: str | None = None, tier: str = "primary") -> UniverseRecord:
    return UniverseRecord(instrument_id, instrument_id, isin, "verified", ticker or instrument_id, "stock", tier, "stocks/equity certificates", True, "daily", "NOK", "NO", "", "", "")


def test_duplicate_identity_and_unknown_isin_are_explicit(tmp_path: Path) -> None:
    records = [_record("A", isin="needs_verification"), _record("B", isin="needs_verification", ticker="A")]
    report = validate_universe(records)
    assert report.valid is False
    assert any("ticker" in issue for issue in report.errors)
    assert report.unknown_isin_ids == ("A", "B")


def test_save_uses_revision_conflict_protection(tmp_path: Path) -> None:
    records = [_record("A")]
    first = save_universe(records, expected_revision="", root=tmp_path)
    assert first.revision
    with pytest.raises(UniverseRevisionConflict):
        save_universe(records, expected_revision="wrong", root=tmp_path)
    second = save_universe(records + [_record("B", isin="NO0000000002", ticker="B")], expected_revision=first.revision, root=tmp_path)
    assert second.revision != first.revision
    assert (tmp_path / "configs" / "universe_store.json").exists()


def test_saved_universe_is_the_canonical_config_input(tmp_path: Path) -> None:
    source_configs = Path(__file__).resolve().parents[1] / "configs"
    target_configs = tmp_path / "configs"
    shutil.copytree(source_configs, target_configs)
    save_universe([_record("ONLY", ticker="ONLY.OL")], expected_revision="", root=tmp_path)

    config = load_config(target_configs)

    assert config.universe.enabled_ids == ["ONLY"]
    assert config.universe.by_id()["ONLY"].provider_symbol == "ONLY.OL"


def test_crud_operations_validate_and_mark_pending_refresh_without_running_workflows() -> None:
    records = [_record("A")]
    added = add_record(records, _record("B", isin="NO0000000002", ticker="B", tier="secondary"))
    edited = edit_record(added, "B", notes="review me", sector="Banks")
    disabled = disable_record(edited, "B")
    remaining = remove_record(disabled, "A")
    assert len(remaining) == 1
    assert remaining[0].enabled is False
    assert remaining[0].notes == "review me"


def test_legacy_import_keeps_sparebanken_rows_and_unknown_isin_states(tmp_path: Path) -> None:
    primary = tmp_path / "universe.yaml"
    primary.write_text("etfs:\n  - id: CORE\n    name: Core\n    ticker: CORE.OL\n    isin: NO0000000001\n    instrument_type: stock\n    analysis_tier: primary\n", encoding="utf-8")
    candidate = tmp_path / "candidates.csv"
    candidate.write_text("name,symbol,yahoo_symbol,isin,analysis_tier,asset_type\nAurskog Sparebank,AURG,AURG.OL,needs_verification,sparebanken,equity_certificate\n", encoding="utf-8")
    result = import_legacy_universe(primary, candidate)
    rows = tuple(result.records)
    assert len([row for row in rows if row.tier == "sparebanken"]) == 15
    assert any(row.ticker == "AURG.OL" and row.isin_status == "needs_verification" for row in rows)
    assert any(row.instrument_id == "CORE" for row in rows)


def test_save_creates_backup_and_compatibility_exports(tmp_path: Path) -> None:
    records = [_record("A")]
    first = save_universe(records, expected_revision="", root=tmp_path)
    second = save_universe(records + [_record("B", isin="NO0000000002", ticker="B")], expected_revision=first.revision, root=tmp_path)
    assert second.backup_path is not None and second.backup_path.exists()
    loaded = load_universe(tmp_path)
    assert len(loaded.records) == 2
    outputs = export_compatibility(loaded.records, tmp_path / "exports")
    assert outputs.yaml_path.exists() and outputs.csv_path.exists()


def test_universe_filter_is_case_insensitive_and_tier_scoped() -> None:
    rows = (_record("CORE", ticker="CORE.OL"), _record("BANK", ticker="BANK.OL", tier="secondary", isin="NO0000000002"))
    assert filter_records(rows, "bank", tier="secondary")[0].instrument_id == "BANK"
    assert filter_records(rows, "missing") == ()


def test_legacy_migration_publishes_versioned_store(tmp_path: Path) -> None:
    primary = tmp_path / "configs" / "universe.yaml"
    primary.parent.mkdir(parents=True)
    primary.write_text("etfs:\n  - id: CORE\n    name: Core\n    ticker: CORE.OL\n    isin: NO0000000001\n", encoding="utf-8")
    imported, saved = migrate_legacy_universe(tmp_path)
    assert imported.records and saved.path.name == "universe_store.json"
    assert load_universe(tmp_path).revision == saved.revision
