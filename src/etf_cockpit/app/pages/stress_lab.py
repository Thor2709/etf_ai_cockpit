from __future__ import annotations

from decimal import Decimal

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    GlassCard,
    KpiTile,
    Note,
    Segmented,
    TableColumn,
    Tag,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_currency, format_percent, format_timestamp
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.stress_lab import (
    StressLabFacade,
    StressLabPersistenceError,
    build_stress_scenario,
)


_SHOCKS = {
    "Equity": "equity",
    "Rates": "rates",
    "FX": "fx",
    "Credit": "credit",
    "Commodity": "commodity",
    "Liquidity": "liquidity",
}
_SCENARIO_FACTORS = {
    "Equity": "equity",
    "Rates": "rates",
    "FX": "fx",
    "Credit": "credit",
    "Commodity": "commodity",
    "Liquidity": "liquidity",
    "Residual": "residual",
}


def _percent_text(shock: object) -> str:
    """Shock fraction as an exact percent string: at least two decimals, never rounded, no thousands separators."""
    text = format((Decimal(repr(float(shock))) * 100).normalize(), "f")
    whole, _point, fraction = text.partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}"


def stress_factor_categories(factor_values: dict[str, object]) -> list[tuple[str, str]]:
    """Chart categories: the standard factors plus every other returned factor (e.g. ``factor:*``), never dropped."""
    known = set(_SCENARIO_FACTORS.values())
    extra = sorted(key for key in factor_values if key not in known and key != "None")
    return [*_SCENARIO_FACTORS.items(), *((key, key) for key in extra)]


def stress_lab_page(page: ft.Page | None, state: AppState) -> PageView:
    facade = StressLabFacade(state.snapshot)
    currency = str(state.snapshot.config.targets.base_currency)
    fields = {
        "scenario_id": text_field("Scenario ID", "stress-lab.scenario-id"),
        "name": text_field("Scenario name", "stress-lab.name"),
        "historical_date": text_field("Historical adjusted-return date (optional)", "stress-lab.historical-date"),
        "equity": text_field("Equity (%)", "stress-lab.equity"),
        "rates": text_field("Rates (%)", "stress-lab.rates"),
        "fx": text_field("FX (%)", "stress-lab.fx"),
        "credit": text_field("Credit (%)", "stress-lab.credit"),
        "commodity": text_field("Commodity (%)", "stress-lab.commodity"),
        "liquidity": text_field("Liquidity cost (%)", "stress-lab.liquidity"),
        "notional": text_field("Notional", "stress-lab.notional"),
        "reverse_limit": text_field("Reverse loss limit", "stress-lab.loss-limit"),
    }
    reverse_shock = {"value": "equity"}
    shown = {"scenario": False, "reverse": False}
    # Scenario attributes the input fields cannot show; kept from a loaded scenario so Save/Run never drop them.
    carried: dict[str, object] = {"horizon_days": 1, "version": 1, "extra_shocks": {}}
    revisions: dict[str, int] = {}
    result_host = Well(
        EmptyState(
            "No scenario run yet",
            "Instrument contributions and factor contributions (including residual) appear after a scenario run.",
        )
    )
    instrument_host = Well(EmptyState("Unavailable", "Instrument contributions appear after a scenario run."))
    result_note = Note("Scenario result unavailable until a scenario has been run.")
    result_insight = Note("Scenario result is not a forecast.")
    result_card_host: dict[str, ft.Control | None] = {"control": None}
    reverse_host = Well(
        ck.line_chart(
            [],
            [],
            x_name="Dimension shock (%)",
            y_name=f"Loss ({currency})",
            unavailable_reason="Run reverse stress to receive a threshold; an existing loss curve is not available.",
            insight="Reverse stress threshold evidence.",
        )
    )
    reverse_threshold = ft.Column(
        [KpiTile("Reverse shock threshold", None, sub="No reverse stress result is available.")],
        spacing=theme.SPACE_2,
    )
    reverse_details = ft.Container(content=Disclosure("reverse result", "Reverse stress has not been run."))
    status_note = Note("No probability or execution authority is created; execution_allowed=false.")

    def scenario_from_controls():
        shocks = dict(carried["extra_shocks"])
        for name in _SHOCKS.values():
            value = input_of(fields[name]).value
            if value:
                shocks[name] = float(value) / 100.0
        return build_stress_scenario(
            scenario_id=input_of(fields["scenario_id"]).value or "",
            name=input_of(fields["name"]).value or "",
            shocks=shocks,
            horizon_days=carried["horizon_days"],
            version=carried["version"],
            historical_date=(input_of(fields["historical_date"]).value or "").strip() or None,
        )

    def invalidate_outputs(_event: object | None = None) -> None:
        """Inputs changed: scenario and reverse-stress outputs no longer describe them, so they are reset."""
        if not shown["scenario"] and not shown["reverse"]:
            return
        if shown["scenario"]:
            result_host.content = EmptyState("No scenario run yet", "Inputs changed; run the scenario again.")
            instrument_host.content = EmptyState("Unavailable", "Inputs changed; run the scenario again.")
            result_note.value = "Scenario result unavailable until a scenario has been run."
            result_insight.value = "Scenario result is not a forecast."
            result_details.content = Disclosure("scenario details", "No scenario run yet.")
            if result_card_host["control"] is not None:
                result_card_host["control"].data["note_control"].value = f"Scenario · P&L in {currency}"
        if shown["reverse"]:
            reverse_threshold.controls = [KpiTile("Reverse shock threshold", None, sub="Inputs changed; run reverse stress again.")]
            reverse_details.content = Disclosure("reverse result", "Reverse stress has not been run.")
        shown.update(scenario=False, reverse=False)
        show_status("Inputs changed; earlier results were cleared.")

    def show_status(message: str) -> None:
        status_note.value = message
        if page is not None:
            page.update()

    def run(_event: ft.ControlEvent | None) -> None:
        try:
            raw_notional = input_of(fields["notional"]).value
            if not raw_notional:
                raise ValueError
            notional = float(raw_notional)
            shown["scenario"] = True
            result = facade.run(scenario_from_controls(), notional=notional)
            factor_values = {
                str(row.get("factor")): row.get("pnl")
                for row in result.factor_contributions
                if row.get("pnl") is not None and pd.notna(row.get("pnl"))
            }
            factor_categories = stress_factor_categories(factor_values)
            categories = [*(label for label, _key in factor_categories), "Total"]
            values = []
            bases = []
            cumulative = 0.0
            for _label, key in factor_categories:
                value = factor_values.get(key)
                if value is None:
                    values.append(None)
                    bases.append(None)
                else:
                    values.append(float(value))
                    bases.append(cumulative)
                    cumulative += float(value)
            values.append(float(result.total_pnl) if result.total_pnl is not None else None)
            bases.append(0.0 if result.total_pnl is not None else None)
            if result.total_pnl is None:
                result_host.content = EmptyState(
                    "Scenario result unavailable",
                    "No complete adjusted-return or explicit-shock result is available for the selected holdings.",
                )
                result_insight.value = "Scenario P&L is unavailable for the selected evidence."
            else:
                result_host.content = ck.bar_chart(
                    categories,
                    values,
                    bases=bases,
                    kinds=["neg" if value is not None and value < 0 else "pos" for value in values],
                    x_name="Shock factor",
                    y_name=f"P&L ({currency})",
                    unit=currency,
                    insight="Scenario factor contributions, including residual and total.",
                    unavailable_reason="Scenario factor contributions are unavailable.",
                )
                equity_share = next(
                    (row.get("share") for row in result.factor_contributions if row.get("factor") == "equity"),
                    None,
                )
                loss_label = "gains" if result.total_pnl > 0 else "loses" if result.total_pnl < 0 else "is unchanged"
                loss_percent = format_percent(result.total_pnl / notional, decimals=2, unavailable="—")
                equity_percent = format_percent(equity_share, decimals=1, unavailable="—")
                result_insight.value = (
                    f"The scenario {loss_label} {format_currency(result.total_pnl, currency=currency).replace('-', '−')} "
                    f"({loss_percent}); equity explains {equity_percent}."
                )
            instruments = list(result.instrument_contributions)
            if instruments:
                instrument_host.content = ck.bar_chart(
                    [str(row.get("instrument_id", "—")) for row in instruments],
                    [row.get("pnl") for row in instruments],
                    kinds=["neg" if row.get("pnl") is not None and row["pnl"] < 0 else "pos" for row in instruments],
                    x_name="Instrument",
                    y_name=f"P&L ({currency})",
                    unit=currency,
                    insight="Instrument contributions to the scenario result.",
                    unavailable_reason="Instrument contributions are unavailable.",
                )
            else:
                instrument_host.content = EmptyState(
                    "Instrument contributions unavailable",
                    "No instrument contributions were returned for this scenario.",
                )
            scenario_status = {"available": "Available", "partial": "Partial", "unavailable": "Unavailable"}.get(
                str(result.status),
                "Unavailable",
            )
            result_note.value = (
                f"{scenario_status} · Total P&L: {format_currency(result.total_pnl, currency=currency).replace('-', '−')}"
                if result.total_pnl is not None
                else f"{scenario_status} · Total P&L is unavailable for the selected evidence."
            )
            result_details.content = str(result.to_payload())
            if result_card_host["control"] is not None:
                result_card_host["control"].data["note_control"].value = f"{result.scenario.name} · P&L in {currency}"
            show_status("Scenario result is local evidence only; no execution authority was created.")
        except (TypeError, ValueError):
            result_host.content = EmptyState(
                "Scenario unavailable",
                "Complete the required scenario inputs and use adjusted-price evidence.",
            )
            instrument_host.content = EmptyState(
                "Instrument contributions unavailable",
                "No scenario result is available.",
            )
            result_note.value = "Total P&L is unavailable."
            result_insight.value = "Scenario P&L is unavailable for the selected evidence."
            result_details.content = "Scenario result is unavailable."
            show_status("Scenario unavailable: complete the required inputs.")

    def save(_event: ft.ControlEvent | None) -> None:
        try:
            scenario = scenario_from_controls()
            saved = facade.save(scenario, expected_revision=revisions.get(scenario.scenario_id, 0))
            revisions[scenario.scenario_id] = saved.revision
            show_status("Scenario saved locally.")
        except Exception:
            show_status("Scenario was not saved; local storage may be unavailable or conflicting.")

    def load(_event: ft.ControlEvent | None) -> None:
        try:
            saved = facade.load((input_of(fields["scenario_id"]).value or "").strip())
            revisions[saved.scenario.scenario_id] = saved.revision
            input_of(fields["name"]).value = saved.scenario.name
            input_of(fields["historical_date"]).value = saved.scenario.historical_date or ""
            for name in _SHOCKS.values():
                input_of(fields[name]).value = ""
            carried.update(horizon_days=getattr(saved.scenario, "horizon_days", 1), version=getattr(saved.scenario, "version", 1), extra_shocks={})
            for name, value in saved.scenario.shocks.items():
                if name in _SHOCKS.values():
                    input_of(fields[name]).value = _percent_text(value)
                else:
                    carried["extra_shocks"][name] = float(value)
            invalidate_outputs()
            show_status("Saved local scenario loaded and verified.")
        except Exception:
            show_status("Saved scenario unavailable; it may be missing, corrupt or conflicting.")

    def reverse(_event: ft.ControlEvent | None) -> None:
        try:
            shown["reverse"] = True
            result = facade.reverse(
                shock_name=reverse_shock["value"],
                loss_limit=float(input_of(fields["reverse_limit"]).value),
                notional=float(input_of(fields["notional"]).value),
            )
            threshold = result.get("threshold")
            reverse_threshold.controls = [
                KpiTile(
                    "Reverse shock threshold",
                    format_percent(threshold, decimals=2, unavailable="—") if threshold is not None else None,
                    sub=(
                        "Smallest shock that breaches the configured limit"
                        if threshold is not None
                        else "The configured loss limit was not reached or a threshold is unavailable"
                    ),
                )
            ]
            status_label = {"available": "Available", "not_reached": "Limit not reached", "unavailable": "Unavailable"}.get(
                str(result.get("status")),
                "Unavailable",
            )
            reverse_details.content = Disclosure("reverse result", str(result))
            reverse_host.content = ck.line_chart(
                [],
                [],
                x_name="Dimension shock (%)",
                y_name=f"Loss ({currency})",
                unavailable_reason="The reverse stress result provides a threshold, not a loss curve.",
                insight="Reverse stress threshold evidence.",
            )
            show_status(f"Reverse stress result: {status_label}.")
        except (TypeError, ValueError):
            shown["reverse"] = True
            reverse_threshold.controls = [
                KpiTile("Reverse shock threshold", None, sub="Complete the reverse shock, loss limit and notional inputs.")
            ]
            reverse_details.content = Disclosure("reverse result", "Reverse stress result is unavailable.")
            show_status("Reverse stress unavailable: complete the required inputs.")

    def scenario_id_changed(_event: object | None = None) -> None:
        carried.update(horizon_days=1, version=1, extra_shocks={})  # loaded extras belong to the previously loaded ID
        invalidate_outputs()

    for field_name, field in fields.items():
        input_of(field).on_change = scenario_id_changed if field_name == "scenario_id" else invalidate_outputs

    def select_reverse_shock(label: str) -> None:
        reverse_shock.update(value=_SHOCKS[label])
        invalidate_outputs()

    shock_selector = Segmented(list(_SHOCKS), "Equity", on_change=select_reverse_shock)
    shock_selector_field = ft.Column([Note("Reverse shock"), shock_selector], spacing=theme.SPACE_1)

    assumptions = GlassCard(
        "Scenario assumptions",
        note="shocks in % · versioned with checksums",
        body=ft.Column(
            [
                ft.Row(
                    [
                        KpiTile("Authority", "evidence only"),
                        KpiTile("Data", "adjusted prices"),
                        KpiTile("Execution", "disabled", tone="neg"),
                    ],
                    spacing=theme.SPACE_2,
                    wrap=True,
                ),
                ft.Column(
                    [fields[name] for name in ("scenario_id", "name", "historical_date", "equity", "rates", "fx", "credit", "commodity", "liquidity", "notional")],
                    spacing=theme.SPACE_2,
                    tight=True,
                ),
                ft.Row(
                    [
                        Button.primary("Run scenario", key="stress-lab.run", on_click=run),
                        Button.secondary("Save scenario", key="stress-lab.save", on_click=save),
                        Button.secondary("Load scenario", key="stress-lab.load", on_click=load),
                    ],
                    spacing=theme.SPACE_2,
                    wrap=True,
                ),
                status_note,
            ],
            spacing=theme.SPACE_2,
        ),
    )
    result_details = ft.Container(content=Disclosure("scenario details", "No scenario run yet."))
    result_card = GlassCard(
        "Scenario result",
        note=f"Scenario · P&L in {currency}",
        insight="The scenario result is evidence, not a forecast.",
        body=ft.Column(
            [
                result_note,
                result_insight,
                result_host,
                result_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )
    result_card_host["control"] = result_card
    instrument_card = GlassCard("Instrument contributions", body=instrument_host)
    reverse_card = GlassCard(
        "Reverse stress",
        note="smallest shock that breaches the limit",
        body=ft.Column(
            [
                shock_selector_field,
                fields["reverse_limit"],
                reverse_threshold,
                reverse_host,
                Button.primary("Run reverse stress", key="stress-lab.reverse", on_click=reverse),
                reverse_details,
                ft.Row([Tag("Probability: not estimated", "warn")]),
                Note("No probability or execution authority is created; execution_allowed=false."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    try:
        saved_rows = [
            {
                "scenario": item.scenario.scenario_id or "—",
                "name": item.scenario.name or "—",
                "saved": format_timestamp(item.updated_at, unavailable="—"),
                "checksum": Disclosure("checksum", "No checksum is returned by the saved scenario view."),
                "status": Tag("Available", "ok"),
            }
            for item in facade.list_saved()
        ]
        saved_reason = "No readable local scenarios are available."
    except StressLabPersistenceError:
        saved_rows = []
        saved_reason = "Saved scenarios are unavailable; local storage may be unavailable or conflicting."
    saved_table = DataTable(
        [
            TableColumn("scenario", "Scenario"),
            TableColumn("name", "Name"),
            TableColumn("saved", "Saved"),
            TableColumn("checksum", "Checksum"),
            TableColumn("status", "Status"),
        ],
        saved_rows,
        empty_title="Saved scenarios unavailable",
        empty_reason=saved_reason,
    )
    cards = [
        assumptions,
        result_card,
        instrument_card,
        reverse_card,
        GlassCard("Saved local scenarios", body=Well(saved_table)),
    ]
    return PageView(
        chrome=PageChrome("Stress Lab", "Historical replay and explicit hypothetical shocks · not forecasts"),
        body=page_body(cards),
    )


__all__ = ["stress_lab_page"]
