from __future__ import annotations

import pytest

from etf_cockpit.data.catalogue import DataCatalogue, DataCatalogueError, DatasetDefinition, DatasetSnapshot


def _definition(dataset_id: str, *, layer: str = "raw") -> DatasetDefinition:
    return DatasetDefinition(
        dataset_id=dataset_id,
        layer=layer,
        schema={"instrument_id": "string", "value": "number"},
        owner="data-platform",
        source_id="local-fixture",
        licence="fixture",
        update_schedule="manual",
        partitions=("2024",),
        row_count=2,
        quality={"status": "passed", "missing_rows": 0},
        pii_classification="none",
        retention_days=365,
    )


def test_snapshot_ids_are_reproducible_and_catalogue_is_reloadable(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    catalogue.register_dataset(_definition("prices"))
    rows = [{"instrument_id": "AAA", "value": 1.0}, {"instrument_id": "BBB", "value": 2.0}]

    first = catalogue.register_rows("prices", rows, schema=_definition("prices").schema, coverage_ids=("AAA", "BBB"), captured_at="2024-01-01T00:00:00Z")
    repeated = catalogue.register_rows("prices", list(reversed(rows)), schema=_definition("prices").schema, coverage_ids=("BBB", "AAA"), captured_at="2025-01-01T00:00:00Z")
    reloaded = DataCatalogue(tmp_path)

    assert first.snapshot_id == repeated.snapshot_id
    assert reloaded.snapshots[0].snapshot_id == first.snapshot_id
    assert reloaded.summary()["catalogue_signature"] == catalogue.summary()["catalogue_signature"]
    assert reloaded.summary()["execution_allowed"] is False
    assert reloaded.retention_candidates("2024-06-01T00:00:00Z")["candidate_snapshot_ids"] == [first.snapshot_id]

    newer = reloaded.register_rows("prices", [{"instrument_id": "AAA", "value": 3.0}], schema=_definition("prices").schema, captured_at="2025-01-01T00:00:00Z")
    assert reloaded.compaction_candidates("prices")["candidate_snapshot_ids"] == [first.snapshot_id]
    assert newer.snapshot_id != first.snapshot_id


def test_lineage_validation_impact_and_instrument_provenance(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    source = catalogue.register_dataset(_definition("source"))
    derived = catalogue.register_dataset(_definition("derived", layer="derived"))
    source_snapshot = catalogue.register_rows("source", [{"instrument_id": "AAA", "value": 1.0}], schema=source.schema, coverage_ids=("AAA",))
    derived_snapshot = catalogue.register_rows(
        "derived",
        [{"instrument_id": "AAA", "value": 1.0}],
        schema=derived.schema,
        dependency_snapshot_ids=(source_snapshot.snapshot_id,),
        coverage_ids=("AAA",),
    )

    validation = catalogue.validate()
    impact = catalogue.impact_analysis(source_snapshot.snapshot_id)
    provenance = catalogue.provenance_for("AAA")

    assert validation["status"] == "passed"
    assert impact["affected_snapshot_ids"] == [derived_snapshot.snapshot_id]
    assert impact["affected_dataset_ids"] == ["derived"]
    assert provenance["snapshot_ids"] == sorted([source_snapshot.snapshot_id, derived_snapshot.snapshot_id])


def test_orphan_and_schema_drift_are_flagged_without_becoming_authority(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    dataset = catalogue.register_dataset(_definition("derived", layer="derived"))
    snapshot = DatasetSnapshot(
        dataset_id=dataset.dataset_id,
        snapshot_id="derived:" + "a" * 24 + ":" + "b" * 16,
        content_sha256="a" * 64,
        schema_sha256="b" * 64,
        row_count=1,
        dependency_snapshot_ids=("missing:source",),
        captured_at="2024-01-01T00:00:00Z",
    )
    catalogue.register_snapshot(snapshot)

    report = catalogue.validate()
    assert report["status"] == "failed"
    assert report["orphan_snapshot_ids"] == [snapshot.snapshot_id]
    assert report["incompatible_dataset_ids"] == ["derived"]
    assert catalogue.summary()["execution_allowed"] is False

    with pytest.raises(DataCatalogueError):
        catalogue.register_dataset(_definition("derived", layer="clean"))
