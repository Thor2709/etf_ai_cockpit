from __future__ import annotations

from collections.abc import Mapping
import math

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.charts import equity_drawdown_chart, history_chart
from etf_cockpit.app.components.tables import accessible_table
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


def _format_number(value: object, *, percent: bool = False, money: bool = False, decimals: int = 2) -> str:
    if value is None or value != value:
        return "n/a"
    number = float(value)
    if money:
        return f"EUR {number:,.0f}"
    if percent:
        return f"{number:.1%}"
    return f"{number:.{decimals}f}"


def backtests_page(_page: ft.Page, state: AppState) -> ft.Control:
    report = state.snapshot.backtest
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
                        spacing=10,
                    )
                )
            ],
            expand=True,
            spacing=14,
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
                        spacing=10,
                    )
                )
            ],
            expand=True,
            spacing=14,
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
        f"Expected value per period: {_format_number(signal.get('expected_value_per_period'), percent=True)}",
        f"Payoff warning: {signal.get('payoff_asymmetry_warning', 'n/a')}",
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
        f"Worst 1-day return: {_format_number(signal.get('worst_1d_return'), percent=True)}",
        f"Worst 5-day return: {_format_number(signal.get('worst_5d_return'), percent=True)}",
        f"Worst 10-day return: {_format_number(signal.get('worst_10d_return'), percent=True)}",
        f"Worst drawdown window: {signal.get('worst_drawdown_start', 'n/a')} to {signal.get('worst_drawdown_end', 'n/a')}",
        f"Maximum consecutive loss periods: {signal.get('loss_cluster_max_days', 'n/a')}",
        f"Largest negative period: {_format_number(signal.get('largest_negative_period_return'), percent=True)}",
    ]
    operational_evidence = [
        f"Signal timestamp: {report.metadata.get('lookahead_protection', 'n/a')}",
        f"Execution delay: {report.metadata.get('execution_delay_sessions', 'n/a')} complete session",
        f"Same-bar execution avoided: {'yes' if report.metadata.get('same_bar_execution_avoided') else 'no'}",
        "Decision price and next-open reference are shown in the simulated execution table.",
        "No forward-fill is applied to incomplete adjusted-price rows.",
    ]
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
                    spacing=6,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Operational execution evidence", "Quality-momentum uses point-in-time evidence and next-session simulation; decision-price assumptions are descriptive only and same-bar execution is forbidden."),
                        ft.Text("\n".join(operational_evidence), color=theme.MUTED, selectable=True),
                    ],
                    spacing=6,
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
        spacing=14,
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
            spacing=6,
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
            spacing=6,
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
            spacing=6,
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
            spacing=6,
        )
    )


def _news_validation_warning() -> ft.Control:
    """Expose rejected point-in-time news without changing backtest results."""

    try:
        frame = pd.read_parquet(NEWS_TIMESTAMP_VALIDATION_PATH) if NEWS_TIMESTAMP_VALIDATION_PATH.exists() else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    if frame.empty or "backtest_eligible" not in frame.columns:
        return panel(ft.Column([section_header("News point-in-time checks", "News is optional context and cannot rescue or alter deterministic backtests."), ft.Text("No invalid news evidence detected; no canonical validation rows are available.", color=theme.MUTED, selectable=True)], spacing=6))
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
    return panel(ft.Column([section_header("News point-in-time checks", "Rejected news is visible here and cannot change deterministic backtest authority."), ft.Text(message, color=theme.AMBER if not invalid.empty else theme.MUTED, selectable=True)], spacing=6))


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
