"""Bughunt D22 (#935): immutable put_many must not acknowledge a tombstoned record."""

from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.data.peer_cohort_store import PeerCohortStore, PeerCohortStoreError
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageTombstoneConflict,
    TransactionalStore,
)

from tests.test_peer_cohorts import _projection

_TYPE = "d22_tombstone"
_PAYLOAD = {"a": 1, "b": [1, 2]}


def test_identical_immutable_retry_after_soft_delete_conflicts_and_stays_invisible(
    tmp_path: Path,
) -> None:
    with TransactionalStore(tmp_path) as store:
        store.put_many([(_TYPE, "x", _PAYLOAD)], immutable=True)
        assert store.delete(_TYPE, "x")
        with pytest.raises(StorageTombstoneConflict):
            store.put_many([(_TYPE, "x", dict(_PAYLOAD))], immutable=True)
        assert store.list(_TYPE) == ()
        assert store.get(_TYPE, "x") is None


def test_different_payload_on_immutable_record_still_conflicts(tmp_path: Path) -> None:
    with TransactionalStore(tmp_path) as store:
        store.put_many([(_TYPE, "x", _PAYLOAD)], immutable=True)
        with pytest.raises(StorageRevisionConflict):
            store.put_many([(_TYPE, "x", {"a": 2})], immutable=True)
        store.delete(_TYPE, "x")
        with pytest.raises(StorageRevisionConflict):
            store.put_many([(_TYPE, "x", {"a": 2})], immutable=True)


def test_normal_immutable_idempotent_retry_is_unchanged(tmp_path: Path) -> None:
    with TransactionalStore(tmp_path) as store:
        first = store.put_many([(_TYPE, "x", _PAYLOAD)], immutable=True)[0]
        again = store.put_many([(_TYPE, "x", dict(_PAYLOAD))], immutable=True)[0]
        assert again.revision == first.revision == 1
        assert again.created_at == first.created_at
        assert len(store.list(_TYPE)) == 1


def test_peer_cohort_append_after_tombstone_raises_store_error(tmp_path: Path) -> None:
    projection = _projection()
    with PeerCohortStore(tmp_path) as store:
        store.append(projection)
        raw = store._opened()
        (record,) = raw.list("peer_cohort_result_v1")
        assert raw.delete(record.entity_type, record.entity_id)
        with pytest.raises(PeerCohortStoreError, match="soft-deleted"):
            store.append(projection)
        with pytest.raises(KeyError):
            store.get(projection.result_hash)
