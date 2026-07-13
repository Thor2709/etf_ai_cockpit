from __future__ import annotations

import pandas as pd
import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH, normalise_holdings
from etf_cockpit.data.trust_artifacts import CORRELATION_CLUSTERS_PATH, BENCHMARK_ATTRIBUTION_PATH
from etf_cockpit.data.reference_data import load_reference_dataset
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.portfolio.allocation import allocation_frame, exposure_summary
from etf_cockpit.portfolio.risk_analytics import drawdown_contribution, exposure_limit_report, return_correlation_matrix, underlying_holdings_exposure

SCOREBOARD_PATH = DERIVED_DIR / "scoreboard.parquet"


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


def _holdings_quality_panel(holdings: pd.DataFrame) -> ft.Control:
    """Show the evidence quality cap separately from portfolio exposure."""
    if holdings.empty or not {"instrument_id", "completeness"}.issubset(holdings.columns):
        return panel(
            ft.Column(
                [
                    section_header("ETF holdings evidence", "Completeness and freshness determine whether look-through exposure is current."),
                    ft.Text("No normalised holdings evidence is available; current exposure remains unavailable.", color=theme.MUTED),
                ]
            )
        )
    columns = [column for column in ("instrument_id", "as_of_date", "completeness", "freshness", "confidence", "authority", "score_eligible") if column in holdings.columns]
    rows = [
        ft.DataRow(cells=[ft.DataCell(ft.Text(str(row.get(column, "")), color=theme.TEXT if column in {"instrument_id", "completeness"} else theme.MUTED, size=11, selectable=True)) for column in columns])
        for _, row in holdings.drop_duplicates(subset=["instrument_id"]).iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("ETF holdings evidence", "Issuer full/current holdings can support exposure; vendor partial, stale and invalid rows remain context-only."),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text(column, color=theme.TEXT, size=11)) for column in columns],
                    rows=rows,
                )
                if rows
                else ft.Text("No normalised holdings evidence is available; current exposure remains unavailable.", color=theme.MUTED),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )


def _load_holdings_evidence() -> pd.DataFrame:
    canonical = pd.DataFrame()
    try:
        if FUND_HOLDINGS_PATH.exists():
            canonical = pd.read_parquet(FUND_HOLDINGS_PATH)
    except Exception:
        canonical = pd.DataFrame()
    legacy = load_reference_dataset("etf_holdings")
    if legacy.empty or not {"etf_id", "weight"}.issubset(legacy.columns):
        return canonical if not canonical.empty else legacy
    # Reference-data imports pre-date the normalised fund store. Adapt them in
    # memory so existing holdings remain visible while issuer/vendor and
    # freshness eligibility are still enforced by the normaliser.
    rows: list[pd.DataFrame] = []
    for etf_id, group in legacy.groupby("etf_id", dropna=False):
        as_of = group.get("as_of_date", pd.Series(dtype=str)).dropna()
        as_of_value = str(as_of.max().date()) if not as_of.empty and hasattr(as_of.max(), "date") else str(as_of.max()) if not as_of.empty else ""
        source = str(group.get("source", pd.Series(["legacy_import"])).iloc[0])
        adapted = normalise_holdings(group, str(etf_id), as_of_value, source)
        if not adapted.frame.empty:
            rows.append(adapted.frame)
    legacy_context = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if canonical.empty:
        return legacy_context
    if legacy_context.empty:
        return canonical
    return pd.concat([canonical, legacy_context], ignore_index=True, sort=False)


def _exposure_eligible_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    required = {"score_eligible", "authority", "freshness", "completeness"}
    if holdings.empty or not required.issubset(holdings.columns):
        return pd.DataFrame(columns=holdings.columns)
    eligible = holdings.copy()
    eligible = eligible[
        eligible["score_eligible"].map(_as_bool)
        & eligible["authority"].astype(str).str.strip().str.lower().eq("issuer")
        & eligible["freshness"].astype(str).str.strip().str.lower().eq("fresh")
        & eligible["completeness"].astype(str).str.strip().str.lower().eq("full")
    ]
    if "as_of_date" in eligible.columns:
        as_of = pd.to_datetime(eligible["as_of_date"], errors="coerce")
        eligible = eligible[as_of.notna() & (as_of.dt.date <= pd.Timestamp.now(tz="UTC").date())]
    return eligible


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


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


def _crowding_attribution_panel() -> ft.Control:
    try:
        crowding = pd.read_parquet(CORRELATION_CLUSTERS_PATH) if CORRELATION_CLUSTERS_PATH.exists() else pd.DataFrame()
    except Exception:
        crowding = pd.DataFrame()
    try:
        attribution = pd.read_parquet(BENCHMARK_ATTRIBUTION_PATH) if BENCHMARK_ATTRIBUTION_PATH.exists() else pd.DataFrame()
    except Exception:
        attribution = pd.DataFrame()
    if crowding.empty and attribution.empty:
        return panel(ft.Column([section_header("Crowding and attribution", "Trust evidence from clean adjusted-price returns."), ft.Text("Correlation and benchmark attribution evidence is unavailable; no cluster or sector-relative conclusion is inferred.", color=theme.MUTED)]))
    warnings = crowding[crowding.get("crowding_warning", pd.Series(dtype=str)).astype(str).str.contains("warning", na=False)] if not crowding.empty else pd.DataFrame()
    sector_available = int((attribution.get("sector_attribution_status", pd.Series(dtype=str)).astype(str) == "available").sum()) if not attribution.empty else 0
    theme_available = int((attribution.get("theme_attribution_status", pd.Series(dtype=str)).astype(str) == "available").sum()) if not attribution.empty else 0
    broad_available = int(
        pd.to_numeric(attribution.get("benchmark_return", pd.Series(dtype=float)), errors="coerce").notna().sum()
    ) if not attribution.empty else 0
    risk_contribution = pd.to_numeric(crowding.get("cluster_risk_contribution", pd.Series(dtype=float)), errors="coerce") if not crowding.empty else pd.Series(dtype=float)
    top_contribution = float(risk_contribution.max()) if not risk_contribution.dropna().empty else None
    coverage = pd.to_numeric(crowding.get("ranking_coverage", pd.Series(dtype=float)), errors="coerce") if not crowding.empty else pd.Series(dtype=float)
    mean_coverage = float(coverage.mean()) if not coverage.dropna().empty else None
    return panel(ft.Column([
        section_header("Crowding and attribution", "Configured metadata and clean adjusted-price evidence; diagnostics are descriptive and non-executable."),
        ft.Text(f"Clusters with warnings: {len(warnings)} | highest cluster risk contribution: {_number(top_contribution)} | mean ranking coverage: {_number(mean_coverage)} | execution_allowed=false", color=theme.MUTED, selectable=True),
        ft.Text(f"Broad benchmark attribution: {broad_available} rows available | Sector attribution: {sector_available} rows available | Theme attribution: {theme_available} rows available | horizons use clean overlapping returns; unavailable or insufficient evidence is N/A.", color=theme.MUTED, selectable=True),
    ]))


def _friction_edge_panel() -> ft.Control:
    """Show persisted gross/net edge and cost scenarios as risk evidence."""

    try:
        scoreboard = pd.read_parquet(SCOREBOARD_PATH) if SCOREBOARD_PATH.exists() else pd.DataFrame()
    except Exception:
        scoreboard = pd.DataFrame()
    required = {"gross_expected_edge_bps", "estimated_total_cost_bps", "net_expected_edge_bps", "edge_to_cost_ratio", "cost_stress_scenario"}
    id_column = next((column for column in ("display_id", "instrument_id", "etf_id") if column in scoreboard.columns), None)
    if scoreboard.empty or id_column is None or not required.issubset(scoreboard.columns):
        return panel(
            ft.Column(
                [
                    section_header("Expected edge and trading costs", "Gross/net edge, estimated cost, ratio and stress scenario are descriptive evidence only."),
                    ft.Text("Expected edge and cost evidence unavailable; no scenario conclusion is inferred.", color=theme.MUTED, selectable=True),
                ]
            )
        )

    def _bps(value: object) -> str:
        try:
            return f"{float(value):.2f} bps"
        except (TypeError, ValueError):
            return "N/A"

    def _ratio(value: object) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "N/A"

    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.get(id_column, "N/A")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_bps(row.get("gross_expected_edge_bps")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_bps(row.get("estimated_total_cost_bps")), color=theme.MUTED, size=11)),
                ft.DataCell(ft.Text(_bps(row.get("net_expected_edge_bps")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_ratio(row.get("edge_to_cost_ratio")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(str(row.get("cost_stress_scenario") or "unavailable"), color=theme.MUTED, size=11)),
            ]
        )
        for _, row in scoreboard.iterrows()
    ]
    summary = [
        f"{row.get(id_column, 'N/A')}: Gross edge {_bps(row.get('gross_expected_edge_bps'))} | Estimated cost {_bps(row.get('estimated_total_cost_bps'))} | Net edge {_bps(row.get('net_expected_edge_bps'))} | Edge/cost {_ratio(row.get('edge_to_cost_ratio'))} | Cost scenario: {row.get('cost_stress_scenario') or 'unavailable'}"
        for _, row in scoreboard.iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("Expected edge and trading costs", "Gross/net edge, estimated cost, ratio and stress scenario are descriptive evidence only."),
                *[ft.Text(line, color=theme.MUTED, size=11, selectable=True) for line in summary],
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text(column, color=theme.TEXT, size=11)) for column in ("Instrument", "Gross edge", "Estimated cost", "Net edge", "Edge/cost", "Cost scenario")],
                    rows=rows,
                ),
                ft.Text("execution_allowed=false", color=theme.MUTED, size=11),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
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
    imported_holdings = _load_holdings_evidence()
    eligible_holdings = _exposure_eligible_holdings(imported_holdings)
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
            _holdings_quality_panel(imported_holdings),
            _underlying_holdings_panel(eligible_holdings, allocation),
            _correlation_table(correlation),
            _crowding_attribution_panel(),
            _friction_edge_panel(),
            _drawdown_table(contribution),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
