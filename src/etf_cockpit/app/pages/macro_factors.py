"""Local Macro and Factors workspace."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.macro_context import build_macro_context_binding
from etf_cockpit.application.ui_facade import MacroWarehouse
from etf_cockpit.core.paths import ROOT


def macro_factors_page(page: ft.Page | None, state: AppState) -> ft.Control:
    def refresh_context(_event: ft.ControlEvent) -> None:
        if page is not None:
            _run_action(page, state, "Refresh macro/news context", state.refresh_signals)

    reference_context = context_from_snapshot(
        state.snapshot,
        purpose="comparison",
        analysis_id=f"macro:{getattr(state.snapshot, 'universe_revision', 'unknown')}",
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
    context_rows = binding.observations
    curve_coverage = binding.curve_coverage
    error_text = binding.error or ""
    decision_time = binding.decision_time or "unavailable"
    macro_context = binding.context
    scenario_context = binding.scenario

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
            f"source={row.source_id} | authority={row.source_authority or 'unavailable'} | "
            f"observed_at={row.observed_at} | published_at={row.published_at} | "
            f"available_at={row.available_at} | revised_at={row.revised_at or 'unavailable'} | "
            f"ingested_at={row.ingested_at} | revision={row.revision} | "
            f"source_observation_ids={','.join(row.source_observation_ids) or 'unavailable'} | "
            f"checksum={row.source_checksum} | "
            f"country={row.country or 'unavailable'} | currency={row.currency or 'unavailable'} | "
            f"uncertainty={row.availability_confidence}/{row.timezone_confidence} | "
            f"freshness={row.freshness_status or 'unavailable'} | "
            f"limitations={row.source_terms or 'unavailable'} | "
            f"transformation={row.transformation_version} | context={row.availability_status}",
            color=theme.TEXT,
            size=11,
            selectable=True,
        )
        for row in sorted(context_rows, key=lambda item: (item.dataset_id, item.period_start, item.series_id))[-24:]
    ]
    if not entries:
        entries = [ft.Text("No local macro/factor observations have been ingested yet.", color=theme.MUTED, selectable=True)]

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
            f"source={row['source']} | authority={row.get('source_authority') or 'unavailable'} | "
            f"observed_at={row.get('observed_at') or 'unavailable'} | "
            f"published_at={row.get('published_at') or 'unavailable'} | "
            f"available_at={row.get('available_at') or 'unavailable'} | "
            f"revised_at={row.get('revised_at') or 'unavailable'} | "
            f"ingested_at={row.get('ingested_at') or 'unavailable'} | revision={row.get('revision', 'unavailable')} | "
            f"source_observation_ids={','.join(row.get('source_observation_ids') or ()) or 'unavailable'} | "
            f"checksum={row.get('source_checksum') or 'unavailable'} | freshness={row['freshness_status']} | "
            f"reasons={','.join(row.get('reason_codes') or ()) or 'none'}",
            color=theme.TEXT,
            size=11,
            selectable=True,
        )
        for row in inflation_rates.get("rows", [])
    ]
    if not inflation_entries:
        inflation_entries = [ft.Text("No local inflation or rates series is available.", color=theme.MUTED, size=11, selectable=True)]
    scenario_entries = [
        ft.Text(
            f"{row.get('scenario', 'unavailable')} | driver={row.get('driver', 'unavailable')} | "
            f"link={row.get('link_id', 'unavailable')} | status={row.get('status', 'unavailable')} | "
            f"evidence={row.get('evidence_id') or 'unavailable'} | source={row.get('source_id') or 'unavailable'} | "
            f"authority={row.get('authority') or 'unavailable'} | checksum={row.get('source_sha256') or 'unavailable'} | "
            f"country={row.get('country') or 'unavailable'} | currency={row.get('currency') or 'unavailable'} | "
            f"unit={row.get('unit') or 'unavailable'} | horizon_days={row.get('horizon_days', 'unavailable')} | "
            f"observation_time={row.get('observation_time') or 'unavailable'} | "
            f"effective_time={row.get('effective_time') or 'unavailable'} | "
            f"available={row.get('available_at') or 'unavailable'} | revision={row.get('revision', 'unavailable')} | "
            f"confidence={row.get('confidence', 'unavailable')} | "
            f"reasons={','.join(row.get('reason_codes') or ()) or 'none'} | "
            f"limitations={','.join(scenario_context.get('limitations') or ()) or 'none'}",
            color=theme.TEXT if row.get("status") == "available" else theme.MUTED,
            size=11,
            selectable=True,
        )
        for row in scenario_context.get("rows", [])
    ]
    if not scenario_entries:
        scenario_entries = [ft.Text("No local macro scenario links are available.", color=theme.MUTED, size=11, selectable=True)]

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
                        ft.Text(
                            f"Shared snapshot decision cutoff: {decision_time}",
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
                            f"decision cutoff: {macro_context.get('decision_time', decision_time)} | "
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
            panel(
                ft.Column(
                    [
                        ft.Text("Scenario-linked macro evidence", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            f"Status: {scenario_context.get('status', 'unavailable')} | "
                            f"decision_time={scenario_context.get('decision_time', decision_time)} | "
                            f"portfolio_currency={scenario_context.get('portfolio_currency') or 'unavailable'} | "
                            f"horizon_days={scenario_context.get('horizon_days') or 'unavailable'} | "
                            f"context_only={scenario_context.get('context_only', False)} | "
                            f"score_eligible={scenario_context.get('score_eligible', False)} | "
                            f"execution_allowed={scenario_context.get('execution_allowed', False)}",
                            color=theme.TEXT if scenario_context.get("status") == "available" else theme.MUTED,
                            selectable=True,
                        ),
                        ft.Column(scenario_entries, spacing=6),
                    ],
                    spacing=8,
                )
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
