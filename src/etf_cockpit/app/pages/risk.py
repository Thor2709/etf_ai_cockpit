from __future__ import annotations

import math
import os
from pathlib import Path

import pandas as pd
import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.simple_scores import _is_crowding_warning_state
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    BENCHMARK_ATTRIBUTION_PATH,
    CORRELATION_CLUSTERS_PATH,
    FUND_HOLDINGS_PATH,
    allocation_frame,
    build_factor_risk_report,
    drawdown_contribution,
    exposure_limit_report,
    exposure_summary,
    export_table,
    load_reference_dataset,
    normalise_holdings,
    return_correlation_matrix,
    underlying_holdings_exposure,
)
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.core.paths import EXPORTS_DIR

SCOREBOARD_PATH = DERIVED_DIR / "scoreboard.parquet"


def _pct(value: object) -> str:
    number = _finite_float(value)
    return "n/a" if number is None else f"{number:.1%}"


def _number(value: object) -> str:
    number = _finite_float(value)
    return "n/a" if number is None else f"{number:.2f}"


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
    unique_rows = holdings.drop_duplicates(subset=["instrument_id"])
    rows = [
        ft.DataRow(cells=[ft.DataCell(ft.Text(str(row.get(column, "")), color=theme.TEXT if column in {"instrument_id", "completeness"} else theme.MUTED, size=11)) for column in columns])
        for _, row in unique_rows.iterrows()
    ]
    summaries = [
        f"{row.get('instrument_id', 'N/A')}: as_of {row.get('as_of_date', 'N/A')} | completeness={row.get('completeness', 'N/A')} | freshness={row.get('freshness', 'N/A')} | confidence={row.get('confidence', 'N/A')} | authority={row.get('authority', 'N/A')} | score_eligible={row.get('score_eligible', 'N/A')}"
        for _, row in unique_rows.iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("ETF holdings evidence", "Issuer full/current holdings can support exposure; vendor partial, stale and invalid rows remain context-only."),
                *[ft.Text(summary, color=theme.MUTED, size=11) for summary in summaries],
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


def _refresh_holdings_freshness(holdings: pd.DataFrame, *, stale_after_days: int = 90) -> pd.DataFrame:
    """Recompute persisted holding freshness before rendering or scoring."""

    if holdings.empty or "as_of_date" not in holdings.columns:
        return holdings
    refreshed = holdings.copy()
    as_of = pd.to_datetime(refreshed["as_of_date"], errors="coerce", utc=True)
    today = pd.Timestamp.now(tz="UTC").normalize()
    age_days = (today - as_of.dt.normalize()).dt.days
    invalid = as_of.isna()
    stale = as_of.notna() & age_days.gt(max(0, int(stale_after_days)))
    future = as_of.notna() & age_days.lt(0)
    if "freshness" in refreshed.columns:
        refreshed.loc[invalid, "freshness"] = "invalid"
        refreshed.loc[stale, "freshness"] = "stale"
        refreshed.loc[future, "freshness"] = "invalid"
    if "completeness" in refreshed.columns:
        refreshed.loc[invalid, "completeness"] = "invalid"
        full_stale = stale & refreshed["completeness"].astype(str).str.strip().str.lower().eq("full")
        refreshed.loc[full_stale, "completeness"] = "stale"
    if "score_eligible" in refreshed.columns:
        refreshed.loc[invalid | stale | future, "score_eligible"] = False
    if "confidence" in refreshed.columns:
        confidence = pd.to_numeric(refreshed["confidence"], errors="coerce")
        refreshed.loc[invalid, "confidence"] = 0.0
        refreshed.loc[stale, "confidence"] = confidence.loc[stale].clip(upper=0.25)
        refreshed.loc[future, "confidence"] = 0.0
    return refreshed


def _holdings_file_candidates() -> tuple[Path, ...]:
    """Return canonical holdings paths, including the runtime portable root."""

    candidates = [FUND_HOLDINGS_PATH]
    env_root = os.getenv("ETF_COCKPIT_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root) / "data" / "clean" / "fund_holdings.parquet")
    candidates.append(Path.cwd() / "data" / "clean" / "fund_holdings.parquet")
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def _load_holdings_evidence() -> pd.DataFrame:
    canonical = pd.DataFrame()
    for holdings_path in _holdings_file_candidates():
        try:
            csv_path = holdings_path.with_suffix(".csv")
            if not holdings_path.exists() and not csv_path.exists():
                continue
            try:
                canonical = pd.read_parquet(holdings_path)
            except Exception:
                # Portable builds may have a usable CSV mirror even when the
                # optional parquet engine cannot load a bundled binary.
                if csv_path.exists():
                    canonical = pd.read_csv(csv_path)
            if canonical.empty:
                if csv_path.exists():
                    canonical = pd.read_csv(csv_path)
            if not canonical.empty:
                break
        except Exception:
            canonical = pd.DataFrame()
    legacy = load_reference_dataset("etf_holdings")
    if legacy.empty or not {"etf_id", "weight"}.issubset(legacy.columns):
        return _refresh_holdings_freshness(canonical if not canonical.empty else legacy)
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
        return _refresh_holdings_freshness(legacy_context)
    if legacy_context.empty:
        return _refresh_holdings_freshness(canonical)
    return _refresh_holdings_freshness(pd.concat([canonical, legacy_context], ignore_index=True, sort=False))


def _exposure_eligible_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    required = {"score_eligible", "authority", "freshness", "completeness"}
    if holdings.empty or not required.issubset(holdings.columns):
        return pd.DataFrame(columns=holdings.columns)
    eligible = _refresh_holdings_freshness(holdings)
    eligible = eligible[
        eligible["score_eligible"].map(_as_bool)
        & eligible["authority"].astype(str).str.strip().str.lower().eq("issuer")
        & eligible["freshness"].astype(str).str.strip().str.lower().eq("fresh")
        & eligible["completeness"].astype(str).str.strip().str.lower().eq("full")
    ]
    if "as_of_date" in eligible.columns:
        as_of = pd.to_datetime(eligible["as_of_date"], errors="coerce", utc=True)
        today = pd.Timestamp.now(tz="UTC").normalize()
        valid_as_of = as_of.notna() & as_of.le(today)
        eligible = eligible[valid_as_of]
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


def _factor_summary_panel(report: dict[str, object]) -> ft.Control:
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
    lookthrough = coverage.get("lookthrough") if isinstance(coverage.get("lookthrough"), dict) else {}
    selected = diagnostics.get("selected_factors", [])
    warnings = report.get("warnings", [])
    warning_text = ", ".join(str(item) for item in warnings) if warnings else "none"
    return panel(
        ft.Column(
            [
                section_header("Multi-factor risk model", "Versioned, evidence-only factor decomposition from adjusted prices and transparent descriptors."),
                ft.Text(
                    f"Status: {report.get('status', 'unavailable')} | model={report.get('model_version', 'unknown')} | selected factors={', '.join(map(str, selected)) or 'none'} | execution_allowed=false",
                    color=theme.TEXT,
                    selectable=True,
                ),
                ft.Text(
                    f"Return observations: {coverage.get('return_observations', 0)} across {coverage.get('return_instrument_count', 0)} instruments | specific-risk sample is visible below | ETF look-through: {lookthrough.get('status', 'unavailable')}",
                    color=theme.MUTED,
                    selectable=True,
                ),
                ft.Text(
                    f"Covariance condition number: {_number(diagnostics.get('covariance', {}).get('condition_number') if isinstance(diagnostics.get('covariance'), dict) else None)} | regularised: {diagnostics.get('covariance', {}).get('regularised', 'n/a') if isinstance(diagnostics.get('covariance'), dict) else 'n/a'} | warnings: {warning_text}",
                    color=theme.AMBER if warnings else theme.MUTED,
                    selectable=True,
                ),
            ],
            spacing=6,
        )
    )


def _factor_contribution_panel(report: dict[str, object]) -> ft.Control:
    frame = report.get("portfolio_contributions")
    frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.get("factor", "")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_number(row.get("portfolio_exposure")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_pct(row.get("variance_share")), color=theme.TEXT, size=11)),
            ]
        )
        for _, row in frame.iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("Factor exposure and contribution", "Portfolio variance contribution reconciles to factor plus specific risk."),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Factor")), ft.DataColumn(ft.Text("Exposure")), ft.DataColumn(ft.Text("Variance share"))],
                    rows=rows,
                )
                if rows
                else ft.Text("Factor contribution is unavailable; no complete cross-sectional fit was produced.", color=theme.MUTED),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _factor_history_panel(report: dict[str, object]) -> ft.Control:
    frame = report.get("factor_returns")
    frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if not frame.empty:
        frame = frame.sort_values(["date", "factor"], kind="stable").tail(24)
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.get("date", "")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(str(row.get("factor", "")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_pct(row.get("factor_return")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_number(row.get("standard_error")), color=theme.MUTED, size=11)),
                ft.DataCell(ft.Text(str(row.get("sample_count", "")), color=theme.MUTED, size=11)),
            ]
        )
        for _, row in frame.iterrows()
    ]
    return panel(
        ft.Column(
            [
                section_header("Historical factor returns", "Recent robust cross-sectional estimates; standard errors and sample counts remain visible."),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Date")), ft.DataColumn(ft.Text("Factor")), ft.DataColumn(ft.Text("Return")), ft.DataColumn(ft.Text("SE")), ft.DataColumn(ft.Text("N"))],
                    rows=rows,
                )
                if rows
                else ft.Text("Historical factor returns are unavailable; insufficient complete observations.", color=theme.MUTED),
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
    warning_values = (
        crowding["crowding_warning"]
        if "crowding_warning" in crowding.columns
        else pd.Series("", index=crowding.index, dtype=str)
    )
    warning_mask = warning_values.map(_is_crowding_warning_state)
    warning_rows = crowding.loc[warning_mask] if not crowding.empty else pd.DataFrame()
    if not warning_rows.empty and "cluster_id" in warning_rows.columns:
        warning_ids = warning_rows["cluster_id"].astype("string").str.strip()
        warning_count = int(warning_ids[warning_ids.notna() & warning_ids.ne("")].nunique())
    else:
        warning_count = 0
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
        ft.Text(f"Clusters with warnings: {warning_count} | highest cluster risk contribution: {_number(top_contribution)} | mean ranking coverage: {_number(mean_coverage)} | execution_allowed=false", color=theme.MUTED, selectable=True),
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
        number = _finite_float(value)
        return "N/A" if number is None else f"{number:.2f} bps"

    def _ratio(value: object) -> str:
        number = _finite_float(value)
        return "N/A" if number is None else f"{number:.2f}"

    def _scenario(value: object) -> str:
        if value is None or pd.isna(value):
            return "unavailable"
        text = str(value).strip()
        return text or "unavailable"

    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.get(id_column, "N/A")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_bps(row.get("gross_expected_edge_bps")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_bps(row.get("estimated_total_cost_bps")), color=theme.MUTED, size=11)),
                ft.DataCell(ft.Text(_bps(row.get("net_expected_edge_bps")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_ratio(row.get("edge_to_cost_ratio")), color=theme.TEXT, size=11)),
                ft.DataCell(ft.Text(_scenario(row.get("cost_stress_scenario")), color=theme.MUTED, size=11)),
            ]
        )
        for _, row in scoreboard.iterrows()
    ]
    summary = [
        f"{row.get(id_column, 'N/A')}: Gross edge {_bps(row.get('gross_expected_edge_bps'))} | Estimated cost {_bps(row.get('estimated_total_cost_bps'))} | Net edge {_bps(row.get('net_expected_edge_bps'))} | Edge/cost {_ratio(row.get('edge_to_cost_ratio'))} | Cost scenario: {_scenario(row.get('cost_stress_scenario'))}"
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
    factor_report = build_factor_risk_report(state.snapshot.prices, allocation, state.snapshot.latest_features, eligible_holdings)
    top_contributor = contribution.iloc[0]["etf_id"] if not contribution.empty else "n/a"
    export_status = ft.Text("Risk tables show text status independent of colour.", color=theme.MUTED, selectable=True)

    def export_limits(_event: ft.ControlEvent) -> None:
        result = export_table("risk_limits", limit_report, EXPORTS_DIR / "risk_limits.csv")
        export_status.value = f"Export {'complete' if result.ok else 'failed'}: {result.destination}; {result.error or f'{result.rows} rows'}."
        export_status.color = theme.GREEN if result.ok else theme.RED
        _page.update()

    def export_risk_frame(table_id: str, frame: pd.DataFrame, filename: str) -> None:
        result = export_table(table_id, frame if not frame.empty else None, EXPORTS_DIR / filename)
        export_status.value = f"Export {'complete' if result.ok else 'unavailable'}: {result.destination}; {result.error or f'{result.rows} rows'}."
        export_status.color = theme.GREEN if result.ok else theme.AMBER
        _page.update()

    def export_allocation(_event: ft.ControlEvent) -> None:
        export_risk_frame("risk_allocation", allocation, "risk_allocation.csv")

    def export_holdings(_event: ft.ControlEvent) -> None:
        export_risk_frame("risk_holdings", imported_holdings, "risk_holdings.csv")

    def export_correlation(_event: ft.ControlEvent) -> None:
        export_risk_frame("risk_correlation", correlation.reset_index(), "risk_correlation.csv")

    def export_drawdown(_event: ft.ControlEvent) -> None:
        export_risk_frame("risk_drawdown", contribution, "risk_drawdown.csv")

    def export_factor_contributions(_event: ft.ControlEvent) -> None:
        export_risk_frame("risk_factor_contributions", factor_report.get("portfolio_contributions", pd.DataFrame()), "risk_factor_contributions.csv")

    def export_factor_history(_event: ft.ControlEvent) -> None:
        export_risk_frame("risk_factor_returns", factor_report.get("factor_returns", pd.DataFrame()), "risk_factor_returns.csv")

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
            _factor_summary_panel(factor_report),
            ft.Row([_factor_contribution_panel(factor_report), _factor_history_panel(factor_report)], spacing=12),
            _correlation_table(correlation),
            _crowding_attribution_panel(),
            _friction_edge_panel(),
            _drawdown_table(contribution),
            panel(ft.Column([section_header("Risk evidence export", "CSV output is local-only and does not trigger execution. Empty canonical sources report unavailable and do not write placeholders."), ft.Row([ft.OutlinedButton("Export risk limits CSV", key="risk.export-limits", icon=ft.Icons.DOWNLOAD, on_click=export_limits), ft.OutlinedButton("Export allocation CSV", key="risk.export-allocation", icon=ft.Icons.DOWNLOAD, on_click=export_allocation), ft.OutlinedButton("Export holdings CSV", key="risk.export-holdings", icon=ft.Icons.DOWNLOAD, on_click=export_holdings), ft.OutlinedButton("Export correlation CSV", key="risk.export-correlation", icon=ft.Icons.DOWNLOAD, on_click=export_correlation), ft.OutlinedButton("Export drawdown CSV", key="risk.export-drawdown", icon=ft.Icons.DOWNLOAD, on_click=export_drawdown), ft.OutlinedButton("Export factor contributions CSV", key="risk.export-factor-contributions", icon=ft.Icons.DOWNLOAD, on_click=export_factor_contributions), ft.OutlinedButton("Export factor returns CSV", key="risk.export-factor-returns", icon=ft.Icons.DOWNLOAD, on_click=export_factor_history)], wrap=True), export_status], spacing=8)),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
