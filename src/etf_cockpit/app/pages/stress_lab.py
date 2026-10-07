from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import Button, DataTable, Disclosure, EmptyState, GlassCard, KpiTile, Note, TableColumn
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.stress_lab import StressLabFacade, StressLabPersistenceError, build_stress_scenario


def stress_lab_page(page: ft.Page | None, state: AppState) -> PageView:
    facade = StressLabFacade(state.snapshot)
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
    revision = 0
    result_host: dict[str, ft.Control] = {
        "control": EmptyState(
            "No scenario run yet",
            "Instrument contributions and factor contributions (including residual) appear after a scenario run.",
        )
    }
    instrument_host: dict[str, ft.Control] = {
        "control": EmptyState("Unavailable", "Instrument contributions are available after a scenario run.")
    }
    status = ft.Text("No probability or execution authority is created; execution_allowed=false.")

    def scenario_from_controls():
        def percent(name: str) -> float:
            value = input_of(fields[name]).value
            return float(value) / 100.0 if value else 0.0

        return build_stress_scenario(
            scenario_id=input_of(fields["scenario_id"]).value or "",
            name=input_of(fields["name"]).value or "",
            shocks={name: percent(name) for name in ("equity", "rates", "fx", "credit", "commodity", "liquidity")},
            historical_date=(input_of(fields["historical_date"]).value or "").strip() or None,
        )

    def show_status(message: str) -> None:
        status.value = message
        if page is not None:
            page.update()

    def run(_event: ft.ControlEvent | None) -> None:
        try:
            raw_notional = input_of(fields["notional"]).value
            if not raw_notional:
                raise ValueError
            result = facade.run(scenario_from_controls(), notional=float(raw_notional))
            factor_rows = list(result.factor_contributions)
            instrument_rows = list(result.instrument_contributions)
            result_host["control"] = ck.bar_chart(
                [str(row["factor"]) for row in factor_rows],
                [row["pnl"] for row in factor_rows],
                x_name="Shock factor",
                y_name="P&L",
                unit="",
                insight="Scenario factor contributions, including residual.",
                unavailable_reason="Scenario factor contributions are unavailable.",
            )
            instrument_host["control"] = ck.bar_chart(
                [str(row["instrument_id"]) for row in instrument_rows],
                [row["pnl"] for row in instrument_rows],
                x_name="Instrument",
                y_name="P&L",
                insight="Instrument contributions to the scenario result.",
                unavailable_reason="Instrument contributions are unavailable.",
            )
            show_status("Scenario result is local evidence only; no execution authority was created.")
        except Exception:
            result_host["control"] = EmptyState("Scenario unavailable", "Complete the scenario inputs and use adjusted-price evidence.")
            show_status("Scenario unavailable: complete the required inputs.")

    def save(_event: ft.ControlEvent | None) -> None:
        nonlocal revision
        try:
            saved = facade.save(scenario_from_controls(), expected_revision=revision)
            revision = saved.revision
            show_status("Scenario saved locally.")
        except Exception:
            show_status("Scenario was not saved; local storage may be unavailable or conflicting.")

    def load(_event: ft.ControlEvent | None) -> None:
        nonlocal revision
        try:
            saved = facade.load((input_of(fields["scenario_id"]).value or "").strip())
            revision = saved.revision
            input_of(fields["name"]).value = saved.scenario.name
            input_of(fields["historical_date"]).value = saved.scenario.historical_date or ""
            for name, value in saved.scenario.shocks.items():
                if name in fields:
                    input_of(fields[name]).value = f"{float(value) * 100:g}"
            show_status("Saved local scenario loaded and verified.")
        except Exception:
            show_status("Saved scenario unavailable; it may be missing, corrupt or conflicting.")

    def reverse(_event: ft.ControlEvent | None) -> None:
        try:
            result = facade.reverse(
                shock_name=reverse_shock["value"],
                loss_limit=float(input_of(fields["reverse_limit"]).value),
                notional=float(input_of(fields["notional"]).value),
            )
            show_status(f"Reverse stress {result['status']}; execution_allowed=false.")
        except Exception:
            show_status("Reverse stress unavailable: complete the required inputs.")

    assumptions = GlassCard(
        "Scenario assumptions",
        note="shocks in % · versioned with checksums",
        body=ft.Column(
            [
                ft.Row([KpiTile("Authority", "evidence only"), KpiTile("Data", "adjusted prices"), KpiTile("Execution", "disabled", tone="neg")], wrap=True),
                ft.Row([fields[name] for name in ("scenario_id", "name", "historical_date")], wrap=True),
                ft.Row([fields[name] for name in ("equity", "rates", "fx", "credit", "commodity", "liquidity", "notional")], wrap=True),
                ft.Row(
                    [
                        Button.primary("Run scenario", key="stress-lab.run", on_click=run),
                        Button.secondary("Save scenario", key="stress-lab.save", on_click=save),
                        Button.secondary("Load scenario", key="stress-lab.load", on_click=load),
                    ],
                    wrap=True,
                ),
                status,
            ],
            spacing=theme.SPACE_2,
        ),
    )
    reverse_card = GlassCard(
        "Reverse stress",
        note="smallest shock that breaches the limit",
        body=ft.Column(
            [
                fields["reverse_limit"],
                ck.line_chart([], [], x_name="Dimension shock (%)", y_name="Loss", unavailable_reason="Reverse stress has not been run.", insight="Reverse stress loss threshold."),
                Button.primary("Run reverse stress", key="stress-lab.reverse", on_click=reverse),
                Note("No probability or execution authority is created; execution_allowed=false."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    try:
        saved_rows = [
            {"scenario": item.scenario.scenario_id, "name": item.scenario.name, "saved": "—", "checksum": "—", "status": "Available"}
            for item in facade.list_saved()
        ]
    except StressLabPersistenceError:
        saved_rows = []
    saved_table = DataTable(
        [TableColumn("scenario", "Scenario"), TableColumn("name", "Name"), TableColumn("saved", "Saved"), TableColumn("checksum", "Checksum"), TableColumn("status", "Status")],
        saved_rows,
        empty_title="Saved scenarios unavailable",
        empty_reason="No readable local scenarios are available.",
    )
    cards = [
        assumptions,
        GlassCard("Scenario result", note="scenario · P&L", body=result_host["control"]),
        GlassCard("Instrument contributions", body=instrument_host["control"]),
        reverse_card,
        GlassCard("Saved local scenarios", body=Disclosure("hashes and records", saved_table)),
    ]
    return PageView(
        chrome=PageChrome("Stress Lab", "Historical replay and explicit hypothetical shocks · not forecasts"),
        body=page_body(cards),
    )


__all__ = ["stress_lab_page"]
