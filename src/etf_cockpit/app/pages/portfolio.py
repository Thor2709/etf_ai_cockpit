"""Interactive local portfolio candidate sandbox."""

from __future__ import annotations

import math
import json
from collections.abc import Callable, Mapping
from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.components.charts import portfolio_performance_chart
from etf_cockpit.app.components.overlap import overlap_evidence_panel
from etf_cockpit.app.formatting import format_currency, format_number, format_percent
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    PortfolioAnalysis,
    PortfolioCandidate,
    PortfolioSandboxPersistenceError,
    RebalanceConstraints,
    RebalanceReport,
    StorageRevisionConflict,
    analyse_portfolio_candidate,
    build_rebalance_report,
    build_portfolio_candidate,
    candidate_id,
    draft_portfolio_candidate,
    load_portfolio_candidate,
    load_portfolio_forecast_aggregation,
    load_portfolio_performance_series,
    load_portfolio_risk_profile_projection,
    load_portfolio_calendar_projection,
    load_portfolio_holdings_projection,
    load_portfolio_goals_projection,
    portfolio_snapshot_binding,
    performance_series_frame,
    CANONICAL_DISTRIBUTION_HORIZONS_DAYS,
    PRIMARY_MODEL_HORIZON_DAYS,
    rebalance_inapplicable_instruments,
    save_portfolio_candidate,
    select_holdings_view,
    export_table,
)
from etf_cockpit.application.portfolio_sandbox import (
    draft_portfolio_proposal,
    export_portfolio_analysis,
)
from etf_cockpit.application.monthly_decision_template import (
    build_monthly_decision_template,
    monthly_decision_template_lines,
    unavailable_monthly_evidence,
)
from etf_cockpit.core.paths import EXPORTS_DIR, ROOT


def _portfolio_performance_block(page: ft.Page | None) -> ft.Control:
    metric = ft.Dropdown(
        key="portfolio.performance.metric",
        label="Metric",
        value="twr_index",
        options=[
            ft.dropdown.Option(value)
            for value in (
                "portfolio_value",
                "net_invested_capital",
                "investment_pnl",
                "twr_index",
                "twr_return",
                "mwr_return",
                "drawdown",
                "cash_value",
                "net_contributions",
                "income",
                "fees_tax",
                "fx",
                "benchmark",
            )
        ],
        width=220,
        dense=True,
    )
    date_range = ft.Dropdown(
        key="portfolio.performance.range",
        label="Range",
        value="inception",
        options=[ft.dropdown.Option(value) for value in ("inception", "YTD", "1M", "3M", "6M", "1Y", "3Y", "5Y", "custom")],
        width=140,
        dense=True,
    )
    aggregation = ft.Dropdown(
        key="portfolio.performance.aggregation",
        label="Aggregation",
        value="day",
        options=[ft.dropdown.Option(value) for value in ("day", "week", "month", "quarter", "year")],
        width=150,
        dense=True,
    )
    currency = ft.TextField(
        key="portfolio.performance.currency",
        label="Output currency",
        value="EUR",
        width=150,
        dense=True,
    )
    custom_start = ft.TextField(
        key="portfolio.performance.custom-start",
        label="Custom start (YYYY-MM-DD)",
        width=205,
        dense=True,
    )
    custom_end = ft.TextField(
        key="portfolio.performance.custom-end",
        label="Custom end (YYYY-MM-DD)",
        width=205,
        dense=True,
    )
    chart_host = ft.Column(key="portfolio.performance.chart", spacing=6)
    status = ft.Text("Loading saved portfolio performance…", key="portfolio.performance.status", color=theme.MUTED, selectable=True)
    export_status = ft.Text("CSV export writes the selected series to the local exports folder.", key="portfolio.performance.export-status", color=theme.MUTED, selectable=True)
    current_series: list[object] = []

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        series = load_portfolio_performance_series(
            metric=str(metric.value or "twr_index"),
            date_range=str(date_range.value or "inception"),
            aggregation=str(aggregation.value or "day"),
            currency=str(currency.value or "EUR"),
            custom_start=str(custom_start.value or "") or None,
            custom_end=str(custom_end.value or "") or None,
        )
        current_series[:] = [series]
        descriptor = portfolio_performance_chart(
            performance_series_frame(series),
            metric=series.metric,
            unit=series.unit,
            currency=series.currency,
            status=series.status,
            reason=series.reason,
            aggregation=series.aggregation,
        )
        chart_host.controls = [descriptor.control]
        status.value = f"Performance series status: {series.status}; quality={series.quality}."
        if series.reason:
            status.value = f"{status.value} {series.reason}"
        status.color = theme.GREEN if series.status == "available" else theme.AMBER if series.status == "partial" else theme.RED
        if _event is not None:
            _safe_update(page)

    def export_selected(_event: ft.ControlEvent) -> None:
        if not current_series:
            refresh()
        series = current_series[0]
        result = export_table(
            "portfolio_performance_series",
            performance_series_frame(series),
            EXPORTS_DIR / "portfolio_performance_series.csv",
        )
        if result.ok:
            export_status.value = f"CSV ready: {result.destination} ({result.rows} rows)."
            export_status.color = theme.GREEN
        else:
            export_status.value = f"CSV export unavailable: {result.error}; previous output preserved."
            export_status.color = theme.RED
        _safe_update(page)

    for control in (metric, date_range, aggregation, currency, custom_start, custom_end):
        control.on_change = refresh
    refresh()
    return panel(
        ft.Column(
            [
                section_header(
                    "Portfolio performance",
                    "Saved daily valuations only. Contributions remain separate from investment P&L; unavailable or partial periods are labeled.",
                ),
                ft.Row([metric, date_range, aggregation, currency, custom_start, custom_end], wrap=True, spacing=8),
                status,
                chart_host,
                ft.Row([ft.OutlinedButton("Download CSV", key="portfolio.performance.download", icon=ft.Icons.DOWNLOAD, on_click=export_selected), export_status], wrap=True),
            ],
            spacing=8,
        )
    )


def _portfolio_risk_profiles_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
) -> ft.Control:
    selected_id = ["medium"]
    saved_versions: dict[str, Mapping[str, object]] = {}
    saved_history: dict[str, list[Mapping[str, object]]] = {}
    projection = [
        load_portfolio_risk_profile_projection(
            state.snapshot,
            current_analysis[0],
            profile_id=selected_id[0],
        )
    ]
    comparison_rows = projection[0].get("comparison", ())
    comparison_rows = comparison_rows if isinstance(comparison_rows, (list, tuple)) else ()
    options = [
        ft.dropdown.Option(
            key=str(item.get("profile_id")),
            text=str(item.get("label", item.get("profile_id", ""))),
        )
        for item in comparison_rows
        if isinstance(item, Mapping)
    ]
    selector = ft.Dropdown(
        key="portfolio.risk-profile.select",
        label="Risk profile",
        value=selected_id[0] if options else None,
        options=options,
        width=240,
        dense=True,
        disabled=not options,
    )
    policy_editor = ft.TextField(
        key="portfolio.risk-profile.policy",
        label="Editable profile parameters (JSON)",
        value="{}",
        multiline=True,
        min_lines=4,
        max_lines=7,
        expand=True,
    )
    status = ft.Text(color=theme.MUTED, selectable=True)
    intent = ft.Text(color=theme.MUTED, selectable=True)
    version_label = ft.Text(color=theme.MUTED, selectable=True)
    anchor = ft.Text(color=theme.MUTED, selectable=True)
    guardrails_view = ft.Text(color=theme.MUTED, selectable=True)
    binding_reasons = ft.Text(color=theme.AMBER, selectable=True)
    comparison = ft.Column(spacing=2)
    history = ft.Text(color=theme.MUTED, selectable=True, font_family="Consolas", size=11)

    def render_projection(value: Mapping[str, object]) -> None:
        profile = value.get("profile")
        profile = profile if isinstance(profile, Mapping) else {}
        parameters = profile.get("parameters")
        parameters = parameters if isinstance(parameters, Mapping) else {}
        guardrails = profile.get("guardrails")
        anchor_value = value.get("vwce_anchor")
        anchor_value = anchor_value if isinstance(anchor_value, Mapping) else {}
        eligibility = value.get("eligibility")
        eligibility = eligibility if isinstance(eligibility, Mapping) else {}
        status_value = str(value.get("status", "unavailable"))
        reason = value.get("reason")
        status.value = (
            f"Profile projection {status_value}; risk-relative rank/recommendation unavailable: {reason}."
            if reason
            else f"Profile projection {status_value}; execution remains disabled."
        )
        status.color = theme.GREEN if status_value == "partial" else theme.AMBER
        intent.value = f"{profile.get('label', 'Risk profile')} · {profile.get('intent', '')}"
        version_label.value = (
            f"Policy version {profile.get('version', 'unavailable')} · "
            f"origin={profile.get('origin', 'unavailable')} · "
            f"hash={profile.get('policy_hash', 'unavailable')}"
        )
        guardrails_view.value = "Editable guardrails: " + json.dumps(
            guardrails if isinstance(guardrails, Mapping) else {},
            ensure_ascii=False,
            sort_keys=True,
        )
        if anchor_value.get("status") == "available":
            anchor.value = (
                "VWCE anchor resolved: "
                f"share class={anchor_value.get('canonical_share_class_id')}; "
                f"listing={anchor_value.get('listing_id')}; date={anchor_value.get('effective_date')}; "
                f"currency={anchor_value.get('output_currency')}; horizon={anchor_value.get('horizon_years')} years; "
                f"known={anchor_value.get('knowledge_cutoff')}; "
                f"source_digest={anchor_value.get('anchor_digest')}; "
                f"resolution_digest={anchor_value.get('resolution_digest')}; "
                f"risk distribution={anchor_value.get('risk_envelope_status')}."
            )
        else:
            anchor.value = f"VWCE anchor unavailable: {anchor_value.get('reason', 'saved anchor resolution unavailable')}."
        reasons = eligibility.get("binding_reasons", ())
        binding_reasons.value = "Binding reasons: " + (", ".join(map(str, reasons)) if reasons else "none")
        policy_editor.value = json.dumps(parameters, ensure_ascii=False, indent=2, sort_keys=True)
        history_rows = value.get("version_history", ())
        history.value = "Version history (this page session; persistent store unavailable): " + json.dumps(
            history_rows if isinstance(history_rows, (list, tuple)) else [],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        rows = value.get("comparison", ())
        rows = rows if isinstance(rows, (list, tuple)) else ()
        comparison.controls = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            result = item.get("eligibility")
            result = result if isinstance(result, Mapping) else {}
            comparison.controls.append(
                ft.Text(
                    f"{item.get('label', item.get('profile_id'))}: eligibility={result.get('status')}; "
                    f"rank={result.get('rank', 'unavailable')}; recommendation={result.get('recommendation', 'unavailable')}",
                    selectable=True,
                )
            )
        if isinstance(profile, Mapping) and profile.get("profile_id"):
            saved_versions[str(profile["profile_id"])] = dict(profile)
            saved_history[str(profile["profile_id"])] = [
                dict(item) for item in history_rows if isinstance(item, Mapping)
            ] if isinstance(history_rows, (list, tuple)) else []

    def refresh(
        _event: ft.ControlEvent | None = None,
        *,
        profile_edits: Mapping[str, object] | None = None,
        reset_to_preset: bool = False,
    ) -> Mapping[str, object]:
        profile_id = selected_id[0]
        result = load_portfolio_risk_profile_projection(
            state.snapshot,
            current_analysis[0],
            profile_id=profile_id,
            profile_version=saved_versions.get(profile_id),
            version_history=saved_history.get(profile_id, ()),
            profile_edits=profile_edits,
            reset_to_preset=reset_to_preset,
        )
        projection[0] = result
        render_projection(result)
        _safe_update(page)
        return result

    def select_profile(_event: ft.ControlEvent | None) -> None:
        value = str(selector.value or "").strip()
        if value:
            selected_id[0] = value
            refresh()

    def save_profile(_event: ft.ControlEvent | None) -> None:
        try:
            values = json.loads(str(policy_editor.value or "{}"))
            if not isinstance(values, Mapping):
                raise ValueError("profile parameters must be a JSON object")
            result = refresh(profile_edits=values)
            active = result.get("profile")
            version = active.get("version") if isinstance(active, Mapping) else "unavailable"
            status.value = f"Created risk-profile version {version}; the preset and earlier versions were retained."
            status.color = theme.GREEN
            _safe_update(page)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            status.value = f"Profile version was not saved: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def reset_profile(_event: ft.ControlEvent | None) -> None:
        result = refresh(reset_to_preset=True)
        active = result.get("profile")
        version = active.get("version") if isinstance(active, Mapping) else "unavailable"
        status.value = f"Created reset version {version}; the preset and earlier versions were retained."
        status.color = theme.GREEN
        _safe_update(page)

    selector.on_change = select_profile
    render_projection(projection[0])
    return panel(
        ft.Column(
            [
                section_header(
                    "Risk profiles",
                    "Five advisory policies share the same saved analysis. VWCE-relative scoring abstains when a sealed, horizon and currency matched risk distribution is unavailable.",
                ),
                ft.Row([selector], wrap=True),
                intent,
                version_label,
                anchor,
                ft.Row([policy_editor], expand=True),
                guardrails_view,
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "Save as new version",
                            key="portfolio.risk-profile.save",
                            on_click=save_profile,
                            disabled=not options,
                        ),
                        ft.TextButton(
                            "Reset to preset",
                            key="portfolio.risk-profile.reset",
                            on_click=reset_profile,
                            disabled=not options,
                        ),
                    ],
                    wrap=True,
                ),
                status,
                binding_reasons,
                section_header("Profile comparison", "Unavailable ranks stay explicit; binding after-trade constraints are shown per selected profile."),
                comparison,
                history,
                ft.Text(
                    f"Raw portfolio analysis remains unchanged. Snapshot binding: {projection[0].get('source_snapshot_hash') or 'unavailable'}.",
                    color=theme.MUTED,
                    selectable=True,
                ),
            ],
            spacing=8,
        )
    )


def _portfolio_forecast_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
) -> ft.Control:
    status = ft.Text("Loading saved portfolio forecast…", key="portfolio.forecast.status", color=theme.MUTED, selectable=True)
    result_host = ft.Column(key="portfolio.forecast.results", spacing=8)

    def cell_text(value: object, *, as_currency: bool = False, as_percent: bool = False) -> str:
        if not isinstance(value, Mapping) or value.get("status") not in {"available", "partial"}:
            reason = value.get("reason") if isinstance(value, Mapping) else None
            return f"Unavailable: {reason or 'saved input unavailable'}"
        raw = value.get("value")
        if as_currency:
            return format_currency(raw, currency=str(currency.value or "EUR").upper())
        if as_percent:
            return format_percent(raw)
        return str(raw) if raw is not None else "N/A"

    def render_view(label: str, view: Mapping[str, object]) -> ft.Control:
        net = view.get("net")
        gross = view.get("gross")
        selected = net if isinstance(net, Mapping) and net.get("status") != "unavailable" else gross
        selected = selected if isinstance(selected, Mapping) else {}
        quantiles = selected.get("quantiles")
        gain_quantiles = selected.get("gain_loss_quantiles")
        probabilities = selected.get("probabilities")
        coverage = view.get("coverage")
        coverage = coverage if isinstance(coverage, Mapping) else {}
        components = view.get("components")
        components = components if isinstance(components, Mapping) else {}
        costs = view.get("cost_contributions")
        costs = costs if isinstance(costs, Mapping) else {}
        tail = selected.get("tail_dependence")
        tail = tail if isinstance(tail, Mapping) else {}
        rows = []
        if isinstance(quantiles, Mapping):
            for percentile in ("q05", "q25", "q50", "q75", "q95"):
                gain = gain_quantiles.get(percentile) if isinstance(gain_quantiles, Mapping) else None
                rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(percentile.upper(), size=11)),
                            ft.DataCell(ft.Text(format_percent(quantiles.get(percentile)), size=11)),
                            ft.DataCell(ft.Text(format_currency(gain, currency=str(currency.value or "EUR").upper()), size=11)),
                        ]
                    )
                )
        fan = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Fan percentile")), ft.DataColumn(ft.Text("Return")), ft.DataColumn(ft.Text("Gain / loss"))],
            rows=rows,
            column_spacing=16,
            horizontal_margin=6,
        ) if rows else ft.Text(str(selected.get("reason") or "Forecast quantiles unavailable."), color=theme.MUTED, selectable=True)
        probability_lines = []
        if isinstance(probabilities, Mapping):
            for key, title in (("loss", "Loss"), ("beat_cash", "Beat cash"), ("beat_benchmark", "Beat benchmark")):
                probability_lines.append(ft.Text(f"{title}: {cell_text(probabilities.get(key), as_percent=True)}", size=11, selectable=True))
        contribution_lines = [
            ft.Text(
                f"{title}: {cell_text(components.get(key), as_currency=True)}",
                size=11,
                selectable=True,
            )
            for key, title in (("price", "Price"), ("income", "Income"), ("fx", "FX"))
        ]
        contribution_lines.extend(
            ft.Text(f"Cost {key}: {cell_text(value, as_currency=True)}", size=11, selectable=True)
            for key, value in costs.items()
        )
        status_value = str(view.get("status", "unavailable"))
        return panel(
            ft.Column(
                [
                    section_header(label, f"Status: {status_value}; exposure confidence: {format_percent(coverage.get('confidence'))}; unsupported weight: {format_percent(coverage.get('unsupported_exposure_weight'))}."),
                    ft.Text(f"Expected gain / loss: {cell_text(selected.get('expected_gain_loss'), as_currency=True)}", selectable=True),
                    ft.Text(f"Expected return: {cell_text(selected.get('expected_return'), as_percent=True)}", selectable=True),
                    fan,
                    ft.Row(probability_lines, wrap=True, spacing=12),
                    ft.Text(
                        "Contributions and costs use saved holding records; missing inputs remain unavailable.",
                        color=theme.MUTED,
                        selectable=True,
                        size=11,
                    ),
                    ft.Column(contribution_lines, spacing=2),
                    ft.Text(
                        f"Scenario volatility: {cell_text(selected.get('volatility'), as_percent=True)} | "
                        f"Tail dependence: {tail.get('status', 'unavailable')} | "
                        f"Cost sensitivity: {cell_text(view.get('cost_sensitivity'), as_currency=True)}",
                        color=theme.MUTED,
                        selectable=True,
                        size=11,
                    ),
                    ft.Text(str(view.get("reason") or ""), color=theme.AMBER if status_value == "partial" else theme.MUTED, selectable=True, size=11),
                ],
                spacing=6,
            )
        )

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        forecast = load_portfolio_forecast_aggregation(
            state.snapshot,
            current_analysis[0],
            horizon_days=int(horizon.value or PRIMARY_MODEL_HORIZON_DAYS),
            output_currency=str(currency.value or "EUR").upper(),
        )
        status.value = f"Portfolio forecast status: {forecast.status}; horizon={forecast.horizon_days or 'unavailable'} days; execution_allowed=false."
        if forecast.reason:
            status.value = f"{status.value} {forecast.reason}"
        status.color = theme.GREEN if forecast.status == "available" else theme.AMBER if forecast.status == "partial" else theme.RED
        result_host.controls = [
            ft.Row(
                [render_view("Current holdings", forecast.current), render_view("What-if target", forecast.target)],
                wrap=True,
                spacing=10,
            ),
            ft.Text(
                f"Target minus current expected return: {format_percent(forecast.comparison.get('expected_return_difference') if isinstance(forecast.comparison, Mapping) else None)} | "
                f"q05: {format_percent(forecast.comparison.get('q05_return_difference') if isinstance(forecast.comparison, Mapping) else None)}",
                color=theme.MUTED,
                selectable=True,
            ),
            ft.Text(
                "Assumptions: seeded saved-distribution scenarios; q05–q95 tails clamp to saved endpoints; perfect positive correlation is the stress case. "
                f"Seed={forecast.provenance.get('scenario_seed', 'unavailable')}; count={forecast.provenance.get('scenario_count', 'unavailable')}; "
                f"risk model={forecast.provenance.get('risk_model_version', 'unavailable')}; input hashes are retained in forecast evidence.",
                color=theme.MUTED,
                selectable=True,
                size=11,
            ),
        ]
        if _event is not None:
            _safe_update(page)

    horizon = ft.Dropdown(
        key="portfolio.forecast.horizon",
        label="Forecast horizon (days)",
        value=str(PRIMARY_MODEL_HORIZON_DAYS),
        options=[ft.dropdown.Option(str(value)) for value in sorted(CANONICAL_DISTRIBUTION_HORIZONS_DAYS)],
        width=210,
        dense=True,
        on_select=refresh,
    )
    currency = ft.TextField(
        key="portfolio.forecast.currency",
        label="Output currency",
        value="EUR",
        width=150,
        dense=True,
        on_submit=refresh,
    )
    refresh_button = ft.OutlinedButton(
        "Refresh forecast",
        key="portfolio.forecast.refresh",
        on_click=refresh,
    )
    refresh()
    return panel(
        ft.Column(
            [
                section_header(
                    "Portfolio forecast fan chart",
                    "Exact-horizon seeded scenarios combine saved holding distributions with the bound covariance model. Unknown exposure and assumptions remain visible.",
                ),
                ft.Row([horizon, currency, refresh_button], wrap=True, spacing=8),
                status,
                result_host,
            ],
            spacing=8,
        )
    )


def _portfolio_calendar_block(
    page: ft.Page | None,
    state: AppState,
    analysis: PortfolioAnalysis,
) -> ft.Control:
    projection = load_portfolio_calendar_projection(state.snapshot, analysis, output_currency="EUR")
    available = projection.get("available_output_currencies", ("EUR",))
    currencies = sorted({str(item).upper() for item in available if str(item).isalpha() and len(str(item)) == 3}) if isinstance(available, (list, tuple, set)) else ["EUR"]
    if "EUR" not in currencies:
        currencies.insert(0, "EUR")
    calendar_host = ft.Column(spacing=8)

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        nonlocal projection
        projection = load_portfolio_calendar_projection(
            state.snapshot,
            analysis,
            output_currency=str(currency.value or "EUR"),
        )
        calendar_host.controls = [render(projection)]
        if page is not None:
            _safe_update(page)

    currency = ft.Dropdown(
        key="portfolio.calendar.currency",
        label="Output currency",
        value="EUR",
        options=[ft.dropdown.Option(item) for item in currencies],
        width=150,
        dense=True,
        on_select=refresh,
    )

    def render(current: Mapping[str, object]) -> ft.Control:
        warnings = current.get("warnings", ())
        warning_text = "; ".join(str(item) for item in warnings[:4]) if isinstance(warnings, (list, tuple)) else ""
        status = ft.Text(
            f"Calendar status: {current.get('status', 'unavailable')}; output currency: {current.get('currency') or 'unavailable'}; execution_allowed=false."
            + (f" Coverage: {warning_text}" if warning_text else ""),
            color=theme.AMBER if warning_text or current.get("status") != "available" else theme.GREEN,
            selectable=True,
        )
        event_records = current.get("events", ())
        event_rows: list[ft.DataRow] = []
        if isinstance(event_records, (list, tuple)):
            for item in event_records:
                if not isinstance(item, Mapping):
                    continue
                exposure = item.get("affected_exposure", {})
                exposure = exposure if isinstance(exposure, Mapping) else {}
                market_value = exposure.get("market_value")
                exposure_text = (
                    format_currency(market_value, currency=str(exposure.get("currency") or "EUR"))
                    if market_value is not None
                    else f"Qty {format_number(exposure.get('quantity'))}"
                )
                event_date = str(item.get("event_date") or "Unavailable")
                timezone_name = item.get("timezone_name")
                if timezone_name:
                    event_date = f"{event_date} {timezone_name}"
                payment_date = item.get("payment_date")
                if payment_date and str(payment_date)[:10] != event_date[:10]:
                    event_date = f"{event_date} / pay {payment_date}"
                authority = str(item.get("source_authority") or "Unavailable")
                confidence = str(item.get("confidence") or "Unavailable")
                event_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(event_date, selectable=True)),
                            ft.DataCell(ft.Text(str(item.get("title") or item.get("event_type") or "Unavailable"), selectable=True)),
                            ft.DataCell(ft.Text(str(item.get("instrument_id") or "Unavailable"), selectable=True)),
                            ft.DataCell(ft.Text(str(item.get("status") or "Unavailable"), selectable=True)),
                            ft.DataCell(ft.Text(f"{item.get('source_rank', 'other')}: {authority}; {confidence}", selectable=True)),
                            ft.DataCell(ft.Text(exposure_text, selectable=True)),
                            ft.DataCell(ft.Text("Candidate" if item.get("blackout_candidate") else "No", selectable=True)),
                        ]
                    )
                )
        event_table: ft.Control = (
            ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(label))
                    for label in ("Event date / payable", "Event", "Holding", "Status", "Source / confidence", "Exposure", "Blackout")
                ],
                rows=event_rows,
            )
            if event_rows
            else ft.Text(str(current.get("reason") or "No saved events are available."), color=theme.MUTED, selectable=True)
        )
        summary_records = current.get("cash_flow_summaries", ())
        summary_rows: list[ft.DataRow] = []
        if isinstance(summary_records, (list, tuple)):
            for item in summary_records:
                if not isinstance(item, Mapping):
                    continue
                summary_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(f"{item.get('period_type', '')}: {item.get('period', '')}", selectable=True)),
                            ft.DataCell(ft.Text(str(item.get("flow_type") or "Unavailable"), selectable=True)),
                            ft.DataCell(
                                ft.Text(
                                    format_currency(item.get("amount"), currency=str(item.get("currency") or "EUR")),
                                    selectable=True,
                                )
                            ),
                            ft.DataCell(ft.Text(str(item.get("status") or "unavailable"), selectable=True)),
                        ]
                    )
                )
        summary_table: ft.Control = (
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text(label)) for label in ("Period", "Cash flow", "Projected amount", "Status")],
                rows=summary_rows,
            )
            if summary_rows
            else ft.Text("Monthly and quarterly amounts are unavailable until saved event amounts, terms, quantities, and FX are covered.", color=theme.MUTED, selectable=True)
        )
        return ft.Column(
            [
                status,
                event_table,
                section_header("Projected monthly and quarterly cash flows"),
                summary_table,
            ],
            spacing=8,
        )

    calendar_host.controls = [render(projection)]
    return panel(
        ft.Column(
            [
                section_header(
                    "Income, events, maturity and liquidity calendar",
                    "Saved point-in-time events and contractual cash flows. Estimated dates stay distinct; missing amounts and FX remain unavailable. Blackout candidates are advisory.",
                ),
                currency,
                calendar_host,
            ],
            spacing=8,
        )
    )


def _portfolio_holdings_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
    proposal_callback: Callable[[ft.ControlEvent | None], None],
    refresh_callbacks: list[Callable[[ft.ControlEvent | None], None]],
) -> ft.Control:
    initial = load_portfolio_holdings_projection(
        state.snapshot,
        current_analysis[0],
        horizon_days=PRIMARY_MODEL_HORIZON_DAYS,
    )
    run_rows = initial.get("analysis_runs", ())
    run_ids = [
        str(item.get("run_id"))
        for item in run_rows
        if isinstance(item, Mapping) and str(item.get("run_id", "")).strip()
    ]
    selected_run = str(initial.get("selected_analysis_run_id") or "unavailable")
    if selected_run != "unavailable" and selected_run not in run_ids:
        run_ids.insert(0, selected_run)
    run_options = [ft.dropdown.Option(value) for value in run_ids] or [ft.dropdown.Option("unavailable")]

    analysis_run = ft.Dropdown(
        key="portfolio.holdings.analysis-run",
        label="Analysis run",
        value=selected_run,
        options=run_options,
        width=260,
        dense=True,
    )
    horizon = ft.Dropdown(
        key="portfolio.holdings.horizon",
        label="Exact forecast horizon (days)",
        value=str(PRIMARY_MODEL_HORIZON_DAYS),
        options=[ft.dropdown.Option(str(value)) for value in sorted(CANONICAL_DISTRIBUTION_HORIZONS_DAYS)],
        width=210,
        dense=True,
    )
    currency = ft.TextField(
        key="portfolio.holdings.currency",
        label="Output currency",
        value="EUR",
        width=145,
        dense=True,
    )
    search = ft.TextField(
        key="portfolio.holdings.search",
        label="Filter holdings",
        width=200,
        dense=True,
    )
    export_path = ft.TextField(
        key="portfolio.holdings.export-path",
        label="CSV destination",
        hint_text="Enter a local file path",
        width=280,
        dense=True,
    )
    asset_filter = ft.Dropdown(
        key="portfolio.holdings.asset-filter",
        label="Asset type",
        value="all",
        options=[ft.dropdown.Option(value) for value in ("all", "stock", "etf", "bond")],
        width=150,
        dense=True,
    )
    sort = ft.Dropdown(
        key="portfolio.holdings.sort",
        label="Sort",
        value="instrument_id:asc",
        options=[
            ft.dropdown.Option(value, text=label)
            for value, label in (
                ("instrument_id:asc", "Instrument A–Z"),
                ("instrument_id:desc", "Instrument Z–A"),
                ("value:desc", "Value high to low"),
                ("value:asc", "Value low to high"),
                ("weight:desc", "Weight high to low"),
                ("expected_return:desc", "Expected return high to low"),
            )
        ],
        width=210,
        dense=True,
    )
    preset = ft.Dropdown(
        key="portfolio.holdings.column-preset",
        label="Columns",
        value="full",
        options=[ft.dropdown.Option(value) for value in ("full", "values", "analysis")],
        width=135,
        dense=True,
    )
    status = ft.Text("Loading holdings evidence…", key="portfolio.holdings.status", color=theme.MUTED, selectable=True)
    row_host = ft.ListView(key="portfolio.holdings.rows", spacing=5, expand=True)
    projection_state: list[dict[str, object]] = [initial]

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        selected_sort, _, direction = str(sort.value or "instrument_id:asc").partition(":")
        try:
            selected_horizon = int(str(horizon.value or PRIMARY_MODEL_HORIZON_DAYS))
        except (TypeError, ValueError):
            selected_horizon = 0
        projection = load_portfolio_holdings_projection(
            state.snapshot,
            current_analysis[0],
            horizon_days=selected_horizon,
            output_currency=str(currency.value or ""),
            analysis_run_id=None if str(analysis_run.value or "") == "unavailable" else str(analysis_run.value),
            search=str(search.value or ""),
            asset_type=None if str(asset_filter.value or "all").casefold() == "all" else str(asset_filter.value),
            sort_by=selected_sort,
            descending=direction == "desc",
            column_preset=str(preset.value or "full").casefold(),
        )
        projection_state[:] = [projection]
        render_projection(projection)
        if _event is not None:
            _safe_update(page)

    def open_detail(_event: ft.ControlEvent, instrument_id: str) -> None:
        state.selected_etf = instrument_id
        if page is not None:
            page.go("/etf")

    def prepare_proposal(event: ft.ControlEvent | None) -> None:
        if not bool(projection_state[0].get("proposal_handoff_allowed")):
            status.value = "Proposal hand-off blocked: " + str(
                projection_state[0].get("proposal_handoff_reason") or "analysis_is_not_current_for_selected_snapshot"
            )
            status.color = theme.AMBER
            _safe_update(page)
            return
        proposal_callback(event)

    def export_selected(_event: ft.ControlEvent | None) -> None:
        destination_text = str(export_path.value or "").strip()
        if not destination_text:
            status.value = "CSV export unavailable: enter a local destination path."
            status.color = theme.AMBER
            _safe_update(page)
            return
        projection = projection_state[0]
        rows = projection.get("rows", ())
        rows = rows if isinstance(rows, list) else []
        if not rows:
            status.value = "CSV export unavailable: the selected projection has no holding rows."
            status.color = theme.AMBER
            _safe_update(page)
            return
        portfolio_meta = projection.get("portfolio_snapshot")
        portfolio_meta = portfolio_meta if isinstance(portfolio_meta, Mapping) else {}
        performance_meta = projection.get("performance_snapshot")
        performance_meta = performance_meta if isinstance(performance_meta, Mapping) else {}
        metadata = {
            "projection_status": projection.get("status"),
            "portfolio_id": portfolio_meta.get("portfolio_id"),
            "portfolio_snapshot_id": portfolio_meta.get("snapshot_id"),
            "portfolio_source_checksum": portfolio_meta.get("source_checksum"),
            "performance_snapshot_date": performance_meta.get("date"),
            "analysis_run_id": projection.get("analysis_run_id"),
            "analysis_date": projection.get("analysis_date"),
            "analysis_policy_id": projection.get("analysis_policy_id"),
            "horizon_days": projection.get("horizon_days"),
            "output_currency": projection.get("output_currency"),
            "projection_reasons": ";".join(str(item) for item in projection.get("reasons", ())),
            "projection_conflicts": ";".join(str(item) for item in projection.get("conflicts", ())),
        }
        records: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            record = dict(metadata)
            for field, value in row.items():
                if isinstance(value, Mapping) and "status" in value:
                    record[field] = value.get("value")
                    record[f"{field}_status"] = value.get("status")
                    record[f"{field}_reason"] = value.get("reason")
                elif isinstance(value, Mapping):
                    for subfield, cell in value.items():
                        name = f"{field}_{subfield}"
                        if isinstance(cell, Mapping) and "status" in cell:
                            record[name] = cell.get("value")
                            record[f"{name}_status"] = cell.get("status")
                            record[f"{name}_reason"] = cell.get("reason")
                        else:
                            record[name] = cell
                elif isinstance(value, (tuple, list)):
                    record[field] = ";".join(str(item) for item in value)
                else:
                    record[field] = value
            records.append(record)
        result = export_table(
            "portfolio_holdings_analysis",
            pd.DataFrame.from_records(records),
            Path(destination_text),
        )
        if result.ok:
            status.value = f"Holdings evidence CSV ready: {result.destination} ({result.rows} rows)."
            status.color = theme.GREEN
        else:
            status.value = f"Holdings evidence CSV unavailable: {result.error}; previous output preserved."
            status.color = theme.AMBER
        _safe_update(page)

    def render_projection(projection: dict[str, object]) -> None:
        rows = projection.get("rows", ())
        rows = rows if isinstance(rows, list) else []
        output_currency = str(projection.get("output_currency") or "EUR")
        horizon_days = projection.get("horizon_days")
        portfolio_meta = projection.get("portfolio_snapshot")
        portfolio_meta = portfolio_meta if isinstance(portfolio_meta, Mapping) else {}
        performance_meta = projection.get("performance_snapshot")
        performance_meta = performance_meta if isinstance(performance_meta, Mapping) else {}
        reason = projection.get("reason") or projection.get("analysis_reason")
        status.value = (
            f"Holdings: {projection.get('status', 'unavailable')} · {projection.get('row_count', 0)} of "
            f"{projection.get('total_rows', 0)} positions · run {projection.get('analysis_run_id') or 'unavailable'} · "
            f"data/performance as-of {portfolio_meta.get('as_of') or 'unavailable'}/"
            f"{performance_meta.get('date') or 'unavailable'} · "
            f"analysis as-of {projection.get('analysis_date') or 'unavailable'} · "
            f"policy {projection.get('analysis_policy_ids') or 'unavailable'} · horizon {horizon_days or 'unavailable'} days"
        )
        if projection.get("conflicts"):
            status.value += " · conflicts: " + ", ".join(str(item) for item in projection["conflicts"])
        if reason:
            status.value += f" · {reason}"
        status.color = theme.GREEN if projection.get("status") == "available" else theme.AMBER
        proposal_button.disabled = not bool(projection.get("proposal_handoff_allowed"))
        controls: list[ft.Control] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            instrument_id = str(item.get("instrument_id", ""))
            if not instrument_id:
                continue
            asset = _holding_display(item.get("asset_type"))
            quantity_cell = item.get("quantity")
            if isinstance(quantity_cell, Mapping) and quantity_cell.get("status") != "available":
                quantity_cell = item.get("face_value")
            quantity = _holding_display(quantity_cell)
            value = _holding_display(item.get("value"), currency=output_currency)
            weight = _holding_display(item.get("weight"), percent=True)
            action = _holding_display(item.get("action"))
            expected = _holding_display(item.get("expected_return"), percent=True)
            details: list[ft.Control] = []
            preset_value = str(projection.get("column_preset", "full"))
            value_fields = (
                ("Quantity / face value", "quantity", None),
                ("Face value", "face_value", None),
                ("Local currency", "local_currency", None),
                ("Local value", "local_value", None),
                ("Output value", "value", output_currency),
                ("Weight", "weight", "percent"),
                ("Cost basis", "cost_basis", output_currency),
                ("Realised P&L", "realised_pnl", output_currency),
                ("Unrealised P&L", "unrealised_pnl", output_currency),
                ("Income", "income", output_currency),
                ("Fees", "fees", output_currency),
            )
            analysis_fields = (
                ("Scores", "scores", None),
                ("Universe rank", "rank", None),
                ("Peer rank", "peer_rank", None),
                ("Action", "action", None),
                ("Blockers", "blockers", None),
                ("Coverage", "coverage", "percent"),
                ("Data as-of", "data_as_of", None),
                ("Performance as-of", "performance_as_of", None),
                ("Analysis as-of", "analysis_as_of", None),
                ("Model as-of", "model_as_of", None),
                ("Analysis stale", "analysis_stale", None),
                ("Policy identities", "policy_ids", None),
                ("Expected return", "expected_return", "percent"),
                ("Forecast quantiles", "forecast_quantiles", "percent"),
                ("Expected gain / loss", "expected_gain_loss", output_currency),
            )
            selected_fields = value_fields if preset_value == "values" else analysis_fields if preset_value == "analysis" else (*value_fields, *analysis_fields)
            for label, field, style in selected_fields:
                raw = item.get(field)
                if field == "scores" and isinstance(raw, Mapping):
                    shown = ", ".join(f"{name}: {_holding_display(cell)}" for name, cell in raw.items())
                elif field in {"forecast_quantiles", "expected_gain_loss", "asset_details"} and isinstance(raw, Mapping):
                    shown = ", ".join(f"{name}: {_holding_display(cell, currency=style if field == 'expected_gain_loss' else None, percent=field == 'forecast_quantiles') }" for name, cell in raw.items())
                else:
                    shown = _holding_display(raw, currency=style if style != "percent" else None, percent=style == "percent")
                details.append(ft.Text(f"{label}: {shown}", size=11, color=theme.MUTED, selectable=True))
            asset_details = item.get("asset_details")
            if isinstance(asset_details, Mapping) and preset_value != "analysis":
                details.append(
                    ft.Text(
                        "Asset-specific: " + ", ".join(f"{name}: {_holding_display(cell)}" for name, cell in asset_details.items()),
                        size=11,
                        color=theme.MUTED,
                        selectable=True,
                    )
                )
            for label, field in (("Transactions / lots", "transactions"), ("Lots", "lots"), ("Events", "events"), ("Portfolio impact", "portfolio_impact")):
                details.append(ft.Text(f"{label}: {_holding_display(item.get(field))}", size=11, color=theme.MUTED, selectable=True))
            details.append(
                ft.OutlinedButton(
                    "Open instrument detail",
                    key=f"portfolio.holdings.instrument-detail.{instrument_id}",
                    on_click=lambda event, selected_id=instrument_id: open_detail(event, selected_id),
                )
            )
            controls.append(
                ft.ExpansionTile(
                    key=f"portfolio.holdings.row.{instrument_id}",
                    title=ft.Row(
                        [
                            ft.Text(instrument_id, width=135, size=12),
                            ft.Text(asset, width=80, size=11),
                            ft.Text(quantity, width=100, size=11),
                            ft.Text(value, width=140, size=11),
                            ft.Text(weight, width=85, size=11),
                            ft.Text(action, width=130, size=11),
                            ft.Text(expected, width=110, size=11),
                        ],
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    controls=details,
                )
            )
        row_host.controls = controls or [ft.Text("No holdings match the selected snapshot and filters.", color=theme.MUTED)]

    proposal_button = ft.OutlinedButton(
        "Prepare ISSUE-0130 draft",
        key="portfolio.holdings.proposal",
        on_click=prepare_proposal,
        disabled=True,
    )
    analysis_run.on_change = refresh
    horizon.on_change = refresh
    currency.on_change = refresh
    search.on_change = refresh
    asset_filter.on_change = refresh
    sort.on_change = refresh
    preset.on_change = refresh
    refresh_callbacks[:] = [refresh]
    render_projection(initial)

    return panel(
        ft.Column(
            [
                section_header(
                    "Portfolio holdings analysis",
                    "Bound to the selected local holdings snapshot and exact analysis run. Missing values and drill-down evidence remain explicit; execution is disabled.",
                ),
                ft.Row([analysis_run, horizon, currency, asset_filter, sort, preset], wrap=True, spacing=8),
                ft.Row([search, export_path, ft.OutlinedButton("Refresh holdings", key="portfolio.holdings.refresh", on_click=refresh), ft.OutlinedButton("Export holdings evidence", key="portfolio.holdings.export", on_click=export_selected), proposal_button], wrap=True, spacing=8),
                status,
                ft.Container(content=row_host, height=520),
            ],
            spacing=8,
        )
    )


def _holding_display(
    cell: object,
    *,
    currency: str | None = None,
    percent: bool = False,
) -> str:
    if isinstance(cell, Mapping):
        if cell.get("status") != "available" or cell.get("value") is None:
            reason = str(cell.get("reason") or "source_value_unavailable")
            return f"unavailable · {reason}"
        value = cell.get("value")
    else:
        value = cell
    if value is None:
        return "unavailable · source_value_unavailable"
    if percent:
        return format_percent(value)
    if currency:
        return format_currency(value, currency=currency)
    if isinstance(value, (tuple, list)):
        return ", ".join(str(item) for item in value) or "none"
    return format_number(value) if isinstance(value, (int, float)) else str(value)


def _portfolio_goals_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
) -> ft.Control:
    projection = [load_portfolio_goals_projection(state.snapshot, current_analysis[0])]
    policy_editor = ft.TextField(
        key="portfolio-goals.policy",
        label="Versioned portfolio policy (JSON)",
        value=json.dumps(projection[0].get("policy_editor", {}), ensure_ascii=False, indent=2),
        multiline=True,
        min_lines=7,
        max_lines=12,
        expand=True,
    )
    snooze_until = ft.TextField(
        key="portfolio-goals.snooze-until",
        label="Snooze until (ISO 8601 with timezone)",
        hint_text="For example, 2026-10-02T12:00:00+02:00",
        width=330,
        dense=True,
    )
    status = ft.Text("Policy limits are optional; unavailable evidence stays unavailable.", color=theme.MUTED, selectable=True)
    results = ft.Text(key="portfolio-goals.results", selectable=True, font_family="Consolas", size=12)

    def render_result(value: Mapping[str, object]) -> None:
        summary = {
            "status": value.get("status"),
            "source_snapshot_hash": value.get("source_snapshot_hash"),
            "policy": value.get("policy"),
            "policy_as_of": value.get("policy_as_of"),
            "policy_history": value.get("policy_history"),
            "alerts": value.get("alerts"),
            "unavailable_alerts": value.get("unavailable_alerts"),
            "scenario": value.get("scenario"),
            "acknowledgement_history": value.get("acknowledgement_history"),
            "execution_allowed": value.get("execution_allowed", False),
        }
        results.value = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        editor_value = value.get("policy_editor")
        if isinstance(editor_value, Mapping) and value.get("policy") is not None:
            policy_editor.value = json.dumps(editor_value, ensure_ascii=False, indent=2, sort_keys=True, default=str)

    render_result(projection[0])

    def apply_action(action: Mapping[str, object], message: str) -> None:
        result = load_portfolio_goals_projection(state.snapshot, current_analysis[0], action=action)
        if result.get("status") in {"available", "partial"}:
            projection[0] = result
            status.value = message
            status.color = theme.GREEN
        else:
            status.value = f"Portfolio goals unavailable: {result.get('reason', result.get('status', 'unknown'))}"
            status.color = theme.AMBER
        render_result(result)
        _safe_update(page)

    def save_policy(_event: ft.ControlEvent | None) -> None:
        try:
            values = json.loads(str(policy_editor.value or "{}"))
            if not isinstance(values, Mapping):
                raise ValueError("policy must be a JSON object")
            apply_action({"type": "save_policy", "policy": values}, "Validated policy saved as a new version.")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            status.value = f"Policy was not saved: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def run_what_if(_event: ft.ControlEvent | None) -> None:
        apply_action({"type": "simulate"}, "What-if recorded from the selected snapshot; the portfolio ledger was not changed.")

    def active_alert_ids() -> tuple[str, ...]:
        alerts = projection[0].get("alerts", ())
        if not isinstance(alerts, (list, tuple)):
            return ()
        return tuple(
            str(item.get("alert_id"))
            for item in alerts
            if isinstance(item, Mapping) and item.get("alert_id")
        )

    def acknowledge_alerts(_event: ft.ControlEvent | None) -> None:
        identifiers = active_alert_ids()
        if not identifiers:
            status.value = "There are no active alert conditions to acknowledge."
            status.color = theme.MUTED
            _safe_update(page)
            return
        apply_action({"type": "acknowledge", "alert_ids": identifiers}, "Acknowledgement saved; active conditions remain visible.")

    def snooze_alerts(_event: ft.ControlEvent | None) -> None:
        identifiers = active_alert_ids()
        if not identifiers:
            status.value = "There are no active alert conditions to snooze."
            status.color = theme.MUTED
            _safe_update(page)
            return
        apply_action(
            {"type": "snooze", "alert_ids": identifiers, "until": str(snooze_until.value or "")},
            "Snooze saved; active conditions remain visible.",
        )

    def draft_what_if(_event: ft.ControlEvent | None) -> None:
        scenario = projection[0].get("scenario")
        candidate = current_analysis[0].candidate
        if (
            not isinstance(scenario, Mapping)
            or scenario.get("status") != "ready"
            or scenario.get("source_snapshot_hash") != projection[0].get("source_snapshot_hash")
            or scenario.get("candidate_id") != candidate.candidate_id
        ):
            status.value = "Draft proposal blocked: run a ready what-if for the current candidate and snapshot first."
            status.color = theme.AMBER
            _safe_update(page)
            return
        try:
            handoff = draft_portfolio_proposal(state.snapshot, current_analysis[0])
            status.value = f"Draft proposal hand-off prepared ({len(handoff.get('changes', ())) } changes); execution remains disabled."
            status.color = theme.GREEN
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            status.value = f"Draft proposal unavailable: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def export_audit(_event: ft.ControlEvent | None) -> None:
        try:
            audit = projection[0].get("audit_export")
            source_hash = str(projection[0].get("source_snapshot_hash") or "").strip()
            if not isinstance(audit, Mapping) or not source_hash:
                raise ValueError("snapshot-bound portfolio goals audit is unavailable")
            path = EXPORTS_DIR / f"portfolio_goals_{current_analysis[0].candidate.candidate_id}_{source_hash[:12]}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
            state.last_export_path = path
            status.value = f"Portfolio goals audit exported to {path.name}; execution remains disabled."
            status.color = theme.GREEN
            _safe_update(page)
        except (OSError, TypeError, ValueError) as exc:
            status.value = f"Portfolio goals audit unavailable: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    return panel(
        ft.Column(
            [
                section_header(
                    "Portfolio goals, alerts and what-if",
                    "Edit optional non-advisory limits, inspect after-trade evidence, and create a draft hand-off only after an explicit what-if action. Execution is disabled.",
                ),
                ft.Text("Enter target_weights and target_bands by existing instrument id; percentage fields use fractions from 0 to 1. Omitted limits remain unconfigured, and unsupported evidence is shown as unavailable.", color=theme.MUTED, selectable=True),
                policy_editor,
                ft.Row([snooze_until], wrap=True),
                ft.Row(
                    [
                        ft.Button("Save policy version", key="portfolio-goals.policy.save", on_click=save_policy),
                        ft.OutlinedButton("Run what-if", key="portfolio-goals.what-if", on_click=run_what_if),
                        ft.OutlinedButton("Acknowledge active alerts", key="portfolio-goals.alert.acknowledge", on_click=acknowledge_alerts),
                        ft.OutlinedButton("Snooze active alerts", key="portfolio-goals.alert.snooze", on_click=snooze_alerts),
                        ft.OutlinedButton("Prepare draft proposal", key="portfolio-goals.draft-proposal", on_click=draft_what_if),
                        ft.TextButton("Export goals audit", key="portfolio-goals.audit-export", on_click=export_audit),
                    ],
                    wrap=True,
                ),
                status,
                results,
            ],
            spacing=10,
        )
    )


def portfolio_page(page: ft.Page | None, state: AppState) -> ft.Control:
    """Render editable research candidates without creating executable intent."""

    initial = draft_portfolio_candidate(state.snapshot)
    saved_revision = [0]
    saved_candidate_id: list[str | None] = [None]
    universe = {
        str(item.id): item
        for item in state.snapshot.config.universe.etfs
        if bool(item.enabled)
    }
    control_ids = sorted(set(universe) | _holding_ids(state.snapshot.holdings))
    name = ft.TextField(
        key="portfolio.workspace-name",
        label="Candidate name",
        value=initial.name,
        width=260,
        dense=True,
    )
    notional = ft.TextField(
        key="portfolio.analysis-notional",
        label="Analysis notional (EUR)",
        value=f"{initial.analysis_notional_eur:.2f}",
        width=220,
        dense=True,
    )
    target_inputs = {
        instrument_id: ft.TextField(
            key=f"portfolio.target-weight.{instrument_id}",
            label=_target_label(instrument_id, universe.get(instrument_id), state.snapshot.holdings),
            value=f"{initial.targets.get(instrument_id, 0.0) * 100:.4f}",
            width=190,
            dense=True,
        )
        for instrument_id in control_ids
    }
    cash = ft.TextField(
        key="portfolio.cash-weight",
        label="Cash target (%)",
        value=f"{initial.cash_weight * 100:.4f}",
        width=190,
        dense=True,
    )
    account = ft.Dropdown(
        key="portfolio.account",
        label="Account snapshot",
        value=str(getattr(state.snapshot, "account_id", "default") or "default"),
        options=[ft.dropdown.Option(str(value)) for value in _snapshot_values(state.snapshot, "account_id", "default")],
        width=190,
        dense=True,
    )
    portfolio = ft.Dropdown(
        key="portfolio.portfolio",
        label="Portfolio snapshot",
        value=str(getattr(state.snapshot, "portfolio_id", "default") or "default"),
        options=[ft.dropdown.Option(str(value)) for value in _snapshot_values(state.snapshot, "portfolio_id", "default")],
        width=190,
        dense=True,
    )
    snapshot = ft.Dropdown(
        key="portfolio.snapshot",
        label="As-of snapshot",
        value=str(getattr(state.snapshot, "snapshot_id", "current") or "current"),
        options=[ft.dropdown.Option(str(value)) for value in _snapshot_values(state.snapshot, "snapshot_id", "current")],
        width=190,
        dense=True,
    )
    holdings_view = ft.Dropdown(
        key="portfolio.holdings-view",
        label="Holdings view",
        value="combined",
        options=[ft.dropdown.Option(value) for value in ("direct", "look_through", "combined")],
        width=160,
        dense=True,
    )
    initial_analysis = analyse_portfolio_candidate(
        state.snapshot,
        initial,
        account_id=str(account.value or "default"),
        portfolio_id=str(portfolio.value or "default"),
        snapshot_id=str(snapshot.value or "current"),
        holdings_view=str(holdings_view.value or "combined"),
    )
    current_analysis = [initial_analysis]
    holdings_refresh_callbacks: list[Callable[[ft.ControlEvent | None], None]] = []
    initial_status = "Unsaved candidate. Edit weights and select Analyse candidate."
    if state.snapshot.holdings.empty:
        initial_status = "No current holdings are available. Candidate targets can still be analysed from a zero-current baseline."
    status = ft.Text(
        initial_status,
        key="portfolio.status",
        color=theme.MUTED,
        selectable=True,
    )
    result_host = ft.Column(
        [_analysis_view(initial_analysis, benchmark_registry=getattr(state.snapshot, "benchmark_reference_registry", None))],
        key="portfolio.results",
        spacing=12,
    )
    rebalance_host = ft.Column(
        [panel(ft.Text("Select Validate rebalance preview to compare local alternatives.", color=theme.MUTED, selectable=True))],
        key="portfolio.rebalance-results",
        spacing=12,
    )

    def values() -> tuple[str, str, dict[str, object], object]:
        targets: dict[str, object] = {}
        selected_ids = _holding_ids(
            select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
        )
        actionable_ids = set(universe) | selected_ids
        for instrument_id, control in target_inputs.items():
            if instrument_id in actionable_ids:
                targets[instrument_id] = _percentage(control.value)
        return str(name.value or ""), str(notional.value or ""), targets, _percentage(cash.value)

    def refresh(candidate: PortfolioCandidate, *, message: str, colour: str = theme.GREEN) -> None:
        analysis = analyse_portfolio_candidate(
            state.snapshot,
            candidate,
            account_id=str(account.value or "default"),
            portfolio_id=str(portfolio.value or "default"),
            snapshot_id=str(snapshot.value or "current"),
            holdings_view=str(holdings_view.value or "combined"),
        )
        current_analysis[:] = [analysis]
        result_host.controls = [_analysis_view(analysis, benchmark_registry=getattr(state.snapshot, "benchmark_reference_registry", None))]
        if holdings_refresh_callbacks:
            holdings_refresh_callbacks[0](None)
        status.value = message
        status.color = colour
        state.last_message = message
        _safe_update(page)

    def analyse(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                holdings_view=str(holdings_view.value or "combined"),
            )
            message = "Candidate analysed from the current local snapshot; execution remains disabled."
            if saved_revision[0]:
                message += " Save to create the next local revision."
            refresh(candidate, message=message)
        except (TypeError, ValueError) as exc:
            status.value = f"Candidate not analysed: {exc}"
            status.color = theme.AMBER
            result_host.controls = [
                panel(ft.Text("Candidate results are unavailable until the validation error is corrected.", color=theme.AMBER, selectable=True))
            ]
            _safe_update(page)

    def rebalance_preview(_event: ft.ControlEvent | None) -> None:
        try:
            _, candidate_notional, targets, candidate_cash = values()
            selected_holdings = select_holdings_view(
                state.snapshot.holdings,
                str(holdings_view.value or "combined"),
            )
            binding = portfolio_snapshot_binding(
                state.snapshot,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            inapplicable = rebalance_inapplicable_instruments(
                state.snapshot,
                selected_holdings,
                _holding_ids(selected_holdings)
                | {
                    instrument_id
                    for instrument_id, target_weight in targets.items()
                    if float(target_weight) > 0
                },
            )
            if inapplicable:
                rebalance_host.controls = [
                    panel(
                        ft.Column(
                            [
                                section_header(
                                    "Rebalance workspace",
                                    "The existing discrete rebalance service is ETF-only; mixed-asset targets remain explicit and are not silently discarded.",
                                ),
                                ft.Text(
                                    "Inapplicable mixed-asset targets: " + ", ".join(inapplicable),
                                    color=theme.AMBER,
                                    selectable=True,
                                ),
                                ft.Text(
                                    f"source=account={binding.account_id} | portfolio={binding.portfolio_id} | snapshot={binding.snapshot_id} | "
                                    f"as_of={binding.as_of or 'unavailable'} | view={binding.holdings_view} | checksum={binding.source_checksum[:12]} | execution_allowed=false",
                                    color=theme.MUTED,
                                    size=11,
                                    selectable=True,
                                ),
                            ]
                        )
                    )
                ]
                status.value = "Rebalance preview is inapplicable for mixed-asset targets; no target was dropped and no order was created."
                status.color = theme.AMBER
                state.last_message = status.value
                _safe_update(page)
                return
            report = build_rebalance_report(
                state.snapshot.config,
                selected_holdings,
                targets,
                target_cash_weight=candidate_cash,
                portfolio_value_eur=candidate_notional,
                constraints=RebalanceConstraints(
                    cash_buffer_weight=0.02,
                    min_trade_eur=50.0,
                    lot_size=1.0,
                    allow_fractional_lots=False,
                ),
            )
            rebalance_host.controls = [_rebalance_view(report, source_binding=binding)]
            status.value = "Rebalance preview validated from the current local snapshot; no order or broker action was created."
            status.color = theme.GREEN if report.feasible else theme.AMBER
            state.last_message = status.value
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            status.value = f"Rebalance preview unavailable: {exc}"
            status.color = theme.AMBER
            rebalance_host.controls = [panel(ft.Text("Rebalance alternatives are unavailable until the validation error is corrected.", color=theme.AMBER, selectable=True))]
            _safe_update(page)

    def save(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            identity = candidate_id(candidate_name)
            saved = save_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                expected_revision=saved_revision[0] if saved_candidate_id[0] == identity else 0,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            saved_revision[0] = saved.revision
            saved_candidate_id[0] = saved.candidate.candidate_id
            refresh(
                saved.candidate,
                message=f"Saved local candidate revision {saved.revision}; no order or proposal was created.",
            )
        except StorageRevisionConflict as exc:
            status.value = f"Candidate not saved because a newer local revision exists: {exc}"
            status.color = theme.AMBER
            _safe_update(page)
        except (OSError, PortfolioSandboxPersistenceError, TypeError, ValueError) as exc:
            status.value = f"Candidate not saved: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def load(_event: ft.ControlEvent | None) -> None:
        try:
            saved = load_portfolio_candidate(
                state.snapshot,
                str(name.value or ""),
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            saved_revision[0] = saved.revision
            saved_candidate_id[0] = saved.candidate.candidate_id
            _apply_candidate(saved.candidate, name, notional, target_inputs, cash)
            message = f"Loaded local candidate revision {saved.revision}."
            colour = theme.GREEN
            if saved.source_stale:
                message += " Its source binding changed, so derived values were re-evaluated from the current snapshot."
                colour = theme.AMBER
            refresh(saved.candidate, message=message, colour=colour)
        except (OSError, PortfolioSandboxPersistenceError, TypeError, ValueError) as exc:
            status.value = f"Candidate not loaded: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def export(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                holdings_view=str(holdings_view.value or "combined"),
            )
            analysis = analyse_portfolio_candidate(
                state.snapshot,
                candidate,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            path = export_portfolio_analysis(
                analysis,
                ROOT / "data" / "exports" / f"portfolio_sandbox_{candidate.candidate_id}.json",
            )
            state.last_export_path = path
            status.value = f"Sandbox export written: {path.name}; execution remains disabled."
            status.color = theme.GREEN
            _safe_update(page)
        except (OSError, TypeError, ValueError) as exc:
            status.value = f"Sandbox export unavailable: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def draft_proposal(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                holdings_view=str(holdings_view.value or "combined"),
            )
            analysis = analyse_portfolio_candidate(
                state.snapshot,
                candidate,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            handoff = draft_portfolio_proposal(state.snapshot, analysis)
            status.value = f"Draft hand-off prepared for ISSUE-0130 ({len(handoff['changes'])} changes); no proposal or order was created."
            status.color = theme.GREEN
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            status.value = f"Draft hand-off unavailable: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def draft_holdings_proposal(_event: ft.ControlEvent | None) -> None:
        binding = current_analysis[0].snapshot_binding
        if (
            binding is None
            or binding.account_id != str(account.value or "default")
            or binding.portfolio_id != str(portfolio.value or "default")
            or binding.snapshot_id != str(snapshot.value or "current")
            or binding.holdings_view != str(holdings_view.value or "combined")
        ):
            status.value = "Proposal hand-off blocked: analyse the currently selected portfolio snapshot before using the holdings action."
            status.color = theme.AMBER
            _safe_update(page)
            return
        draft_proposal(_event)

    def reset_current(_event: ft.ControlEvent | None) -> None:
        current_lines = {instrument_id: [] for instrument_id in target_inputs}
        selected_holdings = select_holdings_view(
            state.snapshot.holdings,
            str(holdings_view.value or "combined"),
        )
        for _, row in selected_holdings.iterrows():
            instrument_id = str(row.get("etf_id", row.get("instrument_id", "")))
            if instrument_id in current_lines:
                current_lines[instrument_id].append(float(row.get("current_weight", 0.0)))
        current = {
            instrument_id: math.fsum(sorted(weights))
            for instrument_id, weights in current_lines.items()
        }
        for instrument_id, control in target_inputs.items():
            control.value = f"{current[instrument_id] * 100:.4f}"
        cash.value = f"{max(0.0, 1.0 - sum(current.values())) * 100:.4f}"
        status.value = "Controls reset to the current local allocation; select Analyse candidate to recompute."
        status.color = theme.MUTED
        _safe_update(page)

    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header(
                            "Portfolio Sandbox",
                            "Create and compare a local research candidate. Every result is advisory context; broker execution and order creation are disabled.",
                        ),
                        ft.Row(
                            [
                                evidence_chip("Authority", "portfolio research only", theme.CYAN),
                                evidence_chip("Persistence", "local revisioned state", theme.BLUE_GREY),
                                evidence_chip("ETF overlap", "direct evidence enabled", theme.AMBER),
                                evidence_chip("Execution", "disabled", theme.GREEN),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header(
                            "Candidate controls",
                            "Select an account/portfolio snapshot and holdings view. Targets plus cash must equal exactly 100%; results cite the selected snapshot and remain advisory.",
                        ),
                        ft.Row([account, portfolio, snapshot, holdings_view], wrap=True),
                        ft.Row([name, notional, cash], wrap=True),
                        ft.Row(list(target_inputs.values()), wrap=True, spacing=8),
                        ft.Row(
                            [
                                ft.Button("Analyse candidate", key="portfolio.analyse", on_click=analyse),
                                ft.OutlinedButton("Validate rebalance preview", key="portfolio.rebalance-preview", on_click=rebalance_preview),
                                ft.OutlinedButton("Save revision", key="portfolio.save", icon=ft.Icons.SAVE, on_click=save),
                                ft.OutlinedButton("Load latest", key="portfolio.load", on_click=load),
                                ft.OutlinedButton("Export evidence", key="portfolio.export", on_click=export),
                                ft.OutlinedButton("Prepare ISSUE-0130 draft", key="portfolio.draft-proposal", on_click=draft_proposal),
                                ft.TextButton("Reset to current", key="portfolio.reset-current", on_click=reset_current),
                            ],
                            wrap=True,
                        ),
                        status,
                    ],
                    spacing=10,
                )
            ),
            _portfolio_performance_block(page),
            _portfolio_risk_profiles_block(page, state, current_analysis),
            _portfolio_forecast_block(page, state, current_analysis),
            _portfolio_calendar_block(page, state, current_analysis[0]),
            _portfolio_holdings_block(page, state, current_analysis, draft_holdings_proposal, holdings_refresh_callbacks),
            result_host,
            rebalance_host,
            _portfolio_goals_block(page, state, current_analysis),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _analysis_view(analysis: PortfolioAnalysis, *, benchmark_registry: object | None = None) -> ft.Control:
    cost = analysis.cost
    binding = analysis.snapshot_binding
    source_text = "snapshot binding unavailable"
    if binding is not None:
        source_text = (
            f"account={binding.account_id} | portfolio={binding.portfolio_id} | snapshot={binding.snapshot_id} | "
            f"as_of={binding.as_of or 'unavailable'} | view={binding.holdings_view} | source_checksum={binding.source_checksum[:12]}"
        )
    cards = ft.Row(
        [
            ft.Container(content=panel(ft.Column([ft.Text("Current value", color=theme.MUTED), ft.Text(f"EUR {analysis.current_value_eur:,.0f}", color=theme.TEXT, size=20)])), width=260),
            ft.Container(content=panel(ft.Column([ft.Text("Current cash", color=theme.MUTED), ft.Text(f"{analysis.current_cash_weight:.1%}", color=theme.TEXT, size=20)])), width=260),
            ft.Container(content=panel(ft.Column([ft.Text("Estimated rebalance cost", color=theme.MUTED), ft.Text(f"EUR {cost.total_cost_eur:,.2f} · {cost.weighted_cost_bps:.1f} bps", color=theme.TEXT, size=16)])), width=260),
        ],
        spacing=12,
        wrap=True,
    )

    allocation = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Instrument")),
            ft.DataColumn(ft.Text("Current")),
            ft.DataColumn(ft.Text("Target")),
            ft.DataColumn(ft.Text("Target - current")),
            ft.DataColumn(ft.Text("Signed notional")),
                    ft.DataColumn(ft.Text("Band")),
                    ft.DataColumn(ft.Text("Capability")),
                    ft.DataColumn(ft.Text("Why not")),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(f"{row.instrument_id} · {row.name}", size=11)),
                    ft.DataCell(ft.Text(f"{row.current_weight:.2%}", size=11)),
                    ft.DataCell(ft.Text(f"{row.target_weight:.2%}", size=11)),
                    ft.DataCell(ft.Text(f"{row.drift:+.2%}", size=11)),
                    ft.DataCell(ft.Text(f"EUR {row.signed_notional_eur:+,.2f}", size=11)),
                    ft.DataCell(ft.Text(row.drift_status.replace("_", " "), size=11)),
                    ft.DataCell(ft.Text(f"{row.asset_type}: {row.capability_status}", size=11)),
                    ft.DataCell(ft.Text(row.why_not or row.marginal_effect, size=11)),
                ]
            )
            for row in analysis.allocations
        ],
    )
    benchmark = analysis.service_evidence.get("benchmark_reference")
    profile = analysis.service_evidence.get("profile_relative")
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    benchmark_blockers = ", ".join(str(item) for item in benchmark.get("blockers", ())) or "none"
    profile_blockers = ", ".join(str(item) for item in profile.get("blockers", ())) or "none"
    benchmark_provenance = benchmark.get("provenance", {})
    benchmark_registry_hash = benchmark.get("registry_hash")
    if isinstance(benchmark_provenance, dict):
        benchmark_registry_hash = benchmark_provenance.get("registry_hash", benchmark_registry_hash)
    selected_identity_parts: list[str] = []
    for label, key in (("benchmark", "benchmark"), ("cash", "cash"), ("peer", "peer_set")):
        selected = benchmark.get(key, {})
        if isinstance(selected, dict) and selected.get("status") == "available":
            selected_identity_parts.append(
                f"{label}={selected.get('id')}@{selected.get('version')} digest:{selected.get('content_hash')}"
            )
    reference_identity_parts = [
        f"{item.get('id')}@{item.get('version')} digest:{item.get('content_hash')}"
        for item in benchmark.get("references", ())
        if isinstance(item, dict)
    ]
    selected_identities = " | ".join(selected_identity_parts) or "unavailable"
    reference_identities = " | ".join(reference_identity_parts) or "unavailable"
    anchor_resolution = profile.get("anchor_resolution", {})
    anchor_resolution = anchor_resolution if isinstance(anchor_resolution, dict) else {}
    reference_evidence = panel(
        ft.Column(
            [
                section_header(
                    "Benchmark and profile reference evidence",
                    "Canonical status, blockers and provenance remain visible; unavailable evidence never becomes an implicit comparison.",
                ),
                ft.Text(
                    "benchmark_reference: "
                    f"status={benchmark.get('status', 'unavailable')} | blockers={benchmark_blockers} | "
                    f"selected={selected_identities} | references={reference_identities} | "
                    f"provenance=registry_hash:{benchmark_registry_hash or 'unavailable'}",
                    color=theme.MUTED,
                    selectable=True,
                    size=11,
                ),
                ft.Text(
                    "profile_relative: "
                    f"status={profile.get('profile_relative_status', profile.get('status', 'unavailable'))} | blockers={profile_blockers} | "
                    f"canonical_share_class_id:{anchor_resolution.get('canonical_share_class_id') or 'unavailable'} "
                    f"listing_id:{anchor_resolution.get('listing_id') or 'unavailable'} "
                    f"effective_date:{anchor_resolution.get('effective_date') or 'unavailable'} "
                    f"knowledge_cutoff:{anchor_resolution.get('knowledge_cutoff') or 'unavailable'} | "
                    f"provenance=anchor_digest:{anchor_resolution.get('anchor_digest') or 'unavailable'} "
                    f"conversion_digest:{anchor_resolution.get('conversion_digest') or 'unavailable'} "
                    f"resolution_digest:{anchor_resolution.get('resolution_digest') or 'unavailable'}",
                    color=theme.MUTED,
                    selectable=True,
                    size=11,
                ),
            ]
        )
    )
    monthly_template = build_monthly_decision_template(
        benchmark_reference=benchmark,
        benchmark_registry=benchmark_registry,
        alternatives={
            name: unavailable_monthly_evidence(f"portfolio_{name}_return_projection_unavailable")
            for name in ("basket", "benchmark", "cash", "no_action")
        },
        expected_returns=unavailable_monthly_evidence("portfolio_level_expected_return_distribution_unavailable"),
        optimiser=_monthly_portfolio_optimiser(analysis),
        costs=_monthly_portfolio_costs(analysis),
        events=unavailable_monthly_evidence("event_replay_projection_not_bound_to_portfolio_candidate"),
        forward_evidence=unavailable_monthly_evidence("forward_evidence_snapshot_not_bound_to_portfolio_candidate"),
        paper_outcomes=unavailable_monthly_evidence("paper_account_snapshot_not_bound_to_portfolio_candidate"),
        concentration={
            "status": "partial",
            "reason": "theme_exposure_not_present_in_portfolio_analysis_contract",
            "sector": {
                "status": "available" if analysis.sector_exposure else "unavailable",
                "source_id": "PortfolioAnalysis.sector_exposure",
                "exposures": [
                    {"label": row.bucket, "weight": row.target_weight}
                    for row in analysis.sector_exposure
                ],
            },
            "theme": unavailable_monthly_evidence("theme_exposure_not_present_in_portfolio_analysis_contract"),
            "execution_allowed": False,
        },
        assumptions={
            "status": "available",
            "version": "monthly-decision-assumptions.v1",
            "source_id": analysis.candidate.candidate_id,
            "values": {
                "rebalance_cadence": "monthly",
                "execution_assumption": "next_session",
                "candidate_id": analysis.candidate.candidate_id,
                "candidate_source_revision": analysis.candidate.source_revision,
                "source_snapshot_bound": analysis.snapshot_binding is not None,
            },
            "execution_allowed": False,
        },
        evidence_maturity="unavailable",
        source=f"portfolio_candidate:{analysis.candidate.candidate_id}",
    )
    monthly_decision_evidence = panel(
        ft.Column(
            [
                section_header(
                    "Monthly decision template",
                    "Advisory comparison context for a monthly basket, canonical benchmark, canonical cash proxy and no-action alternative.",
                ),
                ft.Text("\n".join(monthly_decision_template_lines(monthly_template)), color=theme.MUTED, selectable=True),
            ],
            spacing=6,
        ),
    )
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Selected portfolio snapshot", "Every before/after result is bound to this local source identity; live ledger state is never mutated."),
                        ft.Text(source_text, color=theme.MUTED, selectable=True, size=11),
                        ft.Text("Direct and look-through holdings remain separate; complete ETF look-through is unavailable until ISSUE-0022.", color=theme.MUTED, selectable=True, size=11),
                    ]
                )
            ),
            cards,
            panel(
                ft.Column(
                    [
                        section_header("Current versus candidate", "Positive signed notional means an increase for analysis; it is not an instruction."),
                        ft.Row([allocation], scroll=ft.ScrollMode.AUTO),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            ft.Row(
                [
                    _exposure_table("Sector exposure", analysis.sector_exposure),
                    _exposure_table("Region exposure", analysis.region_exposure),
                    _exposure_table("Currency exposure", analysis.currency_exposure),
                ],
                spacing=12,
                wrap=True,
            ),
            overlap_evidence_panel(analysis.overlap, key="portfolio.etf-overlap"),
            _holding_evidence_view(analysis),
            _constraint_evidence_view(analysis),
            reference_evidence,
            monthly_decision_evidence,
            panel(
                ft.Column(
                    [
                        section_header("Existing service evidence", "What-if targets are passed to canonical factor-risk, covariance, optimiser, rebalance, scenario and attribution services; no calculation is duplicated here."),
                        ft.Text(
                            " | ".join(
                                f"{name}={value.get('status', 'unavailable')}"
                                for name, value in analysis.service_evidence.items()
                                if isinstance(value, dict)
                                and name in {"optimiser", "optimiser_comparison", "factor_risk", "risk", "correlation", "rebalancing", "scenarios", "attribution", "cost"}
                            ) or "service evidence unavailable",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        ft.Text(
                            _portfolio_service_coverage(analysis),
                            color=theme.MUTED,
                            selectable=True,
                            size=11,
                        ),
                        _portfolio_service_results(analysis),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Limitations and warnings", "Warnings remain visible and do not grant authority."),
                        ft.Text("\n".join(analysis.warnings or ("No candidate concentration warnings.",)), color=theme.MUTED, selectable=True),
                        ft.Text(
                            f"source_stale={str(analysis.source_stale).lower()} | overlap={analysis.overlap_status} | proposal_boundary=ISSUE-0130:draft-only | execution_allowed=false",
                            color=theme.MUTED,
                            size=11,
                            selectable=True,
                        ),
                    ]
                )
            ),
        ],
        spacing=12,
    )


def _service_value(value: object) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "unavailable"
    return str(value)


def _service_result_controls(label: str, value: object) -> list[ft.Control]:
    """Display canonical projections, retaining table axes and every disclosed row."""
    if isinstance(value, Mapping):
        if {"columns", "index", "data"}.issubset(value):
            table = ft.DataTable(
                columns=[ft.DataColumn(ft.Text(str(value.get("index_name") or "row"))),
                         *[ft.DataColumn(ft.Text(str(column))) for column in value["columns"]]],
                rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(_service_value(index), selectable=True)),
                                       *[ft.DataCell(ft.Text(_service_value(item), selectable=True)) for item in row]])
                      for index, row in zip(value["index"], value["data"], strict=True)],
            )
            return [ft.Text(label, color=theme.TEXT), ft.Row([table], scroll=ft.ScrollMode.AUTO)]
        controls = []
        for key, item in value.items():
            controls.extend(_service_result_controls(f"{label} / {key}", item))
        return controls or [ft.Text(f"{label}: unavailable", color=theme.MUTED)]
    if isinstance(value, (list, tuple)):
        return [control for index, item in enumerate(value, start=1)
                for control in _service_result_controls(f"{label} [{index}]", item)] or [ft.Text(f"{label}: none reported", color=theme.MUTED)]
    return [ft.Text(f"{label}: {_service_value(value)}", color=theme.MUTED, selectable=True, size=11)]


def _portfolio_service_results(analysis: PortfolioAnalysis) -> ft.Control:
    titles = {"optimiser_comparison": "Optimiser comparisons and baselines", "optimiser": "Selected optimiser",
              "factor_risk": "Factor risk and contributions", "risk": "Covariance and risk contributions",
              "correlation": "Correlation matrix",
              "rebalancing": "Rebalance and tax evidence", "scenarios": "Scenario results", "attribution": "Performance attribution", "cost": "Cost evidence"}
    controls: list[ft.Control] = []
    for name, title in titles.items():
        result = analysis.service_evidence.get(name)
        if not isinstance(result, Mapping):
            result = {"status": "unavailable", "reason": "canonical service result missing"}
        for warning in result.get("warnings", ()):
            controls.append(ft.Text(f"{title}: {warning}", color=theme.AMBER, selectable=True, size=11))
        if result.get("reason"):
            controls.append(ft.Text(f"{title}: {result['reason']}", color=theme.AMBER, selectable=True, size=11))
        controls.append(ft.ExpansionTile(
            title=ft.Text(title), subtitle=ft.Text(str(result.get("status", "unavailable"))),
            maintain_state=True, expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[ft.Column(_service_result_controls(title, result), height=320, scroll=ft.ScrollMode.AUTO)],
        ))
    return ft.Column(controls, spacing=6)


def _portfolio_service_coverage(analysis: PortfolioAnalysis) -> str:
    """Summarise method/coverage evidence without hiding unavailable inputs."""

    comparison = analysis.service_evidence.get("optimiser_comparison")
    methods = comparison.get("methods", ()) if isinstance(comparison, dict) else ()
    factor = analysis.service_evidence.get("factor_risk")
    risk = analysis.service_evidence.get("risk")
    scenario = analysis.service_evidence.get("scenarios")
    attribution = analysis.service_evidence.get("attribution")
    factor_coverage = factor.get("coverage", {}) if isinstance(factor, dict) else {}
    risk_coverage = risk.get("coverage", {}) if isinstance(risk, dict) else {}
    scenario_count = len(scenario.get("results", ())) if isinstance(scenario, dict) else 0
    factor_status = (
        factor_coverage.get("status", factor.get("status", "unavailable"))
        if isinstance(factor_coverage, dict) and isinstance(factor, dict)
        else "unavailable"
    )
    risk_status = (
        risk_coverage.get("status", risk.get("status", "unavailable"))
        if isinstance(risk_coverage, dict) and isinstance(risk, dict)
        else "unavailable"
    )
    return (
        f"methods={len(methods) if isinstance(methods, (list, tuple)) else 0} | "
        f"factor_coverage={factor_status} | "
        f"covariance_coverage={risk_status} | "
        f"scenarios={scenario_count} | attribution={attribution.get('status', 'unavailable') if isinstance(attribution, dict) else 'unavailable'} | execution_allowed=false"
    )


def _monthly_portfolio_optimiser(analysis: PortfolioAnalysis) -> dict[str, object]:
    value = analysis.service_evidence.get("optimiser")
    if not isinstance(value, dict) or value.get("status") == "unavailable":
        return unavailable_monthly_evidence("canonical_optimiser_solution_unavailable")
    return {
        "status": "partial",
        "reason": "solver_binding_diagnostics_not_exposed_by_portfolio_service_projection",
        "model_version": value.get("model_version"),
        "method": value.get("method"),
        "source_id": "PortfolioAnalysis.service_evidence.optimiser",
        "constraints": {
            "status": "available",
            "source_id": "PortfolioAnalysis.constraints",
            "rows": [
                {
                    "name": row.name,
                    "current_value": row.current_value,
                    "target_value": row.target_value,
                    "limit": row.limit,
                    "status": row.status,
                    "reason": row.reason,
                }
                for row in analysis.constraints
            ],
            "execution_allowed": False,
        },
        "solution": {
            "status": value.get("status"),
            "feasible": value.get("feasible"),
            "weights": value.get("weights", {}),
            "warnings": value.get("warnings", []),
            "diagnostics": unavailable_monthly_evidence("solver_binding_diagnostics_unavailable"),
            "execution_allowed": False,
        },
        "execution_allowed": False,
    }


def _monthly_portfolio_costs(analysis: PortfolioAnalysis) -> dict[str, object]:
    cost = analysis.cost
    return {
        "status": "available" if cost.capacity_eur is not None else "partial",
        "reason": "capacity_unavailable" if cost.capacity_eur is None else "complete_portfolio_cost_estimate",
        "model_id": cost.model_id,
        "source_id": "PortfolioCostEstimate",
        "components": [
            {
                "estimate_id": item.estimate_id,
                "instrument_id": item.instrument_id,
                "order_value_eur": item.order_value_eur,
                "cost_eur": item.total_cost_eur,
                "cost_bps": item.total_cost_bps,
                "commission_eur": item.commission_eur,
                "spread_bps": item.spread_bps,
                "slippage_bps": item.slippage_bps,
                "market_impact_bps": item.market_impact_bps,
                "capacity_eur": item.capacity_eur,
                "capacity_status": item.capacity_status,
                "data_quality": item.data_quality,
                "execution_allowed": False,
            }
            for item in cost.estimates
        ],
        "total": {
            "order_value_eur": cost.total_order_value_eur,
            "cost_eur": cost.total_cost_eur,
            "cost_bps": cost.weighted_cost_bps,
        },
        "capacity": {
            "status": "available" if cost.capacity_eur is not None else "unavailable",
            "amount_eur": cost.capacity_eur,
        },
        "assumptions": [
            assumption
            for item in cost.estimates
            for assumption in item.assumptions
        ],
        "execution_allowed": False,
    }


def _holding_evidence_view(analysis: PortfolioAnalysis) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(row.instrument_id, size=11)),
                ft.DataCell(ft.Text(row.holding_view, size=11)),
                ft.DataCell(ft.Text(row.asset_type, size=11)),
                ft.DataCell(ft.Text(f"{row.current_weight:.2%}", size=11)),
                ft.DataCell(ft.Text(row.capability_status, size=11)),
                ft.DataCell(ft.Text(row.capability_reason, size=11)),
            ]
        )
        for row in analysis.holdings
    ]
    return panel(
        ft.Column(
            [
                section_header("Direct and look-through holdings", "Lineage, capability and source identity remain explicit; unresolved ETF look-through is not redistributed."),
                ft.Row(
                    [
                        ft.DataTable(
                            columns=[ft.DataColumn(ft.Text(value)) for value in ("Instrument", "View", "Asset", "Current", "Capability", "Reason")],
                            rows=rows,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )


def _constraint_evidence_view(analysis: PortfolioAnalysis) -> ft.Control:
    constraint_lines = [
        f"{item.name}: {item.status} ({item.reason})"
        for item in analysis.constraints
    ]
    why_not_lines = [f"{instrument_id}: {reason}" for instrument_id, reason in analysis.why_not]
    before_after = [f"{instrument_id}: {before:.2%} → {after:.2%}" for instrument_id, before, after in analysis.before_after]
    text = "\n".join(
        [
            "Applicable constraints:",
            *(constraint_lines or ["none available"]),
            "Marginal before/after weight effect:",
            *(before_after or ["none"]),
            "Explicit why-not outcomes:",
            *(why_not_lines or ["none"]),
        ]
    )
    return panel(
        ft.Column(
            [
                section_header("Constraints, marginal effect and why not", "A blocked, inapplicable or no-trade outcome is visible rather than silently omitted."),
                ft.Text(text, color=theme.MUTED, selectable=True, size=11),
            ]
        )
    )


def _rebalance_view(report: RebalanceReport, *, source_binding: object | None = None) -> ft.Control:
    alternatives = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Alternative")), ft.DataColumn(ft.Text("Changes")), ft.DataColumn(ft.Text("Drift proxy")), ft.DataColumn(ft.Text("Cost")), ft.DataColumn(ft.Text("Cash"))],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(item.name.replace("_", " ").title(), size=11)),
                    ft.DataCell(ft.Text(str(item.trade_count), size=11)),
                    ft.DataCell(ft.Text(f"{item.tracking_error_proxy:.2%}", size=11)),
                    ft.DataCell(ft.Text(f"EUR {item.estimated_cost_eur:,.2f}", size=11)),
                    ft.DataCell(ft.Text(f"{item.cash_weight:.2%}", size=11)),
                ]
            )
            for item in report.alternatives.values()
        ],
    )
    trades = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Instrument")), ft.DataColumn(ft.Text("Change")), ft.DataColumn(ft.Text("Value")), ft.DataColumn(ft.Text("Status")), ft.DataColumn(ft.Text("Cost"))],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(item.instrument_id, size=11)),
                    ft.DataCell(ft.Text(item.action.replace("buy", "increase").replace("sell", "reduce"), size=11)),
                    ft.DataCell(ft.Text(f"EUR {item.trade_value_eur:+,.2f}", size=11)),
                    ft.DataCell(ft.Text(item.status.replace("_", " "), size=11)),
                    ft.DataCell(ft.Text(f"EUR {item.estimated_cost_eur:,.2f}", size=11)),
                ]
            )
            for item in report.trades
            if abs(item.trade_value_eur) > 0 or item.status not in {"no_change"}
        ],
    )
    warning_text = "\n".join(report.warnings or ("No rebalance warnings.",))
    return panel(
        ft.Column(
            [
                section_header("Rebalance workspace", "Compare cost-, cash-, lot- and restriction-aware alternatives. This is advisory evidence only."),
                ft.Text(
                    "source="
                    + (
                        f"account={getattr(source_binding, 'account_id')} | portfolio={getattr(source_binding, 'portfolio_id')} | "
                        f"snapshot={getattr(source_binding, 'snapshot_id')} | as_of={getattr(source_binding, 'as_of') or 'unavailable'} | "
                        f"view={getattr(source_binding, 'holdings_view')} | checksum={getattr(source_binding, 'source_checksum')[:12]}"
                        if source_binding is not None
                        else "unavailable"
                    ),
                    color=theme.MUTED,
                    size=11,
                    selectable=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Feasibility", "available" if report.feasible else "manual review", theme.GREEN if report.feasible else theme.AMBER),
                        evidence_chip("Cash after change", f"{report.cash_weight:.1%}", theme.BLUE_GREY),
                        evidence_chip("Tax", report.tax_status.replace("_", " "), theme.AMBER),
                        evidence_chip("Execution", "disabled", theme.GREEN),
                    ],
                    wrap=True,
                    spacing=8,
                ),
                ft.Text("Alternatives", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                ft.Row([alternatives], scroll=ft.ScrollMode.AUTO),
                ft.Text("Proposed changes", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                ft.Row([trades], scroll=ft.ScrollMode.AUTO),
                ft.Text(warning_text, color=theme.MUTED, selectable=True),
                ft.Text(
                    f"model_version={report.model_version} | lot_policy={report.assumptions['lot_policy']} | min_trade_eur={report.assumptions['min_trade_eur']:.2f} | tax_jurisdiction={report.tax_jurisdiction} | execution_allowed=false",
                    color=theme.MUTED,
                    size=11,
                    selectable=True,
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )
    )
def _exposure_table(title: str, rows: object) -> ft.Control:
    return panel(
        ft.Column(
            [
                ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Bucket")), ft.DataColumn(ft.Text("Current")), ft.DataColumn(ft.Text("Target"))],
                    rows=[
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(row.bucket, size=11)),
                                ft.DataCell(ft.Text(f"{row.current_weight:.1%}", size=11)),
                                ft.DataCell(ft.Text(f"{row.target_weight:.1%}", size=11)),
                            ]
                        )
                        for row in rows  # type: ignore[union-attr]
                    ],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _percentage(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("weights must be finite percentages")
    try:
        return float(str(value or "").strip()) / 100.0
    except ValueError as exc:
        raise ValueError("weights must be finite percentages") from exc


def _holding_ids(holdings: object) -> set[str]:
    if not hasattr(holdings, "iterrows"):
        return set()
    return {
        instrument_id
        for _, row in holdings.iterrows()  # type: ignore[union-attr]
        if (instrument_id := str(row.get("etf_id", row.get("instrument_id", ""))).strip())
    }


def _target_label(instrument_id: str, configured: object | None, holdings: object) -> str:
    if configured is not None:
        return f"{instrument_id} target (%)"
    asset_types = sorted(
        {
            str(row.get("asset_type", row.get("instrument_type", row.get("asset_class", "unknown"))) or "unknown")
            for _, row in holdings.iterrows()  # type: ignore[union-attr]
            if str(row.get("etf_id", row.get("instrument_id", ""))).strip() == instrument_id
        }
    )
    return f"{instrument_id} target (%) [current {'/'.join(asset_types) or 'unknown'}]"


def _apply_candidate(candidate: object, name: ft.TextField, notional: ft.TextField, targets: dict[str, ft.TextField], cash: ft.TextField) -> None:
    name.value = str(getattr(candidate, "name"))
    notional.value = f"{float(getattr(candidate, 'analysis_notional_eur')):.2f}"
    values = dict(getattr(candidate, "target_weights"))
    for instrument_id, control in targets.items():
        control.value = f"{float(values.get(instrument_id, 0.0)) * 100:.4f}"
    cash.value = f"{float(getattr(candidate, 'cash_weight')) * 100:.4f}"


def _safe_update(page: ft.Page | None) -> None:
    if page is None:
        return
    try:
        page.update()
    except (AssertionError, RuntimeError):
        return


def _snapshot_values(snapshot: object, field: str, fallback: str) -> tuple[str, ...]:
    raw = getattr(snapshot, field, None)
    return (str(raw or fallback),)


__all__ = ["portfolio_page"]
