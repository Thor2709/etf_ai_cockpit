from __future__ import annotations

import shutil
import json
from pathlib import Path

import pytest

from etf_cockpit.data.universe_store import (
    SPAREBANKEN_ROWS,
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
from etf_cockpit.core.config import _load_universe_config, load_config
from etf_cockpit.app.pages.universe_manager import filter_records


def _record(instrument_id: str, *, isin: str = "NO0000000001", ticker: str | None = None, tier: str = "primary") -> UniverseRecord:
    return UniverseRecord(instrument_id, instrument_id, isin, "verified", ticker or instrument_id, "stock", tier, "stocks/equity certificates", True, "daily", "NOK", "NO", "", "", "")


def test_duplicate_identity_and_unknown_isin_are_explicit(tmp_path: Path) -> None:
    records = [_record("A", isin="needs_verification"), _record("B", isin="needs_verification", ticker="A")]
    report = validate_universe(records)
    assert report.valid is False
    assert any("ticker" in issue for issue in report.errors)
    assert report.unknown_isin_ids == ("A", "B")


def test_malformed_ticker_is_rejected_without_inventing_isin() -> None:
    malformed = _record("BAD", isin="needs_verification", ticker="!!!")
    report = validate_universe([malformed])
    assert report.valid is False
    assert any("malformed ticker" in error for error in report.errors)
    assert report.unknown_isin_ids == ("BAD",)


def test_cross_tier_duplicate_override_is_explicit() -> None:
    records = [_record("A", ticker="DUP", tier="primary"), _record("A", ticker="DUP", tier="secondary", isin="NO0000000002")]
    rejected = validate_universe(records)
    assert rejected.valid is False
    accepted = validate_universe(records, allow_cross_tier_duplicates=True)
    assert accepted.valid is True
    assert any("override" in warning for warning in accepted.warnings)


def test_crud_and_save_thread_cross_tier_override(tmp_path: Path) -> None:
    primary = _record("A", ticker="DUP", tier="primary")
    secondary = _record("A", ticker="DUP", tier="secondary", isin="NO0000000002")
    with pytest.raises(ValueError):
        add_record([primary], secondary)
    added = add_record([primary], secondary, allow_cross_tier_duplicates=True)
    assert len(added) == 2
    other = _record("B", ticker="B", tier="secondary", isin="NO0000000003")
    with pytest.raises(ValueError):
        edit_record([primary, other], "B", ticker="DUP")
    edited = edit_record([primary, other], "B", ticker="DUP", allow_cross_tier_duplicates=True)
    assert edited[1].ticker == "DUP"
    with pytest.raises(ValueError):
        save_universe(added, expected_revision="", root=tmp_path)
    saved = save_universe(added, expected_revision="", root=tmp_path, allow_cross_tier_duplicates=True)
    assert saved.record_count == 2
    assert json.loads(saved.path.read_text(encoding="utf-8"))["allow_cross_tier_duplicates"] is True


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


def test_primary_sparebanken_identity_is_replaced_by_authoritative_fallback(tmp_path: Path) -> None:
    primary = tmp_path / "universe.yaml"
    primary.write_text(
        "etfs:\n  - id: NONG\n    name: Wrong primary\n    ticker: NONG.OL\n    isin: NO0006000801\n    analysis_tier: primary\n",
        encoding="utf-8",
    )
    result = import_legacy_universe(primary)
    nong = [row for row in result.records if row.instrument_id.casefold() == "nong"]
    assert len(nong) == 1
    assert nong[0].tier == "sparebanken"
    assert nong[0].name == "SpareBank 1 Nord-Norge"
    assert sum(row.tier == "sparebanken" for row in result.records) == 15


def test_secondary_nong_is_replaced_by_authoritative_sparebanken_fallback(tmp_path: Path) -> None:
    primary = tmp_path / "universe.yaml"
    primary.write_text("etfs:\n", encoding="utf-8")
    candidate = tmp_path / "candidates.csv"
    candidate.write_text(
        "instrument_id,name,ticker,isin,analysis_tier,asset_type\n"
        "NONG,Wrong secondary,NONG.OL,NO0006000801,secondary,stock\n",
        encoding="utf-8",
    )
    result = import_legacy_universe(primary, candidate)
    nong = [row for row in result.records if row.instrument_id.casefold() == "nong"]
    assert len(nong) == 1
    assert nong[0].tier == "sparebanken"
    assert nong[0].name == "SpareBank 1 Nord-Norge"
    assert sum(row.tier == "sparebanken" for row in result.records) == 15


def test_sparebanken_yaml_and_legacy_import_paths_have_identical_identity(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True)
    source_yaml = Path(__file__).resolve().parents[1] / "configs" / "universe.yaml"
    shutil.copyfile(source_yaml, config_dir / "universe.yaml")

    without_candidates = _load_universe_config(config_dir)
    candidates_dir = tmp_path / "data" / "raw" / "trade_candidates"
    candidates_dir.mkdir(parents=True)
    (candidates_dir / "yahoo_trade_candidates_20260714.csv").write_text(
        "instrument_id,name,ticker,analysis_tier\n", encoding="utf-8"
    )
    with_candidates = _load_universe_config(config_dir)

    expected = {
        instrument_id: (name, ticker, None if _isin == "needs_verification" else _isin)
        for name, instrument_id, ticker, _isin in SPAREBANKEN_ROWS
    }
    for config in (without_candidates, with_candidates):
        actual = {
            record.id: (record.name, record.ticker, record.isin)
            for record in config.etfs
            if record.id in expected
        }
        assert actual == expected
    assert {
        record.id: (record.name, record.ticker, record.isin)
        for record in without_candidates.etfs
        if record.id in expected
    } == {
        record.id: (record.name, record.ticker, record.isin)
        for record in with_candidates.etfs
        if record.id in expected
    }


def test_leveraged_inverse_state_round_trips_and_is_not_score_eligible(tmp_path: Path) -> None:
    record = _record("LEV", ticker="LEV", isin="NO0000000003")
    record = UniverseRecord(**{**record.__dict__, "leveraged": True})
    saved = save_universe([record], expected_revision="", root=tmp_path)
    loaded = load_universe(tmp_path).records[0]
    assert loaded.leveraged is True
    assert validate_universe([loaded]).valid is True
    assert loaded.enabled is True
    assert saved.revision


def test_save_creates_backup_and_compatibility_exports(tmp_path: Path) -> None:
    records = [_record("A")]
    first = save_universe(records, expected_revision="", root=tmp_path)
    second = save_universe(records + [_record("B", isin="NO0000000002", ticker="B")], expected_revision=first.revision, root=tmp_path)
    assert second.backup_path is not None and second.backup_path.exists()
    loaded = load_universe(tmp_path)
    assert len(loaded.records) == 2
    outputs = export_compatibility(loaded.records, tmp_path / "exports")
    assert outputs.yaml_path.exists() and outputs.csv_path.exists()


def test_load_snapshot_preserves_cross_tier_override_state(tmp_path: Path) -> None:
    saved = save_universe(
        [_record("A", ticker="A", tier="primary"), _record("A", ticker="A", tier="secondary", isin="NO0000000002")],
        expected_revision="",
        root=tmp_path,
        allow_cross_tier_duplicates=True,
    )
    snapshot = load_universe(tmp_path)
    assert snapshot.revision == saved.revision
    assert snapshot.allow_cross_tier_duplicates is True


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
