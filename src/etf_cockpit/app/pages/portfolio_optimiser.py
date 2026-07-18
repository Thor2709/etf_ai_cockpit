"""Portfolio Optimiser Lab: advisory, local and explicitly non-executable."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.portfolio_optimiser import (
    METHODS,
    OptimiserConstraints,
    build_portfolio_optimiser,
)


_METHOD_LABELS = {
    "equal_weight": "Equal weight",
    "inverse_volatility": "Inverse volatility",
    "minimum_variance": "Minimum variance",
    "equal_risk_contribution": "Equal risk contribution",
    "hrp": "HRP/HERC (deterministic) ",
    "maximum_diversification": "Maximum diversification",
    "cvar": "CVaR tail-risk baseline",
    "robust_mean_risk": "Robust mean-risk",
}


def portfolio_optimiser_page(page: ft.Page | None, state: AppState) -> ft.Control:
    optimiser, returns = build_portfolio_optimiser(getattr(state.snapshot, "prices", None))
    method = ft.Dropdown(
        key="portfolio-optimiser.method",
        label="Method",
        value="equal_weight",
        options=[ft.dropdown.Option(value, _METHOD_LABELS[value]) for value in METHODS],
        width=260,
        dense=True,
    )
    cash = ft.TextField(key="portfolio-optimiser.cash", label="Cash (%)", value="0", width=140, dense=True)
    maximum = ft.TextField(key="portfolio-optimiser.max-weight", label="Max weight (%)", value="60", width=160, dense=True)
    status = ft.Text(key="portfolio-optimiser.status", color=theme.MUTED, selectable=True)
    result_host = ft.Column(spacing=12)

    def render(message: str | None = None, colour: str = theme.MUTED) -> None:
        try:
            if returns.empty:
                raise ValueError("adjusted-price returns are required")
            constraints = OptimiserConstraints(
                cash_weight=float(str(cash.value or "0")) / 100.0,
                max_weight=float(str(maximum.value or "60")) / 100.0,
            )
            comparison = optimiser.compare(METHODS, constraints=constraints)
            result_host.controls = [_comparison_view(comparison, len(returns), constraints)]
            status.value = message or "Eight transparent methods compared on a held-out local return slice."
            status.color = colour
        except (TypeError, ValueError) as exc:
            result_host.controls = [panel(ft.Text(f"Optimisation unavailable: {exc}", color=theme.AMBER, selectable=True))]
            status.value = f"Optimisation unavailable: {exc}"
            status.color = theme.AMBER
        _safe_update(page)

    def run(_event: ft.ControlEvent | None) -> None:
        render(f"{_METHOD_LABELS.get(str(method.value), str(method.value))} recomputed; no order or proposal was created.", theme.GREEN)

    render()
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header(
                            "Portfolio Optimiser Lab",
                            "Compare constrained research candidates from adjusted-price returns. Solver output is advisory context only; execution remains disabled.",
                        ),
                        ft.Row(
                            [
                                evidence_chip("Authority", "portfolio research only", theme.CYAN),
                                evidence_chip("Data", "adjusted prices", theme.BLUE_GREY),
                                evidence_chip("Fallback", "visible equal weight", theme.AMBER),
                                evidence_chip("Execution", "disabled", theme.GREEN),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Constraints and method", "Cash is held outside invested weights. Solver versions, parameters, feasibility and fingerprints remain visible in the comparison."),
                        ft.Row([method, cash, maximum, ft.Button("Run comparison", key="portfolio-optimiser.run", on_click=run)], wrap=True),
                        status,
                    ],
                    spacing=10,
                )
            ),
            result_host,
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _comparison_view(comparison, observations: int, constraints: OptimiserConstraints) -> ft.Control:
    if comparison.empty:
        return panel(ft.Text("Optimisation unavailable: adjusted-price returns are required.", color=theme.AMBER, selectable=True))
    columns = ["Method", "Status", "Feasible", "Validation return", "Validation volatility", "Max weight", "Binding constraints"]
    rows = []
    for _, row in comparison.iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(_METHOD_LABELS.get(str(row["method"]), str(row["method"])), size=11)),
                    ft.DataCell(ft.Text(str(row["status"]), size=11)),
                    ft.DataCell(ft.Text(str(bool(row["feasible"])).lower(), size=11)),
                    ft.DataCell(ft.Text(_percent(row["validation_return_ann"]), size=11)),
                    ft.DataCell(ft.Text(_percent(row["validation_vol_ann"]), size=11)),
                    ft.DataCell(ft.Text(_percent(row["max_weight"]), size=11)),
                    ft.DataCell(ft.Text(str(row["binding_constraints"] or "none"), size=11)),
                ]
            )
        )
    warning_rows = [str(value) for value in comparison["warnings"] if str(value)]
    fingerprints = [f"{row['method']}={str(row['fingerprint'])[:12]}" for _, row in comparison.iterrows()]
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Risk-return frontier and baseline comparison", f"Held-out observations: {observations}. Naive equal weight remains visible in every comparison."),
                        ft.Row([ft.DataTable(columns=[ft.DataColumn(ft.Text(value)) for value in columns], rows=rows)], scroll=ft.ScrollMode.AUTO),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            panel(
                ft.Column(
                    [
                        ft.Text("Audit and limitations", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text(f"model_version=portfolio-optimiser.v1 | cash_weight={constraints.cash_weight:.1%} | max_weight={constraints.max_weight:.1%} | execution_allowed=false", color=theme.MUTED, selectable=True, size=11),
                        ft.Text("solver_fingerprints=" + "; ".join(fingerprints), color=theme.MUTED, selectable=True, size=11),
                        ft.Text("; ".join(dict.fromkeys(warning_rows)) or "No solver warnings. Input perturbation and concentration diagnostics are available through the local contract.", color=theme.MUTED, selectable=True),
                    ]
                )
            ),
        ],
        spacing=12,
    )


def _percent(value: object) -> str:
    try:
        return "unavailable" if value is None else f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "unavailable"


def _safe_update(page: ft.Page | None) -> None:
    if page is None:
        return
    try:
        page.update()
    except (AssertionError, RuntimeError):
        return


__all__ = ["portfolio_optimiser_page"]
