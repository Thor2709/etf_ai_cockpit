from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.state import AppState


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
    if report.results.empty or "strategy_name" not in report.results.columns:
        return ft.Column(
            [
                panel(
                    ft.Column(
                        [
                            section_header("Backtests", "Run Refresh yfinance data and Run algorithms before backtests can be evaluated for the current two-tier universe."),
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
    rows = []
    for _, row in report.results.iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(row["strategy_name"], color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['cagr']:.1%}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['volatility']:.1%}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['sharpe']:.2f}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['sortino']:.2f}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['max_drawdown']:.1%}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['calmar']:.2f}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row['turnover']:.2f}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"EUR {row['cost_drag']:.2f}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(int(row["n_walk_forward_periods"])), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(int(row["trade_count"])), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_format_number(row.get("return_hit_rate"), percent=True), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_format_number(row.get("payoff_ratio")), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_format_number(row.get("expected_value_per_period"), percent=True), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(row.get("payoff_asymmetry_warning", "n/a")), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_format_number(row["average_trade_eur"], money=True), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_format_number(row["turnover_annualised"]), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_format_number(row["worst_12m_return"], percent=True), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(row["backtest_quality"]), color=theme.TEXT, size=12)),
                ]
            )
        )
    signal_rows = report.results[report.results["strategy_name"] == "signal_strategy"]
    if signal_rows.empty:
        return ft.Column(
            [
                panel(
                    ft.Column(
                        [
                            section_header("Backtests", "No signal-strategy backtest row is available for the current run."),
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
            panel(
                ft.Column(
                    [
                        section_header("Strategy diagnostics", "After-cost results versus buy-and-hold, equal-weight, momentum-only and trend-only baselines."),
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Strategy")),
                                ft.DataColumn(ft.Text("CAGR")),
                                ft.DataColumn(ft.Text("Vol")),
                                ft.DataColumn(ft.Text("Sharpe")),
                                ft.DataColumn(ft.Text("Sortino")),
                                ft.DataColumn(ft.Text("Max DD")),
                                ft.DataColumn(ft.Text("Calmar")),
                                ft.DataColumn(ft.Text("Turnover")),
                                ft.DataColumn(ft.Text("Costs")),
                                ft.DataColumn(ft.Text("WF periods")),
                                ft.DataColumn(ft.Text("Trades")),
                                ft.DataColumn(ft.Text("Hit rate")),
                                ft.DataColumn(ft.Text("Payoff")),
                                ft.DataColumn(ft.Text("EV/period")),
                                ft.DataColumn(ft.Text("Payoff warning")),
                                ft.DataColumn(ft.Text("Avg trade")),
                                ft.DataColumn(ft.Text("Ann turnover")),
                                ft.DataColumn(ft.Text("Worst 12m")),
                                ft.DataColumn(ft.Text("Quality")),
                            ],
                            rows=rows,
                        ),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
            ),
            panel(ft.Column([section_header("Backtest quality", "Walk-forward and overfitting diagnostics for the scoring method."), ft.Text("\n".join(diagnostics), color=theme.MUTED, selectable=True)])),
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
            panel(ft.Text("Backtest logs are written to data/backtests/ for audit. Diagnostics are local deterministic estimates, not proof of future performance.", color=theme.MUTED, selectable=True)),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
