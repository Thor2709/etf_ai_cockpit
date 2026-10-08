"""Portfolio Optimiser Lab: advisory, local and explicitly non-executable."""

from __future__ import annotations

import math

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.chartkit import Bubble
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    KpiTile,
    Note,
    TableColumn,
    Tag,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_count, format_number, format_percent
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.portfolio_optimiser import METHODS, OptimiserConstraints, build_portfolio_optimiser
from etf_cockpit.application.ui_views.portfolio_optimiser import portfolio_optimiser_view


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
_STATUS_LABELS = {
    "success": ("Available", "ok"),
    "fallback": ("Fallback", "warn"),
    "unavailable": ("Unavailable", "bad"),
}


def portfolio_optimiser_page(page: ft.Page | None, state: AppState) -> PageView:
    optimiser, returns = build_portfolio_optimiser(getattr(state.snapshot, "prices", None))
    model_metadata = portfolio_optimiser_view()
    cash_default = float(state.snapshot.config.targets.cash_target_weight)
    max_weight_default = float(state.snapshot.config.risks.portfolio_limits.max_single_etf_weight)
    method_selection = {"value": "equal_weight"}
    def select_method(label: str) -> None:
        method_selection["value"] = next((key for key, value in _METHOD_LABELS.items() if value == label), "equal_weight")

    method = Field(
        "Method",
        options=[_METHOD_LABELS[key] for key in METHODS],
        value=_METHOD_LABELS[method_selection["value"]],
        on_change=select_method,
        key="portfolio-optimiser.method",
    )
    cash = text_field(
        "Cash (%)",
        "portfolio-optimiser.cash",
        value=format_number(cash_default * 100, decimals=1, unavailable=""),
    )
    maximum = text_field(
        "Max weight (%)",
        "portfolio-optimiser.max-weight",
        value=format_number(max_weight_default * 100, decimals=1, unavailable=""),
    )
    status = {"text": "Unavailable: adjusted-price returns are required."}
    result_table: dict[str, ft.Control] = {
        "control": EmptyState("Comparison unavailable", "Adjusted-price returns are required.")
    }
    frontier: dict[str, ft.Control] = {
        "control": EmptyState("Frontier unavailable", "No held-out validation results are available.")
    }
    weights_by_method: dict[str, ft.Control] = {
        "control": EmptyState(
            "Weights unavailable",
            "Per-method instrument weights are not present in the current comparison result.",
        )
    }
    audit = {"text": "", "details": ""}
    status_note = Note(status["text"])
    table_well = Well(result_table["control"])
    frontier_well = Well(frontier["control"])
    weights_well = Well(weights_by_method["control"])

    def percent(value: object, *, decimals: int = 2) -> str:
        return format_percent(value, decimals=decimals, unavailable="—").replace("-", "−")

    def run(_event: ft.ControlEvent | None = None) -> None:
        if returns.empty:
            status["text"] = "Optimisation unavailable: adjusted-price returns are required."
            result_table["control"] = EmptyState("Comparison unavailable", "Adjusted-price returns are required.")
            frontier["control"] = EmptyState("Frontier unavailable", "No held-out validation results are available.")
            weights_by_method["control"] = EmptyState(
                "Weights unavailable",
                "Per-method instrument weights are not present in the current comparison result.",
            )
            audit["text"] = ""
            audit["details"] = ""
        else:
            try:
                cash_percent = float(input_of(cash).value) if input_of(cash).value else cash_default * 100
                max_percent = float(input_of(maximum).value) if input_of(maximum).value else max_weight_default * 100
                if not math.isfinite(cash_percent) or not math.isfinite(max_percent):
                    raise ValueError("non-finite constraint")
                constraints = OptimiserConstraints(
                    cash_weight=cash_percent / 100,
                    max_weight=max_percent / 100,
                )
                methods = [method_selection["value"], *[method_id for method_id in METHODS if method_id != method_selection["value"]]]
                comparison = optimiser.compare(methods, constraints=constraints)
                rows = []
                points = []
                warnings = []
                for method_id, row in comparison.iterrows():
                    method_id = str(row.get("method", method_id))
                    status_label, status_kind = _STATUS_LABELS.get(str(row.get("status")), ("Unavailable", "bad"))
                    feasible_value = row.get("feasible")
                    feasible = bool(feasible_value) if pd.notna(feasible_value) else None
                    rows.append(
                        {
                            "method": _METHOD_LABELS.get(method_id, method_id),
                            "status": Tag(status_label, status_kind),
                            "feasible": Tag(
                                "Feasible" if feasible else "Not feasible" if feasible is False else "Unavailable",
                                "ok" if feasible else "bad" if feasible is False else "mute",
                            ),
                            "return": percent(row.get("validation_return_ann")),
                            "volatility": percent(row.get("validation_vol_ann")),
                            "max_weight": percent(row.get("max_weight")),
                            "constraints": (
                                Disclosure("binding constraints", str(row.get("binding_constraints")))
                                if pd.notna(row.get("binding_constraints")) and str(row.get("binding_constraints"))
                                else "—"
                            ),
                        }
                    )
                    validation_vol = row.get("validation_vol_ann")
                    validation_return = row.get("validation_return_ann")
                    if pd.notna(validation_vol) and pd.notna(validation_return):
                        points.append(
                            Bubble(
                                _METHOD_LABELS.get(method_id, method_id),
                                float(validation_vol) * 100,
                                float(validation_return) * 100,
                                1.0,
                                _METHOD_LABELS.get(method_id, method_id),
                                method_id == "equal_weight",
                            )
                        )
                    warning = row.get("warnings")
                    if pd.notna(warning) and str(warning):
                        warnings.append(f"{method_id}: {warning}")
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
                table_well.content = result_table["control"]
                method_groups = [
                    (label, theme.CATEGORICAL[index % len(theme.CATEGORICAL)])
                    for index, method_id in enumerate(METHODS)
                    for label in [_METHOD_LABELS[method_id]]
                ]
                frontier["control"] = ck.scatter_bubble(
                    points,
                    groups=method_groups,
                    x_name="Validation volatility (%)",
                    y_name="Validation return (%)",
                    x_unit="%",
                    y_unit="%",
                    insight="Held-out validation return and volatility; equal weight remains visible as the baseline.",
                    unavailable_reason="No held-out method results are available.",
                )
                frontier_well.content = frontier["control"]
                weights_by_method["control"] = EmptyState(
                    "Weights unavailable",
                    "Per-method instrument weights are not present in the current comparison result.",
                )
                weights_well.content = weights_by_method["control"]
                fingerprints = [
                    f"{method_id}={str(row.get('fingerprint'))}"
                    for method_id, row in comparison.iterrows()
                    if pd.notna(row.get("fingerprint"))
                ]
                audit["text"] = "\n".join(fingerprints)
                audit["details"] = "\n".join(
                    [
                        f"Model version: {model_metadata['model_version']}",
                        f"Cash weight: {percent(cash_percent / 100)}",
                        f"Max weight: {percent(max_percent / 100)}",
                        *warnings,
                    ]
                )
                status["text"] = "Transparent methods compared on a held-out local return slice."
            except (TypeError, ValueError):
                status["text"] = "Optimisation unavailable: check the constraint values."
                result_table["control"] = EmptyState("Comparison unavailable", "Check the constraint values.")
                frontier["control"] = EmptyState("Frontier unavailable", "No held-out validation results are available.")
                weights_by_method["control"] = EmptyState(
                    "Weights unavailable",
                    "Per-method instrument weights are not present in the current comparison result.",
                )
                table_well.content = result_table["control"]
                frontier_well.content = frontier["control"]
                weights_well.content = weights_by_method["control"]
        status_note.value = status["text"]
        if page is not None:
            page.update()

    constraints_card = GlassCard(
        "Constraints and method",
        note="cash is held outside invested weights",
        body=ft.Column(
            [
                ft.Row(
                    [KpiTile("Authority", "portfolio research only"), KpiTile("Data", "adjusted prices")],
                    spacing=theme.SPACE_2,
                    wrap=True,
                ),
                ft.Row(
                    [
                        KpiTile("Fallback", "visible equal weight"),
                        KpiTile(
                            "Held-out observations",
                            format_count(len(returns), unavailable="—") if not returns.empty else None,
                            sub="Held-out local return observations" if not returns.empty else "Adjusted-price returns are unavailable",
                        ),
                    ],
                    spacing=theme.SPACE_2,
                    wrap=True,
                ),
                method,
                ft.Row([cash, maximum], spacing=theme.SPACE_2, wrap=True),
                Button.primary("Run comparison", key="portfolio-optimiser.run", on_click=run),
                status_note,
                Note(f"{len(METHODS)} transparent methods compared on a held-out local return slice."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    run()
    cards = [
        constraints_card,
        GlassCard(
            "Risk-return frontier and baseline comparison",
            note="held-out validation slice",
            body=frontier_well,
        ),
        GlassCard("Method comparison", body=table_well),
        GlassCard("Weights by method", body=weights_well),
        GlassCard(
            "Audit and limitations",
            body=ft.Column(
                [
                    Disclosure("model and constraint details", audit["details"] or "Comparison details are unavailable."),
                    Disclosure(
                        "solver fingerprints",
                        f"solver_fingerprints={audit['text'] or 'Unavailable'}",
                    ),
                    Disclosure("Authority boundary", "execution_allowed=false"),
                ],
                spacing=theme.SPACE_2,
            ),
        ),
    ]
    return PageView(
        chrome=PageChrome(
            "Portfolio Optimiser Lab",
            "Constrained research candidates from adjusted-price returns · advisory only",
        ),
        body=page_body(cards),
    )


__all__ = ["portfolio_optimiser_page"]
