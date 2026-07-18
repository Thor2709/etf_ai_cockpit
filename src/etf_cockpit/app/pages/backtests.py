from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.charts import equity_drawdown_chart, history_chart
from etf_cockpit.app.components.tables import accessible_table
from etf_cockpit.app.state import AppState
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
    validation_panel = _validation_panel(getattr(state.snapshot, "prices", None))
    event_panel = _event_replay_panel()
    cost_panel = _cost_capacity_panel(state.snapshot.config)
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
                            validation_panel,
                            event_panel,
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
                            cost_panel,
                            event_panel,
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
            panel(
                ft.Column(
                    [
                        section_header("Strategy diagnostics", "After-cost results versus buy-and-hold, equal-weight, momentum-only and trend-only baselines."),
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
                        section_header("Operational execution evidence", "Decision-price and next-open assumptions are descriptive evidence only; same-bar execution is forbidden."),
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


def _validation_panel(prices: object) -> ft.Control:
    report = build_validation_preview(prices)
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
