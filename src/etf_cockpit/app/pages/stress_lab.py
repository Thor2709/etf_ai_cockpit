"""Stress Lab: local, deterministic scenario evidence without execution authority."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.stress_lab import (
    StressLabFacade,
    StressLabPersistenceError,
    build_stress_scenario,
)


def stress_lab_page(page: ft.Page | None, state: AppState) -> ft.Control:
    facade = StressLabFacade(state.snapshot)
    scenario_id = ft.TextField(label="Scenario ID", value="baseline-stress", key="stress-lab.scenario-id", width=180, dense=True)
    name = ft.TextField(label="Scenario name", value="Equity drawdown", key="stress-lab.name", width=220, dense=True)
    equity = ft.TextField(label="Equity (%)", value="-10", key="stress-lab.equity", width=120, dense=True)
    rates = ft.TextField(label="Rates (%)", value="0", key="stress-lab.rates", width=120, dense=True)
    fx = ft.TextField(label="FX (%)", value="0", key="stress-lab.fx", width=120, dense=True)
    credit = ft.TextField(label="Credit (%)", value="0", key="stress-lab.credit", width=120, dense=True)
    commodity = ft.TextField(label="Commodity (%)", value="0", key="stress-lab.commodity", width=140, dense=True)
    liquidity = ft.TextField(label="Liquidity cost (%)", value="0", key="stress-lab.liquidity", width=150, dense=True)
    historical_date = ft.TextField(label="Historical adjusted-return date (optional)", key="stress-lab.historical-date", width=280, dense=True)
    notional = ft.TextField(label="Notional", value="100000", key="stress-lab.notional", width=140, dense=True)
    loss_limit = ft.TextField(label="Reverse loss limit", value="10000", key="stress-lab.loss-limit", width=160, dense=True)
    reverse_name = ft.Dropdown(
        label="Reverse shock",
        value="equity",
        key="stress-lab.reverse-shock",
        width=150,
        dense=True,
        options=[ft.dropdown.Option(value) for value in ("equity", "rates", "fx", "credit", "commodity", "liquidity")],
    )
    status = ft.Text("No probability or execution authority is created; execution_allowed=false.", color=theme.MUTED, selectable=True, key="stress-lab.status")
    result_host = ft.Column(
        [ft.Text("Instrument contributions and factor contributions (including residual) appear after a scenario run.", color=theme.MUTED, selectable=True)],
        spacing=8,
    )
    revision = 0
    current_scenario = None

    def show(message: str, colour: str = theme.MUTED) -> None:
        status.value = message
        status.color = colour
        _safe_update(page)

    def scenario_from_controls():
        return build_stress_scenario(
            scenario_id=scenario_id.value or "",
            name=name.value or "",
            shocks={
                "equity": _percent_value(equity.value),
                "rates": _percent_value(rates.value),
                "fx": _percent_value(fx.value),
                "credit": _percent_value(credit.value),
                "commodity": _percent_value(commodity.value),
                "liquidity": _percent_value(liquidity.value),
            },
            historical_date=(historical_date.value or "").strip() or None,
        )

    def run(_event: ft.ControlEvent | None) -> None:
        nonlocal current_scenario
        try:
            current_scenario = scenario_from_controls()
            result = facade.run(current_scenario, notional=_number(notional.value, "notional"))
            result_host.controls = [_result_view(result)]
            show(f"{current_scenario.name}: {result.status}; scenario PnL is evidence only.", theme.GREEN if result.status == "available" else theme.AMBER)
        except Exception as exc:
            result_host.controls = [ft.Text(f"Stress scenario unavailable: {exc}", color=theme.AMBER, selectable=True)]
            show(f"Stress scenario unavailable: {exc}", theme.AMBER)

    def save(_event: ft.ControlEvent | None) -> None:
        nonlocal current_scenario, revision
        try:
            current_scenario = current_scenario or scenario_from_controls()
            saved = facade.save(current_scenario, expected_revision=revision)
            revision = saved.revision
            show(f"Saved local scenario {saved.scenario.scenario_id} revision {saved.revision}; prior revisions remain auditable.", theme.GREEN)
        except Exception as exc:
            show(f"Scenario was not saved: {exc}", theme.AMBER)

    def load(_event: ft.ControlEvent | None) -> None:
        nonlocal current_scenario, revision
        try:
            saved = facade.load((scenario_id.value or "").strip())
            current_scenario = saved.scenario
            revision = saved.revision
            name.value = saved.scenario.name
            historical_date.value = saved.scenario.historical_date or ""
            for field, shock_name in ((equity, "equity"), (rates, "rates"), (fx, "fx"), (credit, "credit"), (commodity, "commodity"), (liquidity, "liquidity")):
                field.value = f"{float(saved.scenario.shocks.get(shock_name, 0.0)) * 100:g}"
            show(f"Loaded local scenario {saved.scenario.scenario_id} revision {saved.revision}; assumptions were checksum-verified.", theme.GREEN)
        except Exception as exc:
            show(f"Scenario was not loaded: {exc}", theme.AMBER)

    def reverse(_event: ft.ControlEvent | None) -> None:
        try:
            result = facade.reverse(
                shock_name=str(reverse_name.value or "equity"),
                loss_limit=_number(loss_limit.value, "loss limit"),
                notional=_number(notional.value, "notional"),
            )
            result_host.controls = [_reverse_view(result)]
            show(f"Reverse stress: {result['status']}; threshold remains a deterministic scenario boundary.", theme.GREEN if result["status"] == "available" else theme.AMBER)
        except Exception as exc:
            show(f"Reverse stress unavailable: {exc}", theme.AMBER)

    saved = _saved_view(facade)
    return ft.Column(
        [
            panel(ft.Column([
                section_header("Stress Lab", "Replay adjusted-price history or apply explicit hypothetical shocks. Coverage, limitations and nonlinear gaps remain visible."),
                ft.Row([
                    evidence_chip("Authority", "evidence only", theme.CYAN),
                    evidence_chip("Data", "adjusted prices", theme.BLUE_GREY),
                    evidence_chip("Execution", "disabled", theme.GREEN),
                    evidence_chip("Probability", "not estimated", theme.AMBER),
                ], wrap=True),
            ], spacing=10)),
            panel(ft.Column([
                section_header("Scenario assumptions", "Values are decimal shocks entered as percentages. Saved scenarios are versioned local records with checksums."),
                ft.Row([scenario_id, name, historical_date], wrap=True),
                ft.Row([equity, rates, fx, credit, commodity, liquidity], wrap=True),
                ft.Row([notional, ft.Button("Run scenario", key="stress-lab.run", on_click=run), ft.Button("Save scenario", key="stress-lab.save", on_click=save), ft.Button("Load scenario", key="stress-lab.load", on_click=load)], wrap=True),
            ], spacing=8)),
            panel(ft.Column([
                section_header("Reverse stress", "Find the smallest monotonic shock in the selected dimension that breaches the loss limit."),
                ft.Row([reverse_name, loss_limit, ft.Button("Run reverse stress", key="stress-lab.reverse", on_click=reverse)], wrap=True),
            ], spacing=8)),
            status,
            result_host,
            saved,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


def _result_view(result) -> ft.Control:
    instrument_rows = [
        ft.DataRow(cells=[ft.DataCell(ft.Text(str(row["instrument_id"]))), ft.DataCell(ft.Text(_display(row["pnl"]))), ft.DataCell(ft.Text(str(row["source"]))), ft.DataCell(ft.Text(str(row["factor_components"])))])
        for row in result.instrument_contributions
    ]
    factor_rows = [
        ft.DataRow(cells=[ft.DataCell(ft.Text(str(row["factor"]))), ft.DataCell(ft.Text(_display(row["pnl"]))), ft.DataCell(ft.Text(_display(row["share"])))])
        for row in result.factor_contributions
    ]
    rows = [
        ft.Text(f"status={result.status} | total_pnl={_display(result.total_pnl)} | execution_allowed=false", selectable=True),
        ft.Text(f"coverage={result.coverage}", selectable=True, size=11),
        ft.Text("Instrument contributions", weight=ft.FontWeight.BOLD),
        ft.DataTable(columns=[ft.DataColumn(ft.Text(label)) for label in ("Instrument", "PnL", "Source", "Components")], rows=instrument_rows),
        ft.Text("Factor contributions (including residual)", weight=ft.FontWeight.BOLD),
        ft.DataTable(columns=[ft.DataColumn(ft.Text(label)) for label in ("Factor", "PnL", "Share")], rows=factor_rows),
        ft.Text("limitations=" + " | ".join(result.limitations), selectable=True, size=11),
    ]
    return panel(ft.Column(rows, spacing=6))


def _reverse_view(result: dict[str, object]) -> ft.Control:
    return panel(ft.Text(f"{result['shock_name']} | status={result['status']} | threshold={_display(result['threshold'])} | binding={result['binding_exposure']} | execution_allowed=false", selectable=True))


def _saved_view(facade: StressLabFacade) -> ft.Control:
    try:
        rows = [ft.Text(f"{item.scenario.scenario_id} | v{item.scenario.version} | revision={item.revision} | assumptions={item.scenario.shocks}", selectable=True, size=11) for item in facade.list_saved()]
    except StressLabPersistenceError as exc:
        rows = [ft.Text(f"Saved scenarios unavailable: {exc}", color=theme.AMBER, selectable=True)]
    return panel(ft.Column([section_header("Saved local scenarios", "Corrupt or conflicting records remain visible as unavailable and never grant execution authority."), *rows], spacing=6))


def _percent_value(value: str | None) -> float:
    return float(str(value or "0")) / 100.0


def _number(value: str | None, label: str) -> float:
    parsed = float(str(value or ""))
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return parsed


def _display(value: object) -> str:
    return "unavailable" if value is None else f"{float(value):.4f}"


def _safe_update(page: ft.Page | None) -> None:
    if page is None:
        return
    try:
        page.update()
    except (AssertionError, RuntimeError):
        return


__all__ = ["stress_lab_page"]
