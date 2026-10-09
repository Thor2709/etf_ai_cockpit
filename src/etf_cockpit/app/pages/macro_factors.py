"""Point-in-time macro and factors context page."""

from __future__ import annotations

import math

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck, kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l2_common import display_value
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.macro_context import build_macro_context_binding
from etf_cockpit.application.ui_facade import MacroWarehouse
from etf_cockpit.core.paths import ROOT


def _regime_tag(value: object) -> ft.Control:
    available = value is not None and str(value).strip().casefold() not in {"", "unavailable", "none", "nan", "nat"}
    return kit.Tag("Available" if available else "Unavailable", "ok" if available else "warn")


def macro_factors_page(page: ft.Page | None, state: AppState) -> PageView:
    def refresh_context(event: ft.ControlEvent) -> None:
        if page is not None:
            from etf_cockpit.app.pages.dashboard import _run_action

            _run_action(page, state, "Refresh macro/news context", state.refresh_signals)

    reference_context = context_from_snapshot(
        state.snapshot,
        purpose="comparison",
        analysis_id=f"macro:{getattr(state.snapshot, 'universe_revision', 'unavailable')}",
    )
    binding = build_macro_context_binding(
        state.snapshot,
        warehouse=MacroWarehouse(),
        root=ROOT,
        benchmark_data_id=reference_context.benchmark_data_id,
        benchmark_reference=reference_context.projection,
        benchmark_registry=reference_context.registry,
    )
    summary = binding.summary
    observations = list(binding.observations)
    curve_coverage = binding.curve_coverage
    macro_context = binding.context
    scenario_context = binding.scenario
    decision_time = binding.decision_time or "Unavailable"
    unavailable = binding.error or summary.get("reason") or "No local macro snapshot is available."
    regime = macro_context.get("regime", {})
    breadth = macro_context.get("breadth", {})
    volatility = macro_context.get("volatility", {})
    inflation = macro_context.get("inflation_rates", {})
    breadth_value = _numeric_value(breadth.get("pct_above_sma200"))
    volatility_value = _numeric_value(volatility.get("median_annualised"))
    view_state = {"view": "Regime", "horizon": "1Y"}
    view_note = kit.Note("View: Regime · Horizon: 1Y")
    view_sections: dict[str, ft.Control] = {}

    def change_view(value: str) -> None:
        view_state["view"] = value
        view_note.value = f"View: {value} · Horizon: {view_state['horizon']}"
        for name, section in view_sections.items():
            section.visible = name == value
        if page is not None:
            page.update()

    def change_horizon(value: str) -> None:
        view_state["horizon"] = value
        view_note.value = f"View: {view_state['view']} · Horizon: {value}"
        if page is not None:
            page.update()

    regime_label = regime.get("label")
    regime_rows = [
        ft.Row([kit.Headline(str(regime_label or "Unavailable"), 54), _regime_tag(regime_label)], spacing=12, wrap=True),
        kit.KpiTile(
            "Breadth above SMA200",
            _format_metric(breadth_value) if breadth_value is not None else None,
            "Local breadth observation unavailable." if breadth_value is None else "Context only",
        ),
        kit.KpiTile(
            "Median annualised vol",
            _format_metric(volatility_value) if volatility_value is not None else None,
            "Local volatility observation unavailable." if volatility_value is None else "Context only",
        ),
    ]
    proxy_details = [
        f"{row.get('proxy', 'Unavailable')}: {row.get('status', 'Unavailable')}; "
        f"return={_format_metric(row.get('period_return_20d'))}; "
        f"volatility={_format_metric(row.get('volatility_annualised'))}; "
        f"as of={row.get('as_of') or 'Unavailable'}; freshness={row.get('freshness_status') or 'Unavailable'}"
        for row in macro_context.get("proxy_rows", [])
    ]
    regime_card = kit.GlassCard(
        "Regime and proxy context",
        "local snapshot",
        body=ft.Column(
            [
                *regime_rows,
                kit.Disclosure(
                    "Proxy details",
                    "\r\n".join(proxy_details) if proxy_details else unavailable,
                ),
                kit.Note("Context only. No score, forecast or execution authority is created."),
            ],
            spacing=8,
        ),
    )

    colours = (theme.BAR_BLUE, theme.CHART_POS, theme.CHART_NEG, theme.AMBER)
    unit_groups: dict[str, list[object]] = {}
    for row in observations:
        unit_groups.setdefault(display_value(row.unit), []).append(row)
    chart_wells: list[ft.Control] = []
    for unit, unit_rows in sorted(unit_groups.items()):
        dates = sorted(
            {
                display_value(row.period_start)
                for row in unit_rows
                if display_value(row.period_start) != "—"
            }
        )
        series_ids = sorted({str(row.series_id) for row in unit_rows})
        chart_series = []
        for index, series_id in enumerate(series_ids):
            values_by_date = {
                display_value(row.period_start): _numeric_value(row.value)
                for row in unit_rows
                if str(row.series_id) == series_id
                and display_value(row.period_start) != "—"
            }
            chart_series.append(
                ck.Series(
                    series_id,
                    [values_by_date.get(date) for date in dates],
                    color=colours[index % len(colours)],
                    unit=unit,
                )
            )
        has_values = any(_numeric_value(row.value) is not None for row in unit_rows)
        chart_wells.extend(
            [
                kit.Note(f"Unit: {unit}"),
                kit.Well(
                    ck.line_chart(
                        dates,
                        chart_series,
                        x_name="Date",
                        y_name=f"Value ({unit})",
                        unavailable_reason=(
                            None
                            if has_values
                            else f"No numeric observations are available for {unit}."
                        ),
                        empty_title="Unavailable",
                        insight="Local macro and factor observations available at the recorded decision time.",
                    ),
                    expand=True,
                ),
            ]
        )
    if not chart_wells:
        chart_wells = [
            kit.Well(
                ck.line_chart(
                    [],
                    [],
                    x_name="Date",
                    y_name="Value (unit unavailable)",
                    unavailable_reason=str(unavailable),
                    empty_title="Unavailable",
                    insight="Local macro and factor observations available at the recorded decision time.",
                ),
                expand=True,
            )
        ]
    series_card = kit.GlassCard(
        "Macro series",
        "point-in-time observations grouped by unit",
        body=ft.Column(chart_wells, spacing=8),
    )

    curve_status = str(curve_coverage.get("status") or "unavailable")
    curve_card = kit.GlassCard(
        "Risk-free curves and lawful benchmarks",
        "coverage",
        body=ft.Column(
            [
                kit.Tag(
                    "Available" if curve_status == "available" else "Unavailable",
                    "ok" if curve_status == "available" else "warn",
                ),
                kit.Note(
                    "Curve interpolation is bounded and declared per curve. Extrapolation and unsupported currency or horizon fallbacks remain unavailable."
                ),
                kit.Disclosure(
                    "Curve and benchmark detail",
                    "\r\n".join(
                        (
                            f"Decision time: {curve_coverage.get('decision_time') or decision_time}",
                            f"Curve identifiers: {', '.join(curve_coverage.get('curve_ids') or ()) or 'Unavailable'}",
                            f"Curve types: {', '.join(curve_coverage.get('curve_types') or ()) or 'Unavailable'}",
                            f"Currencies: {', '.join(curve_coverage.get('currencies') or ()) or 'Unavailable'}",
                            f"Benchmarks: {', '.join(curve_coverage.get('benchmark_ids') or ()) or 'Unavailable'}",
                            f"Sources and methodology: {', '.join(curve_coverage.get('source_ids') or ()) or 'Unavailable'} / {', '.join(curve_coverage.get('methodologies') or ()) or 'Unavailable'}",
                        )
                    ),
                ),
            ],
            spacing=8,
        ),
    )

    latest_rows = []
    for row in sorted(observations, key=lambda item: (item.dataset_id, item.period_start, item.series_id))[-24:]:
        latest_rows.append(
            {
                "dataset": str(row.dataset_id),
                "series": str(row.series_id),
                "period": str(row.period_start),
                "value": display_value(row.value),
                "observed": display_value(row.observed_at),
                "available_at": display_value(row.available_at),
                "vintage": display_value(row.revision),
                "unit": str(row.unit or "—"),
                "freshness": kit.Tag(
                    display_value(row.freshness_status).replace("_", " ").title(),
                    "warn",
                ),
                "detail": kit.Disclosure(
                    "Observation provenance",
                    "\r\n".join(
                        (
                            f"Source: {row.source_id or 'Unavailable'}",
                            f"Authority: {row.source_authority or 'Unavailable'}",
                            f"Observed: {row.observed_at or 'Unavailable'}",
                            f"Published: {row.published_at or 'Unavailable'}",
                            f"Available: {row.available_at or 'Unavailable'}",
                            f"Revision: {row.revision}",
                            f"Source checksum: {row.source_checksum or 'Unavailable'}",
                            f"Transformation: {row.transformation_version or 'Unavailable'}",
                        )
                    ),
                ),
            }
        )
    observations_card = kit.GlassCard(
        "Latest local observations",
        "selected local values",
        body=(
            kit.DataTable(
                [
                    kit.TableColumn("series", "Series"),
                    kit.TableColumn("value", "Value", numeric=True),
                    kit.TableColumn("unit", "Unit"),
                    kit.TableColumn("observed", "Observed"),
                    kit.TableColumn("available_at", "Available at"),
                    kit.TableColumn("vintage", "Vintage"),
                ],
                latest_rows,
            )
            if latest_rows
            else kit.EmptyState("Unavailable", str(unavailable))
        ),
        expand=True,
    )

    inflation_rows = inflation.get("rows", [])
    rates_card = kit.GlassCard(
        "Rates and inflation",
        "local series context",
        body=(
            kit.EvidenceTableSwitcher(
                [
                    kit.EvidenceTable(
                        "Latest rates and inflation",
                        [
                            kit.TableColumn("series", "Series"),
                            kit.TableColumn("value", "Value", numeric=True),
                            kit.TableColumn("unit", "Unit"),
                            kit.TableColumn("freshness", "Freshness"),
                        ],
                        [
                            {
                                "series": str(row.get("series_id") or "—"),
                                "value": display_value(row.get("value")),
                                "unit": str(row.get("unit") or "—"),
                                "freshness": kit.Tag(
                                    display_value(row.get("freshness_status")).replace("_", " ").title(),
                                    "warn",
                                ),
                            }
                            for row in inflation_rows
                        ],
                        file_name="Rates and inflation",
                    )
                ],
                title="Rates and inflation evidence",
            )
            if inflation_rows
            else kit.EmptyState("Unavailable", str(inflation.get("reason") or unavailable))
        ),
    )

    scenario_rows = [
        {
            "scenario": str(row.get("scenario") or "—"),
            "driver": str(row.get("driver") or "—"),
            "status": kit.Tag(
                str(row.get("status") or "Unavailable").replace("_", " ").title(),
                "ok" if row.get("status") == "available" else "warn",
            ),
            "detail": kit.Disclosure(
                "Scenario evidence",
                "\r\n".join(
                    (
                        f"Evidence: {row.get('evidence_id') or 'Unavailable'}",
                        f"Source: {row.get('source_id') or 'Unavailable'}",
                        f"Authority: {row.get('authority') or 'Unavailable'}",
                        f"Source checksum: {row.get('source_sha256') or 'Unavailable'}",
                        f"Country and currency: {row.get('country') or 'Unavailable'} / {row.get('currency') or 'Unavailable'}",
                        f"Horizon days: {row.get('horizon_days') or 'Unavailable'}",
                        f"Available at: {row.get('available_at') or 'Unavailable'}",
                        f"Limitations: {', '.join(scenario_context.get('limitations') or ()) or 'Unavailable'}",
                    )
                ),
            ),
        }
        for row in scenario_context.get("rows", [])
    ]
    scenarios_card = kit.GlassCard(
        "Scenario-linked macro evidence",
        "context only",
        body=(
            kit.DataTable(
                [
                    kit.TableColumn("scenario", "Scenario"),
                    kit.TableColumn("driver", "Driver"),
                    kit.TableColumn("status", "Status"),
                    kit.TableColumn("detail", "Evidence detail", sortable=False),
                ],
                scenario_rows,
            )
            if scenario_rows
            else kit.EmptyState("Unavailable", "No local macro scenario links are available.")
        ),
    )
    view_sections.update(
        {
            "Regime": ft.Column([regime_card, series_card], spacing=8),
            "Rates & inflation": ft.Column([curve_card, rates_card, observations_card], spacing=8),
            "Scenarios": scenarios_card,
        }
    )
    for name, section in view_sections.items():
        section.visible = name == "Regime"
    body = ft.Column(
        [
            view_note,
            ft.Row(
                [kit.Button.secondary(
                    "Refresh local macro/news context",
                    on_click=refresh_context if page is not None else None,
                    key="macro.refresh-context",
                )],
                wrap=True,
            ),
            *view_sections.values(),
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        PageChrome(
            "Macro and Factors",
            "Local versioned macro, factor, risk-free and benchmark snapshots",
            segment_groups=(
                SegmentGroup("macro_view", ("Regime", "Rates & inflation", "Scenarios"), "Regime", on_change=change_view),
                SegmentGroup("macro_horizon", ("3M", "1Y", "5Y"), "1Y", on_change=change_horizon),
            ),
        ),
        body,
    )


def _format_metric(value: object) -> str:
    if value is None:
        return "Unavailable"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    return f"{parsed:.2%}" if math.isfinite(parsed) else "Unavailable"


def _numeric_value(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


__all__ = ["macro_factors_page"]
