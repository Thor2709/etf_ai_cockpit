from __future__ import annotations

import shutil
import json
from pathlib import Path

import pytest
import etf_cockpit.data.universe_store as universe_store

from etf_cockpit.data.universe_store import (
    CURRENT_INVESTABILITY_POLICY_VERSION,
    SPAREBANKEN_ROWS,
    InvestabilityPolicyProfile,
    UniverseRecord,
    UniverseRevisionConflict,
    add_record,
    build_policy_backfill_plan,
    create_policy_profile,
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


def test_legacy_policy_backfill_plan_is_deterministic_inspectable_and_non_mutating(
    tmp_path: Path,
) -> None:
    path = tmp_path / "configs" / "universe_store.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "revision": "legacy-revision",
                "records": [universe_store.asdict(_record("A"))],
            }
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    snapshot = load_universe(tmp_path)
    assert snapshot.policy_evidence[0].state == "legacy_unmigrated"

    first = build_policy_backfill_plan(snapshot)
    second = build_policy_backfill_plan(snapshot)

    assert first == second
    assert first.mutates_store is False
    assert first.execution_allowed is False
    assert first.actions[0].action == "review_legacy"
    assert path.read_bytes() == before

    saved = save_universe(snapshot.records, snapshot.revision, root=tmp_path)
    after_legacy_edit = load_universe(tmp_path)
    assert saved.revision == after_legacy_edit.revision
    assert after_legacy_edit.schema_version == 2
    assert after_legacy_edit.policy_evidence[0].state == "legacy_unmigrated"


def test_policy_profile_round_trip_and_policy_version_change_marks_recompute(
    tmp_path: Path,
) -> None:
    record = _record("A")
    stale = create_policy_profile(
        instrument_id="A",
        policy_id="safe-long-only",
        policy_version="investability-v0",
        source_id="local-reviewed-policy",
        as_of="2026-07-28T00:00:00+00:00",
        authority="user_reviewed",
        coverage=("prices", "classification"),
        classification_confidence=0.9,
        dependency_plan=("prices:A",),
    )
    saved = save_universe((record,), "", root=tmp_path, policy_profiles=(stale,))
    snapshot = load_universe(tmp_path)

    assert saved.revision == snapshot.revision
    assert snapshot.policy_profiles == (stale,)
    assert snapshot.policy_evidence[0].state == "stale"
    assert snapshot.policy_evidence[0].recompute_required is True
    plan = build_policy_backfill_plan(snapshot)
    assert plan.actions[0].from_policy_version == "investability-v0"
    assert plan.actions[0].to_policy_version == CURRENT_INVESTABILITY_POLICY_VERSION

    current = create_policy_profile(
        instrument_id="A",
        policy_id="safe-long-only",
        policy_version=CURRENT_INVESTABILITY_POLICY_VERSION,
        source_id="local-reviewed-policy",
        as_of="2026-07-28T00:00:00+00:00",
        authority="user_reviewed",
        coverage=("classification", "prices"),
        classification_confidence=0.9,
        dependency_plan=("prices:A",),
    )
    save_universe(
        (record,),
        snapshot.revision,
        root=tmp_path,
        policy_profiles=(current,),
    )
    refreshed = load_universe(tmp_path)
    assert refreshed.policy_evidence[0].state == "current"
    assert refreshed.policy_evidence[0].recompute_required is False
    assert build_policy_backfill_plan(refreshed).actions == ()


def test_tampered_or_unauthorised_policy_profile_fails_closed(tmp_path: Path) -> None:
    profile = create_policy_profile(
        instrument_id="A",
        policy_id="safe-long-only",
        policy_version=CURRENT_INVESTABILITY_POLICY_VERSION,
        source_id="official-prospectus",
        as_of="2026-07-28T00:00:00Z",
        authority="official",
    )
    save_universe((_record("A"),), "", root=tmp_path, policy_profiles=(profile,))
    path = tmp_path / "configs" / "universe_store.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["policy_profiles"][0]["coverage"] = ["invented"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    snapshot = load_universe(tmp_path)
    assert snapshot.policy_profiles == ()
    assert snapshot.policy_evidence[0].state == "manual_review"
    assert "checksum mismatch" in snapshot.policy_evidence[0].reason
    assert snapshot.policy_evidence[0].execution_allowed is False

    with pytest.raises(ValueError, match="unsupported policy authority"):
        create_policy_profile(
            instrument_id="A",
            policy_id="unsafe",
            policy_version=CURRENT_INVESTABILITY_POLICY_VERSION,
            source_id="unknown",
            as_of="2026-07-28T00:00:00Z",
            authority="model_generated",
        )
    with pytest.raises(ValueError, match="integrity failed"):
        save_universe(
            (_record("A"),),
            str(payload["revision"]),
            root=tmp_path,
            policy_profiles=(InvestabilityPolicyProfile(**{**universe_store.asdict(profile), "checksum": "bad"}),),
        )


def test_policy_profile_save_failure_leaves_prior_revision_atomic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    saved = save_universe((_record("A"),), "", root=tmp_path)
    path = tmp_path / "configs" / "universe_store.json"
    before = path.read_bytes()

    def fail_atomic_write(*_args, **_kwargs):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(universe_store, "atomic_write_json", fail_atomic_write)
    with pytest.raises(OSError, match="simulated publication failure"):
        save_universe((_record("A"),), saved.revision, root=tmp_path)
    assert path.read_bytes() == before


def _valid_v3_payload(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    profile = create_policy_profile(
        instrument_id="A",
        policy_id="safe-long-only",
        policy_version=CURRENT_INVESTABILITY_POLICY_VERSION,
        source_id="official-prospectus",
        as_of="2026-07-28T00:00:00Z",
        authority="official",
    )
    save_universe((_record("A"),), "", root=tmp_path, policy_profiles=(profile,))
    path = tmp_path / "configs" / "universe_store.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_v3_revision_mismatch_is_manual_review_and_cannot_be_saved(
    tmp_path: Path,
) -> None:
    path, payload = _valid_v3_payload(tmp_path)
    payload["records"][0]["name"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()

    snapshot = load_universe(tmp_path)

    assert snapshot.integrity_errors == ("store revision checksum mismatch",)
    assert snapshot.policy_evidence[0].state == "manual_review"
    with pytest.raises(ValueError, match="store revision checksum mismatch"):
        save_universe(snapshot.records, snapshot.revision, root=tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("corruption", "fingerprint"),
    (
        ("duplicate_profile", "duplicate policy profile: A"),
        ("non_object_profile", "policy profile 1 must be an object"),
        ("unknown_profile", "unknown instrument_id: B"),
        ("malformed_profiles_collection", "policy_profiles must be a list"),
        ("malformed_profile_collection_field", "coverage must be a list of strings"),
        ("duplicate_record", "duplicate universe record: A"),
        ("schema_boolean", "schema_version must be a non-negative integer"),
    ),
)
def test_v3_structural_corruption_is_deterministic_and_non_destructive(
    tmp_path: Path,
    corruption: str,
    fingerprint: str,
) -> None:
    path, payload = _valid_v3_payload(tmp_path)
    if corruption == "duplicate_profile":
        payload["policy_profiles"].append(dict(payload["policy_profiles"][0]))
    elif corruption == "non_object_profile":
        payload["policy_profiles"].append("not-an-object")
    elif corruption == "unknown_profile":
        unknown = create_policy_profile(
            instrument_id="B",
            policy_id="safe-long-only",
            policy_version=CURRENT_INVESTABILITY_POLICY_VERSION,
            source_id="official-prospectus",
            as_of="2026-07-28T00:00:00Z",
            authority="official",
        )
        payload["policy_profiles"].append(
            {
                **universe_store._policy_profile_payload(unknown),
                "checksum": unknown.checksum,
            }
        )
    elif corruption == "malformed_profiles_collection":
        payload["policy_profiles"] = {"A": payload["policy_profiles"][0]}
    elif corruption == "malformed_profile_collection_field":
        payload["policy_profiles"][0]["coverage"] = {"prices": True}
    elif corruption == "duplicate_record":
        payload["records"].append(dict(payload["records"][0]))
    elif corruption == "schema_boolean":
        payload["schema_version"] = True
    payload["revision"] = universe_store._payload_revision(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()

    first = load_universe(tmp_path)
    second = load_universe(tmp_path)

    assert first.integrity_errors == second.integrity_errors
    assert any(fingerprint in error for error in first.integrity_errors)
    assert first.policy_profiles == ()
    assert all(item.state == "manual_review" for item in first.policy_evidence)
    for profiles in (None, ()):
        kwargs = {} if profiles is None else {"policy_profiles": profiles}
        with pytest.raises(ValueError, match="Universe store"):
            save_universe(
                first.records,
                first.revision,
                root=tmp_path,
                **kwargs,
            )
    assert path.read_bytes() == before
    assert not (tmp_path / "backups" / "universe").exists()
