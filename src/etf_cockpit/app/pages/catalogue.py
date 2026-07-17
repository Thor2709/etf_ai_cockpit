"""Read-only Data Catalogue and instrument provenance workspace."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import DataCatalogue, DataCatalogueError
from etf_cockpit.core.paths import ROOT


def catalogue_page(_page: ft.Page, state: AppState) -> ft.Control:
    instrument_id = str(getattr(state, "selected_etf", "") or "")
    try:
        catalogue = DataCatalogue(ROOT)
        summary = catalogue.summary()
        validation = catalogue.validate()
        provenance = catalogue.provenance_for(instrument_id) if instrument_id else {"snapshot_ids": [], "dataset_ids": []}
        datasets = catalogue.datasets
        snapshots = catalogue.snapshots
        error_text = ""
    except (DataCatalogueError, OSError) as exc:
        summary = {"status": "unavailable", "dataset_count": 0, "snapshot_count": 0}
        validation = {"status": "failed", "errors": [f"{type(exc).__name__}: local catalogue requires manual review"]}
        provenance = {"snapshot_ids": [], "dataset_ids": []}
        datasets = ()
        snapshots = ()
        error_text = f"Manual review required: the local catalogue could not be read ({type(exc).__name__})."

    status = str(summary.get("status", "unavailable"))
    status_colour = theme.GREEN if status == "available" else theme.AMBER
    if error_text:
        status_text = error_text
    else:
        status_text = (
            f"{status.title()}: {summary.get('dataset_count', 0)} dataset(s), "
            f"{summary.get('snapshot_count', 0)} immutable snapshot(s), "
            f"{summary.get('lineage_edge_count', 0)} lineage edge(s). "
            f"Orphans: {len(summary.get('orphan_snapshot_ids', []))}; "
            f"schema incompatibilities: {len(summary.get('incompatible_dataset_ids', []))}."
        )

    dataset_lines = [
        (
            f"{item.dataset_id} | layer={item.layer} | owner={item.owner} | source={item.source_id} | "
            f"licence={item.licence} | rows={item.row_count} | pii={item.pii_classification}"
        )
        for item in datasets
    ] or ["No datasets have been registered locally."]
    snapshot_lines = [
        (
            f"{item.snapshot_id} | rows={item.row_count} | sha256={item.content_sha256[:16]} | "
            f"upstream={len(item.dependency_snapshot_ids)} | stale={str(item.stale).lower()}"
        )
        for item in snapshots[-24:]
    ] or ["No immutable snapshots have been registered locally."]
    provenance_lines = [
        f"{item} | dataset={next((snapshot.dataset_id for snapshot in snapshots if snapshot.snapshot_id == item), 'unavailable')}"
        for item in provenance.get("snapshot_ids", [])
    ] or [f"No snapshot coverage is registered for {instrument_id or 'the selected instrument'}."]
    errors = validation.get("errors", [])
    validation_text = "\n".join(str(item) for item in errors) or "Lineage and schema contracts pass."

    return ft.Column(
        [
            section_header(
                "Data Catalogue",
                "Generated local metadata, immutable dataset snapshots and redacted provenance; no remote fetch or execution authority.",
            ),
            panel(
                ft.Column(
                    [
                        ft.Text(status_text, color=status_colour, selectable=True),
                        ft.Text(
                            "Snapshot IDs are content- and schema-addressed. Impact analysis identifies downstream artefacts before a source or formula change.",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        ft.Text(
                            f"Execution allowed: false | Retention metadata: {summary.get('retention_policy_dataset_count', 0)} dataset(s); compaction is read-only.",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                    ],
                    spacing=8,
                )
            ),
            panel(ft.Column([section_header("Registered datasets", "Owner, source, licence, quality and retention metadata."), ft.Text("\n".join(dataset_lines), color=theme.TEXT, selectable=True)])),
            panel(ft.Column([section_header("Immutable snapshots", "Content hashes, row counts and dependency edges for reproducible local data."), ft.Text("\n".join(snapshot_lines), color=theme.MUTED, selectable=True)])),
            panel(
                ft.Column(
                    [
                        section_header("Instrument provenance explorer", f"Selected instrument: {instrument_id or 'none'}"),
                        ft.Text("\n".join(provenance_lines), color=theme.MUTED, selectable=True),
                    ]
                )
            ),
            panel(ft.Column([section_header("Lineage and schema checks", "Orphaned, stale and incompatible artefacts remain visible and non-authoritative."), ft.Text(validation_text, color=theme.MUTED, selectable=True)])),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["catalogue_page"]
