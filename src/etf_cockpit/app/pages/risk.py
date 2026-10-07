from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import Button, CardMenu, DataTable, Disclosure, EmptyState, GlassCard, KpiStrip, KpiStripItem, KpiTile, Note, TableColumn
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l4a_common import page_body
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.ui_facade import (
    allocation_frame,
    build_factor_risk_report,
    build_performance_attribution,
    drawdown_contribution,
    exposure_limit_report,
    exposure_summary,
    return_correlation_matrix,
)


def risk_page(page: ft.Page | None, state: AppState) -> PageView:
    snapshot = state.snapshot
    allocation = allocation_frame(snapshot.config, snapshot.holdings)
    limits = exposure_limit_report(snapshot.config, allocation)
    correlation = return_correlation_matrix(snapshot.prices, snapshot.config.universe.enabled_ids, window=120)
    contribution = drawdown_contribution(allocation, snapshot.latest_features)
    factors = build_factor_risk_report(snapshot.prices, allocation, snapshot.latest_features, pd.DataFrame())
    attribution = build_performance_attribution(
        snapshot.prices,
        allocation,
        factor_returns=factors.get("factor_returns"),
        factor_exposures=factors.get("exposure_matrix"),
        reference_context=context_from_snapshot(
            snapshot,
            purpose="attribution",
            analysis_id=f"attribution:{getattr(snapshot, 'universe_revision', 'unknown')}",
        ),
    )
    factor_history_frame = factors.get("factor_returns", pd.DataFrame())

    def export_frame(table_id: str, frame: pd.DataFrame, file_name: str) -> None:
        from etf_cockpit.application.ui_facade import export_table
        from etf_cockpit.core.paths import EXPORTS_DIR

        export_table(table_id, frame if not frame.empty else None, EXPORTS_DIR / file_name)

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
        export_frame("risk_factor_contributions", factors.get("portfolio_contributions", pd.DataFrame()), "risk_factor_contributions.csv")

    def export_factor_history(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_factor_returns", factor_history_frame, "risk_factor_returns.csv")

    def export_attribution(_event: ft.ControlEvent | None) -> None:
        export_frame("risk_performance_attribution", attribution.get("asset_contributions", pd.DataFrame()), "risk_performance_attribution.csv")
    data_report = getattr(snapshot, "data_report", None)
    findings = len(getattr(data_report, "issues", ())) if data_report is not None else None
    data_status = getattr(data_report, "status", None) if data_report is not None else None
    headline = f"Risk data is {data_status}" if data_status else "Risk data unavailable"
    kpis = KpiStrip(
        "Risk data",
        headline,
        f"{findings} data/context findings" if findings is not None else "Data quality is unavailable",
        [
            KpiStripItem("Portfolio guardrails", str(len(limits)) if not limits.empty else None, "Watch items unavailable"),
            KpiStripItem("Top DD contributor", str(contribution.iloc[0]["etf_id"]) if not contribution.empty else None, "Weighted current drawdown"),
            KpiStripItem("Correlation window", "120d" if not correlation.empty else None, "Adjusted-price log returns"),
            KpiStripItem("Volatility (ann.)", None, "Bootstrap interval unavailable"),
        ],
    )

    def download_menu(name: str, table_id: str, frame: pd.DataFrame, file_name: str) -> CardMenu:
        def export(_event: ft.ControlEvent | None) -> None:
            from etf_cockpit.application.ui_facade import export_table
            from etf_cockpit.core.paths import EXPORTS_DIR

            export_table(table_id, frame if not frame.empty else None, EXPORTS_DIR / file_name)

        return CardMenu([(name, export)])

    def table_rows(frame: pd.DataFrame, keys: list[tuple[str, str]]) -> list[dict[str, object]]:
        rows = []
        for _, row in frame.iterrows():
            rows.append({key: _cell(row.get(source)) for key, source in keys})
        return rows

    dimension = "asset_class"
    exposure = exposure_summary(allocation, dimension)
    exposure_rows = table_rows(exposure, [("bucket", str(exposure.columns[0])), ("current", "current_weight"), ("target", "target_weight")])
    exposure_chart = ck.grouped_bar_chart(
        [str(row.get("bucket", "—")) for row in exposure_rows],
        [
            ck.BarSeries("Current", [_numeric(row.get("current")) for row in exposure_rows], kind="blue"),
            ck.BarSeries("Target", [_numeric(row.get("target")) for row in exposure_rows], kind="gold"),
        ],
        x_name="Asset class",
        y_name="Weight (%)",
        unit="%",
        insight="Current asset-class exposure compared with target weights.",
        unavailable_reason="Exposure data is unavailable for the selected holdings.",
    )
    guardrail_rows = table_rows(
        limits,
        [("type", "type"), ("bucket", "bucket"), ("current", "current"), ("limit", "limit"), ("headroom", "headroom"), ("status", "status")],
    )
    guardrail_table = DataTable(
        [TableColumn("type", "Type"), TableColumn("bucket", "Bucket"), TableColumn("current", "Current"), TableColumn("limit", "Limit"), TableColumn("headroom", "Headroom"), TableColumn("status", "Status")],
        guardrail_rows,
        empty_title="Unavailable",
        empty_reason="No portfolio guardrail context is available.",
    )
    exposure_card = GlassCard(
        "Asset class exposure vs. target",
        note="% of portfolio",
        insight="Asset-class exposure versus configured target weights.",
        menu=download_menu("Download asset class exposure CSV", "risk_exposure_asset_class", exposure, "risk_exposure_asset_class.csv"),
        body=ft.Column([exposure_chart, DataTable([TableColumn("bucket", "Bucket"), TableColumn("current", "Current"), TableColumn("target", "Target")], exposure_rows, empty_title="Unavailable", empty_reason="Exposure data is unavailable.")]),
    )
    guardrail_card = GlassCard(
        "Portfolio guardrail context",
        note="breaches are construction context",
        menu=download_menu("Download limits CSV", "risk_limits", limits, "risk_limits.csv"),
        body=ft.Column([guardrail_table, Note("Breaches are shown as construction context. Data-quality failures remain hard blockers.")]),
    )
    if correlation.shape[0] < 2 or correlation.empty:
        correlation_control: ft.Control = EmptyState("Correlation unavailable", "Fewer than two holdings have joint returns.")
    else:
        columns = list(correlation.columns)
        correlation_control = DataTable(
            [TableColumn(str(index), str(column)) for index, column in enumerate(["Instrument", *columns])],
            [
                {str(index): value for index, value in enumerate([str(row[0]), *[_cell(value) for value in row[1:]]])}
                for row in correlation.itertuples(index=True, name=None)
            ],
            empty_title="Correlation unavailable",
            empty_reason="Joint returns are unavailable.",
        )
    correlation_card = GlassCard("Correlation", note="adjusted-price return window", body=correlation_control)
    tail_card = GlassCard(
        "Regimes, tail dependence and liquidity",
        body=ft.Column(
            [
                ck.grouped_bar_chart([], [], x_name="Regime", y_name="Portfolio vol", unavailable_reason="Calm and stress volatility are unavailable."),
                *[KpiTile(label, None, sub="Unavailable from the current snapshot") for label in ("Tail VaR 95%", "Expected shortfall 95%", "Downside volatility", "Maximum drawdown", "Lower-tail dependence", "Liquidity multiplier")],
            ],
        ),
    )

    factor_contributions = factors.get("portfolio_contributions", pd.DataFrame())
    if factor_contributions is None or factor_contributions.empty:
        factor_chart: ft.Control = EmptyState("Factor contribution unavailable", "No complete cross-sectional fit was produced.")
    else:
        factor_chart = ck.bar_chart(
            factor_contributions.iloc[:, 0].astype(str).tolist(),
            [_numeric(value) for value in factor_contributions.iloc[:, -1].tolist()],
            x_name="Factor",
            y_name="Contribution",
            insight="Factor exposure and contribution.",
            unavailable_reason="Factor contribution is unavailable.",
        )
    factor_returns = factor_history_frame
    factor_history = DataTable(
        [TableColumn(key, label) for key, label in (("date", "Date"), ("factor", "Factor"), ("return", "Return"), ("se", "SE"), ("n", "N"))],
        table_rows(factor_returns, [("date", "date"), ("factor", "factor"), ("return", "return"), ("se", "se"), ("n", "n")]) if isinstance(factor_returns, pd.DataFrame) else [],
        empty_title="Unavailable",
        empty_reason="Historical factor returns are unavailable.",
    )
    factor_card = GlassCard("Factor exposure and contribution", body=factor_chart)
    history_card = GlassCard("Historical factor returns", body=factor_history)
    model_card = GlassCard("Multi-factor risk model", body=Disclosure("model warnings", "Model status and warnings are unavailable."))
    robust_card = GlassCard("Robust risk model", body=DataTable([TableColumn("estimator", "Estimator"), TableColumn("error", "OOS error"), TableColumn("n", "Validation N"), TableColumn("selected", "Selected")], [], empty_title="Unavailable", empty_reason="Robust risk model results are unavailable."))
    performance_card = GlassCard("Performance and decision attribution", body=Disclosure("attribution details", str(attribution.get("status", "Unavailable"))))
    tail_regimes_card = GlassCard("Regimes and tail evidence", body=EmptyState("Unavailable", "Regime and tail evidence is unavailable."))
    holdings_card = GlassCard("ETF holdings evidence", body=EmptyState("Unavailable", "No eligible ETF holdings evidence is available."))
    overlap_card = GlassCard("ETF direct overlap", body=DataTable([TableColumn("instrument", "Instrument"), TableColumn("coverage", "Coverage"), TableColumn("freshness", "Freshness"), TableColumn("as_of", "As of"), TableColumn("resolved", "Resolved"), TableColumn("unresolved", "Unresolved"), TableColumn("source", "Source"), TableColumn("authority", "Authority")], [], empty_title="Unavailable", empty_reason="Direct overlap evidence is unavailable."))
    underlying_card = GlassCard("Underlying holdings context", body=EmptyState("Unavailable", "Underlying holdings context is unavailable."))
    export_card = GlassCard(
        "Risk evidence export",
        note="CSV output is local-only and does not trigger execution",
        body=ft.Row(
            [
                Button.secondary("Export risk limits CSV", key="risk.export-limits", on_click=export_limits),
                Button.secondary("Export allocation CSV", key="risk.export-allocation", on_click=export_allocation),
                Button.secondary("Export holdings CSV", key="risk.export-holdings", on_click=export_holdings),
                Button.secondary("Export correlation CSV", key="risk.export-correlation", on_click=export_correlation),
                Button.secondary("Export drawdown CSV", key="risk.export-drawdown", on_click=export_drawdown),
                Button.secondary("Export factor contributions CSV", key="risk.export-factor-contributions", on_click=export_factor_contributions),
                Button.secondary("Export factor returns CSV", key="risk.export-factor-returns", on_click=export_factor_history),
                Button.secondary("Export performance attribution CSV", key="risk.export-performance-attribution", on_click=export_attribution),
            ],
            wrap=True,
        ),
    )

    groups = [
        SegmentGroup("risk-view", ["Exposure", "Factors", "Tail & regimes"], "Exposure"),
        SegmentGroup("risk-dimension", ["Asset class", "Region", "Currency", "Sector", "Theme"], "Asset class"),
    ]
    return PageView(
        chrome=PageChrome("Risk Evidence", "Exposure, volatility, drawdown, liquidity and cost evidence for the selected holdings", groups),
        body=page_body(
            [
                kpis,
                exposure_card,
                guardrail_card,
                correlation_card,
                tail_card,
                factor_card,
                history_card,
                model_card,
                robust_card,
                performance_card,
                tail_regimes_card,
                holdings_card,
                overlap_card,
                underlying_card,
                export_card,
            ]
        ),
    )


def _cell(value: object) -> object:
    if value is None or pd.isna(value):
        return "—"
    return value


def _numeric(value: object) -> float | None:
    try:
        return float(value) if value is not None and pd.notna(value) else None
    except (TypeError, ValueError):
        return None


__all__ = ["risk_page"]
