from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from etf_cockpit.data.universe_store import (
    UniverseRecord,
    UniverseRevisionConflict,
    save_universe,
    validate_universe,
)
from etf_cockpit.core.config import load_config


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
