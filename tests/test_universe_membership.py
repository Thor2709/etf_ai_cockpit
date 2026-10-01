from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

import etf_cockpit.data.universe_membership as universe_membership
from etf_cockpit.analysis.decision import rank_validation
from etf_cockpit.analysis.decision.rank_validation import load_rank_validation_policy, replay_rank_panel
from etf_cockpit.data.universe_store import UniverseRecord, load_universe, save_universe
from etf_cockpit.data.catalogue import DataCatalogue
from etf_cockpit.portfolio.costs import COST_MODEL_ID


_SCOPE = "listing:euronext_oslo:all"


def _known(day: int, hour: int = 12) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=timezone.utc)


def _record(instrument_id: str, isin_suffix: str) -> UniverseRecord:
    return UniverseRecord(
        instrument_id=instrument_id,
        name=instrument_id,
        isin=f"NO00000000{isin_suffix}",
        ticker=instrument_id,
        tier="primary",
    )


def test_captures_are_deduplicated_and_membership_is_interval_based(tmp_path: Path) -> None:
    first_payload = b'[{"instrument_id":"A"},{"instrument_id":"B"}]'
    third_payload = b'[{"instrument_id":"A"},{"instrument_id":"C"}]'
    first = universe_membership.record_listing_capture(first_payload, "fixture", _SCOPE, _known(1), root=tmp_path)
    second = universe_membership.record_listing_capture(first_payload, "fixture", _SCOPE, _known(2), root=tmp_path)
    third = universe_membership.record_listing_capture(third_payload, "fixture", _SCOPE, _known(3), root=tmp_path)

    assert first.checksum == second.checksum
    capture_rows = universe_membership.capture_log(_SCOPE, root=tmp_path)
    assert len(capture_rows) == 3
    assert set(capture_rows["source_id"]) == {"fixture"}
    assert set(capture_rows["row_count"]) == {2}
    assert universe_membership.load_raw_payload(first.checksum, root=tmp_path) == first_payload
    assert len(list((tmp_path / "data" / "raw" / "universe_membership").glob("*.payload.gz"))) == 2
    catalogue = DataCatalogue(tmp_path)
    snapshots = {item.snapshot_id: item for item in catalogue.snapshots}
    assert any(
        snapshots[edge.upstream_snapshot_id].dataset_id == "universe_membership_raw"
        and snapshots[edge.downstream_snapshot_id].dataset_id == "universe_membership_intervals"
        for edge in catalogue.lineage
    )

    intervals = universe_membership.membership_intervals(_SCOPE, _known(3), root=tmp_path)
    indexed = intervals.set_index("instrument_id")
    assert indexed.loc["A", "valid_from"] == "2024-01-01"
    assert pd.isna(indexed.loc["A", "valid_to"])
    assert indexed.loc["B", "valid_from"] == "2024-01-01"
    assert indexed.loc["B", "valid_to"] == "2024-01-03"
    assert indexed.loc["C", "valid_from"] == "2024-01-03"
    assert pd.isna(indexed.loc["C", "valid_to"])
    assert third.checksum != first.checksum


def test_membership_frame_is_point_in_time_and_replays_rank_validation(tmp_path: Path) -> None:
    cutoff = datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc)
    prior = cutoff - timedelta(days=1)
    universe_membership.record_listing_capture(
        [{"instrument_id": "DELISTED"}, {"instrument_id": "SURVIVOR"}],
        "fixture",
        _SCOPE,
        datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc),
        root=tmp_path,
    )
    universe_membership.record_listing_capture(
        [{"instrument_id": "DELISTED"}, {"instrument_id": "SURVIVOR"}, {"instrument_id": "LATER"}],
        "fixture",
        _SCOPE,
        datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
        root=tmp_path,
    )
    memberships = universe_membership.membership_frame(_SCOPE, cutoff, root=tmp_path)

    assert set(memberships.columns) == rank_validation._MEMBERSHIP_COLUMNS
    assert set(memberships["instrument_id"]) == {"DELISTED", "SURVIVOR"}
    assert set(memberships["snapshot_date"].astype(str)) == {"2024-01-01"}

    evidence_rows = []
    costs_rows = []
    price_rows = []
    for instrument_id, quality, value, momentum, v3 in (
        ("DELISTED", 0.5, 0.4, 0.3, 0.2),
        ("SURVIVOR", 0.2, 0.6, 0.7, 0.4),
    ):
        evidence_rows.append(
            {
                "instrument_id": instrument_id,
                "effective_at": prior,
                "known_at": prior,
                "quality_score": quality,
                "value_score": value,
                "momentum_score": momentum,
                "v3_score": v3,
                "sector": "technology",
                "size_bucket": "large",
                "size_value": 1_000_000.0,
            }
        )
        costs_rows.append(
            {
                "instrument_id": instrument_id,
                "known_at": prior,
                "round_trip_cost_bps": 10.0,
                "cost_model_id": COST_MODEL_ID,
            }
        )
        price_rows.extend(
            [
                {
                    "instrument_id": instrument_id,
                    "date": date(2024, 1, 1),
                    "known_at": cutoff - timedelta(seconds=30),
                    "adjusted_close": 100.0,
                    "delisted": False,
                },
                {
                    "instrument_id": instrument_id,
                    "date": date(2024, 1, 2),
                    "known_at": _known(2, 23),
                    "adjusted_close": 101.0,
                    "delisted": False,
                },
                {
                    "instrument_id": instrument_id,
                    "date": date(2024, 1, 3),
                    "known_at": _known(3, 23),
                    "adjusted_close": 102.0,
                    "delisted": False,
                },
            ]
        )
    policy = replace(
        load_rank_validation_policy(),
        holding_period_sessions=2,
        minimum_universe_support=2,
        top_n=1,
        bottom_n=1,
        minimum_decision_dates=1,
    )
    replay = replay_rank_panel(
        pd.DataFrame(evidence_rows),
        memberships,
        pd.DataFrame(price_rows),
        pd.DataFrame(costs_rows),
        pd.DataFrame([{"decision_date": "2024-01-01", "net_return": 0.001}]),
        pd.DataFrame([{"decision_date": "2024-01-01", "net_return": 0.0001}]),
        [cutoff],
        policy=policy,
    )

    assert replay.status == "complete", (
        f"{replay.reason}: {replay.insufficient_decision_times}; {replay.pit_availability}"
    )
    assert replay.reason != "dated complete universe membership is unavailable"


def test_scopes_are_isolated_and_invalid_or_empty_payloads_write_nothing(tmp_path: Path) -> None:
    configured_root = tmp_path / "configured"
    saved = save_universe((_record("WATCH", "01"),), expected_revision="", root=configured_root)
    configured_rows = universe_membership.capture_log("configured", root=configured_root)
    assert len(configured_rows) == 1
    assert bool(configured_rows.iloc[0]["complete"]) is True
    assert universe_membership.membership_frame(_SCOPE, datetime.now(timezone.utc), root=configured_root).empty
    assert saved.revision == load_universe(configured_root).revision

    rejected_root = tmp_path / "rejected"
    with pytest.raises(universe_membership.MembershipCaptureError, match="scope is not declared"):
        universe_membership.record_listing_capture(
            [{"instrument_id": "A"}], "fixture", "unknown", _known(1), root=rejected_root
        )
    with pytest.raises(universe_membership.MembershipCaptureError, match="empty"):
        universe_membership.record_listing_capture([], "fixture", _SCOPE, _known(1), root=rejected_root)
    assert not (rejected_root / "data" / "derived" / "universe_membership" / "membership.sqlite").exists()
    assert not (rejected_root / "data" / "raw" / "universe_membership").exists()


def test_delisted_membership_is_retained_as_a_closure_event(tmp_path: Path) -> None:
    universe_membership.record_listing_capture(
        [{"instrument_id": "DELISTED"}, {"instrument_id": "SURVIVOR"}],
        "fixture",
        _SCOPE,
        _known(1),
        root=tmp_path,
    )
    universe_membership.record_listing_capture(
        [{"instrument_id": "SURVIVOR"}], "fixture", _SCOPE, _known(3), root=tmp_path
    )

    intervals = universe_membership.membership_intervals(_SCOPE, _known(3), root=tmp_path)
    closed = intervals.loc[intervals["instrument_id"].eq("DELISTED")].iloc[0]
    events = universe_membership.closure_events(_SCOPE, _known(3), root=tmp_path)
    assert closed["valid_to"] == "2024-01-03"
    assert "DELISTED" in set(events["instrument_id"])


def test_closure_events_defaults_to_current_cutoff_and_supplied_root(tmp_path: Path) -> None:
    universe_membership.record_listing_capture(
        [{"instrument_id": "DELISTED"}, {"instrument_id": "SURVIVOR"}],
        "fixture",
        _SCOPE,
        _known(1),
        root=tmp_path,
    )
    universe_membership.record_listing_capture(
        [{"instrument_id": "SURVIVOR"}], "fixture", _SCOPE, _known(3), root=tmp_path
    )

    events = universe_membership.closure_events(_SCOPE, root=tmp_path)

    assert "DELISTED" in set(events["instrument_id"])


def test_only_declared_listing_scope_can_be_recorded(tmp_path: Path) -> None:
    with pytest.raises(universe_membership.MembershipCaptureError, match="scope is not declared"):
        universe_membership.record_listing_capture(
            [{"instrument_id": "A"}], "fixture", "listing:undeclared:stock", _known(1), root=tmp_path
        )
    assert not tuple(tmp_path.iterdir())

    status = universe_membership.record_listing_capture(
        [{"instrument_id": "A"}], "fixture", "listing:euronext_oslo:all", _known(1), root=tmp_path
    )

    assert status.status == "recorded"
    assert len(universe_membership.capture_log("listing:euronext_oslo:all", root=tmp_path)) == 1


def test_save_hook_records_capture_and_surfaces_recorder_failure(tmp_path: Path, monkeypatch, caplog) -> None:
    first = save_universe((_record("FIRST", "01"),), expected_revision="", root=tmp_path)
    assert universe_membership.get_configured_capture_status().status == "recorded"
    assert len(universe_membership.capture_log("configured", root=tmp_path)) == 1

    def fail_recorder(*, root=None):
        raise RuntimeError("recorder fault")

    monkeypatch.setattr(universe_membership, "record_configured_capture", fail_recorder)
    with caplog.at_level(logging.ERROR):
        second = save_universe((_record("SECOND", "02"),), expected_revision=first.revision, root=tmp_path)

    persisted = load_universe(tmp_path)
    assert second.revision == persisted.revision
    assert [item.instrument_id for item in persisted.records] == ["SECOND"]
    assert universe_membership.get_configured_capture_status().status == "failed"
    assert "RuntimeError: recorder fault" in universe_membership.get_configured_capture_status().reason
    assert len(universe_membership.capture_log("configured", root=tmp_path)) == 1
    assert any("configured membership capture status=failed" in item.message for item in caplog.records)


def test_licensed_import_requires_provenance_and_preserves_self_captures(tmp_path: Path) -> None:
    self_known_at = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    universe_membership.record_listing_capture(
        [{"instrument_id": "SELF"}], "fixture", _SCOPE, self_known_at, root=tmp_path
    )
    licensed_rows = [
        {
            "scope": _SCOPE,
            "instrument_id": "HISTORICAL",
            "valid_from": "2024-01-01",
            "valid_to": None,
            "snapshot_date": "2024-01-01",
            "snapshot_complete": True,
            "known_at": datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
        },
        {
            "scope": _SCOPE,
            "instrument_id": "LICENSED_CONFLICT",
            "valid_from": "2024-01-02",
            "valid_to": None,
            "snapshot_date": "2024-01-02",
            "snapshot_complete": True,
            "known_at": self_known_at,
        },
    ]
    with pytest.raises(universe_membership.MembershipCaptureError, match="licence_ref"):
        universe_membership.import_licensed_history(licensed_rows, "fixture", "", root=tmp_path)
    missing_known_at = [dict(licensed_rows[0])]
    missing_known_at[0].pop("known_at")
    with pytest.raises(universe_membership.MembershipCaptureError, match="known_at"):
        universe_membership.import_licensed_history(missing_known_at, "fixture", "licence-1", root=tmp_path)

    imported = universe_membership.import_licensed_history(
        licensed_rows, "fixture", "licence-1", root=tmp_path
    )
    frame = universe_membership.membership_frame(
        _SCOPE, datetime(2024, 1, 3, 12, tzinfo=timezone.utc), root=tmp_path
    )
    assert imported.imported_rows == 1
    assert imported.skipped_self_captured_rows == 1
    assert set(frame["instrument_id"]) == {"HISTORICAL", "SELF"}
    connection = sqlite3.connect(
        tmp_path / "data" / "derived" / "universe_membership" / "membership.sqlite"
    )
    try:
        assert connection.execute("SELECT DISTINCT source FROM licensed_history").fetchone()[0] == "licensed"
        assert connection.execute("SELECT COUNT(*) FROM capture_log WHERE snapshot_date='2024-01-02'").fetchone()[0] == 1
    finally:
        connection.close()


def test_licensed_import_rejects_snapshot_outside_half_open_interval_before_writing(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "scope": _SCOPE,
            "instrument_id": "VALID",
            "valid_from": "2024-01-01",
            "valid_to": "2024-01-04",
            "snapshot_date": "2024-01-03",
            "snapshot_complete": True,
            "known_at": datetime(2024, 1, 3, 12, tzinfo=timezone.utc),
        },
        {
            "scope": _SCOPE,
            "instrument_id": "INVALID",
            "valid_from": "2024-01-01",
            "valid_to": "2024-01-04",
            "snapshot_date": "2024-01-04",
            "snapshot_complete": True,
            "known_at": datetime(2024, 1, 4, 12, tzinfo=timezone.utc),
        },
    ]

    with pytest.raises(universe_membership.MembershipCaptureError, match="snapshot_date.*valid interval"):
        universe_membership.import_licensed_history(rows, "fixture", "licence-1", root=tmp_path)

    assert not tuple(tmp_path.iterdir())
