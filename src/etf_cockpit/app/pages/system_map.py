"""System Map governance surface."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.governance_badges import status_badge
from etf_cockpit.app.state import AppState
from etf_cockpit.application.scope_facade import capability_scope_view
from etf_cockpit.application.ui_facade import supply_chain_intake_report
from etf_cockpit.core.paths import ROOT
from etf_cockpit.governance.product_scope import load_authority_matrix, load_feature_registry, load_product_governance


_RESEARCH_ONLY_BOUNDARIES: tuple[tuple[str, str, str], ...] = (
    (
        "Pair trading / cointegration",
        "Point-in-time pair selection; cointegration and residual-stationarity checks; stationarity-break and regime monitoring; borrow availability and borrow-cost evidence; explicit spread, slippage and execution-cost assumptions; and a predeclared multiple-testing budget.",
        "Research-only, authority=none, score_authority=false, paper_authority=false, execution_authority=none. Short legs and default scoring are outside the long-only product boundary. See docs/research/pair-trading.md.",
    ),
    (
        "Triple-barrier labels / purged validation",
        "Predeclared upper, lower and vertical barriers; minimum event/sample and regime-stability checks; transparent parameters; purged folds whose training label windows cannot overlap validation; an embargo at least as long as the label horizon; and leakage canaries.",
        "Research-only, authority=none, score_authority=false, paper_authority=false, execution_authority=none. No classifier, runtime scorer, signal, portfolio or execution path is present; general purged validation is owned by ISSUE-0120. See docs/research/triple-barrier-validation.md.",
    ),
)


def _feature_card(page: ft.Page | None, state: AppState, entry: object) -> ft.Container:
    lifecycle = str(getattr(entry, "lifecycle", "unavailable"))
    authority = str(getattr(entry, "authority", "none"))
    routes = tuple(getattr(entry, "canonical_routes", ()) or ())
    limitations = tuple(getattr(entry, "limitations", ()) or ())
    limitation = "; ".join(str(item) for item in limitations) or "No explicit limitation recorded in the feature registry."
    route = routes[0] if routes else None

    def open_route(_event: ft.ControlEvent) -> None:
        if page is not None and route:
            from etf_cockpit.app.router import navigate_to

            navigate_to(page, state, route)

    required_data = getattr(entry, "required_data", ()) or ()
    data_report = state.snapshot.data_report
    dependency_states: list[str] = []
    for dependency in required_data:
        if dependency == "prices":
            frame = getattr(state.snapshot, "prices", None)
            dependency_states.append(f"prices={'available' if frame is not None and not frame.empty else 'unavailable'}")
        elif dependency == "evidence":
            dependency_states.append(f"evidence={'available' if data_report.dataset_metadata else 'unavailable'}")
        elif dependency in {"feature_registry", "policy", "glossary"}:
            dependency_states.append(f"{dependency}=loaded")
        elif dependency == "local_storage":
            dependency_states.append("local_storage=available")
        else:
            dependency_states.append(f"{dependency}=not_measured")
    data_readiness = "; ".join(dependency_states) or "local evidence=not_measured"
    validation = f"Validation: data-health={data_report.status}; {len(data_report.issues)} issue(s); execution_allowed=false."
    controls: list[ft.Control] = [
        ft.Text(str(getattr(entry, "name", getattr(entry, "feature_id", "Governance feature"))), color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
        ft.Row(
            [status_badge("Lifecycle", lifecycle, colour=theme.CYAN), status_badge("Authority", authority, colour=theme.AMBER)],
            wrap=True,
        ),
        ft.Text(f"Data/validation: {', '.join(str(item) for item in required_data) or 'local evidence'}", color=theme.MUTED, size=11),
        ft.Text(f"Readiness: {data_readiness}", color=theme.MUTED, size=11, selectable=True),
        ft.Text(validation, color=theme.AMBER, size=11, selectable=True),
        ft.Text(f"Limitation: {limitation}", color=theme.MUTED, size=11, selectable=True),
    ]
    if route:
        controls.append(ft.TextButton(f"Open {route}", key=f"system-map.route.{route.strip('/').replace('/', '-')}", tooltip=f"Open {route}", on_click=open_route))
    return panel(ft.Column(controls, spacing=8), expand=True)


def system_map_page(page: ft.Page | None, state: AppState) -> ft.Control:
    loaded = load_feature_registry()
    product = load_product_governance()
    matrix = load_authority_matrix()
    capability_scope = capability_scope_view()
    supply_chain = supply_chain_intake_report(ROOT)
    cards: list[ft.Control] = []
    if capability_scope.status == "available":
        strategy_lines = [
            ft.Text(
                f"{row.strategy_id} · {row.lifecycle} · authority={row.authority} · ui={row.ui_visibility} · data={','.join(row.required_data)} · tests={','.join(row.tests)} · score_authority={str(row.score_authority).lower()} · paper_authority={str(row.paper_authority).lower()} · live_authority=false · {'; '.join(row.stage_summary)}",
                color=theme.MUTED,
                size=11,
                selectable=True,
            )
            for row in capability_scope.strategies
        ]
        instrument_lines = [
            ft.Text(
                f"{row.asset_family} · {row.state} · {row.reason_code} · horizons={','.join(row.horizons)} · {row.prerequisite_summary} · {'; '.join(row.stage_summary)}",
                color=theme.MUTED,
                size=11,
                selectable=True,
            )
            for row in capability_scope.instruments
        ]
        cards.append(
            panel(
                ft.Column(
                    [
                        ft.Text("Strategy and instrument capabilities", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                        status_badge("Matrix", capability_scope.matrix_version, colour=theme.CYAN),
                        ft.Text(" · ".join(capability_scope.stages), color=theme.TEXT, selectable=True),
                        ft.Text(
                            f"Strategies: {capability_scope.strategy_count}; rejected: {', '.join(capability_scope.rejected_strategy_ids)}",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                        ft.Text(f"checksum={capability_scope.checksum}; execution_allowed=false", color=theme.AMBER, selectable=True),
                        *strategy_lines,
                        *instrument_lines,
                    ],
                    spacing=7,
                ),
                expand=True,
            )
        )
    else:
        cards.append(
            panel(
                ft.Column(
                    [
                        ft.Text("Strategy and instrument capabilities", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                        ft.Text("Matrix unavailable; manual review required; execution_allowed=false.", color=theme.AMBER, selectable=True),
                        ft.Text("; ".join(capability_scope.diagnostics), color=theme.MUTED, selectable=True),
                    ],
                    spacing=7,
                ),
                expand=True,
            )
        )
    cards.append(
        panel(
            ft.Column(
                [
                    ft.Text("Research-only strategy boundaries", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "These optional research topics are visible for governance context only. They cannot change baseline scores, actions, paper state or execution authority.",
                        color=theme.MUTED,
                        selectable=True,
                    ),
                    *[
                        ft.Column(
                            [
                                ft.Text(title, color=theme.TEXT, size=13, weight=ft.FontWeight.BOLD),
                                ft.Text(requirements, color=theme.MUTED, size=11, selectable=True),
                                ft.Text(boundary, color=theme.AMBER, size=11, selectable=True),
                            ],
                            spacing=5,
                        )
                        for title, requirements, boundary in _RESEARCH_ONLY_BOUNDARIES
                    ],
                ],
                spacing=9,
            ),
            expand=True,
        )
    )
    if loaded.policy is not None and not loaded.diagnostic_mode:
        cards.extend(_feature_card(page, state, entry) for entry in loaded.policy.entries)
    else:
        cards.append(panel(ft.Column([ft.Text("Feature registry unavailable", color=theme.TEXT, weight=ft.FontWeight.BOLD), ft.Text("Manual review required; no registry authority is inferred.", color=theme.AMBER)])))
    cards.append(
        panel(
            ft.Column(
                [
                    ft.Text("Future execution", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            status_badge("Availability", "Not installed", colour=theme.AMBER),
                            status_badge("Stages", "research · shadow_proposal · paper · broker_read_only · draft_order · capped_automatic · disabled", colour=theme.CYAN),
                        ],
                        wrap=True,
                    ),
                    ft.Text("No broker execution. This cockpit presents local evidence and research context only.", color=theme.MUTED, selectable=True),
                    ft.Text(
                        "Future-only architecture: paper mode first, then broker_read_only observations and human-reviewed order previews; capped_automatic remains separately gated and disabled.",
                        color=theme.MUTED,
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        "Controls required before any future transition: max order value · position size · daily turnover · daily loss · drawdown kill switch · cooldowns · market-hours checks · stale-data block · news/event block.",
                        color=theme.MUTED,
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        "Future governance also requires an explicit human confirmation of an order preview, an immutable audit log, and an independent emergency disable. LLM or model-only authority is prohibited.",
                        color=theme.MUTED,
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(
                        "execution_allowed=false · executable_authority=false · order_submission=disabled · see docs/architecture/future/",
                        color=theme.AMBER,
                        size=11,
                        selectable=True,
                    ),
                ],
                spacing=8,
            ),
            expand=True,
        )
    )
    component_lines = [
        ft.Text(
            f"{row.get('component_id', 'component')} · {row.get('integration_boundary', 'unavailable')} · {row.get('exact_ref', 'unavailable')}",
            color=theme.MUTED,
            size=11,
            selectable=True,
        )
        for row in supply_chain.get("components", [])
    ]
    cards.append(
        panel(
            ft.Column(
                [
                    ft.Text("External components", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                    status_badge("Intake", str(supply_chain.get("review_status", "unavailable")), colour=theme.AMBER),
                    ft.Text(
                        f"Registry: {supply_chain.get('registry_sha256', 'unavailable')} · notices: {supply_chain.get('third_party_notices', 'unavailable')}",
                        color=theme.MUTED,
                        size=11,
                        selectable=True,
                    ),
                    ft.Text("No copied third-party core is permitted without an approved intake record.", color=theme.AMBER, size=11, selectable=True),
                    *component_lines,
                ],
                spacing=8,
            ),
            expand=True,
        )
    )
    if product.policy is not None and matrix.policy is not None:
        active_stage = next((stage for stage in matrix.policy.authority_stages if stage.enabled_by_default), None)
        cards.insert(
            0,
            panel(
                ft.Column(
                    [
                        ft.Text("Product contract", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                        ft.Text(f"{product.policy.product.canonical_name} · ADR {matrix.policy.adr_id}", color=theme.TEXT, selectable=True),
                        status_badge("Active authority", active_stage.label if active_stage else "Manual review", colour=theme.CYAN),
                        ft.Text("Execution: disabled by policy; every route, dataset, model, strategy and broker capability is declared.", color=theme.AMBER, selectable=True),
                        ft.Text(f"Capabilities: {len(matrix.policy.capabilities)} · matrix checksum: {matrix.checksum}", color=theme.MUTED, size=11, selectable=True),
                    ],
                    spacing=8,
                ),
                expand=True,
            ),
        )
    else:
        cards.insert(0, panel(ft.Text("Product contract unavailable; authority remains fail-closed and requires manual review.", color=theme.AMBER, selectable=True), expand=True))
    return ft.Column(
        [
            section_header("System Map", "Lifecycle, authority, data readiness and direct routes for the evidence cockpit."),
            ft.ResponsiveRow([ft.Container(content=card, col={"xs": 12, "md": 6, "lg": 4}) for card in cards], spacing=12),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["system_map_page"]
