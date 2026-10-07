from __future__ import annotations

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
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_number, format_percent
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


def risk_page(page: ft.Page | None, state: AppState) -> PageView:
    snapshot = state.snapshot
    allocation = allocation_frame(snapshot.config, snapshot.holdings)
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
    factors = build_factor_risk_report(
        snapshot.prices,
        allocation,
        snapshot.latest_features,
        pd.DataFrame(),
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
            def export(_event: ft.ControlEvent | None) -> None:
                export_frame(table_id, frame, file_name)

            return export

        return CardMenu([(label, make_action(table_id, frame, file_name)) for label, table_id, frame, file_name in items])

    def percent_cell(value: object) -> str:
        return format_percent(value, unavailable="—")

    def numeric_cell(value: object) -> str:
        return format_number(value, unavailable="—")

    def exposure_card(label: str) -> GlassCard:
        dimension = _DIMENSIONS[label]
        exposure = exposure_summary(allocation, dimension)
        bucket_column = dimension
        exposure_rows = [
            {
                "bucket": str(row.get(bucket_column, "—")) if pd.notna(row.get(bucket_column)) else "—",
                "current": percent_cell(row.get("current_weight")),
                "target": percent_cell(row.get("target_weight")),
            }
            for _, row in exposure.iterrows()
        ]
        chart_values = [
            (row.get("current_weight") * 100) if pd.notna(row.get("current_weight")) else None
            for _, row in exposure.iterrows()
        ]
        target_values = [
            (row.get("target_weight") * 100) if pd.notna(row.get("target_weight")) else None
            for _, row in exposure.iterrows()
        ]
        if exposure.empty:
            insight = f"{label} exposure and target comparison are unavailable."
        else:
            differences = exposure["current_weight"] - exposure["target_weight"]
            over_target = differences.idxmax()
            bucket = str(exposure.loc[over_target, bucket_column])
            points = format_number(differences.loc[over_target] * 100, decimals=1, unavailable="—")
            insight = f"{bucket} is {points} pts over its target."
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
            unavailable_reason=f"{label} exposure data is unavailable for the selected holdings.",
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
        guardrail_rows.append(
            {
                "type": str(row.get("risk_type", "—")),
                "bucket": str(row.get("bucket", "—")),
                "current": percent_cell(row.get("current_weight")),
                "limit": percent_cell(row.get("limit")),
                "headroom": percent_cell(headroom),
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
                    "return": format_percent(row.get("factor_return"), decimals=2, unavailable="—"),
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

    holdings_card = GlassCard(
        "ETF holdings evidence",
        body=Well(EmptyState("Unavailable", "No eligible ETF holdings evidence is available.")),
    )
    overlap_card = GlassCard(
        "ETF direct overlap",
        body=Well(
            DataTable(
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
                [],
                empty_title="Unavailable",
                empty_reason="Direct overlap evidence is unavailable.",
            )
        ),
    )
    underlying_card = GlassCard(
        "Underlying holdings context",
        body=Well(EmptyState("Unavailable", "Underlying holdings context is unavailable.")),
    )

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
        body.controls = [risk_kpis, *cards, *below_fold]
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
