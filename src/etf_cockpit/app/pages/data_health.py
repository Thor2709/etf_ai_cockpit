from __future__ import annotations

from datetime import date

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_date, format_timestamp
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    AnomalyLedger,
    DataHealthReport,
    DataHealthStatus,
    build_data_health,
    bulk_cache_health,
    export_data_health,
    filter_data_health_rows,
)
from etf_cockpit.core.paths import ROOT


def data_health_page(page: ft.Page, state: AppState) -> PageView:
    report = build_data_health(
        state.snapshot.config,
        ROOT,
        as_of_date=state.snapshot.data_report.as_of_date,
    )
    cache_report = bulk_cache_health(ROOT)
    decision_date = state.snapshot.data_report.as_of_date
    anomaly_summary = AnomalyLedger().summary(
        root=ROOT,
        decision_time=f"{decision_date}T23:59:59+00:00",
    )
    rows = tuple(report.rows)
    status_names = {
        DataHealthStatus.HEALTHY: "Healthy",
        DataHealthStatus.STALE: "Stale",
        DataHealthStatus.MISSING: "Missing",
        DataHealthStatus.CORRUPT: "Corrupt",
        DataHealthStatus.SCHEMA_MISMATCH: "Schema mismatch",
        DataHealthStatus.UNAVAILABLE: "Unavailable",
    }
    status_kinds = {
        DataHealthStatus.HEALTHY: "ok",
        DataHealthStatus.STALE: "warn",
        DataHealthStatus.MISSING: "bad",
        DataHealthStatus.CORRUPT: "bad",
        DataHealthStatus.SCHEMA_MISMATCH: "bad",
        DataHealthStatus.UNAVAILABLE: "mute",
    }
    status_counts = {
        status: sum(row.status is status for row in rows) for status in DataHealthStatus
    }
    data_reason = "No data health rows are available."

    if rows:
        if any(row.status is DataHealthStatus.CORRUPT for row in rows):
            health_label = "Failed"
        elif any(row.status is not DataHealthStatus.HEALTHY for row in rows):
            health_label = "Review"
        else:
            health_label = "Clean"
        attention = len(rows) - status_counts[DataHealthStatus.HEALTHY]
        headline_sub = f"{format_count(attention)} of {format_count(len(rows))} stores need attention"
        dataset_value = format_count(len(rows))
        healthy_value = format_count(status_counts[DataHealthStatus.HEALTHY])
        attention_value = format_count(attention)
    else:
        health_label = "Unavailable"
        headline_sub = data_reason
        dataset_value = healthy_value = attention_value = None

    as_of_value = format_date(report.as_of_date, unavailable="—") if report.as_of_date else None
    as_of_reason = "Snapshot data-quality date is unavailable."
    kpi_strip = kit.KpiStrip(
        "Data health",
        f"Data health is {health_label}",
        headline_sub,
        [
            ("Datasets", dataset_value, "configured stores" if rows else data_reason, None),
            ("Healthy", healthy_value, "passing freshness and schema checks" if rows else data_reason, None),
            (
                "Needs attention",
                attention_value,
                "stale, missing, corrupt or unavailable" if rows else data_reason,
                "neg" if rows and attention else None,
            ),
            (
                "As of",
                as_of_value,
                "snapshot data-quality date" if as_of_value else as_of_reason,
                None,
            ),
        ],
    )

    selected = {"status": "All", "dataset": "All", "provider": "All"}
    active_segment = {"status": "All"}
    table_slot = ft.Column(spacing=0)
    visible_rows = list(rows)

    def quick_links() -> ft.Row:
        from etf_cockpit.app.router import navigate_to

        routes = (
            ("Provider status", "/providers", "navigation.providers"),
            ("Filings", "/filings", "navigation.filings"),
            ("ETF", "/etf", "navigation.etf"),
            ("Errors", "/errors", "navigation.errors"),
        )
        return ft.Row(
            [
                kit.Button.secondary(
                    label,
                    on_click=lambda event, destination=route: navigate_to(
                        page, state, destination
                    ),
                    key=key,
                )
                for label, route, key in routes
            ],
            spacing=4,
            wrap=True,
        )

    def make_table_rows(source_rows: tuple[object, ...]) -> list[dict[str, object]]:
        table_rows: list[dict[str, object]] = []
        for row in source_rows:
            warnings = "; ".join(row.warnings) if row.warnings else "—"
            detail = "\n".join(
                (
                    f"Path: {row.path}",
                    f"Checksum: {row.checksum or '—'}",
                    f"Raw status: {row.status.value}",
                    f"Flags: {warnings}",
                    f"Last success: {row.last_success or '—'}",
                    f"Last failure: {row.last_failure or '—'}",
                )
            )
            count_is_missing = row.status in {
                DataHealthStatus.MISSING,
                DataHealthStatus.CORRUPT,
                DataHealthStatus.UNAVAILABLE,
            }
            timestamp = " · ".join(
                (
                    format_timestamp(row.last_success, unavailable="—"),
                    format_timestamp(row.last_failure, unavailable="—"),
                )
            )
            table_rows.append(
                {
                    "dataset": row.dataset,
                    "status": kit.Tag(status_names[row.status], status_kinds[row.status]),
                    "rows": None if count_is_missing else format_count(row.row_count, unavailable="—"),
                    "as_of": format_date(row.as_of, unavailable="—"),
                    "freshness": row.freshness.title() if row.freshness else "—",
                    "provider": row.provider or None,
                    "history": timestamp,
                    "checksum": "Available" if row.checksum else None,
                    "links": ft.Column(
                        [quick_links(), kit.Disclosure("Full record", detail)],
                        spacing=4,
                    ),
                }
            )
        return table_rows

    def filtered_rows() -> tuple[object, ...]:
        candidates = filter_data_health_rows(
            rows,
            dataset=selected["dataset"],
            provider=selected["provider"],
        )
        status = active_segment["status"]
        if status == "Needs attention":
            return tuple(row for row in candidates if row.status is not DataHealthStatus.HEALTHY)
        if status == "Healthy":
            return tuple(row for row in candidates if row.status is DataHealthStatus.HEALTHY)
        return filter_data_health_rows(candidates, status=selected["status"])

    def redraw_inventory() -> None:
        nonlocal visible_rows
        visible_rows = list(filtered_rows())
        table_slot.controls = [
            kit.DataTable(
                [
                    kit.TableColumn("dataset", "Dataset", flex=2),
                    kit.TableColumn("status", "Status"),
                    kit.TableColumn("rows", "Rows", numeric=True),
                    kit.TableColumn("as_of", "As of"),
                    kit.TableColumn("freshness", "Freshness"),
                    kit.TableColumn("provider", "Provider"),
                    kit.TableColumn("history", "Last success / failure", flex=2),
                    kit.TableColumn("checksum", "Checksum"),
                    kit.TableColumn("links", "Quick links", flex=2, sortable=False),
                ],
                make_table_rows(tuple(visible_rows)),
                empty_title="No datasets",
                empty_reason=data_reason,
            )
        ]
        if getattr(page, "update", None):
            try:
                page.update()
            except (RuntimeError, AttributeError):
                pass

    def change_segment(value: str) -> None:
        active_segment["status"] = value
        redraw_inventory()

    def redraw(event: ft.ControlEvent) -> None:
        selected_value = str(getattr(event.control, "value", "All") or "All")
        control_key = getattr(event.control, "key", "")
        if control_key == "data-health.filter.status":
            selected["status"] = selected_value
        elif control_key == "data-health.filter.dataset":
            selected["dataset"] = selected_value
        elif control_key == "data-health.filter.provider":
            selected["provider"] = selected_value
        redraw_inventory()

    filters = ft.Row(
        [
            kit.Field(
                "Filter status",
                control=ft.Dropdown(
                    value="All",
                    options=[ft.dropdown.Option(value) for value in ("All", *(status.value for status in DataHealthStatus))],
                    on_select=redraw,
                    key="data-health.filter.status",
                ),
            ),
            kit.Field(
                "Filter dataset",
                control=ft.Dropdown(
                    value="All",
                    options=[ft.dropdown.Option(value) for value in ("All", *(row.dataset for row in rows))],
                    on_select=redraw,
                    key="data-health.filter.dataset",
                ),
            ),
            kit.Field(
                "Filter provider",
                control=ft.Dropdown(
                    value="All",
                    options=[
                        ft.dropdown.Option(value)
                        for value in (
                            "All",
                            *sorted({row.provider for row in rows if row.provider}),
                        )
                    ],
                    on_select=redraw,
                    key="data-health.filter.provider",
                ),
            ),
        ],
        spacing=8,
        wrap=True,
    )

    export_feedback = ft.Column([kit.Note("")], spacing=0)
    export_location_slot = ft.Column(
        [kit.Disclosure("Export location", str(ROOT / "data" / "derived" / "data_health.csv"))],
        spacing=0,
    )

    def export(_event: object) -> None:
        destination = ROOT / "data" / "derived" / "data_health.csv"
        try:
            export_data_health(
                DataHealthReport(report.created_at, report.as_of_date, tuple(visible_rows)),
                destination,
            )
        except Exception as exc:
            state.last_message = f"Data health export failed: {type(exc).__name__}: {exc}"
            export_feedback.controls = [kit.Note(state.last_message)]
        else:
            state.last_message = "Data health export completed."
            export_feedback.controls = [kit.Note(state.last_message)]
            export_location_slot.controls = [kit.Disclosure("Export location", str(destination))]
        if getattr(page, "update", None):
            try:
                page.update()
            except (RuntimeError, AttributeError):
                pass

    export_button = kit.Button.secondary(
        "Export health CSV",
        on_click=export,
        key="data-health.export",
    )
    inventory_body = ft.Column(
        [
            filters,
            kit.Note("Filters update the inventory and export the visible rows only."),
            ft.Row([export_button, export_feedback], spacing=8, wrap=True),
            table_slot,
            export_location_slot,
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )
    inventory_card = kit.GlassCard(
        "Dataset inventory",
        "every store, no hidden columns",
        body=inventory_body,
        expand=2,
    )
    redraw_inventory()

    chart_slices = [
        ck.Slice("Healthy", status_counts[DataHealthStatus.HEALTHY], theme.CHART_POS),
        ck.Slice("Stale", status_counts[DataHealthStatus.STALE], theme.AMBER),
        ck.Slice("Missing", status_counts[DataHealthStatus.MISSING], theme.CHART_NEG),
        ck.Slice("Corrupt", status_counts[DataHealthStatus.CORRUPT], theme.RED),
        ck.Slice("Schema mismatch", status_counts[DataHealthStatus.SCHEMA_MISMATCH], theme.STRIP_NEG),
        ck.Slice("Unavailable", status_counts[DataHealthStatus.UNAVAILABLE], theme.MUTED),
    ]
    missing_count = status_counts[DataHealthStatus.MISSING]
    healthy_count = status_counts[DataHealthStatus.HEALTHY]
    status_insight = (
        f"{format_count(missing_count)} stores are missing; "
        f"{format_count(healthy_count)} are healthy."
        if rows
        else None
    )
    status_chart = ck.donut_chart(
        chart_slices,
        unit="stores",
        unavailable_reason=data_reason if not rows else None,
        empty_title="No dataset status",
        insight=status_insight,
    )

    ages: list[tuple[str, int, str]] = []
    try:
        cutoff = date.fromisoformat(str(report.as_of_date)[:10])
    except ValueError:
        cutoff = None
    if cutoff is not None:
        for row in rows:
            try:
                observed = date.fromisoformat(str(row.as_of)[:10]) if row.as_of else None
            except ValueError:
                observed = None
            if observed is not None:
                ages.append((row.dataset, (cutoff - observed).days, row.status.value))
    oldest = max(ages, key=lambda item: item[1]) if ages else None
    freshness_insight = (
        f"{oldest[0]} is the stalest ({format_count(oldest[1])} days)." if oldest else None
    )
    freshness_chart = ck.horizontal_stacked_bar(
        [item[0] for item in ages],
        [
            [
                ck.Segment(
                    item[1],
                    kind=(
                        "pos"
                        if item[2] == DataHealthStatus.HEALTHY.value
                        else "gold"
                        if item[2] == DataHealthStatus.STALE.value
                        else "neg"
                        if item[2]
                        in {
                            DataHealthStatus.MISSING.value,
                            DataHealthStatus.CORRUPT.value,
                            DataHealthStatus.SCHEMA_MISMATCH.value,
                        }
                        else "blue"
                    ),
                    label=f"{format_count(item[1])} days",
                )
            ]
            for item in ages
        ],
        x_name="Age (days)",
        empty_title="No freshness observations",
        unavailable_reason="No dataset has an as-of date." if not ages else None,
        insight=freshness_insight,
    )
    freshness_note = (
        kit.Note("Datasets without an as-of date are unavailable in this chart.")
        if len(ages) < len(rows)
        else None
    )

    quality_counts = anomaly_summary.get("counts")
    quality_available = anomaly_summary.get("status") == "available" and isinstance(
        quality_counts, dict
    )
    quality_reason = str(
        anomaly_summary.get("reason") or "Anomaly quality results are unavailable."
    )
    quality_tiles = ft.Row(
        [
            kit.KpiTile(
                label,
                format_count(quality_counts.get(raw)) if quality_available else None,
                "Current quality findings" if quality_available else quality_reason,
                expand=True,
            )
            for label, raw in (
                ("Pass", "pass"),
                ("Warn", "warn"),
                ("Quarantine", "quarantine"),
                ("Block", "block"),
            )
        ],
        spacing=4,
    )
    quality_line = (
        "Unresolved "
        + format_count(anomaly_summary.get("unresolved_count"), unavailable="Unavailable")
        + " · blocked downstream "
        + format_count(anomaly_summary.get("blocked_downstream_count"), unavailable="Unavailable")
        + " · corrections "
        + format_count(anomaly_summary.get("correction_count"), unavailable="Unavailable")
    )
    anomaly_body = ft.Column(
        [
            quality_tiles,
            kit.Note(quality_line),
            kit.Tag(
                "Review available" if quality_available else "Unavailable",
                "ok" if quality_available else "mute",
            ),
            kit.Disclosure(
                "Quality rule detail",
                "\n".join(
                    (
                        f"Raw status: {anomaly_summary.get('status', 'unavailable')}",
                        f"Reason: {quality_reason}",
                        f"Rule coverage: {anomaly_summary.get('rule_count', 'Unavailable')}",
                        f"Versions: {', '.join(anomaly_summary.get('rule_versions', [])) or 'Unavailable'}",
                        f"Invalidation token: {anomaly_summary.get('invalidation_token', 'Unavailable')}",
                        f"execution_allowed={str(anomaly_summary.get('execution_allowed', False)).lower()}",
                        "network_calls=false",
                    )
                ),
            ),
        ],
        spacing=8,
    )

    cache_reason = "Bulk cache health is unavailable."
    cache_fields = (
        ("Objects", "object_count"),
        ("Manifests", "manifest_count"),
        ("Staged", "staged_file_count"),
        ("Promoted generations", "promoted_generation_count"),
    )
    cache_available = all(key in cache_report for _, key in cache_fields)
    cache_tiles = ft.Row(
        [
            kit.KpiTile(
                label,
                format_count(cache_report.get(key)) if cache_available else None,
                "Validated local cache inventory" if cache_available else cache_reason,
                expand=True,
            )
            for label, key in cache_fields
        ],
        spacing=4,
    )
    cache_status = str(cache_report.get("status") or "unavailable")
    cache_body = ft.Column(
        [
            cache_tiles,
            kit.Tag(
                "Validated" if cache_status == "passed" else "Review",
                "ok" if cache_status == "passed" else "warn",
            ),
            kit.Note(
                "Raw bulk sources are immutable and content-addressed. Only validated staged generations may be promoted into analysis."
            ),
            kit.Disclosure(
                "Cache detail",
                "\n".join(
                    (
                        f"Raw status: {cache_status}",
                        f"Cache path: {cache_report.get('cache_path', 'Unavailable')}",
                        f"Failures: {', '.join(cache_report.get('failures', [])) or 'None'}",
                        f"network_calls={str(cache_report.get('network_calls', False)).lower()}",
                    )
                ),
            ),
        ],
        spacing=8,
    )

    subtitle = "Freshness, coverage and schema checks for every local store · created "
    subtitle += format_timestamp(report.created_at, unavailable="Unavailable")
    body = ft.Column(
        [
            kpi_strip,
            ft.Column(
                [
                    inventory_card,
                    kit.GlassCard(
                        "Datasets by status",
                        f"{format_count(len(rows))} stores" if rows else "Unavailable",
                        status_insight,
                        body=kit.Well(status_chart, expand=True),
                        expand=True,
                    ),
                ],
                spacing=8,
            ),
            ft.Column(
                [
                    kit.GlassCard(
                        "Freshness by dataset",
                        "days since the latest observation",
                        freshness_insight,
                        body=ft.Column(
                            [kit.Well(freshness_chart, expand=True)]
                            + ([freshness_note] if freshness_note else []),
                            spacing=8,
                        ),
                        expand=2,
                    ),
                    kit.GlassCard(
                        "Anomaly rules and quarantine",
                        "versioned local rules",
                        body=anomaly_body,
                        expand=True,
                    ),
                    kit.GlassCard(
                        "Bulk source cache",
                        "content-addressed · validated generations only",
                        body=cache_body,
                        expand=True,
                    ),
                ],
                spacing=8,
            ),
        ],
        spacing=8,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        chrome=PageChrome(
            "Data Health",
            subtitle,
            (
                SegmentGroup(
                    "status",
                    ("All", "Healthy", "Needs attention"),
                    "All",
                    on_change=change_segment,
                ),
            ),
        ),
        body=body,
    )


__all__ = ["data_health_page"]
