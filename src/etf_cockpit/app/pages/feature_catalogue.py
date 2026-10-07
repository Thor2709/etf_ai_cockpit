from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    DataTable,
    Disclosure,
    GlassCard,
    KpiStrip,
    KpiStripItem,
    ListRow,
    Note,
    TableColumn,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_count, format_percent
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.feature_service import LocalFeatureStore


def feature_catalogue_page(page: ft.Page, state: AppState) -> PageView:
    """Show versioned feature definitions and their local training preview."""
    del page
    store = LocalFeatureStore(ROOT)
    catalogue = store.feature_catalogue()
    targets = store.target_catalogue()
    source = getattr(getattr(state, "snapshot", None), "features", None)
    coverage = store.coverage(source) if source is not None else None

    def display_value(value: object) -> str:
        if value is None:
            return "—"
        text = str(value).strip()
        return text if text.casefold() not in {"", "none", "nan", "nat"} else "—"

    feature_rows = [
        {
            "feature": display_value(item.feature_id),
            "source": display_value(item.source_column),
            "lookback": f"{format_count(item.lookback_days, unavailable='—')}d / +{format_count(item.availability_delay_days, unavailable='—')}d",
            "units": display_value(item.units),
            "missing": display_value(item.missing_policy),
        }
        for item in catalogue
    ]
    feature_columns = [
        TableColumn("feature", "Feature"),
        TableColumn("source", "Source"),
        TableColumn("lookback", "Lookback / delay"),
        TableColumn("units", "Units"),
        TableColumn("missing", "Missing"),
    ]
    if coverage is None:
        coverage_values: dict[str, float | None] = {}
        preview_rows: list[dict[str, object]] = []
        preview_columns = [TableColumn("preview", "Training data preview")]
        preview_reason = "No feature snapshot is available for the current decision time."
    else:
        raw_coverage = coverage.get("coverage", {})
        coverage_values = raw_coverage if isinstance(raw_coverage, dict) else {}
        preview_reason = "No feature preview rows are available in the local snapshot."
        preview_columns = [TableColumn("decision_timestamp", "Decision timestamp"), *[TableColumn(str(item.feature_id), str(item.feature_id)) for item in catalogue]]
        preview_rows = []
        if hasattr(source, "empty") and not source.empty:
            preview_rows = [
                {key: row.get(key) for key in ("decision_timestamp", *(item.feature_id for item in catalogue))}
                for row in source.head(8).to_dict(orient="records")
            ]
    coverage_items = sorted(coverage_values.items())
    coverage_values_ordered = [value * 100 if value is not None else None for _, value in coverage_items]
    coverage_kinds = ["gold" if value is not None and value < 80 else "blue" for value in coverage_values_ordered]
    available_coverage = [(name, value) for name, value in coverage_items if value is not None and format_percent(value, unavailable="")]
    lowest_name, lowest_value = min(available_coverage, key=lambda item: item[1]) if available_coverage else (None, None)
    lowest_insight = (
        f"{lowest_name} has the lowest coverage ({format_percent(lowest_value, unavailable='—')})."
        if lowest_name is not None and lowest_value is not None
        else "Unavailable: no feature coverage rows are available."
    )
    target_text = "No target definitions are registered."
    if targets:
        target_text = "\n".join(
            f"{display_value(item.target_id)}: {display_value(item.kind)}, horizon={format_count(item.horizon_days, unavailable='—')}d, embargo={format_count(item.embargo_days, unavailable='—')}d"
            for item in targets
        )
    feature_count = len(catalogue) if catalogue else None
    target_count = len(targets) if targets else None
    preview_available = source is not None and hasattr(source, "empty") and not source.empty and coverage is not None
    preview_count = coverage.get("rows") if preview_available else None
    missing_count = coverage.get("missing_rows") if preview_available else None
    feature_value = format_count(feature_count, unavailable="") or None
    target_value = format_count(target_count, unavailable="") or None
    preview_value = format_count(preview_count, unavailable="") or None
    missing_value = format_count(missing_count, unavailable="") or None
    kpi = KpiStrip(
        "FEATURES REGISTERED",
        feature_value or "Unavailable",
        "definitions and built-in baselines" if feature_value else "No feature definitions are registered.",
        [
            KpiStripItem("Registered features", feature_value, "No feature definitions are registered." if not feature_value else ""),
            KpiStripItem("Targets", target_value, "No target definitions are registered." if not target_value else "Stored separately from features."),
            KpiStripItem("Preview rows", preview_value, "No feature snapshot rows are available." if not preview_value else "Local feature snapshot."),
            KpiStripItem("Missing rows", missing_value, "Missing-row count is unavailable without preview rows." if not missing_value else "Visible, never silently imputed."),
        ],
    )
    definitions = GlassCard(
        "Feature definitions",
        note="Lookbacks, delay, units and missing policy are part of the contract",
        body=DataTable(feature_columns, feature_rows, empty_title="No feature definitions", empty_reason="The local feature catalogue has no registered definitions."),
        expand=True,
    )
    coverage_card = GlassCard(
        "Feature coverage",
        insight=lowest_insight,
        body=ck.bar_chart(
            [name for name, _ in coverage_items],
            coverage_values_ordered,
            kinds=coverage_kinds,
            x_name="Feature",
            y_name="Coverage",
            unit="%",
            unavailable_reason="No feature coverage result is available from the current snapshot." if not available_coverage else None,
            insight=lowest_insight,
        ),
        expand=True,
    )
    preview = GlassCard(
        "Training data preview",
        note="Selected by decision timestamp",
        body=ft.Column(
            [
                DataTable(preview_columns, preview_rows, empty_title="Training preview unavailable", empty_reason=preview_reason),
                Note("Rows are selected by decision timestamp; late revisions cannot enter earlier vintages."),
                Note("Parity: offline, paper and disabled live-inference contracts share the same feature definitions."),
                Disclosure("Coverage details", str(coverage.get("coverage", {})) if coverage is not None else "Unavailable"),
            ],
            spacing=8,
        ),
        expand=True,
    )
    leakage = GlassCard(
        "Targets and leakage controls",
        body=ft.Column(
            [
                ListRow("info", "Targets", "None registered; targets remain separate from inference inputs." if not targets else f"{format_count(len(targets))} registered; targets remain separate from inference inputs."),
                Disclosure("Registered target definitions", target_text),
                ListRow("ok", "Embargo checks", "Overlapping target windows are rejected before validation."),
                ListRow("ok", "Parity", "Offline, paper and disabled live-inference share the same feature definitions."),
                Note("execution_allowed=false"),
            ],
            spacing=8,
        ),
        expand=True,
    )
    return PageView(
        chrome=PageChrome("Feature Catalogue", "Versioned point-in-time feature definitions and a leakage-safe training preview"),
        body=ft.Column(
            [
                kpi,
                ft.Row([definitions, coverage_card], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Row([preview, leakage], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
    )


__all__ = ["feature_catalogue_page"]
