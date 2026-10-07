from __future__ import annotations

import json
from collections.abc import Mapping

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_timestamp
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import DataCatalogue, DataCatalogueError
from etf_cockpit.core.paths import ROOT


def catalogue_page(page: ft.Page, state: AppState) -> PageView:
    instrument_id = str(getattr(state, "selected_etf", "") or "")
    catalogue_error: str | None = None
    try:
        catalogue = DataCatalogue(ROOT)
        summary = catalogue.summary()
        validation = catalogue.validate()
        datasets = tuple(catalogue.datasets)
        snapshots = tuple(catalogue.snapshots)
        edges = tuple(catalogue.lineage)
    except (DataCatalogueError, OSError) as exc:
        catalogue = None
        summary = {}
        validation = {}
        datasets = ()
        snapshots = ()
        edges = ()
        catalogue_error = type(exc).__name__

    raw_status = str(summary.get("status") or "unavailable")
    catalogue_available = catalogue is not None and bool(datasets)
    unavailable_reason = (
        "Local catalogue is unavailable and requires manual review."
        if catalogue_error
        else "No datasets are registered locally."
    )
    orphan_ids = set(summary.get("orphan_snapshot_ids", ()) or ())
    incompatible_ids = set(summary.get("incompatible_dataset_ids", ()) or ())
    stale_ids = set(summary.get("stale_snapshot_ids", ()) or ())
    dataset_by_id = {item.dataset_id: item for item in datasets}
    snapshot_by_id = {item.snapshot_id: item for item in snapshots}

    def clean(value: object) -> object | None:
        if value is None or str(value).strip().casefold() in {"", "none", "nan", "nat"}:
            return None
        return value

    def human(value: object) -> str | None:
        text = clean(value)
        if text is None:
            return None
        return " ".join(str(text).replace("_", " ").split()).title()

    dataset_table_rows: list[dict[str, object]] = []
    snapshots_by_dataset: dict[str, list[object]] = {}
    for snapshot in snapshots:
        snapshots_by_dataset.setdefault(snapshot.dataset_id, []).append(snapshot)
    for item in datasets:
        quality = item.quality
        quality_status = (
            quality.get("status") or quality.get("state")
            if isinstance(quality, Mapping)
            else quality
        )
        quality_label = human(quality_status) or (
            "Available" if quality else "Unavailable"
        )
        quality_kind = (
            "warn"
            if item.stale or str(quality_status).casefold() in {"stale", "review"}
            else "bad"
            if str(quality_status).casefold() in {"failed", "invalid", "corrupt"}
            else "ok"
            if quality
            else "mute"
        )
        latest = max(
            snapshots_by_dataset.get(item.dataset_id, ()),
            key=lambda snapshot: snapshot.captured_at,
            default=None,
        )
        technical = {
            "Canonical path": item.canonical_path,
            "Schema": item.schema,
            "Schema hash": item.schema_sha256,
            "Content hash": item.content_sha256,
            "PII classification": item.pii_classification,
            "Access class": item.access_class,
            "Quality detail": quality,
        }
        dataset_table_rows.append(
            {
                "dataset": item.dataset_id,
                "owner": clean(item.owner),
                "source": clean(item.source_id),
                "licence": clean(item.licence),
                "quality": ft.Column(
                    [
                        kit.Tag(quality_label, quality_kind),
                        kit.Disclosure(
                            "Dataset detail",
                            "\n".join(
                                f"{key}: {json.dumps(value, default=str, sort_keys=True)}"
                                for key, value in technical.items()
                                if value is not None
                            )
                            or "Unavailable",
                        ),
                    ],
                    spacing=4,
                ),
                "retention": (
                    f"{format_count(item.retention_days)} days"
                    if item.retention_days is not None
                    else None
                ),
                "as_of": format_timestamp(latest.captured_at, unavailable="—")
                if latest
                else None,
            }
        )

    snapshot_table_rows: list[dict[str, object]] = []
    for item in snapshots:
        dataset = dataset_by_id.get(item.dataset_id)
        details = "\n".join(
            (
                f"Snapshot ID: {item.snapshot_id}",
                f"Schema hash: {item.schema_sha256}",
                f"Content hash: {item.content_sha256}",
                f"Dependencies: {', '.join(item.dependency_snapshot_ids) or 'None'}",
                f"Partitions: {', '.join(item.partitions) or 'None'}",
                f"Quality: {json.dumps(item.quality, default=str, sort_keys=True)}",
                f"Stale: {str(item.stale).lower()}",
                f"Canonical path: {dataset.canonical_path if dataset else 'Unavailable'}",
            )
        )
        snapshot_table_rows.append(
            {
                "snapshot": ft.Column(
                    [
                        kit.Note(
                            f"{item.dataset_id} · "
                            f"{format_timestamp(item.captured_at, unavailable='Unavailable')}"
                        ),
                        kit.Disclosure("Snapshot detail", details),
                    ],
                    spacing=4,
                ),
                "dataset": item.dataset_id,
                "rows": format_count(item.row_count, unavailable="—"),
                "schema": "Recorded" if item.schema_sha256 else None,
                "content_hash": "Recorded" if item.content_sha256 else None,
                "created": format_timestamp(item.captured_at, unavailable="—"),
            }
        )

    main_slot = ft.Column(spacing=0)

    def render_main(selection: str) -> None:
        if selection == "Snapshots":
            title = "Immutable snapshots"
            note = "content hashes, row counts and dependency edges"
            table = kit.DataTable(
                [
                    kit.TableColumn("snapshot", "Snapshot", flex=2),
                    kit.TableColumn("dataset", "Dataset"),
                    kit.TableColumn("rows", "Rows", numeric=True),
                    kit.TableColumn("schema", "Schema"),
                    kit.TableColumn("content_hash", "Content hash"),
                    kit.TableColumn("created", "Created"),
                ],
                snapshot_table_rows,
                empty_title="No immutable snapshots",
                empty_reason="No immutable snapshots are registered locally.",
            )
        else:
            title = "Registered datasets"
            note = "owner, source, licence, quality and retention"
            table = kit.DataTable(
                [
                    kit.TableColumn("dataset", "Dataset", flex=2),
                    kit.TableColumn("owner", "Owner"),
                    kit.TableColumn("source", "Source"),
                    kit.TableColumn("licence", "Licence"),
                    kit.TableColumn("quality", "Quality"),
                    kit.TableColumn("retention", "Retention"),
                    kit.TableColumn("as_of", "As of"),
                ],
                dataset_table_rows,
                empty_title="No registered datasets",
                empty_reason=unavailable_reason,
            )
        main_slot.controls = [
            kit.GlassCard(
                title,
                note,
                body=kit.Well(table, expand=True),
                expand=2,
                key="catalogue.status",
            )
        ]

    def change_main(selection: str) -> None:
        render_main(selection)
        if getattr(page, "update", None):
            try:
                page.update()
            except (RuntimeError, AttributeError):
                pass

    render_main("Datasets")

    dataset_count = format_count(summary.get("dataset_count")) if catalogue_available else None
    snapshot_count = format_count(summary.get("snapshot_count")) if catalogue_available else None
    lineage_count = format_count(summary.get("lineage_edge_count")) if catalogue_available else None
    orphan_count = format_count(len(orphan_ids)) if catalogue_available else None
    incompatible_count = format_count(len(incompatible_ids)) if catalogue_available else None
    catalogue_label = "available" if catalogue_available else "unavailable"
    headline_sub = (
        f"{dataset_count} datasets · {snapshot_count} snapshots · {lineage_count} lineage edges"
        if catalogue_available
        else unavailable_reason
    )
    kpi_strip = kit.KpiStrip(
        "Catalogue status",
        f"Catalogue {catalogue_label}",
        headline_sub,
        [
            ("Datasets", dataset_count, "registered locally" if dataset_count else unavailable_reason, None),
            (
                "Snapshots",
                snapshot_count,
                "immutable, content-addressed" if snapshot_count else unavailable_reason,
                None,
            ),
            (
                "Lineage edges",
                lineage_count,
                "upstream dependencies" if lineage_count else unavailable_reason,
                None,
            ),
            (
                "Orphans",
                orphan_count,
                f"{incompatible_count} schema incompatibilities"
                if incompatible_count is not None
                else unavailable_reason,
                "neg" if orphan_ids or incompatible_ids else None,
            ),
        ],
        key="catalogue.kpi.0",
    )

    coverage_instruments = {
        coverage_id for snapshot in snapshots for coverage_id in snapshot.coverage_ids
    }
    if instrument_id:
        coverage_instruments.add(instrument_id)
    provenance_holder = {"instrument": instrument_id}
    provenance_slot = ft.Column(spacing=8)

    def render_provenance(selected_instrument: str) -> None:
        if catalogue is None:
            provenance = {"snapshot_ids": [], "dataset_ids": []}
        elif selected_instrument:
            try:
                provenance = catalogue.provenance_for(selected_instrument)
            except (DataCatalogueError, OSError):
                provenance = {"snapshot_ids": [], "dataset_ids": []}
        else:
            provenance = {"snapshot_ids": [], "dataset_ids": []}
        covered_datasets = set(provenance.get("dataset_ids", ()) or ())
        coverage_rows: list[ft.Control] = []
        for item in datasets:
            covered = item.dataset_id in covered_datasets
            coverage_rows.append(
                kit.ListRow(
                    "ok" if covered else "warn",
                    item.dataset_id,
                    sub=(
                        "Snapshot coverage is registered."
                        if covered
                        else f"No snapshot coverage is registered for {selected_instrument or 'the selected instrument'}."
                    ),
                    tag=("Covered", "ok") if covered else ("Unavailable", "mute"),
                    last=item is datasets[-1],
                )
            )
        if not coverage_rows:
            coverage_rows = [
                kit.EmptyState(
                    "No snapshot coverage",
                    "No snapshot coverage is registered for the selected instrument.",
                )
            ]
        technical = "\n".join(
            (
                f"Instrument: {selected_instrument or 'Unavailable'}",
                f"Snapshot IDs: {', '.join(provenance.get('snapshot_ids', ()) or ()) or 'Unavailable'}",
                f"Dataset IDs: {', '.join(provenance.get('dataset_ids', ()) or ()) or 'Unavailable'}",
            )
        )
        provenance_slot.controls = [
            kit.Field(
                "Instrument",
                value=selected_instrument,
                placeholder="No instruments available",
                options=tuple(sorted(coverage_instruments)),
                on_change=change_instrument,
            ),
            ft.Column(coverage_rows, spacing=4),
            kit.Disclosure("Provenance detail", technical),
        ]

    def change_instrument(value: str) -> None:
        provenance_holder["instrument"] = value
        render_provenance(value)
        if getattr(page, "update", None):
            try:
                page.update()
            except (RuntimeError, AttributeError):
                pass

    render_provenance(instrument_id)
    provenance_card = kit.GlassCard(
        "Instrument provenance explorer",
        "selected instrument",
        body=provenance_slot,
        expand=True,
    )

    edge_weights: dict[tuple[str, str], int] = {}
    for edge in edges:
        upstream = snapshot_by_id.get(edge.upstream_snapshot_id)
        downstream = snapshot_by_id.get(edge.downstream_snapshot_id)
        if upstream is None or downstream is None:
            continue
        source_id = upstream.dataset_id
        target_id = downstream.dataset_id
        if source_id == target_id:
            continue
        pair = (source_id, target_id)
        edge_weights[pair] = edge_weights.get(pair, 0) + 1
    graph_dataset_ids = {
        dataset_id for pair in edge_weights for dataset_id in pair
    }
    graph_nodes = []
    for dataset_id in sorted(graph_dataset_ids):
        item = dataset_by_id.get(dataset_id)
        layer = item.layer if item else ""
        orphaned = any(
            snapshot.snapshot_id in orphan_ids
            for snapshot in snapshots_by_dataset.get(dataset_id, ())
        )
        color = (
            theme.CHART_NEG
            if orphaned
            else theme.CHART_PRIMARY
            if layer == "raw"
            else theme.CHART_POS
            if layer == "clean"
            else theme.CHART_SECOND
            if layer == "derived"
            else theme.MUTED
        )
        graph_nodes.append(ck.SankeyNode(dataset_id, color))
    graph_links = [
        ck.SankeyLink(source, target, weight)
        for (source, target), weight in sorted(edge_weights.items())
    ]
    incoming: dict[str, int] = {}
    for (_source, target), weight in edge_weights.items():
        incoming[target] = incoming.get(target, 0) + weight
    most_dependent = max(incoming.items(), key=lambda item: item[1], default=None)
    lineage_insight = (
        f"{format_count(most_dependent[1])} artefacts depend on {most_dependent[0]}."
        if most_dependent
        else None
    )
    lineage_chart = ck.sankey(
        graph_nodes,
        graph_links,
        unit="dependencies",
        empty_title="No lineage yet",
        unavailable_reason="Register datasets to see their dependencies."
        if not graph_links
        else None,
        insight=lineage_insight,
    )
    lineage_card = kit.GlassCard(
        "Lineage graph",
        "upstream → downstream",
        lineage_insight,
        body=kit.Well(lineage_chart, expand=True),
        expand=2,
    )

    findings: list[ft.Control] = []
    for snapshot_id in sorted(orphan_ids):
        snapshot = snapshot_by_id.get(snapshot_id)
        dataset = dataset_by_id.get(snapshot.dataset_id) if snapshot else None
        findings.extend(
            (
                kit.ListRow("bad", "Orphan canonical data path", sub="Inspect the finding detail."),
                kit.Disclosure(
                    "Orphan finding",
                    "\n".join(
                        (
                            f"Snapshot ID: {snapshot_id}",
                            f"Dataset: {snapshot.dataset_id if snapshot else 'Unavailable'}",
                            f"Path: {dataset.canonical_path if dataset else 'Unavailable'}",
                        )
                    ),
                ),
            )
        )
    for snapshot_id in sorted(stale_ids):
        findings.extend(
            (
                kit.ListRow("warn", "Stale snapshot", sub="Inspect the finding detail."),
                kit.Disclosure("Stale snapshot detail", f"Snapshot ID: {snapshot_id}"),
            )
        )
    for dataset_id in sorted(incompatible_ids):
        item = dataset_by_id.get(dataset_id)
        findings.extend(
            (
                kit.ListRow("bad", "Incompatible schema", sub="Inspect the finding detail."),
                kit.Disclosure(
                    "Schema finding",
                    "\n".join(
                        (
                            f"Dataset: {dataset_id}",
                            f"Canonical path: {item.canonical_path if item else 'Unavailable'}",
                            f"Schema: {json.dumps(item.schema, default=str, sort_keys=True) if item else 'Unavailable'}",
                        )
                    ),
                ),
            )
        )
    validation_errors = validation.get("errors", ()) or ()
    if validation_errors:
        findings.append(
            kit.Disclosure(
                "Validation detail",
                "\n".join(str(value) for value in validation_errors),
            )
        )
    if not findings:
        findings.append(
            kit.EmptyState(
                "No lineage findings",
                "Lineage and schema checks pass." if catalogue_available else unavailable_reason,
            )
        )
    retention_details = "\n".join(
        f"{item.dataset_id}: {format_count(item.retention_days)} days"
        for item in datasets
        if item.retention_days is not None
    )
    lineage_checks = kit.GlassCard(
        "Lineage and schema checks",
        "orphaned, stale and incompatible artefacts stay visible",
        body=ft.Column(
            [
                kit.Tag(
                    "Manual review required"
                    if catalogue_error
                    else "Available"
                    if catalogue_available
                    else "Unavailable",
                    "warn" if catalogue_error else "ok" if catalogue_available else "mute",
                    key="catalogue.status-tag",
                ),
                ft.Column(findings, spacing=4, scroll=ft.ScrollMode.AUTO),
                kit.Note(
                    "Snapshot IDs are content- and schema-addressed. Impact analysis identifies downstream artefacts before a source or formula change."
                ),
                kit.Note("Execution authority remains disabled."),
                kit.Disclosure(
                    "Retention and authority detail",
                    "\n".join(
                        (
                            "Execution allowed: false",
                            f"Raw status: {raw_status}",
                            f"Catalogue signature: {summary.get('catalogue_signature', 'Unavailable')}",
                            f"Retention metadata: {summary.get('retention_policy_dataset_count', 'Unavailable')} datasets",
                            retention_details or "Retention detail is unavailable.",
                            f"Catalogue read error: {catalogue_error or 'None'}",
                        )
                    ),
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    body = ft.Column(
        [
            kpi_strip,
            ft.Column([main_slot, provenance_card], spacing=8),
            ft.Column([lineage_card, lineage_checks], spacing=8),
        ],
        spacing=8,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        PageChrome(
            "Data Catalogue",
            "Local datasets, immutable snapshots and lineage · no remote fetch",
            (
                SegmentGroup(
                    "main_table",
                    ("Datasets", "Snapshots"),
                    "Datasets",
                    on_change=change_main,
                ),
            ),
        ),
        body,
    )


__all__ = ["catalogue_page"]
