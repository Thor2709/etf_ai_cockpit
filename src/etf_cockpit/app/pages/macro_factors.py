"""Local Macro and Factors workspace."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import MacroWarehouse, MacroWarehouseError
from etf_cockpit.core.paths import ROOT
from etf_cockpit.features.macro import build_macro_context


def macro_factors_page(page: ft.Page | None, state: AppState) -> ft.Control:
    def refresh_context(_event: ft.ControlEvent) -> None:
        if page is not None:
            _run_action(page, state, "Refresh macro/news context", state.refresh_signals)

    warehouse = MacroWarehouse()
    try:
        price_dates = state.snapshot.prices.get("date") if hasattr(state.snapshot.prices, "get") else None
        decision_time = str(price_dates.max()) if price_dates is not None and not price_dates.empty else "9999-12-31T00:00:00+00:00"
        summary = warehouse.summary(root=ROOT)
        context_rows = warehouse.observations_as_of(root=ROOT, decision_time=decision_time)
        curve_coverage = warehouse.curve_benchmark_coverage(
            root=ROOT, decision_time=decision_time
        )
        error_text = ""
    except (MacroWarehouseError, OSError) as exc:
        summary = {"status": "unavailable", "row_count": 0}
        context_rows = []
        curve_coverage = {
            "status": "unavailable",
            "issuer_credit": "unavailable",
            "source_ids": [],
            "methodologies": [],
        }
        error_text = f"Manual review required: local macro warehouse could not be read ({type(exc).__name__})."

    status = str(summary.get("status", "unavailable"))
    status_colour = theme.GREEN if status == "available" else theme.AMBER
    if error_text:
        status_text = error_text
    elif status == "available":
        status_text = (
            f"Available: {summary.get('row_count', 0)} selected observation(s) across "
            f"{len(summary.get('dataset_ids', []))} dataset(s). "
            f"Missing country/currency context: {summary.get('missing_country_or_currency_count', 0)}."
        )
    else:
        status_text = f"Unavailable: {summary.get('reason', 'no local snapshot is available')}."

    entries = [
        ft.Text(
            f"{row.dataset_id} | {row.series_id} | {row.period_start} | {row.value:g} {row.unit} | "
            f"available={row.available_at} | context={row.availability_status}",
            color=theme.TEXT,
            size=11,
            selectable=True,
        )
        for row in sorted(context_rows, key=lambda item: (item.dataset_id, item.period_start, item.series_id))[-24:]
    ]
    if not entries:
        entries = [ft.Text("No local macro/factor observations have been ingested yet.", color=theme.MUTED, selectable=True)]

    macro_context = build_macro_context(state.snapshot.prices, state.snapshot.config.universe.etfs, context_rows)
    regime = macro_context["regime"]
    breadth = macro_context["breadth"]
    volatility = macro_context["volatility"]
    inflation_rates = macro_context["inflation_rates"]
    proxy_entries = [
        ft.Text(
            f"{row['proxy']}: {row['status']} | "
            f"return20d={_format_metric(row.get('period_return_20d'))} | "
            f"vol={_format_metric(row.get('volatility_annualised'))} | "
            f"source={row.get('source', row.get('provenance', 'local adjusted_close price snapshot'))} | "
            f"as_of={row.get('as_of', 'unavailable')} | freshness={row.get('freshness_status', 'unavailable')}",
            color=theme.TEXT if row["status"] == "available" else theme.MUTED,
            size=11,
            selectable=True,
        )
        for row in macro_context["proxy_rows"]
    ]
    inflation_entries = [
        ft.Text(
            f"{row['series_id']}: {row['value']} {row.get('unit') or ''} | "
            f"source={row['source']} | available={row['available_at']} | freshness={row['freshness_status']}",
            color=theme.TEXT,
            size=11,
            selectable=True,
        )
        for row in inflation_rates.get("rows", [])
    ]
    if not inflation_entries:
        inflation_entries = [ft.Text("No local inflation or rates series is available.", color=theme.MUTED, size=11, selectable=True)]

    return ft.Column(
        [
            section_header(
                "Macro and Factors",
                "Local, versioned macro, factor, risk-free and benchmark snapshots; no remote fetch or execution authority.",
            ),
            ft.OutlinedButton(
                "Refresh local macro/news context",
                key="macro.refresh-context",
                icon=ft.Icons.REFRESH,
                on_click=refresh_context if page is not None else None,
            ),
            panel(
                ft.Column(
                    [
                        ft.Text(status_text, color=status_colour, selectable=True),
                        ft.Text(
                            "Decision-time vintages select only observations whose available_at is on or before the decision time. "
                            "Revisions remain append-only and transformations retain source observation IDs.",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        ft.Text("Execution allowed: false", color=theme.AMBER, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        ft.Text(
                            "Risk-free curves and lawful benchmarks",
                            color=theme.TEXT,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            f"Coverage: {curve_coverage.get('status', 'unavailable')} | "
                            f"curves={', '.join(curve_coverage.get('curve_ids', [])) or 'unavailable'} | "
                            f"types={', '.join(curve_coverage.get('curve_types', [])) or 'unavailable'} | "
                            f"currencies={', '.join(curve_coverage.get('currencies', [])) or 'unavailable'} | "
                            f"benchmarks={', '.join(curve_coverage.get('benchmark_ids', [])) or 'unavailable'}",
                            color=theme.TEXT
                            if curve_coverage.get("status") == "available"
                            else theme.MUTED,
                            selectable=True,
                        ),
                        ft.Text(
                            f"Source/methodology: {', '.join(curve_coverage.get('source_ids', [])) or 'unavailable'} / "
                            f"{', '.join(curve_coverage.get('methodologies', [])) or 'unavailable'} | "
                            f"decision-time vintage={curve_coverage.get('decision_time', decision_time)}",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        ft.Text(
                            "Interpolation is declared per curve and bounded; extrapolation is unavailable. "
                            "Currency+horizon fallbacks are explicit and never zero-filled. "
                            f"Issuer-specific credit curves: {curve_coverage.get('issuer_credit', 'unavailable')}.",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        ft.Text("Regime and proxy context", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            f"Regime: {regime.get('label', 'unknown')} | "
                            f"breadth above SMA200: {_format_metric(breadth.get('pct_above_sma200'))} "
                            f"(source={breadth.get('source', 'unavailable')}, freshness={breadth.get('freshness_status', 'unavailable')}) | "
                            f"median annualised volatility: {_format_metric(volatility.get('median_annualised'))} "
                            f"(source={volatility.get('source', 'unavailable')}, freshness={volatility.get('freshness_status', 'unavailable')})",
                            color=theme.TEXT,
                            selectable=True,
                        ),
                        ft.Text(
                            f"As of: {macro_context.get('as_of') or 'unavailable'} | "
                            f"freshness: {macro_context.get('freshness_status', 'unavailable')} | "
                            f"provenance: {macro_context.get('provenance', 'unavailable')}",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        ft.Column(proxy_entries, spacing=6),
                        ft.Text(
                            f"Inflation/rates context: {inflation_rates.get('status', 'unavailable')} | "
                            f"series shown: {len(inflation_rates.get('rows', []))}",
                            color=theme.TEXT if inflation_rates.get("status") == "available" else theme.MUTED,
                            selectable=True,
                        ),
                        ft.Column(inflation_entries, spacing=6),
                        ft.Text(
                            "Context only (context_only=true, score_eligible=false): this dashboard does not produce scores, expected returns or orders. "
                            "Optional FRED: unavailable; no network request was made.",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        ft.Text("Latest local observations", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        ft.Column(entries, spacing=6, scroll=ft.ScrollMode.AUTO),
                    ],
                    spacing=8,
                ),
                expand=True,
            ),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["macro_factors_page"]


def _format_metric(value: object) -> str:
    if value is None:
        return "unavailable"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "unavailable"
