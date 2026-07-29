from __future__ import annotations

import pytest

from etf_cockpit.data.catalogue import DataCatalogue, DataCatalogueError, DatasetDefinition, DatasetSnapshot


def _definition(
    dataset_id: str, *, layer: str = "raw", source_id: str = "local-fixture"
) -> DatasetDefinition:
    return DatasetDefinition(
        dataset_id=dataset_id,
        layer=layer,
        schema={"instrument_id": "string", "value": "number"},
        owner="data-platform",
        source_id=source_id,
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


def test_complete_upstream_graph_is_deterministic_and_exposes_state(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    raw = catalogue.register_dataset(_definition("raw"))
    clean = catalogue.register_dataset(_definition("clean", layer="clean"))
    result = catalogue.register_dataset(_definition("result", layer="derived"))
    raw_snapshot = catalogue.register_rows(
        "raw", [{"instrument_id": "AAA", "value": 1.0}], schema=raw.schema, stale=True
    )
    clean_snapshot = catalogue.register_rows(
        "clean",
        [{"instrument_id": "AAA", "value": 1.0}],
        schema=clean.schema,
        dependency_snapshot_ids=(raw_snapshot.snapshot_id,),
    )
    result_snapshot = catalogue.register_rows(
        "result",
        [{"instrument_id": "AAA", "value": 1.0}],
        schema=result.schema,
        dependency_snapshot_ids=(clean_snapshot.snapshot_id, raw_snapshot.snapshot_id),
    )

    graph = catalogue.upstream_snapshot_graph(result_snapshot.snapshot_id)

    assert [node["snapshot_id"] for node in graph["nodes"]] == sorted(
        [raw_snapshot.snapshot_id, clean_snapshot.snapshot_id, result_snapshot.snapshot_id]
    )
    assert graph["edges"] == sorted(
        graph["edges"],
        key=lambda item: (
            item["upstream_snapshot_id"],
            item["downstream_snapshot_id"],
            item["relation"],
        ),
    )
    assert graph["status"] == "degraded"
    assert graph["complete"] is True
    assert graph["stale_snapshot_ids"] == [raw_snapshot.snapshot_id]
    assert graph["incompatible_snapshot_ids"] == []
    assert graph["execution_allowed"] is False


def test_upstream_graph_fails_closed_for_missing_and_incompatible_dependencies(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    dataset = catalogue.register_dataset(_definition("result", layer="derived"))
    snapshot = catalogue.register_snapshot(
        DatasetSnapshot(
            dataset_id=dataset.dataset_id,
            snapshot_id="result:" + "a" * 24 + ":" + "b" * 16,
            content_sha256="a" * 64,
            schema_sha256="b" * 64,
            row_count=1,
            dependency_snapshot_ids=("missing:upstream",),
        )
    )

    graph = catalogue.upstream_snapshot_graph(snapshot.snapshot_id)

    assert graph["status"] == "failed"
    assert graph["complete"] is False
    assert graph["missing_upstream_snapshot_ids"] == ["missing:upstream"]
    assert graph["incompatible_snapshot_ids"] == [snapshot.snapshot_id]
    assert graph["execution_allowed"] is False


def test_upstream_graph_fails_closed_for_reachable_cycle(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    first = catalogue.register_dataset(_definition("first", layer="derived"))
    second = catalogue.register_dataset(_definition("second", layer="derived"))
    first_id = "first:" + "a" * 24 + ":" + first.schema_sha256[:16]
    second_id = "second:" + "b" * 24 + ":" + second.schema_sha256[:16]
    catalogue.register_snapshot(
        DatasetSnapshot(
            dataset_id="first",
            snapshot_id=first_id,
            content_sha256="a" * 64,
            schema_sha256=first.schema_sha256,
            row_count=1,
            dependency_snapshot_ids=(second_id,),
        )
    )
    catalogue.register_snapshot(
        DatasetSnapshot(
            dataset_id="second",
            snapshot_id=second_id,
            content_sha256="b" * 64,
            schema_sha256=second.schema_sha256,
            row_count=1,
            dependency_snapshot_ids=(first_id,),
        )
    )

    graph = catalogue.upstream_snapshot_graph(first_id)

    assert graph["status"] == "failed"
    assert graph["complete"] is False
    assert graph["cycle_snapshot_ids"] == sorted([first_id, second_id])
    assert graph["failure_reasons"] == ["lineage cycle detected"]


def test_dataset_and_source_downstream_impact_include_transitive_results(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    raw = catalogue.register_dataset(_definition("raw"))
    peer = catalogue.register_dataset(_definition("peer"))
    clean = catalogue.register_dataset(
        _definition("clean", layer="clean", source_id="transformation")
    )
    result = catalogue.register_dataset(
        _definition("result", layer="derived", source_id="calculation")
    )
    raw_snapshot = catalogue.register_rows("raw", [{"instrument_id": "A", "value": 1}], schema=raw.schema)
    catalogue.register_rows("peer", [{"instrument_id": "B", "value": 1}], schema=peer.schema)
    clean_snapshot = catalogue.register_rows(
        "clean",
        [{"instrument_id": "A", "value": 1}],
        schema=clean.schema,
        dependency_snapshot_ids=(raw_snapshot.snapshot_id,),
    )
    result_snapshot = catalogue.register_rows(
        "result",
        [{"instrument_id": "A", "value": 1}],
        schema=result.schema,
        dependency_snapshot_ids=(clean_snapshot.snapshot_id,),
    )

    dataset_impact = catalogue.downstream_impact(dataset_id="raw")
    source_impact = catalogue.downstream_impact(source_id="local-fixture")

    assert dataset_impact["direct_snapshot_ids"] == [raw_snapshot.snapshot_id]
    assert dataset_impact["affected_snapshot_ids"] == sorted(
        [clean_snapshot.snapshot_id, result_snapshot.snapshot_id]
    )
    assert dataset_impact["affected_dataset_ids"] == ["clean", "result"]
    assert source_impact["direct_dataset_ids"] == ["peer", "raw"]
    assert source_impact["affected_snapshot_ids"] == sorted(
        [clean_snapshot.snapshot_id, result_snapshot.snapshot_id]
    )
    assert source_impact["affected_dataset_ids"] == ["clean", "result"]
    assert source_impact["execution_allowed"] is False


def test_dataset_impact_retains_same_dataset_descendant(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    dataset = catalogue.register_dataset(_definition("prices", layer="clean"))
    first = catalogue.register_rows(
        "prices", [{"instrument_id": "A", "value": 1}], schema=dataset.schema
    )
    second = catalogue.register_rows(
        "prices",
        [{"instrument_id": "A", "value": 2}],
        schema=dataset.schema,
        dependency_snapshot_ids=(first.snapshot_id,),
    )

    impact = catalogue.downstream_impact(dataset_id="prices")

    assert impact["direct_snapshot_ids"] == sorted([first.snapshot_id, second.snapshot_id])
    assert impact["affected_snapshot_ids"] == [second.snapshot_id]
    assert impact["affected_dataset_ids"] == ["prices"]


def test_downstream_impact_rejects_unknown_and_ambiguous_references(tmp_path) -> None:
    catalogue = DataCatalogue(tmp_path)
    catalogue.register_dataset(_definition("raw"))

    with pytest.raises(DataCatalogueError, match="exactly one"):
        catalogue.downstream_impact()
    with pytest.raises(DataCatalogueError, match="exactly one"):
        catalogue.downstream_impact(dataset_id="raw", source_id="local-fixture")
    with pytest.raises(DataCatalogueError, match="dataset is not registered"):
        catalogue.downstream_impact(dataset_id="missing")
    with pytest.raises(DataCatalogueError, match="source is not registered"):
        catalogue.downstream_impact(source_id="missing")
