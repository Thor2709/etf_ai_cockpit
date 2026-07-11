from __future__ import annotations

import pandas as pd
import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.reference_data import load_reference_dataset
from etf_cockpit.portfolio.allocation import allocation_frame, exposure_summary
from etf_cockpit.portfolio.risk_analytics import drawdown_contribution, exposure_limit_report, return_correlation_matrix, underlying_holdings_exposure


def _pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.1%}"


def _number(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.2f}"


def _status_colour(status: str) -> str:
    if status == "breach":
        return theme.RED
    if status == "watch":
        return theme.AMBER
    if status == "ok":
        return theme.GREEN
    return theme.MUTED


def _exposure_table(title: str, frame: pd.DataFrame) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.iloc[0]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["current_weight"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["target_weight"]), color=theme.MUTED, size=12)),
            ]
        )
        for _, row in frame.iterrows()
    ]
    return panel(
        ft.Column(
            [
                ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Bucket")), ft.DataColumn(ft.Text("Current")), ft.DataColumn(ft.Text("Target"))],
                    rows=rows,
                    data_row_min_height=32,
                    data_row_max_height=38,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _underlying_holdings_panel(holdings: pd.DataFrame, allocation: pd.DataFrame) -> ft.Control:
    if holdings.empty:
        return panel(
            ft.Column(
                [
                    section_header("Underlying holdings context", "Optional look-through data for ETFs."),
                    ft.Text("No look-through holdings file has been imported yet.", color=theme.MUTED),
                ]
            )
        )
    sector = underlying_holdings_exposure(allocation, holdings, "sector")
    region = underlying_holdings_exposure(allocation, holdings, "region")
    currency = underlying_holdings_exposure(allocation, holdings, "currency")
    return panel(
        ft.Column(
            [
                section_header("Underlying holdings context", "Portfolio-weighted exposure from imported look-through holdings; latest holding date per instrument."),
                ft.Row(
                    [
                        _compact_exposure_table("Sector", sector),
                        _compact_exposure_table("Region", region),
                        _compact_exposure_table("Currency", currency),
                    ],
                    spacing=12,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _compact_exposure_table(title: str, frame: pd.DataFrame) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.iloc[0]), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_pct(row["current_weight"]), color=theme.TEXT, size=11)),
            ]
        )
        for _, row in frame.head(8).iterrows()
    ]
    return ft.Column(
        [
            ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD),
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text("Bucket")), ft.DataColumn(ft.Text("Current"))],
                rows=rows,
                data_row_min_height=28,
                data_row_max_height=34,
            )
            if rows
            else ft.Text("No mapped holdings.", color=theme.MUTED, size=12),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _limit_table(report: pd.DataFrame) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row["risk_type"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(str(row["bucket"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["current_weight"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["limit"]), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(_pct(row["headroom"]), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(str(row["status"]).upper(), color=_status_colour(str(row["status"])), size=12, weight=ft.FontWeight.BOLD)),
            ]
        )
        for _, row in report.iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("Portfolio guardrail context", "Breaches are shown as construction context. Data-quality failures remain hard blockers."),
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Type")),
                        ft.DataColumn(ft.Text("Bucket")),
                        ft.DataColumn(ft.Text("Current")),
                        ft.DataColumn(ft.Text("Limit")),
                        ft.DataColumn(ft.Text("Headroom")),
                        ft.DataColumn(ft.Text("Status")),
                    ],
                    rows=rows,
                    data_row_min_height=34,
                    data_row_max_height=42,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _correlation_table(correlation: pd.DataFrame) -> ft.Control:
    columns = list(correlation.columns)
    rows = []
    for etf_id, row in correlation.iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(etf_id), color=theme.TEXT, size=11)),
                    *[ft.DataCell(ft.Text(_number(row[column]), color=theme.TEXT, size=11)) for column in columns],
                ]
            )
        )
    return panel(
        ft.Column(
            [
                section_header("Correlation matrix", "120 trading-day log-return correlation from adjusted prices; no forward-fill."),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Instrument"))] + [ft.DataColumn(ft.Text(str(column))) for column in columns],
                    rows=rows,
                    data_row_min_height=30,
                    data_row_max_height=36,
                )
                if rows
                else ft.Text("Not enough complete price history for correlation.", color=theme.MUTED),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _drawdown_table(contribution: pd.DataFrame) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row["etf_id"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["current_weight"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["drawdown_current"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["drawdown_60d_max"]), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(_pct(row["drawdown_contribution"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(_pct(row["risk_share"]), color=theme.TEXT, size=12)),
            ]
        )
        for _, row in contribution.iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("Drawdown contribution", "Weighted current and recent drawdown context."),
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Instrument")),
                        ft.DataColumn(ft.Text("Weight")),
                        ft.DataColumn(ft.Text("Current DD")),
                        ft.DataColumn(ft.Text("Worst 60d DD")),
                        ft.DataColumn(ft.Text("Weighted DD")),
                        ft.DataColumn(ft.Text("Risk Share")),
                    ],
                    rows=rows,
                    data_row_min_height=34,
                    data_row_max_height=42,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def risk_page(_page: ft.Page, state: AppState) -> ft.Control:
    allocation = allocation_frame(state.snapshot.config, state.snapshot.holdings)
    limit_report = exposure_limit_report(state.snapshot.config, allocation)
    breaches = int((limit_report["status"] == "breach").sum()) if not limit_report.empty else 0
    watch = int((limit_report["status"] == "watch").sum()) if not limit_report.empty else 0
    correlation = return_correlation_matrix(state.snapshot.prices, state.snapshot.config.universe.enabled_ids, window=120)
    contribution = drawdown_contribution(allocation, state.snapshot.latest_features)
    imported_holdings = load_reference_dataset("etf_holdings")
    top_contributor = contribution.iloc[0]["etf_id"] if not contribution.empty else "n/a"
    return ft.Column(
        [
            ft.Row(
                [
                    metric_card("Data status", state.snapshot.data_report.status, f"{len(state.snapshot.data_report.issues)} data/context findings", theme.RED if state.snapshot.data_report.status == "Blocked" else theme.AMBER if state.snapshot.data_report.issues else theme.GREEN),
                    metric_card("Portfolio guardrails", str(breaches), f"{watch} watch items", theme.RED if breaches else theme.AMBER if watch else theme.GREEN),
                    metric_card("Top DD contributor", str(top_contributor), "Weighted current drawdown"),
                    metric_card("Correlation window", "120d", "Adjusted-price log returns"),
                ],
                spacing=12,
            ),
            _limit_table(limit_report),
            ft.Row(
                [
                    _exposure_table("Asset Class Exposure", exposure_summary(allocation, "asset_class")),
                    _exposure_table("Region Exposure", exposure_summary(allocation, "region")),
                    _exposure_table("Currency Exposure", exposure_summary(allocation, "currency")),
                ],
                spacing=12,
            ),
            ft.Row(
                [
                    _exposure_table("Sector Exposure", exposure_summary(allocation, "sector")),
                    _exposure_table("Theme Exposure", exposure_summary(allocation, "theme")),
                ],
                spacing=12,
            ),
            _underlying_holdings_panel(imported_holdings, allocation),
            _correlation_table(correlation),
            _drawdown_table(contribution),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
