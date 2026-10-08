from __future__ import annotations

from collections.abc import Mapping
import math

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.chartkit import Bubble, Series
from etf_cockpit.app.components.kit import (
    Button,
    CardMenu,
    DataTable,
    Disclosure,
    Field,
    GlassCard,
    KpiStrip,
    KpiStripItem,
    KpiTile,
    Note,
    TableColumn,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_date, format_number, format_percent
from etf_cockpit.app.pages._lab_style import lab_page, metric_card, panel, section_header
from etf_cockpit.app.components.charts import equity_drawdown_chart, history_chart
from etf_cockpit.app.components.tables import accessible_table
from etf_cockpit.application.instrument_detail_view import (
    _latest_operational_row,
    _operational_evidence_panel,
)
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.monthly_decision_template import (
    build_monthly_decision_template,
    monthly_decision_template_lines,
    unavailable_monthly_evidence,
)
from etf_cockpit.core.paths import EXPORTS_DIR
from etf_cockpit.application.ui_facade import NEWS_TIMESTAMP_VALIDATION_PATH, cost_capacity_status, event_engine_status, export_table
from etf_cockpit.application.validation import build_validation_preview


def _open_gap_warning_label(row: dict[str, object]) -> str:
    warning = row.get("open_gap_warning")
    if type(warning) is not bool:
        return "unavailable"
    limit = _format_number(row.get("open_gap_warning_threshold"), percent=True)
    return f"WARNING: |gap| >= {limit}" if warning else f"within {limit}"


def _format_number(value: object, *, percent: bool = False, money: bool = False, decimals: int = 2) -> str:
    if value is None or value != value:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    if money:
        return f"EUR {number:,.0f}"
    if percent:
        return f"{number:.1%}"
    return f"{number:.{decimals}f}"


def _negative_contributions_label(value: object) -> str:
    if not isinstance(value, (list, tuple)):
        return "unavailable" if value is None else str(value)
    if not value:
        return "unavailable"
    records = []
    for record in value:
        if isinstance(record, Mapping):
            records.append(f"{record.get('date', 'n/a')}: {_format_number(record.get('return'), percent=True)}")
    return "; ".join(records) if records else "unavailable"


@lab_page("backtests")
def _legacy_backtests_page(_page: ft.Page, state: AppState) -> ft.Control:
    report = state.ensure_backtest()
    if report is None:
        return ft.Column(
            [panel(ft.Column([section_header("Backtests", "Backtest data is unavailable for the current snapshot.")]))],
            expand=True,
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        )
    news_warning = _news_validation_warning()
    reference_context = context_from_snapshot(
        state.snapshot,
        purpose="validation",
        analysis_id=f"validation:{getattr(state.snapshot, 'universe_revision', 'unknown')}",
    )
    validation_panel = _validation_panel(
        getattr(state.snapshot, "prices", None),
        reference_context=reference_context,
    )
    event_panel = _event_replay_panel()
    cost_panel = _cost_capacity_panel(state.snapshot.config)
    monthly_decision_panel = _monthly_decision_panel(
        reference_context,
        report=report,
        config=state.snapshot.config,
    )
    if report.results.empty or "strategy_name" not in report.results.columns:
        return ft.Column(
            [
                panel(
                    ft.Column(
                        [
                            section_header("Backtests", "Run Refresh yfinance data and Run algorithms before backtests can be evaluated for the current two-tier universe."),
                            news_warning,
                            validation_panel,
                            cost_panel,
                            event_panel,
                            monthly_decision_panel,
                            ft.Text("\n".join(report.quality_notes or ["Backtest pending."]), color=theme.MUTED, selectable=True),
                        ],
                        spacing=12,
                    )
                )
            ],
            expand=True,
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        )
    signal_rows = report.results[report.results["strategy_name"] == "signal_strategy"]
    if signal_rows.empty:
        return ft.Column(
            [
                panel(
                    ft.Column(
                        [
                            section_header("Backtests", "No signal-strategy backtest row is available for the current run."),
                            validation_panel,
                            cost_panel,
                            event_panel,
                            monthly_decision_panel,
                            ft.Text("\n".join(report.quality_notes or ["Backtest pending."]), color=theme.MUTED, selectable=True),
                        ],
                        spacing=12,
                    )
                )
            ],
            expand=True,
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        )
    signal = signal_rows.iloc[0]
    equity_frame = _equity_drawdown_frame(report.equity_curves)
    chart_descriptor = equity_drawdown_chart(equity_frame)
    price_chart_descriptor = history_chart(state.snapshot.prices, title="Adjusted-price history")
    recent_evidence = chart_descriptor.data
    strategy_table = accessible_table(report.results, table_id="backtests.strategy-results")
    export_status = ft.Text("CSV exports show the destination path and controlled failure state.", color=theme.MUTED, selectable=True)

    def export_backtest(_event: ft.ControlEvent) -> None:
        result = export_table("backtest_equity_drawdown", equity_frame, EXPORTS_DIR / "backtest_equity_drawdown.csv")
        if result.ok:
            export_status.value = f"Export complete: {result.destination} ({result.rows} rows)."
        else:
            export_status.value = f"Export failed: {result.error}; previous output preserved."
        export_status.color = theme.GREEN if result.ok else theme.RED
        _page.update()

    def export_strategy_results(_event: ft.ControlEvent) -> None:
        result = export_table("backtest_strategy_results", strategy_table.frame, EXPORTS_DIR / "backtest_strategy_results.csv")
        if result.ok:
            export_status.value = f"Export complete: {result.destination} ({result.rows} rows)."
        else:
            export_status.value = f"Export unavailable: {result.error}; no placeholder written."
        export_status.color = theme.GREEN if result.ok else theme.RED
        _page.update()
    diagnostics = [
        f"Quality label: {report.quality_label}",
        *(report.quality_notes or []),
        f"Train periods: {int(signal['train_periods'])}",
        f"Validation periods: {int(signal['validation_periods'])}",
        f"Test periods: {int(signal['test_periods'])}",
        f"Median holding period: {_format_number(signal['median_holding_period_days'], decimals=0)} days",
        f"Return hit rate: {_format_number(signal.get('return_hit_rate'), percent=True)}",
        f"Average win/loss return: {_format_number(signal.get('average_win_return'), percent=True)} / {_format_number(signal.get('average_loss_return'), percent=True)}",
        f"Payoff ratio: {_format_number(signal.get('payoff_ratio'))}",
        f"Return skew: {_format_number(signal.get('skew'))}",
        f"Payoff profile: {signal.get('payoff_profile', 'unavailable')}",
        f"Expected value per period: {_format_number(signal.get('expected_value_per_period'), percent=True)}",
        f"Payoff warning: {signal.get('payoff_asymmetry_warning', 'n/a')}",
        f"Loss dominance warning: {signal.get('loss_dominance_warning', 'n/a')}",
        str(signal.get(
            "payoff_profile_disclaimer",
            "Descriptive payoff profile only; no trade recommendation is derived from payoff profile; execution_allowed=false.",
        )),
        f"Probabilistic Sharpe: {_format_number(signal['probabilistic_sharpe'])}",
        f"Deflated Sharpe: {_format_number(signal['deflated_sharpe'])}",
        f"PBO probability: {_format_number(signal['pbo_probability_backtest_overfitting'])}",
        f"Parameter sensitivity: {signal['parameter_sensitivity_status']}",
        f"Overfitting warning: {signal.get('overfitting_warning', 'n/a')}",
        f"Data quality: {signal.get('data_quality_status', report.metadata.get('data_status', 'n/a'))}",
        f"Strategy: {report.metadata.get('strategy', 'n/a')}",
        f"Benchmark: {report.metadata.get('benchmark_strategy', 'n/a')}",
        f"Date range: {report.metadata.get('date_range_start', signal.get('start_date', 'n/a'))} to {report.metadata.get('date_range_end', signal.get('end_date', 'n/a'))}",
    ]
    tail_diagnostics = [
        "Descriptive/non-causal evidence only; execution_allowed=false.",
        f"Worst 1-day return: {_format_number(signal.get('worst_1d_return'), percent=True)}",
        f"Worst 5-day return: {_format_number(signal.get('worst_5d_return'), percent=True)}",
        f"Worst 10-day return: {_format_number(signal.get('worst_10d_return'), percent=True)}",
        f"Worst drawdown window: {signal.get('worst_drawdown_start', 'n/a')} to {signal.get('worst_drawdown_end', 'n/a')} ({signal.get('worst_drawdown_duration_days', 'n/a')} observed sessions)",
        f"Maximum consecutive loss periods: {signal.get('loss_cluster_max_days', 'n/a')}",
        f"Largest negative contribution period: {_format_number(signal.get('largest_negative_period_return'), percent=True)} on {signal.get('largest_negative_period_date', 'n/a')}",
        f"Largest negative contribution periods: {_negative_contributions_label(signal.get('largest_negative_contribution_periods'))}",
        f"Five worst loss sessions' share of total losses: {_format_number(signal.get('negative_return_concentration_share'), percent=True)} ({signal.get('negative_return_concentration_status', 'unavailable')}; {signal.get('negative_return_concentration_reason', '')})",
        f"Positive gross performance concentration: {_format_number(signal.get('positive_performance_concentration_share'), percent=True)} ({signal.get('positive_performance_concentration_status', 'unavailable')})",
        f"Negative gross performance concentration: {_format_number(signal.get('negative_performance_concentration_share'), percent=True)} ({signal.get('negative_performance_concentration_status', 'unavailable')})",
        f"Few sessions explain most performance (selected gross side): {signal.get('few_days_explain_most_performance', 'unavailable')} (strictly >50%; {signal.get('performance_concentration_basis', 'unavailable')})",
        f"Losses during high volatility: {signal.get('losses_during_high_volatility', 'unavailable')} ({signal.get('high_volatility_loss_status', 'unavailable')}; {signal.get('high_volatility_loss_reason', '')})",
        f"Losses during regime stress: {signal.get('losses_during_regime_stress', 'unavailable')} ({signal.get('regime_stress_loss_status', 'unavailable')}; {signal.get('regime_stress_loss_reason', '')})",
    ]
    operational_evidence = [
        f"Signal timestamp source: price-panel timestamp (lookahead label: {report.metadata.get('lookahead_protection', 'unavailable')})",
        f"Execution delay: {report.metadata.get('execution_delay_sessions', 'n/a')} complete session",
        f"Same-bar execution avoided: {'yes' if report.metadata.get('same_bar_execution_avoided') else 'no'}",
        "Decision price, next-open reference, next-period adjusted close and close-to-next-open gap are shown per exact instrument below.",
        "Observed high-low range proxy and configured/estimated cost spread assumption are separate fields.",
        "Session, auction, expiry and order lifecycle are unavailable unless an event/order record evidences them.",
        "Simulated backtest fills and paper/reconciled fills are separate sources; execution_allowed=false.",
        "No forward-fill is applied to incomplete adjusted-price rows.",
    ]
    operational_frame = getattr(report, "operational_evidence", pd.DataFrame())
    operational_instrument_ids = list(
        getattr(getattr(state.snapshot.config, "universe", None), "enabled_ids", ()) or ()
    )
    validated_operational_rows: list[dict[str, object]] = []
    operational_contract_fields = (
        "signal_date", "signal_timestamp", "execution_date", "execution_timestamp",
        "decision_price", "decision_price_basis", "decision_price_source_identity",
        "next_open_reference_price", "next_open_reference_basis", "next_open_source_identity",
        "next_period_reference_price", "next_period_reference_basis", "next_period_source_identity",
        "close_to_next_open_gap", "price_provenance", "arrival_price_assumption",
        "execution_delay_sessions", "same_bar_execution_avoided", "observed_range_spread_proxy",
        "spread_proxy", "cost_spread_assumption_bps", "cost_spread_assumption_source", "estimated_cost_bps",
        "estimated_cost_bps_source", "session_state", "auction_state", "expiry_state",
        "order_lifecycle", "fill_source", "paper_fill_source", "reconciled_fill_source",
        "execution_allowed",
    )
    if isinstance(operational_frame, pd.DataFrame) and not operational_frame.empty:
        for instrument_id in operational_instrument_ids:
            projection = _operational_evidence_panel(report, str(instrument_id))
            if projection.get("status") == "available":
                validated_operational_rows.extend(projection.get("rows", ()))
            else:
                validated_operational_rows.append(
                    {
                        "evidence_status": "unavailable",
                        "evidence_reason": projection.get(
                            "message", "exact operational evidence unavailable"
                        ),
                        "instrument_id": str(instrument_id),
                        **{field: None for field in operational_contract_fields},
                        "execution_allowed": False,
                    }
                )
    latest_operational_rows: dict[str, dict[str, object]] = {}
    for row in validated_operational_rows:
        instrument_id = str(row.get("instrument_id", "")).strip()
        if not instrument_id:
            continue
        latest_operational_rows[instrument_id] = _latest_operational_row(
            [latest_operational_rows[instrument_id], row]
            if instrument_id in latest_operational_rows
            else [row]
        )
    operational_rows = []
    for row in (latest_operational_rows[key] for key in sorted(latest_operational_rows)):
        operational_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row.get("evidence_status", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("evidence_reason", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("instrument_id", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("signal_date", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("signal_timestamp", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("execution_date", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("execution_timestamp", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("decision_price")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("decision_price_basis", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("decision_price_source_identity", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("next_open_reference_price")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("next_open_reference_basis", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("next_open_source_identity", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("next_period_reference_price")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("next_period_reference_basis", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("next_period_source_identity", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("close_to_next_open_gap"), percent=True), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_open_gap_warning_label(row), color=theme.AMBER if row.get("open_gap_warning") is True else theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("price_provenance", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("arrival_price_assumption", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("execution_delay_sessions", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("same_bar_execution_avoided", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("observed_range_spread_proxy"), percent=True), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("spread_proxy"), percent=True), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("cost_spread_assumption_bps")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("cost_spread_assumption_source", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(_format_number(row.get("estimated_cost_bps")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("estimated_cost_bps_source", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("session_state", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("auction_state", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("expiry_state", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("order_lifecycle", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("fill_source", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("paper_fill_source", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("reconciled_fill_source", "unavailable")), color=theme.TEXT, size=11)),
                    ft.DataCell(ft.Text(str(row.get("execution_allowed", "unavailable")), color=theme.TEXT, size=11)),
                ]
            )
        )
    trade_rows = []
    if not report.trade_log.empty:
        for _, row in report.trade_log.head(8).iterrows():
            trade_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(row.get("strategy", "")), color=theme.TEXT, size=12)),
                        ft.DataCell(ft.Text(str(row.get("signal_date", "")), color=theme.TEXT, size=12)),
                        ft.DataCell(ft.Text(str(row.get("execution_date", row.get("date", ""))), color=theme.TEXT, size=12)),
                        ft.DataCell(ft.Text(_format_number(row.get("turnover", 0.0)), color=theme.TEXT, size=12)),
                        ft.DataCell(ft.Text(_format_number(row.get("cost_eur", 0.0), money=True), color=theme.TEXT, size=12)),
                    ]
                )
            )
    return ft.Column(
        [
            ft.Row(
                [
                    metric_card("Signal strategy CAGR", f"{signal['cagr']:.1%}"),
                    metric_card("Max drawdown", f"{signal['max_drawdown']:.1%}"),
                    metric_card("Turnover", f"{signal['turnover']:.2f}"),
                    metric_card("Model-added value", "Yes" if report.ai_added_value else "No", "diagnostic only"),
            metric_card("Backtest quality", str(report.quality_label).title(), str(signal["parameter_sensitivity_status"])),
                ],
                spacing=12,
            ),
            news_warning,
            validation_panel,
            cost_panel,
            monthly_decision_panel,
            panel(
                ft.Column(
                    [
                        section_header("Strategy diagnostics", "After-cost results versus equal-weight, quality-only, momentum-only, quality-momentum and trend-only baselines."),
                        strategy_table.search_control,
                        strategy_table.control,
                        strategy_table.status_control,
                        ft.Text(f"{strategy_table.search_label}; sortable columns: {', '.join(strategy_table.sortable_columns)}", color=theme.MUTED, selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
            ),
            panel(ft.Column([section_header("Price, equity and drawdown evidence", "Adjusted-price history and backtest curves are descriptive evidence only; they cannot authorise broker execution."), price_chart_descriptor.control, chart_descriptor.control, ft.Text(f"Recent evidence series: {', '.join(recent_evidence) or 'unavailable'}", color=theme.MUTED, selectable=True), ft.Row([ft.OutlinedButton("Export strategy results CSV", key="backtests.export-strategy-results", icon=ft.Icons.DOWNLOAD, on_click=export_strategy_results), ft.OutlinedButton("Export equity/drawdown CSV", key="backtests.export-equity-drawdown", icon=ft.Icons.DOWNLOAD, on_click=export_backtest)]), export_status], spacing=8)),
            panel(ft.Column([section_header("Backtest quality", "Walk-forward and overfitting diagnostics for the scoring method."), ft.Text("\n".join(diagnostics), color=theme.MUTED, selectable=True)])),
            panel(
                ft.Column(
                    [
                        section_header("Tail-event diagnostics", "Worst windows and loss clustering make concentrated drawdown risk visible."),
                        ft.Text("\n".join(tail_diagnostics), color=theme.MUTED, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Instrument operational evidence", "Exact-instrument simulated backtest evidence; unavailable or aggregate-only evidence is not aliased. execution_allowed=false."),
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Status")),
                                ft.DataColumn(ft.Text("Reason")),
                                ft.DataColumn(ft.Text("Instrument")),
                                ft.DataColumn(ft.Text("Signal date")),
                                ft.DataColumn(ft.Text("Signal timestamp")),
                                ft.DataColumn(ft.Text("Execution date")),
                                ft.DataColumn(ft.Text("Execution timestamp")),
                                ft.DataColumn(ft.Text("Decision")),
                                ft.DataColumn(ft.Text("Decision basis")),
                                ft.DataColumn(ft.Text("Decision source")),
                                ft.DataColumn(ft.Text("Next open")),
                                ft.DataColumn(ft.Text("Next-open basis")),
                                ft.DataColumn(ft.Text("Next-open source")),
                                ft.DataColumn(ft.Text("Next-period close")),
                                ft.DataColumn(ft.Text("Next-close basis")),
                                ft.DataColumn(ft.Text("Next-close source")),
                                ft.DataColumn(ft.Text("Close→open gap")),
                                ft.DataColumn(ft.Text("Open-gap warning")),
                                ft.DataColumn(ft.Text("Price provenance")),
                                ft.DataColumn(ft.Text("Arrival assumption")),
                                ft.DataColumn(ft.Text("Delay sessions")),
                                ft.DataColumn(ft.Text("Same-bar avoided")),
                                ft.DataColumn(ft.Text("Observed H-L proxy")),
                                ft.DataColumn(ft.Text("Spread proxy")),
                                ft.DataColumn(ft.Text("Cost spread bps")),
                                ft.DataColumn(ft.Text("Cost spread source")),
                                ft.DataColumn(ft.Text("Estimated all-in cost bps")),
                                ft.DataColumn(ft.Text("Estimated cost source")),
                                ft.DataColumn(ft.Text("Session state")),
                                ft.DataColumn(ft.Text("Auction state")),
                                ft.DataColumn(ft.Text("Expiry state")),
                                ft.DataColumn(ft.Text("Order lifecycle")),
                                ft.DataColumn(ft.Text("Fill source")),
                                ft.DataColumn(ft.Text("Paper fill source")),
                                ft.DataColumn(ft.Text("Reconciled fill source")),
                                ft.DataColumn(ft.Text("Execution allowed")),
                            ],
                            rows=operational_rows,
                        )
                        if operational_rows
                        else ft.Text("Instrument operational evidence unavailable; no exact scoped rows were persisted.", color=theme.MUTED, selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Operational execution evidence", "Quality-momentum uses point-in-time evidence and next-session simulation; decision-price assumptions are descriptive only and same-bar execution is forbidden."),
                        ft.Text("\n".join(operational_evidence), color=theme.MUTED, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Simulated executions", "Backtest uses next-period execution and costs; this is not broker automation."),
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Strategy")),
                                ft.DataColumn(ft.Text("Signal date")),
                                ft.DataColumn(ft.Text("Execution date")),
                                ft.DataColumn(ft.Text("Turnover")),
                                ft.DataColumn(ft.Text("Cost")),
                            ],
                            rows=trade_rows,
                        )
                        if trade_rows
                        else ft.Text("No simulated trades were generated.", color=theme.MUTED),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            event_panel,
            panel(ft.Text("Backtest logs are written to data/backtests/ for audit. Diagnostics are local deterministic estimates, not proof of future performance.", color=theme.MUTED, selectable=True)),
        ],
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
    )


def _monthly_decision_panel(reference_context: object, *, report: object, config: object) -> ft.Control:
    metadata = getattr(report, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    event_status = event_engine_status()
    replay_fields = _backtest_evidence_fields(metadata, "replay")
    next_session_fields = _backtest_evidence_fields(metadata, "next-session")
    replay_available = bool(replay_fields)
    next_session_available = (
        metadata.get("execution_delay_sessions") == 1
        and metadata.get("same_bar_execution_avoided") is True
        and bool(next_session_fields)
    )
    template = build_monthly_decision_template(
        benchmark_reference=getattr(reference_context, "projection", None),
        benchmark_registry=getattr(reference_context, "registry", None),
        alternatives=_monthly_backtest_alternatives(
            report,
            metadata,
            reference=getattr(reference_context, "projection", None),
        ),
        expected_returns=unavailable_monthly_evidence("monthly_expected_return_distribution_not_produced_by_backtest_report"),
        optimiser=unavailable_monthly_evidence("optimiser_solution_not_bound_to_backtest_report"),
        costs=_monthly_backtest_costs(config),
        events={
            "status": "partial",
            "reason": "event_engine_contract_has_no_version_field",
            "source_id": "event_engine_status+BacktestReport.metadata",
            "replay": {
                "status": "available" if replay_available else "unavailable",
                "reason": "canonical_backtest_metadata" if replay_available else "backtest_event_evidence_unavailable",
                **event_status,
                **replay_fields,
            },
            "next_session": {
                "status": "available" if next_session_available else "unavailable",
                "reason": "canonical_backtest_metadata" if next_session_available else "backtest_next_session_evidence_unavailable",
                "execution_delay_sessions": metadata.get("execution_delay_sessions"),
                "same_bar_execution_avoided": metadata.get("same_bar_execution_avoided"),
                "arrival_price_assumption": "next_adjusted_close" if next_session_available else None,
                **next_session_fields,
                "execution_allowed": False,
            },
            "execution_allowed": False,
        },
        forward_evidence=unavailable_monthly_evidence("ForwardEvidenceSnapshot_not_bound_to_backtest_report"),
        paper_outcomes=unavailable_monthly_evidence("PaperAccountSnapshot_not_bound_to_backtest_report"),
        concentration={
            "status": "unavailable",
            "reason": "portfolio_sector_theme_concentration_not_produced_by_backtest_report",
            "execution_allowed": False,
        },
        assumptions={
            "status": "available",
            "version": "monthly-decision-assumptions.v1",
            "source_id": str(metadata.get("input_checksum") or "BacktestReport.metadata"),
            "values": {
                "rebalance_cadence": "monthly",
                "execution_assumption": "next_session",
                "price_field": metadata.get("price_field"),
                "lookahead_protection": metadata.get("lookahead_protection"),
                "execution_delay_sessions": metadata.get("execution_delay_sessions"),
                "same_bar_execution_avoided": metadata.get("same_bar_execution_avoided"),
            },
            "execution_allowed": False,
        },
        evidence_maturity=getattr(report, "quality_label", "unavailable"),
        sample_size=metadata.get("walk_forward_periods"),
        source="backtest_report",
    )
    return panel(
        ft.Column(
            [
                section_header(
                    "Monthly decision template",
                    "Advisory comparison for basket, canonical benchmark, canonical cash proxy and no-action context; backtest evidence remains descriptive.",
                ),
                ft.Text("\n".join(monthly_decision_template_lines(template)), color=theme.MUTED, selectable=True),
            ],
            spacing=8,
        ),
    )


def _monthly_backtest_alternatives(
    report: object,
    metadata: Mapping[str, object],
    *,
    reference: object = None,
) -> dict[str, object]:
    """Project only return curves actually carried by the backtest report."""

    curves = getattr(report, "equity_curves", None)
    if not isinstance(curves, pd.DataFrame) or curves.empty:
        return {
            name: unavailable_monthly_evidence(f"backtest_monthly_{name}_return_projection_unavailable")
            for name in ("basket", "benchmark", "cash", "no_action")
        }
    if not isinstance(curves.index, pd.DatetimeIndex) or not curves.index.is_monotonic_increasing:
        return {
            name: unavailable_monthly_evidence("backtest_monthly_comparison_window_unsorted")
            for name in ("basket", "benchmark", "cash", "no_action")
        }
    benchmark_data_id = metadata.get("benchmark_data_id")
    if benchmark_data_id is not None and (
        not isinstance(benchmark_data_id, str) or not benchmark_data_id.strip()
    ):
        return {
            name: unavailable_monthly_evidence("backtest_monthly_source_identity_invalid")
            for name in ("basket", "benchmark", "cash", "no_action")
        }
    aliases = {
        "basket": ("basket", "signal_strategy"),
        "benchmark": (benchmark_data_id or "", "benchmark"),
        "cash": ("cash", "cash_proxy"),
        "no_action": ("no_action", "buy_and_hold"),
    }
    columns = {name: next((candidate for candidate in names if candidate and candidate in curves.columns), None) for name, names in aliases.items()}
    if any(column is None for column in columns.values()):
        return {
            name: unavailable_monthly_evidence(
                f"backtest_monthly_{name}_return_projection_unavailable" if columns[name] is None else "backtest_monthly_comparison_window_unavailable"
            )
            for name in columns
        }
    if len(set(columns.values())) != len(columns):
        return {
            name: unavailable_monthly_evidence("backtest_monthly_comparison_identity_ambiguous")
            for name in columns
        }
    selected = curves[[column for column in columns.values() if column is not None]].apply(pd.to_numeric, errors="coerce")
    selected = selected.dropna(how="any")
    if len(selected) < 2 or not selected.index.is_monotonic_increasing:
        return {
            name: unavailable_monthly_evidence("backtest_monthly_comparison_window_unavailable")
            for name in columns
        }
    start = selected.index[0]
    end = selected.index[-1]
    horizon_days = (end - start).total_seconds() / 86400.0
    if not math.isfinite(horizon_days) or horizon_days <= 0:
        return {
            name: unavailable_monthly_evidence("backtest_monthly_comparison_window_invalid")
            for name in columns
        }
    source_id = metadata.get("source_id")
    source_digest = metadata.get("input_checksum")
    source_dataset = metadata.get("source_dataset")
    version = metadata.get("backtest_version")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (source_id, source_dataset, version)
    ) or not isinstance(source_digest, str) or len(source_digest) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in source_digest
    ):
        return {
            name: unavailable_monthly_evidence("backtest_monthly_source_identity_invalid")
            for name in columns
        }
    as_of = _timestamp_text(end)
    known_at = metadata.get("known_at") or metadata.get("decision_time")
    canonical_reference = reference if isinstance(reference, Mapping) else metadata.get("benchmark_reference")
    canonical_reference = canonical_reference if isinstance(canonical_reference, Mapping) else {}
    canonical_references = canonical_reference.get("references")
    canonical_references = canonical_references if isinstance(canonical_references, (list, tuple)) else ()
    canonical_no_action = next(
        (
            item
            for item in canonical_references
            if isinstance(item, Mapping) and item.get("method") == "no_trade"
        ),
        None,
    )
    alternatives: dict[str, object] = {}
    for name, column in columns.items():
        series = selected[column]  # type: ignore[index]
        first_value = float(series.iloc[0])
        last_value = float(series.iloc[-1])
        period_return = float(last_value / first_value - 1.0) if first_value > 0 else float("nan")
        if not math.isfinite(period_return) or period_return < -1:
            alternatives[name] = unavailable_monthly_evidence(f"backtest_monthly_{name}_return_projection_invalid")
            continue
        producer_reference = _monthly_producer_reference(metadata, name)
        reference_fields = producer_reference or {}
        alternatives[name] = {
            "status": "available",
            "version": version,
            "source_id": source_id,
            "source_dataset": source_dataset,
            "source_digest": source_digest,
            "as_of": as_of,
            "known_at": known_at,
            "period_return": period_return,
            "horizon_days": horizon_days,
            "reference_id": reference_fields.get("id"),
            "reference_version": reference_fields.get("version"),
            "reference_content_hash": reference_fields.get("content_hash"),
            "reference_method": "no_trade" if name == "no_action" else None,
            "trust": metadata.get("trust"),
            "source_bound": metadata.get("source_bound"),
            "execution_allowed": False,
        }
        if name in {"benchmark", "cash", "no_action"} and any(
            not alternatives[name].get(field)
            for field in ("reference_id", "reference_version", "reference_content_hash")
        ):
            alternatives[name] = unavailable_monthly_evidence(f"backtest_monthly_{name}_reference_unavailable")
        if name == "no_action" and not _monthly_no_action_binding(
            metadata, reference_fields, canonical_no_action
        ):
            alternatives[name] = unavailable_monthly_evidence("backtest_monthly_no_action_binding_unavailable")
        elif name == "no_action" and isinstance(canonical_no_action, Mapping):
            alternatives[name]["constituent_instrument_ids"] = list(  # type: ignore[index]
                canonical_no_action["constituent_instrument_ids"]
            )
            alternatives[name]["current_weights"] = dict(canonical_no_action["current_weights"])  # type: ignore[index]
    basket = alternatives.get("basket")
    benchmark = alternatives.get("benchmark")
    cash = alternatives.get("cash")
    no_action = alternatives.get("no_action")
    if isinstance(basket, dict) and basket.get("status") == "available":
        if (
            isinstance(benchmark, dict)
            and isinstance(cash, dict)
            and isinstance(no_action, dict)
            and benchmark.get("status") == cash.get("status") == no_action.get("status") == "available"
        ):
            basket["benchmark_relative_return"] = float(basket["period_return"]) - float(benchmark["period_return"])
            basket["cash_relative_return"] = float(basket["period_return"]) - float(cash["period_return"])
            basket["no_action_relative_return"] = float(basket["period_return"]) - float(no_action["period_return"])
        else:
            alternatives["basket"] = unavailable_monthly_evidence("backtest_monthly_basket_relative_evidence_unavailable")
    return alternatives


def _backtest_evidence_bound(metadata: Mapping[str, object]) -> bool:
    source_id = metadata.get("source_id")
    digest = metadata.get("input_checksum")
    known_at = metadata.get("known_at") or metadata.get("decision_time")
    return (
        metadata.get("trust") is True
        and metadata.get("source_bound") is True
        and isinstance(source_id, str)
        and bool(source_id.strip())
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdefABCDEF" for character in digest)
        and isinstance(known_at, str)
        and bool(known_at.strip())
    )


def _backtest_evidence_fields(metadata: Mapping[str, object], suffix: str) -> dict[str, object]:
    if not _backtest_evidence_bound(metadata):
        return {}
    end = metadata.get("date_range_end")
    try:
        as_of = _timestamp_text(pd.Timestamp(end))
    except (TypeError, ValueError):
        return {}
    field_prefix = suffix.replace("-", "_")
    version = metadata.get("backtest_version")
    source_id = metadata.get(f"{field_prefix}_source_id")
    source_dataset = metadata.get(f"{field_prefix}_source_dataset", metadata.get("source_dataset"))
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (version, source_id, source_dataset)
    ):
        return {}
    return {
        "version": version,
        "source_id": source_id,
        "source_dataset": source_dataset,
        "source_digest": metadata.get("input_checksum"),
        "as_of": as_of,
        "known_at": metadata.get("known_at") or metadata.get("decision_time"),
        "trust": True,
        "source_bound": True,
    }


def _monthly_producer_reference(metadata: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Read reference identity carried by the producer; never use the current UI registry."""

    if name == "no_action":
        binding = metadata.get("monthly_no_action_binding", metadata.get("no_action_binding"))
        if isinstance(binding, Mapping) and any(binding.get(field) for field in ("id", "version", "content_hash")):
            return binding
    for key in (f"monthly_{name}_reference", f"{name}_reference"):
        value = metadata.get(key)
        if isinstance(value, Mapping):
            return value
    identity = metadata.get("reference_identity")
    if isinstance(identity, Mapping):
        if name == "no_action":
            references = identity.get("references")
            if isinstance(references, (list, tuple)):
                for value in references:
                    if isinstance(value, Mapping) and value.get("method") == "no_trade":
                        return value
        value = identity.get(name)
        if isinstance(value, Mapping):
            return value
    fields = {
        "id": metadata.get(f"monthly_{name}_reference_id", metadata.get(f"{name}_reference_id")),
        "version": metadata.get(f"monthly_{name}_reference_version", metadata.get(f"{name}_reference_version")),
        "content_hash": metadata.get(
            f"monthly_{name}_reference_content_hash", metadata.get(f"{name}_reference_content_hash")
        ),
        "method": "no_trade" if name == "no_action" else None,
    }
    return fields if any(value not in (None, "") for value in fields.values()) else {}


def _monthly_no_action_binding(
    metadata: Mapping[str, object],
    reference: Mapping[str, object],
    canonical_reference: object,
) -> bool:
    binding = metadata.get("monthly_no_action_binding", metadata.get("no_action_binding"))
    if not isinstance(binding, Mapping):
        binding = metadata
    constituents = binding.get("constituents", binding.get("no_action_constituents"))
    weights = binding.get("weights", binding.get("no_action_weights"))
    if not reference.get("id") or not reference.get("version") or not reference.get("content_hash"):
        return False
    if not isinstance(canonical_reference, Mapping) or any(
        reference.get(field) != canonical_reference.get(field)
        for field in ("id", "version", "content_hash")
    ):
        return False
    if not isinstance(constituents, (list, tuple)) or not constituents:
        return False
    if not isinstance(weights, Mapping) or not weights:
        return False
    if any(not isinstance(constituent, str) or not constituent.strip() for constituent in constituents):
        return False
    if len(set(constituents)) != len(constituents) or set(weights) != set(constituents):
        return False
    values = []
    for constituent in constituents:
        weight = weights.get(constituent)
        if isinstance(weight, bool):
            return False
        try:
            number = float(weight)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(number) or number < 0:
            return False
        values.append(number)
    if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
        return False
    canonical_constituents = canonical_reference.get("constituent_instrument_ids")
    canonical_weights = canonical_reference.get("current_weights")
    if not isinstance(canonical_constituents, (list, tuple)) or not isinstance(canonical_weights, Mapping):
        return False
    if any(not isinstance(item, str) or not item.strip() for item in canonical_constituents):
        return False
    if len(set(canonical_constituents)) != len(canonical_constituents):
        return False
    if tuple(constituents) != tuple(canonical_constituents):
        return False
    if set(weights) != set(canonical_weights):
        return False
    if set(canonical_weights) != set(canonical_constituents):
        return False
    try:
        return all(
            not isinstance(canonical_weights.get(key), bool)
            and math.isfinite(float(canonical_weights[key]))
            and float(canonical_weights[key]) >= 0
            and math.isclose(float(weights[key]), float(canonical_weights[key]), rel_tol=0.0, abs_tol=1e-12)
            for key in weights
        )
    except (KeyError, TypeError, ValueError):
        return False


def _timestamp_text(value: pd.Timestamp) -> str:
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _monthly_backtest_costs(config: object) -> dict[str, object]:
    enabled_ids = list(getattr(getattr(config, "universe", None), "enabled_ids", []) or [])
    instrument_id = str(enabled_ids[0]) if enabled_ids else "unselected"
    try:
        value = cost_capacity_status(config, instrument_id)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
        return unavailable_monthly_evidence("cost_capacity_contract_unavailable")
    return {
        "status": "partial",
        "reason": "single_instrument_preview_is_not_a_basket_cost_projection",
        "model_id": value.get("model_id"),
        "source_id": "cost_capacity_status",
        "components": [
            {
                "instrument_id": value.get("instrument_id"),
                "order_value_eur": value.get("order_preview_eur"),
                "estimated_cost_eur": value.get("estimated_cost_eur"),
                "estimated_cost_bps": value.get("estimated_cost_bps"),
                "data_quality": value.get("data_quality"),
                "execution_allowed": False,
            }
        ],
        "total": {
            "order_value_eur": value.get("order_preview_eur"),
            "cost_eur": value.get("estimated_cost_eur"),
            "cost_bps": value.get("estimated_cost_bps"),
        },
        "capacity": {
            "status": "available" if value.get("capacity_eur") is not None else "unavailable",
            "amount_eur": value.get("capacity_eur"),
            "reason": value.get("capacity_status"),
        },
        "assumptions": list(value.get("assumptions", ())),
        "execution_allowed": False,
    }
def _event_replay_panel() -> ft.Control:
    status = event_engine_status()
    lifecycle = ", ".join(str(item).replace("_", " ") for item in status["lifecycle"])
    order_types = ", ".join(str(item) for item in status["order_types"])
    lines = [
        f"Replay mode: {status['mode']}",
        f"Supported order types: {order_types}",
        f"Lifecycle events: {lifecycle}",
        f"Execution authority: {'enabled' if status['execution_allowed'] else 'disabled'}",
        f"External broker: {status['external_broker']}",
        str(status["message"]),
    ]
    return panel(
        ft.Column(
            [
                section_header("Event timeline, orders and fills", "The order-level historical replay contract is deterministic and shared with future paper/proposal adapters."),
                ft.Text("\n".join(lines), color=theme.MUTED, selectable=True),
            ],
            spacing=8,
        )
    )


def _cost_capacity_panel(config: object) -> ft.Control:
    enabled_ids = list(getattr(getattr(config, "universe", None), "enabled_ids", []) or [])
    instrument_id = str(enabled_ids[0]) if enabled_ids else "unselected"
    try:
        status = cost_capacity_status(config, instrument_id)
    except Exception as exc:
        status = {
            "instrument_id": instrument_id,
            "order_preview_eur": 10_000.0,
            "estimated_cost_bps": None,
            "estimated_cost_eur": None,
            "capacity_eur": None,
            "capacity_status": "unavailable",
            "data_quality": f"unavailable: {exc}",
            "model_id": "unavailable",
            "execution_allowed": False,
            "assumptions": (),
        }
    cost_bps = status.get("estimated_cost_bps")
    cost_eur = status.get("estimated_cost_eur")
    capacity = status.get("capacity_eur")
    lines = [
        f"Instrument: {status.get('instrument_id', instrument_id)}; order preview: EUR {_format_number(status.get('order_preview_eur'), money=True)}",
        f"Estimated cost: {_format_number(cost_bps)} bps / {_format_number(cost_eur, money=True)}",
        f"Capacity: {_format_number(capacity, money=True) if capacity is not None else 'unavailable'} ({status.get('capacity_status', 'unavailable')})",
        f"Data quality: {status.get('data_quality', 'unavailable')}; model: {status.get('model_id', 'unavailable')}",
        f"Execution allowed: {'yes' if status.get('execution_allowed') else 'no'}",
    ]
    return panel(
        ft.Column(
            [
                section_header("Cost/Capacity", "The same local estimate feeds signal netting, rebalance previews and historical backtests; missing microstructure data widens the result."),
                ft.Text("\n".join(lines), color=theme.MUTED, selectable=True),
                ft.Text("Order preview is descriptive evidence only. It does not create, submit or amend an order.", color=theme.AMBER, selectable=True),
            ],
            spacing=8,
        )
    )


def _validation_panel(prices: object, *, reference_context=None) -> ft.Control:
    report = build_validation_preview(prices, reference_context=reference_context)
    if report is None:
        message = "Validation Designer unavailable: local adjusted-price history is insufficient for the configured folds."
    else:
        message = "\n".join(
            [
                f"Protocol: {report.protocol_version} · folds={len(report.folds)} · trials_retained={len(report.trials)}",
                f"Selected={report.selected_trial_id} · final_test_used_for_selection={str(report.final_test_used_for_selection).lower()}",
                f"promotion_eligible={str(report.promotion_eligible).lower()} · pbo={report.probability_of_backtest_overfitting}",
                f"Regimes={len(report.regime_results)} · subgroups={len(report.subgroup_results)} · fingerprint={report.to_dict()['report_fingerprint'][:12]}",
            ]
        )
    return panel(
        ft.Column(
            [
                section_header("Validation Designer and report", "Walk-forward folds purge overlapping labels, embargo future observations and keep the final test untouched for selection."),
                ft.Text(message, color=theme.MUTED if report is not None else theme.AMBER, selectable=True),
            ],
            spacing=8,
        )
    )


def _news_validation_warning() -> ft.Control:
    """Expose rejected point-in-time news without changing backtest results."""

    try:
        frame = pd.read_parquet(NEWS_TIMESTAMP_VALIDATION_PATH) if NEWS_TIMESTAMP_VALIDATION_PATH.exists() else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    if frame.empty or "backtest_eligible" not in frame.columns:
        return panel(ft.Column([section_header("News point-in-time checks", "News is optional context and cannot rescue or alter deterministic backtests."), ft.Text("No invalid news evidence detected; no canonical validation rows are available.", color=theme.MUTED, selectable=True)], spacing=8))
    invalid = frame.loc[~frame["backtest_eligible"].fillna(False).astype(bool)]
    if invalid.empty:
        message = "No invalid news evidence detected; all recorded rows are eligible only where their timestamps and availability are proven."
    else:
        if "timestamp_status" in invalid.columns:
            status_values = invalid["timestamp_status"].fillna("unknown").astype(str).str.strip()
        else:
            status_values = pd.Series("unknown", index=invalid.index)
        status_values = status_values.mask(status_values.eq(""), "unknown")
        statuses = ", ".join(f"{status}={count}" for status, count in status_values.value_counts().sort_index().items())
        message = f"{len(invalid)} news rows are excluded from backtests ({statuses}); rejected evidence remains context-only and requires review."
    return panel(ft.Column([section_header("News point-in-time checks", "Rejected news is visible here and cannot change deterministic backtest authority."), ft.Text(message, color=theme.AMBER if not invalid.empty else theme.MUTED, selectable=True)], spacing=8))


def _equity_drawdown_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=["date", "equity", "drawdown"])
    result = frame.copy()
    result = result.reset_index() if result.index.name else result
    if "date" not in result.columns:
        result = result.rename(columns={result.columns[0]: "date"})
    equity_column = "signal_strategy" if "signal_strategy" in result.columns else next((column for column in result.columns if column != "date"), None)
    if equity_column is None:
        return pd.DataFrame(columns=["date", "equity", "drawdown"])
    result["equity"] = pd.to_numeric(result[equity_column], errors="coerce")
    result["drawdown"] = result["equity"] / result["equity"].cummax() - 1.0
    return result[["date", "equity", "drawdown"]].dropna(subset=["equity"])


def _control_text(control: ft.Control) -> str:
    values: list[str] = []

    def collect(item: object) -> None:
        value = getattr(item, "value", None)
        if value:
            values.append(str(value))
        for child in getattr(item, "controls", ()) or ():
            collect(child)
        content = getattr(item, "content", None)
        if content is not None:
            collect(content)

    collect(control)
    return "\n".join(values)


def backtests_page(page: ft.Page, state: AppState, *, _deferred: bool = False) -> PageView:
    if not _deferred and (isinstance(page, ft.Page) or bool(getattr(page, "_shell_defer_render", False))):
        placeholder = ft.Container(content=Note("Loading backtest evidence..."), expand=True)
        placeholder.data = {"shell.deferred-update": lambda: backtests_page(page, state, _deferred=True)}
        return PageView(
            PageChrome(
                "Backtests",
                "Historical results with their universe, dates, benchmark, rebalance and cost assumptions",
            ),
            placeholder,
        )
    """Present saved backtest results as descriptive, non-authoritative evidence."""
    snapshot = getattr(state, "snapshot", None)
    report = getattr(snapshot, "backtest", None)
    results = getattr(report, "results", None)
    if not isinstance(results, pd.DataFrame):
        results = pd.DataFrame()
    strategy_rows = results.to_dict(orient="records") if not results.empty else []
    signal = next((row for row in strategy_rows if row.get("strategy_name") == "signal_strategy"), {})
    equal_weight = next((row for row in strategy_rows if row.get("strategy_name") == "equal_weight"), {})
    quality = getattr(report, "quality_label", None)
    train_periods = format_count(signal.get("train_periods"), unavailable="Unavailable")
    quality_subtitle = (
        f"Quality label {str(quality).title()} · {train_periods} train periods"
        if quality and train_periods != "Unavailable"
        else "Training-period count is unavailable for this snapshot."
    )
    cagr = signal.get("cagr")
    cagr_text = format_percent(cagr, unavailable="")
    try:
        cagr_number = float(cagr)
    except (TypeError, ValueError):
        cagr_number = None
    cagr_tone = "neg" if cagr_number is not None and math.isfinite(cagr_number) and cagr_number < 0 else "pos" if cagr_number is not None and math.isfinite(cagr_number) and cagr_number > 0 else None
    drawdown_text = format_percent(signal.get("max_drawdown"), unavailable="")
    turnover_text = format_number(signal.get("turnover"), unavailable="")
    added_value = getattr(report, "ai_added_value", None)
    added_value_text = "Yes" if added_value is True else "No" if added_value is False else None
    kpi = KpiStrip(
        "BACKTEST QUALITY",
        str(quality).title() if quality else "Unavailable",
        quality_subtitle if quality else "Backtest quality detail is unavailable.",
        [
            KpiStripItem("Signal strategy CAGR", cagr_text or None, "No saved CAGR is available." if not cagr_text else "", tone=cagr_tone),
            KpiStripItem("Max drawdown", drawdown_text or None, "No saved maximum drawdown is available." if not drawdown_text else "", tone="neg"),
            KpiStripItem("Turnover", turnover_text or None, "No saved turnover result is available." if not turnover_text else ""),
            KpiStripItem("Model-added value", added_value_text, "diagnostic only" if added_value_text is not None else "No saved model-added value result is available."),
        ],
    )
    equity_frame = _equity_drawdown_frame(getattr(report, "equity_curves", None))
    palette = {
        "signal_strategy": theme.CHART_PRIMARY,
        "equal_weight": theme.CHART_SECOND,
        "benchmark": theme.CHART_BENCHMARK,
    }
    equity_insight = (
        f"The strategy returned {format_percent(signal.get('cagr'), unavailable='—')} a year vs "
        f"{format_percent(equal_weight.get('cagr'), unavailable='—')} for equal weight; worst drawdown "
        f"{format_percent(signal.get('max_drawdown'), unavailable='—')}."
        if signal and equal_weight
        else "Unavailable: saved strategy and equal-weight results are needed for the comparison insight."
    )
    def equity_chart_for(frame: pd.DataFrame) -> ft.Control:
        columns = [column for column in frame.columns if column not in {"date", "drawdown"}]
        series = [Series(str(column), frame[column].tolist(), palette.get(str(column), theme.CHART_SECOND)) for column in columns]
        return ck.price_drawdown_chart(
            frame["date"].tolist() if not frame.empty else [],
            series,
            [value * 100 if value is not None else None for value in frame["drawdown"].tolist()] if "drawdown" in frame else [],
            price_name="Equity (index pts)",
            unavailable_reason="No saved equity and drawdown series are available." if not series or frame.empty else None,
            insight=equity_insight,
        )

    equity_chart_holder = ft.Container(content=equity_chart_for(equity_frame), expand=True)
    strategy_keys = (
        ("strategy_name", "Strategy"),
        ("cagr", "CAGR"),
        ("volatility", "Vol"),
        ("sharpe", "Sharpe"),
        ("sortino", "Sortino"),
        ("max_drawdown", "Max DD"),
        ("calmar", "Calmar"),
        ("turnover", "Turnover"),
        ("cost_drag", "Cost drag"),
    )
    strategy_columns = [TableColumn(key, label, numeric=label != "Strategy") for key, label in strategy_keys]
    def normalized_strategy_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        normalized = []
        for row in rows:
            cells = {}
            for key, _ in strategy_keys:
                value = row.get(key)
                if value is None or (isinstance(value, str) and value.strip().casefold() in {"", "none", "null", "nan", "nat"}):
                    cells[key] = None
                    continue
                try:
                    cells[key] = None if pd.isna(value) else value
                except (TypeError, ValueError):
                    cells[key] = value
            normalized.append(cells)
        return normalized

    strategy_rows = sorted(
        normalized_strategy_rows(strategy_rows),
        key=lambda row: str(row.get("strategy_name") or "").casefold(),
    )
    strategy_table = DataTable(
        strategy_columns,
        strategy_rows,
        sort_key="strategy_name",
        empty_title="No strategy results",
        empty_reason="No saved strategy results are available for this snapshot.",
    )
    export_status = Note("CSV export status is unavailable.")
    strategy_body = ft.Column(spacing=8)

    def _search_changed(value: str) -> None:
        query = str(value or "").casefold().strip()
        show_all = query == "all strategies"
        filtered_rows = [
            {key: row.get(key) for key, _ in strategy_keys}
            for row in strategy_rows
            if show_all or query == str(row.get("strategy_name", "")).casefold()
        ]
        strategy_body.controls = [
            search_field,
            DataTable(
                strategy_columns,
                sorted(normalized_strategy_rows(filtered_rows), key=lambda row: str(row.get("strategy_name") or "").casefold()),
                sort_key="strategy_name",
                empty_title="No matching strategy results",
                empty_reason="No saved strategy row matches this search.",
            ),
            Button.secondary(
                "Export strategy results CSV",
                export_strategy_results,
                key="backtests.export-strategy-results",
            ),
            CardMenu([("Export strategy results CSV", export_strategy_results)]),
            Disclosure("Export status", export_status),
        ]
        if callable(getattr(page, "update", None)):
            page.update()

    strategy_names = sorted({str(row.get("strategy_name")) for row in strategy_rows if row.get("strategy_name")})
    search_field = Field(
        "Search strategy results",
        options=["All strategies", *strategy_names],
        value="All strategies",
        on_change=_search_changed,
        key="backtests.strategy-results.search",
    )
    scatter_points = []
    for row in strategy_rows:
        drawdown = row.get("max_drawdown")
        cagr = row.get("cagr")
        if drawdown is None or cagr is None:
            continue
        scatter_points.append(Bubble(str(row.get("strategy_name", "Strategy")), float(drawdown) * 100, float(cagr) * 100, group="strategy"))
    comparison_insight = (
        f"{signal.get('strategy_name', 'Strategy')}: CAGR {format_percent(signal.get('cagr'), unavailable='—')} and maximum drawdown {format_percent(signal.get('max_drawdown'), unavailable='—')}."
        if signal and signal.get("cagr") is not None and signal.get("max_drawdown") is not None
        else "Unavailable: saved CAGR and maximum drawdown values are needed for this comparison."
    )
    comparison_chart = ck.scatter_bubble(
        scatter_points,
        groups=[("strategy", theme.CHART_PRIMARY)],
        x_name="Max drawdown (%)",
        y_name="CAGR (%)",
        x_unit="%",
        y_unit="%",
        unavailable_reason="No saved strategy rows contain both CAGR and maximum drawdown." if not scatter_points else None,
        insight=comparison_insight,
    )
    tail_categories = ["Worst 1-day", "Worst 5-day", "Worst 10-day"]
    tail_values = [value * 100 if value is not None else None for value in (signal.get("worst_1d_return"), signal.get("worst_5d_return"), signal.get("worst_10d_return"))]
    tail_available = [(category, value) for category, value in zip(tail_categories, tail_values, strict=True) if value is not None]
    tail_insight = (
        f"{min(tail_available, key=lambda item: item[1])[0]} returned {format_percent(min(tail_available, key=lambda item: item[1])[1] / 100)}."
        if tail_available
        else "Unavailable: no saved worst-window return is available."
    )
    tail_chart = ck.bar_chart(
        tail_categories,
        tail_values,
        kinds=["neg" if value is not None else "blue" for value in tail_values],
        x_name="Window length (days)",
        y_name="Return (%)",
        unit="%",
        unavailable_reason="No saved worst-window return metrics are available." if not any(value is not None for value in tail_values) else None,
        insight=tail_insight,
    )
    diagnostic_fields = (
        ("Return skew", "skew"),
        ("Open gap warning", "open_gap_warning"),
        ("Payoff profile", "payoff_profile"),
        ("Loss dominance warning", "loss_dominance_warning"),
        ("Overfitting warning", "overfitting_warning"),
        ("Probabilistic Sharpe", "probabilistic_sharpe"),
        ("Deflated Sharpe", "deflated_sharpe"),
        ("PBO probability", "pbo_probability_backtest_overfitting"),
        ("Parameter sensitivity", "parameter_sensitivity_status"),
        ("Largest negative contribution period", "largest_negative_period_return"),
        ("Largest negative contribution periods", "largest_negative_contribution_periods"),
        ("Negative return concentration status", "negative_return_concentration_status"),
        ("Few sessions explain most performance", "few_days_explain_most_performance"),
        ("Losses during high volatility", "losses_during_high_volatility"),
        ("Losses during regime stress", "losses_during_regime_stress"),
    )
    diagnostic_text = "\n".join(f"{label}: {signal.get(key, '—')}" for label, key in diagnostic_fields)
    diagnostic_text += "\nquality-momentum evidence: " + str(getattr(report, "quality_momentum_evidence", "Unavailable"))
    diagnostic_text += "\nExecution delay and next-open evidence remain descriptive; no same-bar execution is implied."
    diagnostic_text += "\nDescriptive payoff profile only; no trade recommendation is derived from payoff profile. execution_allowed=false."
    config = getattr(snapshot, "config", None)
    prices = getattr(snapshot, "prices", None)
    reference_context = None
    if snapshot is not None and config is not None:
        try:
            reference_context = context_from_snapshot(
                snapshot,
                purpose="validation",
                analysis_id=f"validation:{getattr(snapshot, 'universe_revision', 'unknown')}",
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            reference_context = None
    try:
        validation_detail = _control_text(_validation_panel(prices, reference_context=reference_context))
    except (AttributeError, KeyError, TypeError, ValueError):
        validation_detail = "Validation Designer unavailable: no saved validation result is available."
    try:
        news_detail = _control_text(_news_validation_warning())
    except (OSError, ValueError, TypeError):
        news_detail = "Unavailable: local point-in-time validation rows could not be read."
    if config is not None and report is not None and reference_context is not None:
        try:
            monthly_detail = _control_text(_monthly_decision_panel(reference_context, report=report, config=config))
        except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
            monthly_detail = "Monthly decision template unavailable for this snapshot."
    else:
        monthly_detail = "Monthly decision template unavailable for this snapshot."
    enabled_ids = list(getattr(getattr(config, "universe", None), "enabled_ids", ()) or ())
    cost = None
    if enabled_ids:
        try:
            cost = cost_capacity_status(config, str(enabled_ids[0]))
        except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
            cost = None
    cost_reason = "No local cost-capacity result is available for this snapshot."
    order_preview = format_number(cost.get("order_preview_eur"), unavailable="") if cost else ""
    estimated_cost = format_number(cost.get("estimated_cost_eur"), unavailable="") if cost else ""
    cost_card = ft.Column(
        [
            KpiTile("Instrument", cost.get("instrument_id") if cost else None, cost_reason),
            KpiTile("Order preview value", order_preview or None, cost_reason),
            KpiTile("Estimated cost", estimated_cost or None, cost_reason),
            Note("Order preview is descriptive evidence only. It does not create, submit or amend an order."),
        ],
        spacing=8,
    )
    operational = getattr(report, "operational_evidence", None)
    operational_rows = operational.to_dict(orient="records") if isinstance(operational, pd.DataFrame) and not operational.empty else []
    latest_operational_rows = operational_rows
    operational_table = DataTable(
        [TableColumn("status", "Status"), TableColumn("reason", "Reason"), TableColumn("instrument_id", "Instrument"), TableColumn("signal_date", "Signal date"), TableColumn("signal_timestamp", "Signal timestamp"), TableColumn("execution_date", "Execution date")],
        latest_operational_rows,
        empty_title="Instrument operational evidence unavailable",
        empty_reason="No exact-instrument operational rows are available.",
    )
    operational_execution_table = DataTable(
        [TableColumn("execution_timestamp", "Execution timestamp"), TableColumn("decision_price", "Decision price", numeric=True), TableColumn("next_open_reference_price", "Next-open reference", numeric=True), TableColumn("close_to_next_open_gap", "Close-to-next-open gap", numeric=True), TableColumn("observed_range_spread_proxy", "Observed H-L proxy", numeric=True), TableColumn("cost_spread_assumption_bps", "Cost spread bps", numeric=True), TableColumn("estimated_all_in_cost_bps", "Estimated all-in cost bps", numeric=True), TableColumn("evidence_status", "Evidence status"), TableColumn("evidence_reason", "Evidence reason"), TableColumn("fill_source", "Fill source")],
        latest_operational_rows,
        empty_title="Operational execution evidence unavailable",
        empty_reason="No saved operational execution rows are available.",
    )
    trade_log = getattr(report, "trade_log", None)
    trade_rows = trade_log.to_dict(orient="records") if isinstance(trade_log, pd.DataFrame) and not trade_log.empty else []
    replay_columns = [TableColumn("strategy", "Strategy"), TableColumn("date", "Date"), TableColumn("cost_eur", "Cost", numeric=True)]
    if isinstance(trade_log, pd.DataFrame):
        known_columns = {"strategy", "date", "cost_eur"}
        replay_columns.extend(TableColumn(str(column), str(column)) for column in trade_log.columns if str(column) not in known_columns)
    replay_table = DataTable(
        replay_columns,
        trade_rows,
        empty_title="No simulated executions",
        empty_reason="No saved simulated execution rows are available.",
    )
    price_frame = prices if isinstance(prices, pd.DataFrame) else pd.DataFrame()
    price_rows = [
        {
            "date": format_date(row.get("date"), unavailable="—"),
            "etf_id": str(row.get("etf_id")) if row.get("etf_id") is not None and not pd.isna(row.get("etf_id")) else "—",
            "adjusted_close": format_number(row.get("adjusted_close"), unavailable="—"),
        }
        for row in price_frame.to_dict(orient="records")
    ] if not price_frame.empty and {"date", "etf_id", "adjusted_close"}.issubset(price_frame.columns) else []
    price_table = DataTable(
        [TableColumn("date", "Date"), TableColumn("etf_id", "Instrument"), TableColumn("adjusted_close", "Adjusted price", numeric=True)],
        price_rows,
        empty_title="Price history unavailable",
        empty_reason="No local adjusted-price rows are available.",
    )
    def export_backtest(_event: object) -> None:
        result = export_table("backtest_equity_drawdown", equity_frame, EXPORTS_DIR / "backtest_equity_drawdown.csv")
        export_status.value = f"{result.error}" if not result.ok else f"Export complete: {result.destination} ({result.rows} rows)."
        if callable(getattr(page, "update", None)):
            page.update()

    def export_strategy_results(_event: object) -> None:
        result = export_table("backtest_strategy_results", results, EXPORTS_DIR / "backtest_strategy_results.csv")
        export_status.value = f"{result.error}" if not result.ok else f"Export complete: {result.destination} ({result.rows} rows)."
        if callable(getattr(page, "update", None)):
            page.update()

    strategy_body.controls = [
        search_field,
        strategy_table,
        Button.secondary(
            "Export strategy results CSV",
            export_strategy_results,
            key="backtests.export-strategy-results",
        ),
        Disclosure("Export status", export_status),
    ]

    def show_range(value: str) -> None:
        frame = equity_frame
        if value != "All" and not frame.empty and "date" in frame.columns:
            dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
            if dates.notna().any():
                latest = dates.max()
                years = int(value[0])
                start = latest - pd.DateOffset(years=years)
                frame = frame.loc[dates >= start].copy()
        equity_chart_holder.content = equity_chart_for(frame)
        if callable(getattr(page, "update", None)):
            page.update()

    strategy_row = ft.Row(
        [
            GlassCard("Equity and drawdown", note="After costs · index starts at 100 · next-session execution", insight=equity_insight, menu=CardMenu([("Export equity/drawdown CSV", export_backtest)]), body=ft.Column([equity_chart_holder, Button.secondary("Export equity/drawdown CSV", export_backtest, key="backtests.export-equity-drawdown"), Disclosure("Export status", export_status)], spacing=8), expand=True),
            GlassCard("Strategy diagnostics", note="After-cost results vs. baselines", menu=CardMenu([("Export strategy results CSV", export_strategy_results)]), body=strategy_body, expand=True),
        ],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )
    strategy_detail_row = ft.Row(
        [
            GlassCard("CAGR vs. max drawdown", insight=comparison_insight, body=comparison_chart, expand=True),
            GlassCard("Tail-event diagnostics", insight=tail_insight, body=ft.Column([tail_chart, Note("Descriptive / non-causal evidence only; execution_allowed=false."), Disclosure("Tail-event details", diagnostic_text)], spacing=8), expand=True),
            GlassCard("Cost/Capacity", body=cost_card, expand=True),
        ],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )
    instrument_row = ft.Row(
            [
                GlassCard("Instrument operational evidence", body=Disclosure("Operational evidence", operational_table), expand=True),
                GlassCard("Operational execution evidence", body=Disclosure("Execution evidence", operational_execution_table), expand=True),
            ],
        spacing=16,
        visible=False,
    )
    replay_row = ft.Row(
        [
            GlassCard("Simulated executions", body=Disclosure("Execution rows", replay_table), expand=True),
            GlassCard("Event timeline, orders and fills", insight="Unavailable: saved event timeline rows are not available.", body=ck.line_chart([], [], x_name="Date", y_name="Events (count)", unavailable_reason="No saved event timeline rows are available for this replay.", insight="Unavailable: saved event timeline rows are not available."), expand=True),
        ],
        spacing=16,
        visible=False,
    )

    def show_view(value: str) -> None:
        strategy_row.visible = value == "Strategies"
        strategy_detail_row.visible = value == "Strategies"
        instrument_row.visible = value == "Instrument evidence"
        replay_row.visible = value == "Replay"
        if callable(getattr(page, "update", None)):
            page.update()

    body = ft.Column(
        [
            kpi,
            strategy_row,
            strategy_detail_row,
            instrument_row,
            replay_row,
            ft.Row(
                [
                    GlassCard("Validation Designer and report", body=Disclosure("Validation report details", validation_detail), expand=True),
                    GlassCard("Walk-forward and overfitting diagnostics", body=Disclosure("Validation diagnostics", "No saved validation detail is available."), expand=True),
                ],
                spacing=16,
            ),
            ft.Row(
                [
                    GlassCard("News point-in-time checks", body=Disclosure("Point-in-time check details", news_detail), expand=True),
                    GlassCard("Monthly decision template", body=Disclosure("Monthly decision details", monthly_detail), expand=True),
                    GlassCard("Price history evidence", body=Disclosure("Price history rows", price_table), expand=True),
                ],
                spacing=16,
            ),
            Note("Backtest logs are written to data/backtests/ for audit. Diagnostics are local deterministic estimates, not proof of future performance."),
            Disclosure("Operational execution evidence", str(latest_operational_rows) if latest_operational_rows else "No exact operational evidence is available."),
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        chrome=PageChrome(
            "Backtests",
            "Historical results with their universe, dates, benchmark, rebalance and cost assumptions",
            (
                SegmentGroup("backtests-view", ("Strategies", "Instrument evidence", "Replay"), "Strategies", on_change=show_view),
                SegmentGroup("backtests-range", ("1Y", "3Y", "5Y", "All"), "All", on_change=show_range),
            ),
        ),
        body=body,
    )
