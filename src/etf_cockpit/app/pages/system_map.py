"""System Map governance surface."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.governance_badges import status_badge
from etf_cockpit.app.state import AppState
from etf_cockpit.governance.product_scope import load_feature_registry


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
    cards: list[ft.Control] = []
    if loaded.policy is not None and not loaded.diagnostic_mode:
        cards.extend(_feature_card(page, state, entry) for entry in loaded.policy.entries)
    else:
        cards.append(panel(ft.Column([ft.Text("Feature registry unavailable", color=theme.TEXT, weight=ft.FontWeight.BOLD), ft.Text("Manual review required; no registry authority is inferred.", color=theme.AMBER)])))
    cards.append(
        panel(
            ft.Column(
                [
                    ft.Text("Future execution", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                    status_badge("Availability", "Not installed", colour=theme.AMBER),
                    ft.Text("No broker execution. This cockpit presents local evidence and research context only.", color=theme.MUTED, selectable=True),
                ],
                spacing=8,
            ),
            expand=True,
        )
    )
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
