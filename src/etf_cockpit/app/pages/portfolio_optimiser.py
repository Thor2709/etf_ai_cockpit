"""Portfolio Optimiser Lab: advisory, local and explicitly non-executable."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.chartkit import Bubble
from etf_cockpit.app.components.kit import Button, DataTable, Disclosure, EmptyState, Field, GlassCard, KpiTile, Note, TableColumn
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.portfolio_optimiser import METHODS, OptimiserConstraints, build_portfolio_optimiser


_METHOD_LABELS = {
    "equal_weight": "Equal weight",
    "inverse_volatility": "Inverse volatility",
    "minimum_variance": "Minimum variance",
    "equal_risk_contribution": "Equal risk contribution",
    "hrp": "HRP/HERC (deterministic)",
    "maximum_diversification": "Maximum diversification",
    "cvar": "CVaR tail-risk baseline",
    "robust_mean_risk": "Robust mean-risk",
}


def portfolio_optimiser_page(page: ft.Page | None, state: AppState) -> PageView:
    optimiser, returns = build_portfolio_optimiser(getattr(state.snapshot, "prices", None))
    method_style = {
        "color": theme.INK,
        "border": ft.InputBorder.NONE,
        "dense": True,
    }
    method_control = ft.Dropdown(
        key="portfolio-optimiser.method",
        label="Method",
        value="equal_weight",
        options=[ft.dropdown.Option(value, _METHOD_LABELS[value]) for value in METHODS],
        **method_style,
    )
    method = Field("Method", control=method_control)
    method.data = {"kit": "Field", "input": method_control}
    cash = text_field("Cash (%)", "portfolio-optimiser.cash")
    maximum = text_field("Max weight (%)", "portfolio-optimiser.max-weight")
    input_of(cash).value = "0"
    input_of(maximum).value = "60"
    status = ft.Text()
    result_table: dict[str, ft.Control] = {"control": EmptyState("Unavailable", "Adjusted-price returns are required.")}
    frontier: dict[str, ft.Control] = {"control": EmptyState("Unavailable", "Held-out validation results are unavailable.")}
    audit = {"text": ""}

    def render(_event: ft.ControlEvent | None = None) -> None:
        if returns.empty:
            status.value = "Optimisation unavailable: adjusted-price returns are required."
            result_table["control"] = EmptyState("Optimisation unavailable", "Adjusted-price returns are required.")
            frontier["control"] = EmptyState("Frontier unavailable", "No held-out validation results are available.")
            return
        try:
            constraints = OptimiserConstraints(
                cash_weight=float(input_of(cash).value or "0") / 100.0,
                max_weight=float(input_of(maximum).value or "60") / 100.0,
            )
            comparison = optimiser.compare(METHODS, constraints=constraints)
            rows = [
                {
                    "method": _METHOD_LABELS.get(str(row["method"]), str(row["method"])),
                    "status": str(row["status"]),
                    "feasible": str(row["feasible"]).lower(),
                    "return": _percent(row["validation_return_ann"]),
                    "volatility": _percent(row["validation_vol_ann"]),
                    "max_weight": _percent(row["max_weight"]),
                    "constraints": str(row["binding_constraints"] or "—"),
                }
                for _, row in comparison.iterrows()
            ]
            result_table["control"] = DataTable(
                [
                    TableColumn("method", "Method"),
                    TableColumn("status", "Status"),
                    TableColumn("feasible", "Feasible"),
                    TableColumn("return", "Validation return", numeric=True),
                    TableColumn("volatility", "Validation volatility", numeric=True),
                    TableColumn("max_weight", "Max weight", numeric=True),
                    TableColumn("constraints", "Binding constraints"),
                ],
                rows,
                empty_title="Comparison unavailable",
                empty_reason="No method results were returned.",
            )
            points = [
                Bubble(
                    _METHOD_LABELS.get(str(row["method"]), str(row["method"])),
                    float(row["validation_vol_ann"]) * 100,
                    float(row["validation_return_ann"]) * 100,
                    0.6,
                    "Equal weight" if row["method"] == "equal_weight" else "Methods",
                    row["method"] == "equal_weight",
                )
                for _, row in comparison.iterrows()
                if row["feasible"] and row["validation_vol_ann"] is not None and row["validation_return_ann"] is not None
            ]
            frontier["control"] = ck.scatter_bubble(
                points,
                groups=[("Equal weight", theme.CHART_SECOND), ("Methods", theme.CATEGORICAL[0])],
                x_name="Validation volatility (%)",
                y_name="Validation return (%)",
                insight="Held-out risk and return by method.",
                unavailable_reason="No feasible held-out methods are available.",
            )
            fingerprints = [f"{row['method']}={str(row['fingerprint'])}" for _, row in comparison.iterrows()]
            audit["text"] = "\n".join(fingerprints)
            status.value = "Transparent methods compared on a held-out local return slice."
        except (TypeError, ValueError):
            status.value = "Optimisation unavailable: check the constraint values."
        if page is not None:
            page.update()

    run_button = Button.primary("Run comparison", key="portfolio-optimiser.run", on_click=render)
    render()
    constraints_card = GlassCard(
        "Constraints and method",
        note="cash is held outside invested weights",
        body=ft.Column(
            [
                ft.Row([KpiTile("Authority", "portfolio research only"), KpiTile("Data", "adjusted prices")], wrap=True),
                ft.Row([KpiTile("Fallback", "visible equal weight"), KpiTile("Held-out observations", str(len(returns)) if not returns.empty else None, sub="Unavailable without adjusted-price returns")], wrap=True),
                method,
                ft.Row([cash, maximum], wrap=True),
                run_button,
                status,
                Note("Eight transparent methods compared on a held-out local return slice."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    cards = [
        constraints_card,
        GlassCard("Risk-return frontier and baseline comparison", note="held-out validation slice", body=frontier["control"]),
        GlassCard("Method comparison", body=result_table["control"]),
        GlassCard("Weights by method", body=EmptyState("Weights unavailable", "Per-method instrument weights are not present in the current comparison result.")),
        GlassCard("Audit and limitations", body=Disclosure("solver fingerprints", ft.Text(audit["text"]) if audit["text"] else EmptyState("Unavailable", "Run a comparison to view solver audit details."))),
    ]
    return PageView(
        chrome=PageChrome("Portfolio Optimiser Lab", "Constrained research candidates from adjusted-price returns · advisory only"),
        body=page_body(cards),
    )


def _percent(value: object) -> str:
    try:
        return "—" if value is None else f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "—"


__all__ = ["portfolio_optimiser_page"]
