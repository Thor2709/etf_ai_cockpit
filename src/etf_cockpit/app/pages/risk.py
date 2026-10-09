from __future__ import annotations

import math
import os
from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    CardMenu,
    DataTable,
    Disclosure,
    EmptyState,
    GlassCard,
    KpiStrip,
    KpiStripItem,
    KpiTile,
    Note,
    TableColumn,
    Tag,
    Well,
)
from etf_cockpit.app.components.overlap import overlap_evidence_panel
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_number, format_percent
from etf_cockpit.app.pages._l4a_common import page_body
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.ui_facade import (
    FUND_HOLDINGS_PATH,
    allocation_frame,
    build_direct_overlap_view,
    build_factor_risk_report,
    build_performance_attribution,
    drawdown_contribution,
    exposure_limit_report,
    exposure_summary,
    export_table,
    load_reference_dataset,
    normalise_holdings,
    return_correlation_matrix,
    underlying_holdings_exposure,
)
from etf_cockpit.core.paths import EXPORTS_DIR, ROOT


_DIMENSIONS = {
    "Asset class": "asset_class",
    "Region": "region",
    "Currency": "currency",
    "Sector": "sector",
    "Theme": "theme",
}
_LIMIT_COLUMNS = [
    "risk_type",
    "bucket",
    "current_weight",
    "limit",
    "headroom",
    "status",
    "status_rank",
]


def _current_weight_availability(holdings: object) -> dict[str, bool]:
    if not isinstance(holdings, pd.DataFrame) or holdings.empty or "current_weight" not in holdings.columns:
        return {}
    identity = "etf_id" if "etf_id" in holdings.columns else "instrument_id" if "instrument_id" in holdings.columns else None
    if identity is None:
        return {}
    available: dict[str, bool] = {}
    for _, row in holdings.iterrows():
        instrument_id = str(row.get(identity) or "").strip()
        if not instrument_id:
            continue
        value = pd.to_numeric(pd.Series([row.get("current_weight")]), errors="coerce").iloc[0]
        has_value = bool(pd.notna(value) and math.isfinite(float(value)))
        available[instrument_id] = available.get(instrument_id, True) and has_value
    return available


def _source_percent(value: object, reason: str, *, decimals: int = 1, source_present: bool = False) -> str | ft.Text:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ft.Text("Unavailable", tooltip=f"Unavailable: {reason}")
    if not math.isfinite(number):
        return ft.Text("Unavailable", tooltip=f"Unavailable: {reason}")
    if number == 0.0:
        return "0" if source_present else ft.Text("Unavailable", tooltip=f"Unavailable: {reason}")
    return format_percent(number, decimals=decimals, unavailable="Unavailable")


def _bucket_weight_available(
    allocation: pd.DataFrame,
    dimension: str,
    bucket: object,
    source_availability: dict[str, bool],
) -> bool:
    if dimension not in allocation.columns or "etf_id" not in allocation.columns:
        return False
    matching = allocation.loc[allocation[dimension].astype(str).eq(str(bucket)), "etf_id"]
    member_ids = [str(item) for item in matching.tolist()]
    return bool(member_ids) and all(source_availability.get(item, False) for item in member_ids)


def _holdings_reference_day(reference_date: object | None) -> pd.Timestamp:
    """Return the UTC day holdings age is measured against (wall clock only when no reference date is given)."""

    if reference_date is None:
        return pd.Timestamp.now(tz="UTC").normalize()
    reference = pd.Timestamp(reference_date)
    reference = reference.tz_localize("UTC") if reference.tzinfo is None else reference.tz_convert("UTC")
    return reference.normalize()


def _refresh_holdings_freshness(
    holdings: pd.DataFrame, *, stale_after_days: int = 90, reference_date: object | None = None
) -> pd.DataFrame:
    """Recompute persisted holding freshness before rendering or scoring."""

    if holdings.empty:
        return holdings
    refreshed = holdings.copy()
    date_columns = [column for column in ("as_of_date", "as_of") if column in refreshed.columns]
    if not date_columns:
        for column, value in (("freshness", "invalid"), ("completeness", "invalid")):
            if column in refreshed.columns:
                refreshed[column] = value
        if "score_eligible" in refreshed.columns:
            refreshed["score_eligible"] = False
        if "confidence" in refreshed.columns:
            refreshed["confidence"] = 0.0
        return refreshed
    parsed_dates = [pd.to_datetime(refreshed[column], errors="coerce", utc=True) for column in date_columns]
    as_of = parsed_dates[0]
    today = _holdings_reference_day(reference_date)
    age_days = (today - as_of.dt.normalize()).dt.days
    invalid = as_of.isna()
    for candidate in parsed_dates[1:]:
        invalid |= candidate.isna() | candidate.dt.normalize().ne(as_of.dt.normalize())
    stale = as_of.notna() & age_days.gt(max(0, int(stale_after_days)))
    future = as_of.notna() & age_days.lt(0)
    if "freshness" in refreshed.columns:
        refreshed.loc[invalid, "freshness"] = "invalid"
        refreshed.loc[stale, "freshness"] = "stale"
        refreshed.loc[future, "freshness"] = "invalid"
    if "completeness" in refreshed.columns:
        refreshed.loc[invalid, "completeness"] = "invalid"
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

    try:
        FUND_HOLDINGS_PATH.absolute().relative_to(ROOT.absolute())
        source_root = ROOT
    except ValueError:
        # Test and embedded callers may inject an isolated canonical path.
        source_root = FUND_HOLDINGS_PATH.parent
    candidates: list[tuple[Path, Path]] = [(FUND_HOLDINGS_PATH, source_root)]
    env_root = os.getenv("ETF_COCKPIT_ROOT", "").strip()
    if env_root:
        runtime_root = Path(env_root)
        candidates.append((runtime_root / "data" / "clean" / "fund_holdings.parquet", runtime_root))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate, root in candidates:
        resolved = _resolved_local_path(candidate, root)
        if resolved is not None and resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def _resolved_local_path(path: Path, root: Path) -> Path | None:
    root_resolved = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    if str(root_resolved).startswith(("\\\\", "//")) or str(resolved).startswith(("\\\\", "//")):
        return None
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


def _load_holdings_evidence() -> pd.DataFrame:
    canonical = pd.DataFrame()
    for holdings_path in _holdings_file_candidates():
        try:
            csv_candidate = holdings_path.with_suffix(".csv").resolve()
            csv_path = csv_candidate if csv_candidate.parent == holdings_path.parent else None
            if not holdings_path.exists() and (csv_path is None or not csv_path.exists()):
                continue
            try:
                canonical = pd.read_parquet(holdings_path)
            except Exception:
                # Portable builds may have a usable CSV mirror even when the
                # optional parquet engine cannot load a bundled binary.
                if csv_path is not None and csv_path.exists():
                    canonical = pd.read_csv(csv_path)
            if canonical.empty:
                if csv_path is not None and csv_path.exists():
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
    canonical_ids = set(canonical.get("instrument_id", pd.Series(dtype=str)).dropna().astype(str))
    legacy_only = legacy_context.loc[~legacy_context["instrument_id"].astype(str).isin(canonical_ids)]
    return _refresh_holdings_freshness(pd.concat([canonical, legacy_only], ignore_index=True, sort=False))


def _exposure_eligible_holdings(holdings: pd.DataFrame, *, reference_date: object | None = None) -> pd.DataFrame:
    required = {"score_eligible", "authority", "freshness", "completeness", "source_id", "weight"}
    if holdings.empty or not required.issubset(holdings.columns):
        return pd.DataFrame(columns=holdings.columns)
    eligible = _refresh_holdings_freshness(holdings, reference_date=reference_date)
    valid_weight = eligible["weight"].map(_valid_holding_weight)
    eligible = eligible[
        eligible["score_eligible"].map(_as_bool)
        & eligible["authority"].astype(str).str.strip().str.lower().eq("issuer")
        & eligible["freshness"].astype(str).str.strip().str.lower().eq("fresh")
        & eligible["completeness"].astype(str).str.strip().str.lower().eq("full")
        & eligible["source_id"].astype(str).str.strip().ne("")
        & valid_weight
    ]
    if "as_of_date" in eligible.columns:
        as_of = pd.to_datetime(eligible["as_of_date"], errors="coerce", utc=True)
        today = _holdings_reference_day(reference_date)
        valid_as_of = as_of.notna() & as_of.dt.normalize().le(today)
        eligible = eligible[valid_as_of]
    return eligible


def _valid_holding_weight(value: object) -> bool:
    if pd.api.types.is_bool(value):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and 0 <= number <= 1


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}




def _holdings_quality_panel(holdings: pd.DataFrame) -> ft.Control:
    """Evidence quality (completeness, freshness, authority) shown apart from portfolio exposure."""

    columns = ("instrument_id", "as_of_date", "completeness", "freshness", "confidence", "authority", "score_eligible")
    if holdings.empty or not {"instrument_id", "completeness"}.issubset(holdings.columns):
        body: ft.Control = EmptyState(
            "Unavailable",
            "No normalised holdings evidence is available; current exposure remains unavailable.",
        )
        details = None
    else:
        unique_rows = holdings.drop_duplicates(subset=["instrument_id"])
        labels = ("Instrument", "As of", "Completeness", "Freshness", "Confidence", "Authority", "Score eligible")
        body = DataTable(
            [TableColumn(name, label) for name, label in zip(columns, labels, strict=True)],
            [{name: str(row.get(name, "—")) for name in columns} for _, row in unique_rows.iterrows()],
            empty_title="Unavailable",
            empty_reason="No normalised holdings evidence is available.",
        )
        details = Disclosure(
            "holdings evidence lines",
            "\n".join(
                f"{row.get('instrument_id', 'N/A')}: as_of {row.get('as_of_date', 'N/A')} | "
                f"completeness={row.get('completeness', 'N/A')} | freshness={row.get('freshness', 'N/A')} | "
                f"confidence={row.get('confidence', 'N/A')} | authority={row.get('authority', 'N/A')} | "
                f"score_eligible={row.get('score_eligible', 'N/A')}"
                for _, row in unique_rows.iterrows()
            ),
        )
    return GlassCard(
        "ETF holdings evidence",
        note="issuer full/current rows support exposure; the rest is context only",
        body=[Well(body), *([details] if details is not None else [])],
    )


def _direct_overlap_card(overlap: object) -> ft.Control:
    coverage = tuple(getattr(overlap, "coverage", ()))
    rows = [
        {
            "instrument": str(item.instrument_id),
            "coverage": str(item.status),
            "freshness": str(item.freshness),
            "as_of": str(item.as_of or "—"),
            "resolved": _source_percent(
                item.resolved_weight,
                "the direct-overlap evidence record has no finite resolved weight.",
                source_present=item.status != "missing" and item.source_id is not None,
            ),
            "unresolved": _source_percent(
                item.unresolved_weight,
                "the direct-overlap evidence record has no finite unresolved weight.",
                source_present=item.status != "missing" and item.source_id is not None,
            ),
            "source": str(item.source_id or "—"),
            "authority": str(getattr(item, "authority", None) or "—"),
        }
        for item in coverage
    ]
    table = DataTable(
        [
            TableColumn("instrument", "Instrument"),
            TableColumn("coverage", "Coverage"),
            TableColumn("freshness", "Freshness"),
            TableColumn("as_of", "As of"),
            TableColumn("resolved", "Resolved", numeric=True),
            TableColumn("unresolved", "Unresolved", numeric=True),
            TableColumn("source", "Source"),
            TableColumn("authority", "Authority"),
        ],
        rows,
        empty_title="Unavailable",
        empty_reason="Direct overlap evidence is unavailable.",
    )
    return GlassCard(
        "ETF direct overlap",
        note="exact typed identities; unresolved holdings are never renormalised",
        body=[
            Well(table),
            Disclosure("overlap pairs and look-through evidence", overlap_evidence_panel(overlap, key="risk.etf-overlap")),
        ],
    )


def _underlying_holdings_card(holdings: pd.DataFrame, allocation: pd.DataFrame) -> ft.Control:
    if holdings.empty:
        return GlassCard(
            "Underlying holdings context",
            body=Well(EmptyState("Unavailable", "No look-through holdings file has been imported yet.")),
        )
    tables = []
    for label, dimension in (("Sector", "sector"), ("Region", "region"), ("Currency", "currency")):
        frame = underlying_holdings_exposure(allocation, holdings, dimension)
        rows = [
            {"bucket": str(row.iloc[0]), "current": _source_percent(row.get("current_weight"), "the underlying holdings evidence has no finite current weight for this bucket.", source_present=True)}
            for _, row in frame.head(8).iterrows()
        ]
        tables.append(
            ft.Column(
                [
                    Note(label),
                    DataTable(
                        [TableColumn("bucket", "Bucket"), TableColumn("current", "Current", numeric=True)],
                        rows,
                        empty_title="Unavailable",
                        empty_reason="No mapped holdings.",
                    ),
                ],
                expand=True,
            )
        )
    return GlassCard(
        "Underlying holdings context",
        note="portfolio-weighted look-through; latest holding date per instrument",
        body=ft.Row(tables, spacing=theme.SPACE_2),
    )


def risk_page(page: ft.Page | None, state: AppState, *, _deferred: bool = False) -> PageView:
    if not _deferred and page is not None and (isinstance(page, ft.Page) or bool(getattr(page, "_shell_defer_render", False))):
        placeholder = ft.Container(content=Note("Loading risk evidence..."), expand=True)
        placeholder.data = {"shell.deferred-update": lambda: risk_page(page, state, _deferred=True)}
        return PageView(
            PageChrome(
                "Risk Evidence",
                "Exposure, volatility, drawdown, liquidity and cost evidence for the selected holdings",
            ),
            placeholder,
        )
    snapshot = state.snapshot
    allocation = allocation_frame(snapshot.config, snapshot.holdings)
    current_weight_availability = _current_weight_availability(snapshot.holdings)
    limits = (
        exposure_limit_report(snapshot.config, allocation)
        if not allocation.empty
        else pd.DataFrame(columns=_LIMIT_COLUMNS)
    )
    correlation_window = 120
    correlation = return_correlation_matrix(
        snapshot.prices,
        snapshot.config.universe.enabled_ids,
        window=correlation_window,
    )
    if allocation.empty or not {"etf_id", "drawdown_current", "drawdown_60d_max", "vol_60d_ann"}.issubset(snapshot.latest_features.columns):
        contribution = pd.DataFrame(
            columns=[
                "etf_id",
                "name",
                "current_weight",
                "drawdown_current",
                "drawdown_60d_max",
                "vol_60d_ann",
                "drawdown_contribution",
                "risk_share",
            ]
        )
        contribution.attrs.update(status="unavailable")
    else:
        contribution = drawdown_contribution(allocation, snapshot.latest_features)
    imported_holdings = _load_holdings_evidence()
    snapshot_date = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    if snapshot_date is None or "as_of_date" not in imported_holdings.columns:
        imported_holdings = imported_holdings.iloc[0:0].copy()
    else:
        cutoff = _holdings_reference_day(snapshot_date)
        holding_dates = pd.to_datetime(imported_holdings["as_of_date"], errors="coerce", utc=True)
        imported_holdings = imported_holdings.loc[holding_dates.notna() & holding_dates.dt.normalize().le(cutoff)]
    eligible_holdings = _exposure_eligible_holdings(imported_holdings, reference_date=snapshot_date)
    overlap = build_direct_overlap_view(
        snapshot,
        list(snapshot.config.universe.enabled_ids),
        current_weights={str(row["etf_id"]): float(row["current_weight"]) for _, row in allocation.iterrows()},
        target_weights={str(row["etf_id"]): float(row["target_weight"]) for _, row in allocation.iterrows()},
        holdings=imported_holdings,
    )
    factors = build_factor_risk_report(
        snapshot.prices,
        allocation,
        snapshot.latest_features,
        eligible_holdings,
    )
    factor_history = factors.get("factor_returns", pd.DataFrame())
    attribution = build_performance_attribution(
        snapshot.prices,
        allocation,
        factor_returns=factor_history,
        factor_exposures=factors.get("exposure_matrix"),
        reference_context=context_from_snapshot(
            snapshot,
            purpose="attribution",
            analysis_id=f"attribution:{getattr(snapshot, 'universe_revision', 'unknown')}",
        ),
    )

    export_status = Note("No risk CSV export has been requested.")

    def export_frame(table_id: str, frame: pd.DataFrame, file_name: str) -> None:
        try:
            result = export_table(table_id, frame if not frame.empty else None, EXPORTS_DIR / file_name)
            if result.ok:
                export_status.value = f"CSV saved locally: {result.destination} ({result.rows} rows)."
            else:
                export_status.value = f"CSV export unavailable: {result.error or result.status}; no file was written."
        except Exception as exc:
            export_status.value = f"CSV export failed safely: {type(exc).__name__}; no file was uploaded."
        if callable(getattr(page, "update", None)):
            page.update()

    def export_limits(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_limits", limits, "risk_limits.csv")

    def export_allocation(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_allocation", allocation, "risk_allocation.csv")

    def export_holdings(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_holdings", pd.DataFrame(), "risk_holdings.csv")

    def export_correlation(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_correlation", correlation.reset_index(), "risk_correlation.csv")

    def export_drawdown(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_drawdown", contribution, "risk_drawdown.csv")

    def export_factor_contributions(_event: ft.ControlEvent | None) -> None:
        frame = factor_contributions if isinstance(factor_contributions, pd.DataFrame) else pd.DataFrame()
        export_frame("risk_factor_contributions", frame, "risk_factor_contributions.csv")

    def export_attribution(_event: ft.ControlEvent | None) -> None:
        frame = asset_contributions if isinstance(asset_contributions, pd.DataFrame) else pd.DataFrame()
        export_frame("risk_performance_attribution", frame, "risk_performance_attribution.csv")

    def export_factor_history(_event: ft.ControlEvent | None) -> None:
        frame = factor_history if isinstance(factor_history, pd.DataFrame) else pd.DataFrame()
        export_frame("risk_factor_returns", frame, "risk_factor_returns.csv")

    data_report = getattr(snapshot, "data_report", None)
    issue_count = len(getattr(data_report, "issues", ())) if data_report is not None else None
    data_status = getattr(data_report, "status", None) if data_report is not None else None
    headline = (
        "Risk data is unavailable"
        if issue_count is None
        else "Risk data is Clean"
        if issue_count == 0
        else "Risk data needs review"
    )
    risk_kpis = KpiStrip(
        "Risk data",
        headline,
        f"{format_count(issue_count, unavailable='—')} data/context findings",
        [
            KpiStripItem(
                "Portfolio guardrails",
                format_count(len(limits), unavailable="—") if not limits.empty else None,
                "Guardrail count" if not limits.empty else "Guardrail evidence unavailable",
            ),
            KpiStripItem(
                "Top DD contributor",
                str(contribution.iloc[0]["etf_id"])
                if not contribution.empty and contribution.attrs.get("status") == "available"
                else None,
                "Weighted current drawdown",
            ),
            KpiStripItem(
                "Correlation window",
                f"{correlation_window}d" if correlation.attrs.get("status") in {"available", "partial"} else None,
                "Adjusted-price log returns",
            ),
            KpiStripItem("Volatility (ann.)", None, "Bootstrap interval unavailable"),
        ],
    )

    def menu(items: list[tuple[str, str, pd.DataFrame, str]]) -> CardMenu:
        def make_action(table_id: str, frame: pd.DataFrame, file_name: str):
            def export(_event: ft.ControlEvent | None = None) -> None:
                export_frame(table_id, frame, file_name)

            return export

        card_menu = CardMenu(
            [(label, make_action(table_id, frame, file_name)) for label, table_id, frame, file_name in items]
        )
        for item, (_label, table_id, _frame, _file) in zip(card_menu.items, items, strict=True):
            # Stable download key per table; the action writes one local CSV only.
            item.key = "risk.download-" + table_id.removeprefix("risk_").replace("_", "-")
            item.tooltip = "Saves a CSV to the local exports folder - local file only, nothing is uploaded."
        return card_menu

    def percent_cell(value: object, reason: str) -> str | ft.Text:
        return _source_percent(value, reason, source_present=True)

    def numeric_cell(value: object) -> str:
        return format_number(value, unavailable="—")

    def exposure_card(label: str) -> GlassCard:
        dimension = _DIMENSIONS[label]
        exposure = exposure_summary(allocation, dimension)
        bucket_column = dimension
        exposure_availability = [
            _bucket_weight_available(allocation, bucket_column, row.get(bucket_column), current_weight_availability)
            for _, row in exposure.iterrows()
        ]
        exposure_rows = [
            {
                "bucket": str(row.get(bucket_column, "—")) if pd.notna(row.get(bucket_column)) else "—",
                "current": percent_cell(
                    row.get("current_weight"),
                    "the selected holdings source has no finite current weight for this bucket.",
                ) if is_available else ft.Text("Unavailable", tooltip="Unavailable: current weight is missing from the selected holdings source."),
                "target": percent_cell(
                    row.get("target_weight"),
                    "the selected exposure source has no finite target weight for this bucket.",
                ),
            }
            for (_, row), is_available in zip(exposure.iterrows(), exposure_availability, strict=True)
        ]
        chart_values = [
            (row.get("current_weight") * 100) if is_available and pd.notna(row.get("current_weight")) else None
            for (_, row), is_available in zip(exposure.iterrows(), exposure_availability, strict=True)
        ]
        target_values = [
            (row.get("target_weight") * 100) if pd.notna(row.get("target_weight")) else None
            for _, row in exposure.iterrows()
        ]
        available_differences = [
            row.get("current_weight") - row.get("target_weight")
            for (_, row), is_available in zip(exposure.iterrows(), exposure_availability, strict=True)
            if is_available and pd.notna(row.get("current_weight")) and pd.notna(row.get("target_weight"))
        ]
        if exposure.empty:
            insight = f"{label} exposure and target comparison are unavailable."
        elif not available_differences:
            insight = f"Current {label.casefold()} exposure is unavailable; no target drift is inferred."
        else:
            over_target = max(
                (
                    (row.get("current_weight") - row.get("target_weight"), str(row.get(bucket_column)))
                    for (_, row), is_available in zip(exposure.iterrows(), exposure_availability, strict=True)
                    if is_available and pd.notna(row.get("current_weight")) and pd.notna(row.get("target_weight"))
                ),
                key=lambda item: item[0],
            )
            points = format_number(over_target[0] * 100, decimals=1, unavailable="—")
            unavailable_suffix = (
                " Some current weights are unavailable and omitted."
                if not all(exposure_availability)
                else ""
            )
            insight = f"{over_target[1]} is {points} pts over its target.{unavailable_suffix}"
        chart = ck.grouped_bar_chart(
            [str(row.get(bucket_column, "—")) for _, row in exposure.iterrows()],
            [
                ck.BarSeries("Current", chart_values, kind="blue"),
                ck.BarSeries("Target", target_values, kind="gold"),
            ],
            x_name=label,
            y_name="Weight (%)",
            unit="%",
            insight=insight,
            unavailable_reason=(
                f"Current {label.casefold()} exposure data is unavailable for the selected holdings."
                if not any(exposure_availability)
                else None
            ),
        )
        return GlassCard(
            f"{label} exposure vs. target",
            note="% of portfolio",
            insight=insight,
            menu=menu(
                [
                    (
                        f"Download {label.casefold()} exposure CSV",
                        f"risk_exposure_{dimension}",
                        exposure,
                        f"risk_exposure_{dimension}.csv",
                    ),
                ]
            ),
            body=ft.Column(
                [
                    Well(chart),
                    Button.secondary("Export allocation CSV", key="risk.export-allocation", on_click=export_allocation),
                    Well(
                        DataTable(
                            [
                                TableColumn("bucket", "Bucket"),
                                TableColumn("current", "Current"),
                                TableColumn("target", "Target"),
                            ],
                            exposure_rows,
                            empty_title="Unavailable",
                            empty_reason=f"{label} exposure data is unavailable.",
                        )
                    ),
                ],
                spacing=theme.SPACE_2,
            ),
        )

    guardrail_rows = []
    status_labels = {"ok": ("Within limit", "ok"), "watch": ("Watch", "warn"), "breach": ("Exceeded", "bad"), "info": ("Informational", "mute")}
    for _, row in limits.iterrows():
        display_status, status_kind = status_labels.get(str(row.get("status")), ("Unavailable", "bad"))
        headroom = row.get("headroom")
        risk_type = str(row.get("risk_type", ""))
        bucket = row.get("bucket")
        dimension = {
            "etf": "etf_id",
            "asset_class": "asset_class",
            "region": "region",
            "sector": "sector",
            "theme": "theme",
            "currency": "currency",
        }.get(risk_type)
        source_value_available = (
            bucket in current_weight_availability
            and current_weight_availability.get(str(bucket), False)
            if dimension == "etf_id"
            else _bucket_weight_available(allocation, dimension, bucket, current_weight_availability)
            if dimension is not None
            else False
        )
        if not source_value_available:
            display_status, status_kind = "Unavailable", "mute"
        guardrail_rows.append(
            {
                "type": str(row.get("risk_type", "—")),
                "bucket": str(row.get("bucket", "—")),
                "current": percent_cell(
                    row.get("current_weight"),
                    "the selected holdings source has no finite current weight for this guardrail.",
                ) if source_value_available else ft.Text("Unavailable", tooltip="Unavailable: current weight is missing from the selected holdings source."),
                "limit": percent_cell(
                    row.get("limit"),
                    "the guardrail source has no finite configured limit.",
                ),
                "headroom": percent_cell(
                    headroom,
                    "the selected holdings source has no finite headroom for this guardrail.",
                ) if source_value_available else ft.Text("Unavailable", tooltip="Unavailable: headroom cannot be derived without a current holding weight."),
                "status": Tag(display_status, status_kind),
            }
        )
    guardrail_card = GlassCard(
        "Portfolio guardrail context",
        note="breaches are construction context",
        menu=menu(
            [
                ("Download limits CSV", "risk_limits", limits, "risk_limits.csv"),
            ]
        ),
        body=ft.Column(
            [
                ft.Row(
                    [
                        Button.secondary("Export risk limits CSV", key="risk.export-limits", on_click=export_limits),
                        Button.secondary("Export holdings CSV", key="risk.export-holdings", on_click=export_holdings),
                    ],
                    wrap=True,
                ),
                Well(
                    DataTable(
                        [
                            TableColumn("type", "Type"),
                            TableColumn("bucket", "Bucket"),
                            TableColumn("current", "Current", numeric=True),
                            TableColumn("limit", "Limit", numeric=True),
                            TableColumn("headroom", "Headroom", numeric=True),
                            TableColumn("status", "Status"),
                        ],
                        guardrail_rows,
                        empty_title="Unavailable",
                        empty_reason="No portfolio guardrail context is available.",
                    )
                ),
                Note("Breaches are shown as construction context. Data-quality failures remain hard blockers."),
                Disclosure("risk data status", str(data_status) if data_status is not None else "Unavailable"),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    if correlation.shape[0] < 2 or correlation.empty or correlation.attrs.get("status") == "unavailable":
        correlation_body: ft.Control = EmptyState(
            "Correlation unavailable",
            "Fewer than two holdings have joint returns.",
        )
        correlation_insight = "Pairwise correlation evidence is unavailable."
        correlation_note = "adjusted-price return window unavailable"
    else:
        corr_columns = [str(column) for column in correlation.columns]
        corr_rows = []
        for index, (instrument, row) in enumerate(correlation.iterrows()):
            corr_rows.append(
                {
                    "instrument": str(instrument),
                    **{
                        str(column): "—" if index == column_index else numeric_cell(row.iloc[column_index])
                        for column_index, column in enumerate(corr_columns)
                    },
                }
            )
        pairs = [
            (float(correlation.iloc[row, column]), str(correlation.index[row]), str(correlation.columns[column]))
            for row in range(len(correlation.index))
            for column in range(row + 1, len(correlation.columns))
            if pd.notna(correlation.iloc[row, column])
        ]
        most_alike = max(pairs) if pairs else None
        correlation_insight = (
            f"{most_alike[1]} and {most_alike[2]} move most alike ({format_number(most_alike[0], decimals=2)})."
            if most_alike
            else "Pairwise correlation evidence is unavailable."
        )
        correlation_note = f"{correlation_window}d · top {len(correlation)} holdings"
        correlation_body = DataTable(
            [TableColumn("instrument", "Instrument"), *[TableColumn(str(column), str(column), numeric=True) for column in corr_columns]],
            corr_rows,
            empty_title="Correlation unavailable",
            empty_reason="Joint returns are unavailable.",
        )
    correlation_card = GlassCard(
        "Correlation",
        note=correlation_note,
        insight=correlation_insight,
        menu=menu([("Download correlation CSV", "risk_correlation", correlation.reset_index(), "risk_correlation.csv")]),
        body=ft.Column(
            [
                Button.secondary(
                    "Export correlation CSV", key="risk.export-correlation", on_click=export_correlation
                ),
                Well(correlation_body),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    tail_tiles = [
        KpiTile(label, None, sub="No existing result provides this measure")
        for label in (
            "Tail VaR 95%",
            "Expected shortfall 95%",
            "Downside volatility",
            "Maximum drawdown",
            "Lower-tail dependence",
            "Liquidity multiplier",
        )
    ]
    regimes_chart = ck.grouped_bar_chart(
        [],
        [],
        x_name="Regime",
        y_name="Portfolio vol (%)",
        unit="%",
        unavailable_reason="Calm and stress portfolio volatility are unavailable.",
        insight="Regime volatility evidence is unavailable.",
    )
    regimes_tail_card = GlassCard(
        "Regimes, tail dependence and liquidity",
        body=ft.Column([Well(regimes_chart), *tail_tiles], spacing=theme.SPACE_2),
    )

    factor_contributions = factors.get("portfolio_contributions", pd.DataFrame())
    if not isinstance(factor_contributions, pd.DataFrame) or factor_contributions.empty:
        factor_chart: ft.Control = EmptyState(
            "Factor contribution unavailable",
            "No complete cross-sectional fit was produced.",
        )
    else:
        factor_values = [
            value * 100 if pd.notna(value) else None
            for value in factor_contributions.get("variance_share", pd.Series(dtype=float)).tolist()
        ]
        factor_chart = ck.bar_chart(
            factor_contributions.get("factor", pd.Series(dtype=str)).astype(str).tolist(),
            factor_values,
            x_name="Factor",
            y_name="Variance contribution (%)",
            unit="%",
            insight="Factor contribution to portfolio variance.",
            unavailable_reason="Factor contribution is unavailable.",
        )
    factor_card = GlassCard(
        "Factor exposure and contribution",
        body=ft.Column(
            [
                Button.secondary(
                    "Export factor contributions CSV",
                    key="risk.export-factor-contributions",
                    on_click=export_factor_contributions,
                ),
                Well(factor_chart),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    factor_history_rows = []
    if isinstance(factor_history, pd.DataFrame):
        for _, row in factor_history.iterrows():
            factor_history_rows.append(
                {
                    "date": str(row.get("date", "—")) if pd.notna(row.get("date")) else "—",
                    "factor": str(row.get("factor", "—")) if pd.notna(row.get("factor")) else "—",
                    "return": _source_percent(row.get("factor_return"), "the historical factor return source has no finite value for this row.", decimals=2, source_present=True),
                    "se": format_number(row.get("standard_error"), decimals=4, unavailable="—"),
                    "n": format_count(row.get("sample_count"), unavailable="—"),
                }
            )
    factor_history_card = GlassCard(
        "Historical factor returns",
        body=ft.Column(
            [
                Button.secondary(
                    "Export factor returns CSV", key="risk.export-factor-returns", on_click=export_factor_history
                ),
                Well(
                    DataTable(
                [
                    TableColumn("date", "Date"),
                    TableColumn("factor", "Factor"),
                    TableColumn("return", "Return", numeric=True),
                    TableColumn("se", "SE", numeric=True),
                    TableColumn("n", "N", numeric=True),
                ],
                factor_history_rows,
                empty_title="Unavailable",
                empty_reason="Historical factor returns are unavailable.",
                    )
                ),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    factor_status = str(factors.get("status", "unavailable"))
    model_status = {"available": "Available", "partial": "Partial", "unavailable": "Unavailable"}.get(
        factor_status,
        "Unavailable",
    )
    model_card = GlassCard(
        "Multi-factor risk model",
        body=ft.Column(
            [
                KpiTile("Model status", model_status, sub="Factor model evidence"),
                Disclosure("model warnings", str(factors.get("diagnostics", {}))),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    robust_card = GlassCard(
        "Robust risk model",
        body=ft.Column(
            [
                KpiTile("Robust risk model", None, sub="No robust estimator result is available."),
                Well(
                    DataTable(
                        [
                            TableColumn("estimator", "Estimator"),
                            TableColumn("error", "OOS error", numeric=True),
                            TableColumn("n", "Validation N", numeric=True),
                            TableColumn("selected", "Selected"),
                        ],
                        [],
                        empty_title="Unavailable",
                        empty_reason="Robust risk model results are unavailable.",
                    )
                ),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    asset_contributions = attribution.get("asset_contributions", pd.DataFrame())
    if not isinstance(asset_contributions, pd.DataFrame) or asset_contributions.empty:
        attribution_chart: ft.Control = EmptyState(
            "Attribution unavailable",
            "No adjusted-price contribution results are available.",
        )
    else:
        contributions = asset_contributions.get("contribution", pd.Series(dtype=float))
        names = asset_contributions.get("instrument_id", pd.Series(dtype=str)).astype(str).tolist()
        values = [value * 100 if pd.notna(value) else None for value in contributions.tolist()]
        if names and any(value is not None for value in values):
            top_index = max(range(len(values)), key=lambda index: abs(values[index] or 0))
            insight = f"{names[top_index]} has the largest observed contribution ({format_number(values[top_index], decimals=2)}%)."
        else:
            insight = "Observed performance contribution is unavailable."
        attribution_chart = ck.bar_chart(
            names,
            values,
            x_name="Instrument",
            y_name="Return contribution (%)",
            unit="%",
            insight=insight,
            unavailable_reason="Observed performance attribution is unavailable.",
        )
    attribution_tiles = [
        KpiTile(
            label,
            format_percent(attribution.get(key), decimals=2, unavailable="Unavailable")
            if attribution.get(key) is not None
            else None,
            sub=reason,
        )
        for label, key, reason in (
            ("TWR", "time_weighted_return", "Time-weighted return unavailable"),
            ("MWR", "money_weighted_return", "Money-weighted return unavailable"),
            ("Net after costs", "net_return_after_explicit_costs", "Cost evidence unavailable"),
        )
    ]
    performance_card = GlassCard(
        "Performance and decision attribution",
        menu=menu([("Download drawdown CSV", "risk_drawdown", contribution, "risk_drawdown.csv")]),
        body=ft.Column(
            [
                ft.Row(
                    [
                        Button.secondary(
                            "Export drawdown CSV", key="risk.export-drawdown", on_click=export_drawdown
                        ),
                        Button.secondary(
                            "Export performance attribution CSV",
                            key="risk.export-performance-attribution",
                            on_click=export_attribution,
                        ),
                    ],
                    wrap=True,
                ),
                Well(attribution_chart),
                ft.Row(attribution_tiles, spacing=theme.SPACE_2, wrap=True),
                Disclosure("attribution warnings", str(attribution.get("warnings", []))),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    regime_table = GlassCard(
        "Regimes",
        body=Well(
            DataTable(
                [
                    TableColumn("regime", "Regime"),
                    TableColumn("observations", "Observations", numeric=True),
                    TableColumn("volatility", "Volatility", numeric=True),
                ],
                [],
                empty_title="Unavailable",
                empty_reason="Regime evidence is unavailable from the current snapshot.",
            )
        ),
    )
    tail_evidence = GlassCard("Tail evidence", body=ft.Row(tail_tiles, spacing=theme.SPACE_2, wrap=True))

    holdings_card = _holdings_quality_panel(imported_holdings)
    overlap_card = _direct_overlap_card(overlap)
    underlying_card = _underlying_holdings_card(eligible_holdings, allocation)

    selection = {"view": "Exposure", "dimension": "Asset class"}
    body = page_body([])

    def render() -> None:
        below_fold = [holdings_card, overlap_card, underlying_card]
        if selection["view"] == "Factors":
            cards = [factor_card, factor_history_card, model_card, robust_card]
        elif selection["view"] == "Tail & regimes":
            cards = [performance_card, regime_table, tail_evidence]
        else:
            cards = [
                exposure_card(selection["dimension"]),
                guardrail_card,
                correlation_card,
                regimes_tail_card,
            ]
        body.controls = [risk_kpis, export_status, *cards, *below_fold]
        if page is not None:
            page.update()

    def select_view(value: str) -> None:
        selection["view"] = value
        render()

    def select_dimension(value: str) -> None:
        selection["dimension"] = value
        render()

    render()
    return PageView(
        chrome=PageChrome(
            "Risk Evidence",
            "Exposure, volatility, drawdown, liquidity and cost evidence for the selected holdings",
            [
                SegmentGroup("risk-view", ["Exposure", "Factors", "Tail & regimes"], "Exposure", select_view),
                SegmentGroup(
                    "risk-dimension",
                    list(_DIMENSIONS),
                    "Asset class",
                    select_dimension,
                ),
            ],
        ),
        body=body,
    )


__all__ = ["risk_page"]
