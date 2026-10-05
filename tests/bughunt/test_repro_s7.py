from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.core.settings_bundle import SettingsError


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S7-01: Private deletion follows links outside the application root")
def test_s7_01_private_root_link_cannot_delete_external_files(tmp_path, monkeypatch):
    from etf_cockpit.data.privacy import delete_private_data

    root = tmp_path / "app"
    (root / "data").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "keep.txt"
    victim.write_text("keep")
    private_root = root / "data" / "private"
    original_resolve = Path.resolve

    def resolve_link(path, *args, **kwargs):
        if path == private_root:
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_link)
    delete_private_data(root, confirmation="DELETE PRIVATE DATA")
    assert victim.exists()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S7-02: SQLite backups can omit committed WAL data")
def test_s7_02_backup_keeps_committed_wal_rows(tmp_path):
    import sqlite3

    from etf_cockpit.data.backup_restore import commit_restore, validate_restore
    from etf_cockpit.data.hybrid_platform import HybridPlatform

    with HybridPlatform(tmp_path / "source") as source:
        source.store.put("journal", "old", {"value": 1})
        source.store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        reader = sqlite3.connect(source.layout.transactional_path)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM transactional_records").fetchall()
        source.store.put("journal", "new", {"value": 2})
        source.store.connection.execute("PRAGMA busy_timeout=1")
        archive = source.create_backup(tmp_path / "backup.zip").archive
        reader.rollback()
        reader.close()
    target = tmp_path / "restored"
    preview = validate_restore(archive, destination=target)
    assert preview.valid and commit_restore(preview, target).ok
    with HybridPlatform(target) as restored:
        assert restored.store.get("journal", "new") is not None


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S7-03: Unreadable history is replaced with only the new run")
def test_s7_03_unreadable_history_is_not_replaced(tmp_path, monkeypatch):
    import pandas as pd

    import etf_cockpit.data.trust_artifacts as artifacts

    path = tmp_path / "history.parquet"
    path.write_bytes(b"damaged parquet")
    monkeypatch.setattr(artifacts, "log_event", lambda **kwargs: None)
    monkeypatch.setattr(artifacts, "wait_for_atomic_group", lambda *args: None)
    writes = []
    monkeypatch.setattr(artifacts, "_write_dual", lambda frame, dest: writes.append(frame.copy()) or dest)
    artifacts._append_parquet(
        path,
        pd.DataFrame([{"run_id": "new", "instrument_id": "X"}]),
        ["run_id", "instrument_id"],
        id_columns=["run_id", "instrument_id"],
    )
    assert writes == []


@pytest.mark.xfail(strict=True, raises=SettingsError, reason="S7-04: Universe saves invalidate otherwise valid saved settings")
def test_s7_04_universe_save_preserves_loadable_settings(tmp_path):
    from dataclasses import replace

    from etf_cockpit.core.settings_bundle import load_settings_bundle, save_settings
    from etf_cockpit.data.universe_store import UniverseRecord, save_universe

    record = UniverseRecord("X", "X", ticker="X", isin_status="needs_verification")
    universe = save_universe([record], "", root=tmp_path)
    bundle = load_settings_bundle(tmp_path)
    controls = bundle.controls.model_copy(update={"analysis_depth": "quick"})
    save_settings(bundle.model_copy(update={"controls": controls}), expected_revision=bundle.revision, root=tmp_path)
    save_universe([replace(record, name="Renamed")], universe.revision, root=tmp_path)
    assert load_settings_bundle(tmp_path).universe["count"] == 1


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S7-05: Nonfinite financial inputs pass data-quality validation")
def test_s7_05_missing_close_blocks_prices():
    from datetime import date

    import pandas as pd

    from etf_cockpit.data.validation import validate_prices

    prices = pd.DataFrame(
        {
            "date": pd.bdate_range(end="2026-10-05", periods=252),
            "etf_id": "X",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": float("nan"),
            "adjusted_close": 10.0,
            "volume": 1,
            "currency": "EUR",
        }
    )
    report = validate_prices(prices, as_of_date=date(2026, 10, 5))
    assert report.status == "Blocked"
    assert not report.analysis_allowed


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S7-08: Unavailable authority decisions become complete analysis")
def test_s7_08_unavailable_decision_stays_unavailable():
    from dataclasses import replace
    from datetime import date

    from etf_cockpit.core.research_states import ResearchState
    from etf_cockpit.core.types import ComponentScores, SignalResult
    from etf_cockpit.governance.gate_policy import resolve_authority

    signal = SignalResult(
        "r",
        date(2026, 10, 5),
        "X",
        "watch",
        0,
        0,
        ComponentScores(*([0.0] * 12)),
        [],
        [],
        "reason",
        "reason",
        "3M",
    )
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, [], None)
    assert decision.analysis_status == "unavailable"
    signal = replace(signal, authority_decision=decision)
    assert signal.to_v2_dict()["analysis_status"] == "unavailable"
