from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import ROOT
from etf_cockpit.features.feature_store import LocalFeatureStore


def feature_catalogue_page(page: ft.Page, state: AppState) -> ft.Control:
    """Show feature definitions and a safe local training-data preview."""

    del page
    store = LocalFeatureStore(ROOT)
    catalogue = store.feature_catalogue()
    targets = store.target_catalogue()
    source = getattr(state.snapshot, "features", None)
    coverage = store.coverage(source) if source is not None else {"rows": 0, "features": 0, "coverage": {}, "missing_rows": 0}
    feature_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(item.feature_id, size=12)),
                ft.DataCell(ft.Text(item.source_column, color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(f"{item.lookback_days}d / +{item.availability_delay_days}d", color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(item.units, color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(item.missing_policy, color=theme.MUTED, size=12)),
            ]
        )
        for item in catalogue
    ]
    target_text = "None registered; targets remain separate from inference inputs."
    if targets:
        target_text = "\n".join(
            f"{item.target_id}: {item.kind}, horizon={item.horizon_days}d, embargo={item.embargo_days}d"
            for item in targets
        )
    return ft.Column(
        [
            section_header(
                "Feature Catalogue",
                "Versioned, point-in-time feature definitions and a leakage-safe training data preview.",
            ),
            ft.Row(
                [
                    metric_card("Registered features", str(len(catalogue)), "definitions and built-in baselines"),
                    metric_card("Targets", str(len(targets)), "stored separately from features"),
                    metric_card("Preview rows", str(coverage.get("rows", 0)), "local feature snapshot"),
                    metric_card("Missing rows", str(coverage.get("missing_rows", 0)), "visible, never silently imputed"),
                ],
                spacing=12,
            ),
            panel(
                ft.Column(
                    [
                        section_header("Feature definitions", "Lookbacks, availability delay, units and missing policy are part of the contract."),
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Feature")),
                                ft.DataColumn(ft.Text("Source")),
                                ft.DataColumn(ft.Text("Lookback / delay")),
                                ft.DataColumn(ft.Text("Units")),
                                ft.DataColumn(ft.Text("Missing")),
                            ],
                            rows=feature_rows,
                        )
                        if feature_rows
                        else ft.Text("No feature definitions are available.", color=theme.MUTED),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
            ),
            ft.Row(
                [
                    panel(
                        ft.Column(
                            [
                                section_header("Training data preview", "Rows are selected by decision timestamp; late revisions cannot enter earlier vintages."),
                                ft.Text("Feature matrix: local snapshot only; run materialisation for an explicit as-of date.", color=theme.MUTED, selectable=True),
                                ft.Text(f"Coverage: {coverage.get('coverage', {})}", color=theme.MUTED, selectable=True),
                                ft.Text("Parity: offline, paper and disabled live-inference contracts share the same feature definitions.", color=theme.MUTED, selectable=True),
                            ],
                            spacing=8,
                        ),
                        expand=True,
                    ),
                    panel(
                        ft.Column(
                            [
                                section_header("Targets and leakage controls", "Outcomes mature after the decision timestamp and are never copied into feature inputs."),
                                ft.Text(target_text, color=theme.MUTED, selectable=True),
                                ft.Text("Embargo checks: overlapping target windows are rejected before validation.", color=theme.MUTED, selectable=True),
                                ft.Text("execution_allowed=false", color=theme.MUTED, selectable=True),
                            ],
                            spacing=8,
                        ),
                        expand=True,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


__all__ = ["feature_catalogue_page"]
