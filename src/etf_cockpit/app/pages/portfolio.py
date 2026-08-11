"""Interactive local portfolio candidate sandbox."""

from __future__ import annotations

import math

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.components.overlap import overlap_evidence_panel
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    PortfolioAnalysis,
    PortfolioCandidate,
    PortfolioSandboxPersistenceError,
    RebalanceConstraints,
    RebalanceReport,
    StorageRevisionConflict,
    analyse_portfolio_candidate,
    build_rebalance_report,
    build_portfolio_candidate,
    candidate_id,
    draft_portfolio_candidate,
    load_portfolio_candidate,
    portfolio_snapshot_binding,
    rebalance_inapplicable_instruments,
    save_portfolio_candidate,
    select_holdings_view,
)
from etf_cockpit.application.portfolio_sandbox import (
    draft_portfolio_proposal,
    export_portfolio_analysis,
)
from etf_cockpit.core.paths import ROOT


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
    control_ids = sorted(set(universe) | _holding_ids(state.snapshot.holdings))
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
            label=_target_label(instrument_id, universe.get(instrument_id), state.snapshot.holdings),
            value=f"{initial.targets.get(instrument_id, 0.0) * 100:.4f}",
            width=190,
            dense=True,
        )
        for instrument_id in control_ids
    }
    cash = ft.TextField(
        key="portfolio.cash-weight",
        label="Cash target (%)",
        value=f"{initial.cash_weight * 100:.4f}",
        width=190,
        dense=True,
    )
    account = ft.Dropdown(
        key="portfolio.account",
        label="Account snapshot",
        value=str(getattr(state.snapshot, "account_id", "default") or "default"),
        options=[ft.dropdown.Option(str(value)) for value in _snapshot_values(state.snapshot, "account_id", "default")],
        width=190,
        dense=True,
    )
    portfolio = ft.Dropdown(
        key="portfolio.portfolio",
        label="Portfolio snapshot",
        value=str(getattr(state.snapshot, "portfolio_id", "default") or "default"),
        options=[ft.dropdown.Option(str(value)) for value in _snapshot_values(state.snapshot, "portfolio_id", "default")],
        width=190,
        dense=True,
    )
    snapshot = ft.Dropdown(
        key="portfolio.snapshot",
        label="As-of snapshot",
        value=str(getattr(state.snapshot, "snapshot_id", "current") or "current"),
        options=[ft.dropdown.Option(str(value)) for value in _snapshot_values(state.snapshot, "snapshot_id", "current")],
        width=190,
        dense=True,
    )
    holdings_view = ft.Dropdown(
        key="portfolio.holdings-view",
        label="Holdings view",
        value="combined",
        options=[ft.dropdown.Option(value) for value in ("direct", "look_through", "combined")],
        width=160,
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
        [_analysis_view(analyse_portfolio_candidate(state.snapshot, initial, account_id=account.value, portfolio_id=portfolio.value, snapshot_id=snapshot.value, holdings_view=holdings_view.value))],
        key="portfolio.results",
        spacing=12,
    )
    rebalance_host = ft.Column(
        [panel(ft.Text("Select Validate rebalance preview to compare local alternatives.", color=theme.MUTED, selectable=True))],
        key="portfolio.rebalance-results",
        spacing=12,
    )

    def values() -> tuple[str, str, dict[str, object], object]:
        targets: dict[str, object] = {}
        selected_ids = _holding_ids(
            select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
        )
        actionable_ids = set(universe) | selected_ids
        for instrument_id, control in target_inputs.items():
            if instrument_id in actionable_ids:
                targets[instrument_id] = _percentage(control.value)
        return str(name.value or ""), str(notional.value or ""), targets, _percentage(cash.value)

    def refresh(candidate: PortfolioCandidate, *, message: str, colour: str = theme.GREEN) -> None:
        analysis = analyse_portfolio_candidate(
            state.snapshot,
            candidate,
            account_id=str(account.value or "default"),
            portfolio_id=str(portfolio.value or "default"),
            snapshot_id=str(snapshot.value or "current"),
            holdings_view=str(holdings_view.value or "combined"),
        )
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
                holdings_view=str(holdings_view.value or "combined"),
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

    def rebalance_preview(_event: ft.ControlEvent | None) -> None:
        try:
            _, candidate_notional, targets, candidate_cash = values()
            selected_holdings = select_holdings_view(
                state.snapshot.holdings,
                str(holdings_view.value or "combined"),
            )
            binding = portfolio_snapshot_binding(
                state.snapshot,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            inapplicable = rebalance_inapplicable_instruments(
                state.snapshot,
                selected_holdings,
                _holding_ids(selected_holdings)
                | {
                    instrument_id
                    for instrument_id, target_weight in targets.items()
                    if float(target_weight) > 0
                },
            )
            if inapplicable:
                rebalance_host.controls = [
                    panel(
                        ft.Column(
                            [
                                section_header(
                                    "Rebalance workspace",
                                    "The existing discrete rebalance service is ETF-only; mixed-asset targets remain explicit and are not silently discarded.",
                                ),
                                ft.Text(
                                    "Inapplicable mixed-asset targets: " + ", ".join(inapplicable),
                                    color=theme.AMBER,
                                    selectable=True,
                                ),
                                ft.Text(
                                    f"source=account={binding.account_id} | portfolio={binding.portfolio_id} | snapshot={binding.snapshot_id} | "
                                    f"as_of={binding.as_of or 'unavailable'} | view={binding.holdings_view} | checksum={binding.source_checksum[:12]} | execution_allowed=false",
                                    color=theme.MUTED,
                                    size=11,
                                    selectable=True,
                                ),
                            ]
                        )
                    )
                ]
                status.value = "Rebalance preview is inapplicable for mixed-asset targets; no target was dropped and no order was created."
                status.color = theme.AMBER
                state.last_message = status.value
                _safe_update(page)
                return
            report = build_rebalance_report(
                state.snapshot.config,
                selected_holdings,
                targets,
                target_cash_weight=candidate_cash,
                portfolio_value_eur=candidate_notional,
                constraints=RebalanceConstraints(
                    cash_buffer_weight=0.02,
                    min_trade_eur=50.0,
                    lot_size=1.0,
                    allow_fractional_lots=False,
                ),
            )
            rebalance_host.controls = [_rebalance_view(report, source_binding=binding)]
            status.value = "Rebalance preview validated from the current local snapshot; no order or broker action was created."
            status.color = theme.GREEN if report.feasible else theme.AMBER
            state.last_message = status.value
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            status.value = f"Rebalance preview unavailable: {exc}"
            status.color = theme.AMBER
            rebalance_host.controls = [panel(ft.Text("Rebalance alternatives are unavailable until the validation error is corrected.", color=theme.AMBER, selectable=True))]
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
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
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
            saved = load_portfolio_candidate(
                state.snapshot,
                str(name.value or ""),
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
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

    def export(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                holdings_view=str(holdings_view.value or "combined"),
            )
            analysis = analyse_portfolio_candidate(
                state.snapshot,
                candidate,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            path = export_portfolio_analysis(
                analysis,
                ROOT / "data" / "exports" / f"portfolio_sandbox_{candidate.candidate_id}.json",
            )
            state.last_export_path = path
            status.value = f"Sandbox export written: {path.name}; execution remains disabled."
            status.color = theme.GREEN
            _safe_update(page)
        except (OSError, TypeError, ValueError) as exc:
            status.value = f"Sandbox export unavailable: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def draft_proposal(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot,
                name=candidate_name,
                analysis_notional_eur=candidate_notional,
                target_weights=targets,
                cash_weight=candidate_cash,
                holdings_view=str(holdings_view.value or "combined"),
            )
            analysis = analyse_portfolio_candidate(
                state.snapshot,
                candidate,
                account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"),
                holdings_view=str(holdings_view.value or "combined"),
            )
            handoff = draft_portfolio_proposal(state.snapshot, analysis)
            status.value = f"Draft hand-off prepared for ISSUE-0130 ({len(handoff['changes'])} changes); no proposal or order was created."
            status.color = theme.GREEN
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            status.value = f"Draft hand-off unavailable: {exc}"
            status.color = theme.AMBER
            _safe_update(page)

    def reset_current(_event: ft.ControlEvent | None) -> None:
        current_lines = {instrument_id: [] for instrument_id in target_inputs}
        selected_holdings = select_holdings_view(
            state.snapshot.holdings,
            str(holdings_view.value or "combined"),
        )
        for _, row in selected_holdings.iterrows():
            instrument_id = str(row.get("etf_id", row.get("instrument_id", "")))
            if instrument_id in current_lines:
                current_lines[instrument_id].append(float(row.get("current_weight", 0.0)))
        current = {
            instrument_id: math.fsum(sorted(weights))
            for instrument_id, weights in current_lines.items()
        }
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
                                evidence_chip("ETF overlap", "direct evidence enabled", theme.AMBER),
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
                            "Select an account/portfolio snapshot and holdings view. Targets plus cash must equal exactly 100%; results cite the selected snapshot and remain advisory.",
                        ),
                        ft.Row([account, portfolio, snapshot, holdings_view], wrap=True),
                        ft.Row([name, notional, cash], wrap=True),
                        ft.Row(list(target_inputs.values()), wrap=True, spacing=8),
                        ft.Row(
                            [
                                ft.Button("Analyse candidate", key="portfolio.analyse", on_click=analyse),
                                ft.OutlinedButton("Validate rebalance preview", key="portfolio.rebalance-preview", on_click=rebalance_preview),
                                ft.OutlinedButton("Save revision", key="portfolio.save", icon=ft.Icons.SAVE, on_click=save),
                                ft.OutlinedButton("Load latest", key="portfolio.load", on_click=load),
                                ft.OutlinedButton("Export evidence", key="portfolio.export", on_click=export),
                                ft.OutlinedButton("Prepare ISSUE-0130 draft", key="portfolio.draft-proposal", on_click=draft_proposal),
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
            rebalance_host,
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _analysis_view(analysis: PortfolioAnalysis) -> ft.Control:
    cost = analysis.cost
    binding = analysis.snapshot_binding
    source_text = "snapshot binding unavailable"
    if binding is not None:
        source_text = (
            f"account={binding.account_id} | portfolio={binding.portfolio_id} | snapshot={binding.snapshot_id} | "
            f"as_of={binding.as_of or 'unavailable'} | view={binding.holdings_view} | source_checksum={binding.source_checksum[:12]}"
        )
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
                    ft.DataColumn(ft.Text("Capability")),
                    ft.DataColumn(ft.Text("Why not")),
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
                    ft.DataCell(ft.Text(f"{row.asset_type}: {row.capability_status}", size=11)),
                    ft.DataCell(ft.Text(row.why_not or row.marginal_effect, size=11)),
                ]
            )
            for row in analysis.allocations
        ],
    )
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Selected portfolio snapshot", "Every before/after result is bound to this local source identity; live ledger state is never mutated."),
                        ft.Text(source_text, color=theme.MUTED, selectable=True, size=11),
                        ft.Text("Direct and look-through holdings remain separate; complete ETF look-through is unavailable until ISSUE-0022.", color=theme.MUTED, selectable=True, size=11),
                    ]
                )
            ),
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
            overlap_evidence_panel(analysis.overlap, key="portfolio.etf-overlap"),
            _holding_evidence_view(analysis),
            _constraint_evidence_view(analysis),
            panel(
                ft.Column(
                    [
                        section_header("Existing service evidence", "What-if targets are passed to the canonical optimiser, robust-risk and cost services; no calculation is duplicated here."),
                        ft.Text(
                            " | ".join(
                                f"{name}={value.get('status', 'unavailable')}"
                                for name, value in analysis.service_evidence.items()
                                if isinstance(value, dict) and name in {"optimiser", "risk", "cost"}
                            ) or "service evidence unavailable",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Limitations and warnings", "Warnings remain visible and do not grant authority."),
                        ft.Text("\n".join(analysis.warnings or ("No candidate concentration warnings.",)), color=theme.MUTED, selectable=True),
                        ft.Text(
                            f"source_stale={str(analysis.source_stale).lower()} | overlap={analysis.overlap_status} | proposal_boundary=ISSUE-0130:draft-only | execution_allowed=false",
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


def _holding_evidence_view(analysis: PortfolioAnalysis) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(row.instrument_id, size=11)),
                ft.DataCell(ft.Text(row.holding_view, size=11)),
                ft.DataCell(ft.Text(row.asset_type, size=11)),
                ft.DataCell(ft.Text(f"{row.current_weight:.2%}", size=11)),
                ft.DataCell(ft.Text(row.capability_status, size=11)),
                ft.DataCell(ft.Text(row.capability_reason, size=11)),
            ]
        )
        for row in analysis.holdings
    ]
    return panel(
        ft.Column(
            [
                section_header("Direct and look-through holdings", "Lineage, capability and source identity remain explicit; unresolved ETF look-through is not redistributed."),
                ft.Row(
                    [
                        ft.DataTable(
                            columns=[ft.DataColumn(ft.Text(value)) for value in ("Instrument", "View", "Asset", "Current", "Capability", "Reason")],
                            rows=rows,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )


def _constraint_evidence_view(analysis: PortfolioAnalysis) -> ft.Control:
    constraint_lines = [
        f"{item.name}: {item.status} ({item.reason})"
        for item in analysis.constraints
    ]
    why_not_lines = [f"{instrument_id}: {reason}" for instrument_id, reason in analysis.why_not]
    before_after = [f"{instrument_id}: {before:.2%} → {after:.2%}" for instrument_id, before, after in analysis.before_after]
    text = "\n".join(
        [
            "Applicable constraints:",
            *(constraint_lines or ["none available"]),
            "Marginal before/after weight effect:",
            *(before_after or ["none"]),
            "Explicit why-not outcomes:",
            *(why_not_lines or ["none"]),
        ]
    )
    return panel(
        ft.Column(
            [
                section_header("Constraints, marginal effect and why not", "A blocked, inapplicable or no-trade outcome is visible rather than silently omitted."),
                ft.Text(text, color=theme.MUTED, selectable=True, size=11),
            ]
        )
    )


def _rebalance_view(report: RebalanceReport, *, source_binding: object | None = None) -> ft.Control:
    alternatives = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Alternative")), ft.DataColumn(ft.Text("Changes")), ft.DataColumn(ft.Text("Drift proxy")), ft.DataColumn(ft.Text("Cost")), ft.DataColumn(ft.Text("Cash"))],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(item.name.replace("_", " ").title(), size=11)),
                    ft.DataCell(ft.Text(str(item.trade_count), size=11)),
                    ft.DataCell(ft.Text(f"{item.tracking_error_proxy:.2%}", size=11)),
                    ft.DataCell(ft.Text(f"EUR {item.estimated_cost_eur:,.2f}", size=11)),
                    ft.DataCell(ft.Text(f"{item.cash_weight:.2%}", size=11)),
                ]
            )
            for item in report.alternatives.values()
        ],
    )
    trades = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Instrument")), ft.DataColumn(ft.Text("Change")), ft.DataColumn(ft.Text("Value")), ft.DataColumn(ft.Text("Status")), ft.DataColumn(ft.Text("Cost"))],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(item.instrument_id, size=11)),
                    ft.DataCell(ft.Text(item.action.replace("buy", "increase").replace("sell", "reduce"), size=11)),
                    ft.DataCell(ft.Text(f"EUR {item.trade_value_eur:+,.2f}", size=11)),
                    ft.DataCell(ft.Text(item.status.replace("_", " "), size=11)),
                    ft.DataCell(ft.Text(f"EUR {item.estimated_cost_eur:,.2f}", size=11)),
                ]
            )
            for item in report.trades
            if abs(item.trade_value_eur) > 0 or item.status not in {"no_change"}
        ],
    )
    warning_text = "\n".join(report.warnings or ("No rebalance warnings.",))
    return panel(
        ft.Column(
            [
                section_header("Rebalance workspace", "Compare cost-, cash-, lot- and restriction-aware alternatives. This is advisory evidence only."),
                ft.Text(
                    "source="
                    + (
                        f"account={getattr(source_binding, 'account_id')} | portfolio={getattr(source_binding, 'portfolio_id')} | "
                        f"snapshot={getattr(source_binding, 'snapshot_id')} | as_of={getattr(source_binding, 'as_of') or 'unavailable'} | "
                        f"view={getattr(source_binding, 'holdings_view')} | checksum={getattr(source_binding, 'source_checksum')[:12]}"
                        if source_binding is not None
                        else "unavailable"
                    ),
                    color=theme.MUTED,
                    size=11,
                    selectable=True,
                ),
                ft.Row(
                    [
                        evidence_chip("Feasibility", "available" if report.feasible else "manual review", theme.GREEN if report.feasible else theme.AMBER),
                        evidence_chip("Cash after change", f"{report.cash_weight:.1%}", theme.BLUE_GREY),
                        evidence_chip("Tax", report.tax_status.replace("_", " "), theme.AMBER),
                        evidence_chip("Execution", "disabled", theme.GREEN),
                    ],
                    wrap=True,
                    spacing=8,
                ),
                ft.Text("Alternatives", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                ft.Row([alternatives], scroll=ft.ScrollMode.AUTO),
                ft.Text("Proposed changes", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                ft.Row([trades], scroll=ft.ScrollMode.AUTO),
                ft.Text(warning_text, color=theme.MUTED, selectable=True),
                ft.Text(
                    f"model_version={report.model_version} | lot_policy={report.assumptions['lot_policy']} | min_trade_eur={report.assumptions['min_trade_eur']:.2f} | tax_jurisdiction={report.tax_jurisdiction} | execution_allowed=false",
                    color=theme.MUTED,
                    size=11,
                    selectable=True,
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )
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


def _holding_ids(holdings: object) -> set[str]:
    if not hasattr(holdings, "iterrows"):
        return set()
    return {
        instrument_id
        for _, row in holdings.iterrows()  # type: ignore[union-attr]
        if (instrument_id := str(row.get("etf_id", row.get("instrument_id", ""))).strip())
    }


def _target_label(instrument_id: str, configured: object | None, holdings: object) -> str:
    if configured is not None:
        return f"{instrument_id} target (%)"
    asset_types = sorted(
        {
            str(row.get("asset_type", row.get("instrument_type", row.get("asset_class", "unknown"))) or "unknown")
            for _, row in holdings.iterrows()  # type: ignore[union-attr]
            if str(row.get("etf_id", row.get("instrument_id", ""))).strip() == instrument_id
        }
    )
    return f"{instrument_id} target (%) [current {'/'.join(asset_types) or 'unknown'}]"


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


def _snapshot_values(snapshot: object, field: str, fallback: str) -> tuple[str, ...]:
    raw = getattr(snapshot, f"{field}s", None)
    if raw is None:
        raw = getattr(snapshot, field, None)
    if isinstance(raw, (list, tuple, set)):
        values = tuple(str(value) for value in raw if str(value).strip())
        if values:
            return values
    return (str(raw or fallback),)


__all__ = ["portfolio_page"]
