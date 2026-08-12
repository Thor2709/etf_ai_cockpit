from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.bitemporal import (
    AmbiguousAvailabilityError,
    BitemporalError,
    BitemporalStore,
    bitemporal_history_summary,
    _observation,
)


CHECKSUM = "a" * 64


def _record(store: BitemporalStore, *, revision: int, available_at: str, value: str, status: str = "active"):
    return store.record_observation(
        dataset_id="fundamentals",
        entity_id="ETF-1",
        stable_id="metric:earnings",
        run_id=f"run-{revision}",
        value={"value": value},
        valid_from="2025-12-31T00:00:00Z",
        valid_to="2026-12-31T00:00:00Z",
        published_at=available_at,
        available_at=available_at,
        observed_at=available_at,
        ingested_at="2026-01-03T00:00:00Z",
        revised_at=available_at if revision > 1 else None,
        revision=revision,
        source_id="source:official",
        source_checksum=CHECKSUM,
        timezone_confidence="exact",
        availability_confidence="exact",
        status=status,
    )


@pytest.mark.parametrize("revision", (True, 1.0, 1.5, "1"))
def test_revision_identity_is_strict_at_append_and_readback(
    tmp_path: Path,
    revision: object,
) -> None:
    with BitemporalStore(tmp_path) as store:
        with pytest.raises(BitemporalError, match="positive integer"):
            store.record_observation(
                dataset_id="fundamentals",
                entity_id="ETF-1",
                stable_id="metric:earnings",
                run_id="run-malformed",
                value={"value": "reported"},
                valid_from="2025-12-31T00:00:00Z",
                valid_to="2026-12-31T00:00:00Z",
                published_at="2026-01-02T10:00:00Z",
                available_at="2026-01-02T10:00:00Z",
                observed_at="2026-01-02T10:00:00Z",
                ingested_at="2026-01-03T00:00:00Z",
                revision=revision,  # type: ignore[arg-type]
                source_id="source:official",
                source_checksum=CHECKSUM,
            )

    row = {
        "observation_id": "observation",
        "dataset_id": "dataset",
        "entity_id": "entity",
        "stable_id": "stable",
        "run_id": "run",
        "value_json": "{}",
        "valid_from": "2026-01-01T00:00:00+00:00",
        "valid_to": None,
        "published_at": "2026-01-01T00:00:00+00:00",
        "available_at": "2026-01-01T00:00:00+00:00",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "ingested_at": "2026-01-01T00:00:00+00:00",
        "revised_at": None,
        "revision": revision,
        "source_id": "source",
        "source_checksum": CHECKSUM,
        "timezone_confidence": "exact",
        "availability_confidence": "exact",
        "status": "active",
    }
    with pytest.raises(BitemporalError, match="positive integer"):
        _observation(row)


@pytest.mark.parametrize(
    ("decision_time", "expected"),
    [
        ("2026-01-15T00:00:00Z", "reported"),
        ("2026-02-15T00:00:00Z", "restated"),
    ],
)
def test_as_of_replays_only_the_vintage_available_at_decision_time(tmp_path: Path, decision_time: str, expected: str) -> None:
    with BitemporalStore(tmp_path) as store:
        first = _record(store, revision=1, available_at="2026-01-02T10:00:00Z", value="reported")
        _record(store, revision=2, available_at="2026-02-02T10:00:00Z", value="restated")

        view = store.as_of("fundamentals", decision_time)
        assert view.loc[0, "value"] == {"value": expected}
        assert view.loc[0, "observation_id"] == (first.observation_id if expected == "reported" else view.loc[0, "observation_id"])

        stamped = store.stamp_derived_frame(pd.DataFrame({"score": [1.0]}), "fundamentals", decision_time)
        assert stamped.loc[0, "decision_time"] == decision_time.replace("Z", "+00:00").replace("00:00:00+00:00", "00:00:00.000000+00:00")
        assert len(stamped.loc[0, "source_vintage_hash"]) == 64


def test_revisions_are_append_only_and_retractions_are_historical(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        first = _record(store, revision=1, available_at="2026-01-02T10:00:00Z", value="reported")
        second = _record(store, revision=2, available_at="2026-02-02T10:00:00Z", value="restated")
        retraction = store.record_retraction(
            second.observation_id,
            available_at="2026-03-02T10:00:00Z",
            run_id="run-retraction",
            reason="official correction withdrawn",
        )
        assert retraction.status == "retracted"
        assert store.as_of("fundamentals", "2026-02-15T00:00:00Z").loc[0, "value"] == {"value": "restated"}
        assert store.as_of("fundamentals", "2026-03-15T00:00:00Z").empty
        assert len(store.observations("fundamentals")) == 3

        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            store.store.connection.execute(
                "DELETE FROM bitemporal_observations WHERE observation_id = ?",
                (first.observation_id,),
            )
        assert store.observations("fundamentals")[0].observation_id == first.observation_id


def test_supersession_is_an_append_only_marker(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        original = _record(store, revision=1, available_at="2026-01-02T10:00:00Z", value="old")
        marker = store.record_supersession(
            original.observation_id,
            available_at="2026-01-03T10:00:00Z",
            run_id="run-supersession",
            replacement_observation_id="replacement-id",
            reason="amended source record",
        )
        assert marker.status == "superseded"
        assert marker.value["replacement_observation_id"] == "replacement-id"
        assert store.as_of("fundamentals", "2026-01-04T00:00:00Z").empty


def test_ambiguous_availability_and_naive_timestamps_fail_closed(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        with pytest.raises(AmbiguousAvailabilityError):
            _record(store, revision=1, available_at=None, value="unknown")  # type: ignore[arg-type]
        with pytest.raises(AmbiguousAvailabilityError):
            store.record_observation(
                dataset_id="fundamentals",
                entity_id="ETF-1",
                value={"value": "unknown"},
                source_id="source:official",
                source_checksum=CHECKSUM,
                revision=1,
                valid_from="2025-12-31T00:00:00Z",
                published_at="2026-01-02T10:00:00Z",
                available_at="2026-01-02T10:00:00Z",
                observed_at="2026-01-02T10:00:00Z",
                run_id="run-ambiguous",
                availability_confidence="ambiguous",  # type: ignore[arg-type]
            )
        with pytest.raises(BitemporalError, match="explicit timezone"):
            _record(store, revision=1, available_at="2026-01-02T10:00:00", value="naive")


def test_timezone_normalisation_and_vintage_manifest_are_deterministic(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        row = _record(store, revision=1, available_at="2026-03-29T01:30:00+01:00", value="dst")
        assert row.available_at == "2026-03-29T00:30:00.000000+00:00"
        first = store.vintage_manifest("fundamentals", "2026-03-29T02:00:00Z")
        second = store.vintage_manifest("fundamentals", "2026-03-29T02:00:00Z")
        assert first == second
        destination = tmp_path / "exports" / "vintage.json"
        store.export_vintage_manifest(destination, "fundamentals", "2026-03-29T02:00:00Z")
        assert json.loads(destination.read_text(encoding="utf-8"))["sha256"] == first.sha256

    summary = bitemporal_history_summary("ETF-1", tmp_path)
    assert summary["status"] == "available"
    assert summary["observation_count"] == 1
    assert summary["vintages"][0]["source_checksum"] == CHECKSUM
