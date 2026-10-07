"""System Map governance surface."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.state import AppState
from etf_cockpit.application.scope_facade import (
    capability_scope_view,
    load_authority_matrix,
    load_feature_registry,
    load_product_governance,
)
from etf_cockpit.application.ui_facade import supply_chain_intake_report
from etf_cockpit.core.paths import ROOT

TextButton = kit.Button.secondary


def system_map_page(page: ft.Page | None, state: AppState) -> PageView:
    loaded = load_feature_registry()
    product = load_product_governance()
    matrix = load_authority_matrix()
    scope = capability_scope_view()
    supply_chain = supply_chain_intake_report(ROOT)

    policy = getattr(loaded, "policy", None)
    entries = list(getattr(policy, "entries", ()) or ()) if policy is not None and not loaded.diagnostic_mode else []
    capability_rows = []
    for entry in entries:
        routes = tuple(getattr(entry, "canonical_routes", ()) or ())
        route = routes[0] if routes else None

        def open_route(_event: ft.ControlEvent, route: str | None = route) -> None:
            if page is not None and route:
                from etf_cockpit.app.router import navigate_to

                navigate_to(page, state, route)

        dependencies = tuple(getattr(entry, "required_data", ()) or ())
        data_tags = [kit.Tag(str(dependency), "mute") for dependency in dependencies] or [kit.Tag("Unavailable", "bad")]
        capability_rows.append(
            {
                "capability": str(getattr(entry, "name", getattr(entry, "feature_id", "Unavailable"))),
                "lifecycle": kit.Tag(str(getattr(entry, "lifecycle", "Unavailable")), "mute"),
                "authority": kit.Tag(str(getattr(entry, "authority", "Unavailable")), "warn"),
                "data": ft.Row(data_tags, wrap=True, spacing=4),
                "validation": "Data health evidence is local and read-only.",
                "limitation": "; ".join(str(item) for item in (getattr(entry, "limitations", ()) or ())) or "No explicit limitation recorded.",
                "open": TextButton(
                    f"Open {route}",
                    key=(
                        f"system-map.route.{route.strip('/').replace('/', '-')}"
                    ),
                    on_click=open_route,
                    disabled=route is None,
                    disabled_reason="No canonical route is registered." if route is None else None,
                ) if route else "—",
            }
        )

    capability_table = kit.DataTable(
        [
            kit.TableColumn("capability", "Capability"),
            kit.TableColumn("lifecycle", "Lifecycle"),
            kit.TableColumn("authority", "Authority"),
            kit.TableColumn("data", "Data readiness"),
            kit.TableColumn("validation", "Validation"),
            kit.TableColumn("limitation", "Limitation"),
            kit.TableColumn("open", "Open"),
        ],
        capability_rows,
        expand=True,
        empty_title="Capability map unavailable",
        empty_reason="The local feature registry is unavailable or requires manual review.",
    )
    data_report = getattr(getattr(state, "snapshot", None), "data_report", None)
    data_health = getattr(data_report, "status", "Unavailable")
    data_issues = len(getattr(data_report, "issues", ()) or ()) if data_report is not None else "Unavailable"
    feature_details = [
        f"{getattr(entry, 'name', getattr(entry, 'feature_id', 'Unavailable'))} · lifecycle={getattr(entry, 'lifecycle', 'Unavailable')} · authority={getattr(entry, 'authority', 'Unavailable')} · routes={','.join(getattr(entry, 'canonical_routes', ()) or ())} · data={','.join(getattr(entry, 'required_data', ()) or ())} · limitations={'; '.join(getattr(entry, 'limitations', ()) or ())}"
        for entry in entries
    ]
    capability_card = kit.GlassCard(
        "Capability map",
        note="Lifecycle, authority, data readiness, validation and limitations",
        body=ft.Column(
            [
                capability_table,
                kit.Disclosure(
                    "Capability validation details",
                    f"Readiness: feature_registry={'loaded' if entries else 'unavailable'}\nValidation: data-health={data_health}; {data_issues} issue(s); execution_allowed=false.\n"
                    + "\n".join(feature_details),
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )

    active_stage = next(
        (stage.label for stage in getattr(getattr(matrix, "policy", None), "authority_stages", ()) if stage.enabled_by_default),
        None,
    )
    matrix_policy = getattr(matrix, "policy", None)
    product_policy = getattr(product, "policy", None)
    matrix_version = getattr(scope, "matrix_version", None) if getattr(scope, "status", None) == "available" else None
    product_card = kit.GlassCard(
        "Product contract",
        body=ft.Column(
            [
                kit.Headline(getattr(getattr(product_policy, "product", None), "canonical_name", "Unavailable")),
                kit.KpiTile("Capabilities", str(len(getattr(matrix_policy, "capabilities", ()))) if matrix_policy is not None else None, "Declared in the local matrix." if matrix_policy is not None else "Unavailable: authority matrix is not loaded."),
                kit.KpiTile("Execution", "disabled", "Execution remains disabled by policy.", tone="neg"),
                kit.KpiTile("Matrix", matrix_version, "Unavailable: capability matrix is not available." if matrix_version is None else ""),
                kit.Note("Execution: disabled by policy; every route, dataset, model, strategy and broker capability is declared."),
                kit.Disclosure(
                    "Authority details",
                    f"active_stage={active_stage or 'Unavailable'}\nADR {getattr(matrix_policy, 'adr_id', 'Unavailable')}\nchecksum={getattr(matrix, 'checksum', 'Unavailable')}\nexecution_allowed=false",
                ),
                kit.Disclosure(
                    "External components and future execution",
                    "Availability: Not installed. No broker execution. This cockpit presents local evidence and research context only.\n"
                    "Future-only architecture: paper mode first, then broker_read_only observations and human-reviewed order previews; capped_automatic remains separately gated and disabled.\n"
                    "Controls required before any future transition: max order value, position size, daily turnover, daily loss, drawdown kill switch, cooldowns, market-hours checks, stale-data block and news/event block.\n"
                    "Future governance requires explicit human confirmation of order previews, an immutable audit log and an independent emergency disable. LLM or model-only authority is prohibited.\n"
                    + "\n".join(
                        f"{row.get('component_id', 'Unavailable')} · {row.get('integration_boundary', 'Unavailable')} · {row.get('exact_ref', 'Unavailable')}"
                        for row in supply_chain.get("components", [])
                    )
                    + f"\nregistry_sha256={supply_chain.get('registry_sha256', 'Unavailable')}\nthird_party_notices={supply_chain.get('third_party_notices', 'Unavailable')}\nexecution_allowed=false"
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )

    stages = tuple(getattr(scope, "stages", ()) or ()) if getattr(scope, "status", None) == "available" else ()
    strategy_rows = []
    for row in getattr(scope, "strategies", ()) if stages else ():
        stage_values = {}
        summaries = tuple(getattr(row, "stage_summary", ()) or ())
        for stage in stages:
            status = next((value.split(":", 1)[-1].strip() for value in summaries if value.casefold().startswith(f"{stage}".casefold())), None)
            stage_values[str(stage)] = kit.Tag(status, "ok" if status and status.casefold() in {"available", "allowed", "supported"} else "mute") if status else "—"
        strategy_rows.append({"strategy": row.strategy_id, **stage_values})
    strategy_columns = [kit.TableColumn("strategy", "Strategy")] + [kit.TableColumn(str(stage), str(stage).replace("_", " ").title()) for stage in stages]
    stage_grid = kit.DataTable(
        strategy_columns,
        strategy_rows,
        expand=True,
        empty_title="Strategy stage coverage unavailable",
        empty_reason="The local capability matrix is unavailable; stage coverage is not inferred.",
    )
    instrument_lines = [
        f"{row.asset_family} · {row.state} · {row.reason_code} · horizons={','.join(row.horizons)} · {row.prerequisite_summary} · {'; '.join(row.stage_summary)}"
        for row in getattr(scope, "instruments", ())
    ]
    rejected_rows = [
        kit.ListRow("bad", str(strategy), "Rejected strategy capability", tag=("rejected", "bad"))
        for strategy in getattr(scope, "rejected_strategy_ids", ())
    ]
    if not rejected_rows:
        rejected_rows = [kit.EmptyState("Unavailable", "Rejected strategies are not available from the local capability matrix.")]
    strategy_card = kit.GlassCard(
        "Strategy and instrument capabilities",
        note="Stage coverage from the local matrix",
        body=ft.Column(
            [
                stage_grid,
                kit.Disclosure("Instrument capabilities", "\n".join(instrument_lines) or "Unavailable: instrument capabilities are not in the local matrix."),
                kit.Disclosure(
                    "Matrix details",
                    f"stages={' · '.join(str(stage) for stage in stages)}\nrejected={'; '.join(getattr(scope, 'rejected_strategy_ids', ()))}\nchecksum={getattr(scope, 'checksum', 'Unavailable')}\nexecution_allowed=false\n"
                    + "\n".join(
                        f"{row.strategy_id} · {row.lifecycle} · authority={row.authority} · ui={row.ui_visibility} · data={','.join(row.required_data)} · tests={','.join(row.tests)} · score_authority={str(row.score_authority).lower()} · paper_authority={str(row.paper_authority).lower()} · live_authority=false · {'; '.join(row.stage_summary)}"
                        for row in getattr(scope, "strategies", ())
                    ),
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    rejected_card = kit.GlassCard("Rejected strategies", body=ft.Column(rejected_rows, spacing=4, scroll=ft.ScrollMode.AUTO), expand=True)

    capabilities_view = ft.ResponsiveRow(
        [
            ft.Container(content=product_card, col={"xs": 12, "md": 4}),
            ft.Container(content=capability_card, col={"xs": 12, "md": 8}),
        ],
        spacing=12,
        run_spacing=12,
        expand=True,
    )
    strategies_view = ft.ResponsiveRow(
        [
            ft.Container(content=strategy_card, col={"xs": 12, "md": 8}),
            ft.Container(content=rejected_card, col={"xs": 12, "md": 4}),
        ],
        spacing=12,
        run_spacing=12,
        expand=True,
        visible=False,
    )
    body = ft.Column([capabilities_view, strategies_view], expand=True, scroll=ft.ScrollMode.AUTO, spacing=12)

    def show_segment(name: str) -> None:
        capabilities_view.visible = name == "Capabilities"
        strategies_view.visible = name == "Strategies"
        if page is not None and hasattr(page, "update"):
            page.update()

    return PageView(
        PageChrome(
            "System Map",
            "Lifecycle, authority, data readiness and routes for every capability",
            (SegmentGroup("system_map_view", ("Capabilities", "Strategies"), "Capabilities", show_segment),),
        ),
        body,
    )


__all__ = ["system_map_page"]
