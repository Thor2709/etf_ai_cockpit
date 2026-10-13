"""Bughunt A22 (#929): catalogue lost update and lineage published before commit."""

from __future__ import annotations

from datetime import datetime, timezone
import multiprocessing
from pathlib import Path
import sqlite3

import pytest

from etf_cockpit.data import universe_membership
from etf_cockpit.data.catalogue import DataCatalogue, DataCatalogueError, DatasetDefinition, DatasetSnapshot

_SCOPE = "listing:euronext_oslo:all"


def _definition() -> DatasetDefinition:
    return DatasetDefinition(
        dataset_id="ds",
        layer="raw",
        schema={"a": "int"},
        owner="o",
        source_id="s",
        licence="l",
        update_schedule="daily",
    )


def _snapshot(name: str, *, dependencies: tuple[str, ...] = ()) -> DatasetSnapshot:
    definition = _definition()
    return DatasetSnapshot(
        dataset_id="ds",
        snapshot_id=f"ds:{name}",
        content_sha256="a" * 64,
        schema_sha256=definition.schema_sha256,
        row_count=1,
        dependency_snapshot_ids=dependencies,
        captured_at="2026-01-01T00:00:00Z",
    )


def _register_in_process(root: str, name: str, dependency: str) -> None:
    catalogue = DataCatalogue(Path(root))
    catalogue.register_snapshot(_snapshot(name, dependencies=(dependency,)))


def test_stale_instances_do_not_lose_snapshots_or_edges(tmp_path: Path) -> None:
    DataCatalogue(tmp_path).register_dataset(_definition())
    first, second = DataCatalogue(tmp_path), DataCatalogue(tmp_path)
    base = first.register_snapshot(_snapshot("base"))
    # `second` was loaded before `base` and `child_a` existed.
    first.register_snapshot(_snapshot("child_a", dependencies=(base.snapshot_id,)))
    second.register_snapshot(_snapshot("child_b", dependencies=(base.snapshot_id,)))

    reloaded = DataCatalogue(tmp_path)
    assert {item.snapshot_id for item in reloaded.snapshots} == {"ds:base", "ds:child_a", "ds:child_b"}
    assert {(e.upstream_snapshot_id, e.downstream_snapshot_id) for e in reloaded.lineage} == {
        ("ds:base", "ds:child_a"),
        ("ds:base", "ds:child_b"),
    }


def test_stale_instance_conflicting_snapshot_id_is_rejected_not_overwritten(tmp_path: Path) -> None:
    DataCatalogue(tmp_path).register_dataset(_definition())
    first, second = DataCatalogue(tmp_path), DataCatalogue(tmp_path)
    first.register_snapshot(_snapshot("x"))
    conflicting = DatasetSnapshot(**{**_snapshot("x").__dict__, "row_count": 9})
    with pytest.raises(DataCatalogueError, match="different content"):
        second.register_snapshot(conflicting)
    assert DataCatalogue(tmp_path).snapshots[0].row_count == 1


def test_two_processes_interleave_without_losing_snapshots(tmp_path: Path) -> None:
    catalogue = DataCatalogue(tmp_path)
    catalogue.register_dataset(_definition())
    base = catalogue.register_snapshot(_snapshot("base"))
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_register_in_process, args=(str(tmp_path), f"child_{index}", base.snapshot_id))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(120)
        assert worker.exitcode == 0
    reloaded = DataCatalogue(tmp_path)
    assert {item.snapshot_id for item in reloaded.snapshots} == {"ds:base", *(f"ds:child_{i}" for i in range(4))}
    assert len(reloaded.lineage) == 4
    assert reloaded.validate()["errors"] == []


def test_sequential_registration_unchanged(tmp_path: Path) -> None:
    catalogue = DataCatalogue(tmp_path)
    catalogue.register_dataset(_definition())
    snapshot = catalogue.register_snapshot(_snapshot("only"))
    assert catalogue.register_snapshot(snapshot) == snapshot
    assert [item.snapshot_id for item in DataCatalogue(tmp_path).snapshots] == ["ds:only"]
    assert (tmp_path / "data" / "catalogue" / "data_dictionary.json").is_file()


class _CommitFails:
    """Connection proxy whose commit fails, as a disk-full / lock error would."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def commit(self) -> None:
        raise sqlite3.OperationalError("injected commit failure")

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def test_failed_membership_commit_leaves_no_catalogue_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = universe_membership._connect
    monkeypatch.setattr(
        universe_membership, "_connect", lambda path, *, create: _CommitFails(real_connect(path, create=create))
    )
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        universe_membership.record_listing_capture(
            [{"instrument_id": "A"}], "fixture", _SCOPE, datetime(2024, 1, 1, 12, tzinfo=timezone.utc), root=tmp_path
        )
    monkeypatch.setattr(universe_membership, "_connect", real_connect)

    assert len(universe_membership.capture_log(_SCOPE, root=tmp_path)) == 0
    assert DataCatalogue(tmp_path).snapshots == ()


def test_committed_capture_publishes_raw_and_processed_lineage(tmp_path: Path) -> None:
    status = universe_membership.record_listing_capture(
        [{"instrument_id": "A"}], "fixture", _SCOPE, datetime(2024, 1, 1, 12, tzinfo=timezone.utc), root=tmp_path
    )
    assert status.status == "recorded" and status.reason is None
    catalogue = DataCatalogue(tmp_path)
    assert {item.dataset_id for item in catalogue.snapshots} == {
        "universe_membership_raw",
        "universe_membership_intervals",
    }
    assert len(catalogue.lineage) == 1


def test_lineage_publish_failure_after_commit_is_reported_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args, **_kwargs):
        raise DataCatalogueError("injected catalogue failure")

    monkeypatch.setattr(universe_membership, "_publish_lineage", broken)
    status = universe_membership.record_listing_capture(
        [{"instrument_id": "A"}], "fixture", _SCOPE, datetime(2024, 1, 1, 12, tzinfo=timezone.utc), root=tmp_path
    )
    assert status.status == "recorded" and status.reason == "catalogue_lineage_unavailable"
    assert len(universe_membership.capture_log(_SCOPE, root=tmp_path)) == 1


def _capture_with_lineage_crash(root: Path, monkeypatch: pytest.MonkeyPatch, instrument: str, day: int) -> None:
    """Commit a capture, but crash before the lineage is published."""

    with monkeypatch.context() as patch:
        patch.setattr(
            universe_membership,
            "_publish_lineage",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("injected crash")),
        )
        universe_membership.record_listing_capture(
            [{"instrument_id": instrument}], "fixture", _SCOPE, datetime(2024, 1, day, 12, tzinfo=timezone.utc), root=root
        )


def test_next_capture_repairs_committed_capture_without_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_with_lineage_crash(tmp_path, monkeypatch, "A", 1)
    assert DataCatalogue(tmp_path).snapshots == ()

    universe_membership.record_listing_capture(
        [{"instrument_id": "A"}, {"instrument_id": "B"}],
        "fixture",
        _SCOPE,
        datetime(2024, 1, 2, 12, tzinfo=timezone.utc),
        root=tmp_path,
    )
    catalogue = DataCatalogue(tmp_path)
    # two captures -> two distinct raw snapshots and two processed snapshots, all linked
    assert len(catalogue.snapshots) == 4 and len(catalogue.lineage) == 2
    # repair is idempotent
    assert universe_membership.repair_catalogue_lineage(tmp_path) == universe_membership.LineageRepairStatus()
    assert len(DataCatalogue(tmp_path).snapshots) == 4


def test_unmatchable_capture_is_reported_unavailable_never_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_with_lineage_crash(tmp_path, monkeypatch, "A", 1)
    raw = next((tmp_path / "data" / "raw" / "universe_membership").glob("*.payload.gz"))
    raw.write_bytes(b"corrupt")

    status = universe_membership.repair_catalogue_lineage(tmp_path)
    assert status.repaired == () and len(status.unavailable) == 1
    assert DataCatalogue(tmp_path).snapshots == ()
    # the broken orphan never blocks later captures
    universe_membership.record_listing_capture(
        [{"instrument_id": "C"}], "fixture", _SCOPE, datetime(2024, 1, 3, 12, tzinfo=timezone.utc), root=tmp_path
    )
    assert len(universe_membership.capture_log(_SCOPE, root=tmp_path)) == 2
