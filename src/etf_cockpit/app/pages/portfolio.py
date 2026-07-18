"""Interactive local portfolio candidate sandbox."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    PortfolioAnalysis,
    PortfolioCandidate,
    PortfolioSandboxPersistenceError,
    StorageRevisionConflict,
    analyse_portfolio_candidate,
    build_portfolio_candidate,
    candidate_id,
    draft_portfolio_candidate,
    load_portfolio_candidate,
    save_portfolio_candidate,
)


def portfolio_page(page: ft.Page | None, state: AppState) -> ft.Control:
    """Render editable research candidates without creating executable intent."""

    initial = draft_portfolio_candidate(state.snapshot)
    saved_revision = [0]
    saved_candidate_id: list[str | None] = [None]
    universe = {
        str(item.id): item
        for item in state.snapshot.config.universe.etfs
        if bool(item.enabled)
    }
    name = ft.TextField(
        key="portfolio.workspace-name",
        label="Candidate name",
        value=initial.name,
        width=260,
        dense=True,
    )
    notional = ft.TextField(
        key="portfolio.analysis-notional",
        label="Analysis notional (EUR)",
        value=f"{initial.analysis_notional_eur:.2f}",
        width=220,
        dense=True,
    )
    target_inputs = {
        instrument_id: ft.TextField(
            key=f"portfolio.target-weight.{instrument_id}",
            label=f"{instrument_id} target (%)",
            value=f"{initial.targets.get(instrument_id, 0.0) * 100:.4f}",
            width=190,
            dense=True,
        )
        for instrument_id in sorted(universe)
    }
    cash = ft.TextField(
        key="portfolio.cash-weight",
        label="Cash target (%)",
        value=f"{initial.cash_weight * 100:.4f}",
        width=190,
        dense=True,
    )
    initial_status = "Unsaved candidate. Edit weights and select Analyse candidate."
    if state.snapshot.holdings.empty:
        initial_status = "No current holdings are available. Candidate targets can still be analysed from a zero-current baseline."
    status = ft.Text(
        initial_status,
        key="portfolio.status",
        color=theme.MUTED,
        selectable=True,
    )
    result_host = ft.Column(
        [_analysis_view(analyse_portfolio_candidate(state.snapshot, initial))],
        key="portfolio.results",
        spacing=12,
    )

    def values() -> tuple[str, str, dict[str, object], object]:
        targets: dict[str, object] = {}
        for instrument_id, control in target_inputs.items():
            targets[instrument_id] = _percentage(control.value)
        return str(name.value or ""), str(notional.value or ""), targets, _percentage(cash.value)

    def refresh(candidate: PortfolioCandidate, *, message: str, colour: str = theme.GREEN) -> None:
        analysis = analyse_portfolio_candidate(state.snapshot, candidate)
        result_host.controls = [_analysis_view(analysis)]
        status.value = message
        status.color = colour
        state.last_message = message
        _safe_update(page)

    def analyse(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
            )
            message = "Candidate analysed from the current local snapshot; execution remains disabled."
            if saved_revision[0]:
                message += " Save to create the next local revision."
            refresh(candidate, message=message)
        except (TypeError, ValueError) as exc:
            status.value = f"Candidate not analysed: {exc}"
            status.color = theme.AMBER
            result_host.controls = [
                panel(ft.Text("Candidate results are unavailable until the validation error is corrected.", color=theme.AMBER, selectable=True))
            ]
            _safe_update(page)

    def save(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            identity = candidate_id(candidate_name)
            saved = save_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                expected_revision=saved_revision[0] if saved_candidate_id[0] == identity else 0,
            )
            saved_revision[0] = saved.revision
            saved_candidate_id[0] = saved.candidate.candidate_id
            refresh(
                saved.candidate,
                message=f"Saved local candidate revision {saved.revision}; no order or proposal was created.",
            )
        except StorageRevisionConflict as exc:
            status.value = f"Candidate not saved because a newer local revision exists: {exc}"
            status.color = theme.AMBER
            _safe_update(page)
        except (OSError, PortfolioSandboxPersistenceError, TypeError, ValueError) as exc:
            status.value = f"Candidate not saved: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def load(_event: ft.ControlEvent | None) -> None:
        try:
            saved = load_portfolio_candidate(state.snapshot, str(name.value or ""))
            saved_revision[0] = saved.revision
            saved_candidate_id[0] = saved.candidate.candidate_id
            _apply_candidate(saved.candidate, name, notional, target_inputs, cash)
            message = f"Loaded local candidate revision {saved.revision}."
            colour = theme.GREEN
            if saved.source_stale:
                message += " Its source binding changed, so derived values were re-evaluated from the current snapshot."
                colour = theme.AMBER
            refresh(saved.candidate, message=message, colour=colour)
        except (OSError, PortfolioSandboxPersistenceError, TypeError, ValueError) as exc:
            status.value = f"Candidate not loaded: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def reset_current(_event: ft.ControlEvent | None) -> None:
        current = {instrument_id: 0.0 for instrument_id in target_inputs}
        for _, row in state.snapshot.holdings.iterrows():
            instrument_id = str(row.get("etf_id", row.get("instrument_id", "")))
            if instrument_id in current:
                current[instrument_id] += float(row.get("current_weight", 0.0))
        for instrument_id, control in target_inputs.items():
            control.value = f"{current[instrument_id] * 100:.4f}"
        cash.value = f"{max(0.0, 1.0 - sum(current.values())) * 100:.4f}"
        status.value = "Controls reset to the current local allocation; select Analyse candidate to recompute."
        status.color = theme.MUTED
        _safe_update(page)

    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header(
                            "Portfolio Sandbox",
                            "Create and compare a local research candidate. Every result is advisory context; broker execution and order creation are disabled.",
                        ),
                        ft.Row(
                            [
                                evidence_chip("Authority", "portfolio research only", theme.CYAN),
                                evidence_chip("Persistence", "local revisioned state", theme.BLUE_GREY),
                                evidence_chip("ETF overlap", "unavailable pending ISSUE-0022", theme.AMBER),
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
                        section_header(
                            "Candidate controls",
                            "Targets plus cash must equal exactly 100%. Saving persists user intent and source bindings only; drift, exposure and cost are always recomputed.",
                        ),
                        ft.Row([name, notional, cash], wrap=True),
                        ft.Row(list(target_inputs.values()), wrap=True, spacing=8),
                        ft.Row(
                            [
                                ft.Button("Analyse candidate", key="portfolio.analyse", on_click=analyse),
                                ft.OutlinedButton("Save revision", key="portfolio.save", icon=ft.Icons.SAVE, on_click=save),
                                ft.OutlinedButton("Load latest", key="portfolio.load", on_click=load),
                                ft.TextButton("Reset to current", key="portfolio.reset-current", on_click=reset_current),
                            ],
                            wrap=True,
                        ),
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


def _analysis_view(analysis: PortfolioAnalysis) -> ft.Control:
    cost = analysis.cost
    cards = ft.Row(
        [
            panel(ft.Column([ft.Text("Current value", color=theme.MUTED), ft.Text(f"EUR {analysis.current_value_eur:,.0f}", color=theme.TEXT, size=20)]), expand=True),
            panel(ft.Column([ft.Text("Current cash", color=theme.MUTED), ft.Text(f"{analysis.current_cash_weight:.1%}", color=theme.TEXT, size=20)]), expand=True),
            panel(ft.Column([ft.Text("Estimated rebalance cost", color=theme.MUTED), ft.Text(f"EUR {cost.total_cost_eur:,.2f} · {cost.weighted_cost_bps:.1f} bps", color=theme.TEXT, size=16)]), expand=True),
        ],
        spacing=12,
        wrap=True,
    )
    allocation = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Instrument")),
            ft.DataColumn(ft.Text("Current")),
            ft.DataColumn(ft.Text("Target")),
            ft.DataColumn(ft.Text("Target - current")),
            ft.DataColumn(ft.Text("Signed notional")),
            ft.DataColumn(ft.Text("Band")),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(f"{row.instrument_id} · {row.name}", size=11)),
                    ft.DataCell(ft.Text(f"{row.current_weight:.2%}", size=11)),
                    ft.DataCell(ft.Text(f"{row.target_weight:.2%}", size=11)),
                    ft.DataCell(ft.Text(f"{row.drift:+.2%}", size=11)),
                    ft.DataCell(ft.Text(f"EUR {row.signed_notional_eur:+,.2f}", size=11)),
                    ft.DataCell(ft.Text(row.drift_status.replace("_", " "), size=11)),
                ]
            )
            for row in analysis.allocations
        ],
    )
    return ft.Column(
        [
            cards,
            panel(
                ft.Column(
                    [
                        section_header("Current versus candidate", "Positive signed notional means an increase for analysis; it is not an instruction."),
                        ft.Row([allocation], scroll=ft.ScrollMode.AUTO),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            ft.Row(
                [
                    _exposure_table("Sector exposure", analysis.sector_exposure),
                    _exposure_table("Region exposure", analysis.region_exposure),
                    _exposure_table("Currency exposure", analysis.currency_exposure),
                ],
                spacing=12,
                wrap=True,
            ),
            panel(
                ft.Column(
                    [
                        section_header("Limitations and warnings", "Warnings remain visible and do not grant authority."),
                        ft.Text("\n".join(analysis.warnings or ("No candidate concentration warnings.",)), color=theme.MUTED, selectable=True),
                        ft.Text(
                            f"source_stale={str(analysis.source_stale).lower()} | overlap={analysis.overlap_status} | execution_allowed=false",
                            color=theme.MUTED,
                            size=11,
                            selectable=True,
                        ),
                    ]
                )
            ),
        ],
        spacing=12,
    )


def _exposure_table(title: str, rows: object) -> ft.Control:
    return panel(
        ft.Column(
            [
                ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Bucket")), ft.DataColumn(ft.Text("Current")), ft.DataColumn(ft.Text("Target"))],
                    rows=[
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(row.bucket, size=11)),
                                ft.DataCell(ft.Text(f"{row.current_weight:.1%}", size=11)),
                                ft.DataCell(ft.Text(f"{row.target_weight:.1%}", size=11)),
                            ]
                        )
                        for row in rows  # type: ignore[union-attr]
                    ],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _percentage(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("weights must be finite percentages")
    try:
        return float(str(value or "").strip()) / 100.0
    except ValueError as exc:
        raise ValueError("weights must be finite percentages") from exc


def _apply_candidate(candidate: object, name: ft.TextField, notional: ft.TextField, targets: dict[str, ft.TextField], cash: ft.TextField) -> None:
    name.value = str(getattr(candidate, "name"))
    notional.value = f"{float(getattr(candidate, 'analysis_notional_eur')):.2f}"
    values = dict(getattr(candidate, "target_weights"))
    for instrument_id, control in targets.items():
        control.value = f"{float(values.get(instrument_id, 0.0)) * 100:.4f}"
    cash.value = f"{float(getattr(candidate, 'cash_weight')) * 100:.4f}"


def _safe_update(page: ft.Page | None) -> None:
    if page is None:
        return
    try:
        page.update()
    except (AssertionError, RuntimeError):
        return


__all__ = ["portfolio_page"]
