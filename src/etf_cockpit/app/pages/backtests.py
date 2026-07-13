from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.charts import equity_drawdown_chart
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import EXPORTS_DIR
from etf_cockpit.data.export_tables import export_table
from etf_cockpit.data.trust_artifacts import NEWS_TIMESTAMP_VALIDATION_PATH


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
    if report.results.empty or "strategy_name" not in report.results.columns:
        return ft.Column(
            [
                panel(
                    ft.Column(
                        [
                            section_header("Backtests", "Run Refresh yfinance data and Run algorithms before backtests can be evaluated for the current two-tier universe."),
                            news_warning,
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
    equity_frame = _equity_drawdown_frame(report.equity_curves)
    chart_descriptor = equity_drawdown_chart(equity_frame)
    export_status = ft.Text("CSV exports show the destination path and controlled failure state.", color=theme.MUTED, selectable=True)

    def export_backtest(_event: ft.ControlEvent) -> None:
        result = export_table("backtest_equity_drawdown", equity_frame, EXPORTS_DIR / "backtest_equity_drawdown.csv")
        if result.ok:
            export_status.value = f"Export complete: {result.destination} ({result.rows} rows)."
        else:
            export_status.value = f"Export failed: {result.error}; previous output preserved."
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
            panel(ft.Column([section_header("Equity and drawdown evidence", "The curve is descriptive backtest evidence only; it cannot authorise broker execution."), chart_descriptor.control, ft.Row([ft.OutlinedButton("Export equity/drawdown CSV", key="backtests.export-equity-drawdown", icon=ft.Icons.DOWNLOAD, on_click=export_backtest)]), export_status], spacing=8)),
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
