from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count
from etf_cockpit.app.state import AppState


def provider_status_page(page: ft.Page, state: AppState) -> PageView:
    from etf_cockpit.app.pages import trust_evidence

    registry = trust_evidence.ProviderRegistry(state.snapshot.config.data_providers)
    capabilities = registry.probe_all()
    status_rows = registry.status_rows(capabilities) + trust_evidence.plugin_status_rows()
    built_in = trust_evidence.plugin_status_rows()
    policy_rows = trust_evidence.source_policy_rows(trust_evidence.Path.cwd())
    terms_rows = trust_evidence.legal_terms_rows(trust_evidence.Path.cwd())

    def human(value: object) -> str | None:
        if value is None or value == "":
            return None
        return " ".join(str(value).replace("_", " ").split()).title()

    def kind_for_status(value: object, *, enabled: bool | None = None) -> str:
        status = str(value or "").casefold()
        if "credential" in status:
            return "warn"
        if enabled is False or status == "disabled":
            return "mute"
        if status in {"ok", "available", "passed", "enabled"}:
            return "ok"
        if status in {"failed", "blocked", "error"}:
            return "bad"
        return "warn" if status else "mute"

    def detail_control(values: dict[str, object]) -> ft.Control:
        detail_lines = [
            f"{key}: {value}"
            for key, value in values.items()
            if value is not None and value != ""
        ]
        return kit.Disclosure("Provider detail", "\n".join(detail_lines) or "Unavailable")

    capability_data: list[dict[str, object]] = []
    for row in status_rows:
        enabled = row.get("enabled")
        configured = row.get("configured")
        status = row.get("status")
        caps = row.get("capabilities")
        capability_value = ", ".join(str(item) for item in caps) if caps else None
        capability_data.append(
            {
                "provider": row.get("provider_id") or None,
                "kind": human(row.get("dataset_type") or row.get("kind")),
                "enabled": ft.Row(
                    [
                        kit.Tag(
                            "Enabled" if enabled else "Disabled",
                            "ok" if enabled else "mute",
                            dense=True,
                        ),
                        kit.Tag(
                            "Configured" if configured else "Not configured",
                            "ok" if configured else "mute",
                            dense=True,
                        ),
                    ],
                    spacing=4,
                    wrap=True,
                ),
                "status": kit.Tag(
                    human(status) or "Unavailable",
                    kind_for_status(status, enabled=enabled),
                ),
                "authority": human(row.get("authority")),
                "capabilities": ft.Column(
                    [
                        kit.Note(capability_value or "Unavailable"),
                        detail_control(
                            {
                                "Redacted configuration": row.get("redacted_configuration"),
                                "Provider message": row.get("message"),
                            }
                        ),
                    ],
                    spacing=4,
                ),
                "entitlement": human(row.get("entitlement")),
                "rate": row.get("rate_limit_note") or None,
                "last_success": row.get("last_success_at") or None,
                "score": kit.Tag(
                    "Eligible" if row.get("score_eligible") else "Not eligible",
                    "ok" if row.get("score_eligible") else "mute",
                ),
            }
        )

    source_data: list[dict[str, object]] = []
    for row in policy_rows:
        source_data.append(
            {
                "provider": row.get("provider_id") or None,
                "dataset": human(row.get("dataset_type")),
                "tier": human(row.get("source_tier")),
                "optionality": human(row.get("optionality")),
                "cache": kit.Tag(
                    human(row.get("cache_status")) or "Unavailable",
                    kind_for_status(row.get("cache_status")),
                ),
                "network": human(row.get("network")),
                "quota": human(row.get("quota_failure")),
            }
        )

    terms_data: list[dict[str, object]] = []
    for row in terms_rows:
        terms_status = row.get("terms_status")
        entry_detail = detail_control(
            {
                "Entry kind": row.get("entry_kind"),
                "Permitted cache": row.get("permitted_cache"),
                "Redistribution": row.get("redistribution"),
                "Audit export": row.get("audit_export"),
            }
        )
        terms_data.append(
            {
                "entry": ft.Column(
                    [kit.Note(str(row.get("entry_id") or "Unavailable")), entry_detail],
                    spacing=4,
                ),
                "status": kit.Tag(
                    human(terms_status) or "Unavailable",
                    kind_for_status(terms_status),
                ),
                "redistribution": human(row.get("redistribution")),
                "audit": human(row.get("audit_export")),
            }
        )

    def table_for(selection: str) -> ft.Control:
        if selection == "Source tiers":
            return kit.DataTable(
                [
                    kit.TableColumn("provider", "Provider", flex=2),
                    kit.TableColumn("dataset", "Dataset"),
                    kit.TableColumn("tier", "Source tier"),
                    kit.TableColumn("optionality", "Optionality"),
                    kit.TableColumn("cache", "Cache"),
                    kit.TableColumn("network", "Network"),
                    kit.TableColumn("quota", "Quota failure"),
                ],
                source_data,
                empty_title="No source tiers",
                empty_reason="No source policy rows are available.",
            )
        if selection == "Terms":
            return kit.DataTable(
                [
                    kit.TableColumn("entry", "Entry", flex=2),
                    kit.TableColumn("status", "Terms status"),
                    kit.TableColumn("redistribution", "Redistribution"),
                    kit.TableColumn("audit", "Audit export"),
                ],
                terms_data,
                empty_title="No terms records",
                empty_reason="No local terms records are available.",
            )
        return kit.DataTable(
            [
                kit.TableColumn("provider", "Provider/plugin", flex=2),
                kit.TableColumn("kind", "Kind"),
                kit.TableColumn("enabled", "Enabled / configured", flex=2),
                kit.TableColumn("status", "Status"),
                kit.TableColumn("authority", "Authority"),
                kit.TableColumn("capabilities", "Capabilities", flex=2),
                kit.TableColumn("entitlement", "Entitlement"),
                kit.TableColumn("rate", "Rate / limit", flex=2),
                kit.TableColumn("last_success", "Last success"),
                kit.TableColumn("score", "Score eligible"),
            ],
            capability_data,
            empty_title="No capabilities",
            empty_reason="No provider capability rows are available.",
        )

    notes = {
        "Capabilities": (
            "one allow-listed contract",
            "Disabled capabilities are never probed and cannot grant execution authority.",
        ),
        "Source tiers": (
            "local-first · no network for release replay",
            "The mandatory path accepts local imports, official bulk files or official cached snapshots. Cache status describes the local replay path; the no-network release replay path does not perform a provider request.",
        ),
        "Terms": (
            "recorded locally",
            "Source, model and package terms are recorded locally and do not grant permission to redistribute restricted material. Restricted sources are local-only or metadata-only in standard audit exports.",
        ),
    }
    main_slot = ft.Column(spacing=0)

    def render_main(selection: str) -> None:
        note, insight = notes[selection]
        title = {
            "Capabilities": "Capability registry",
            "Source tiers": "Mandatory source tiers",
            "Terms": "Legal terms and export boundaries",
        }[selection]
        table = table_for(selection)
        main_slot.controls = [
            kit.GlassCard(
                title,
                note,
                insight,
                body=ft.Column(
                    [
                        kit.Note(insight),
                        table,
                    ],
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=2,
            )
        ]

    def change_table(selection: str) -> None:
        render_main(selection)
        if getattr(page, "update", None):
            try:
                page.update()
            except (RuntimeError, AttributeError):
                pass

    render_main("Capabilities")

    counts = {"available": 0, "disabled": 0, "unavailable": 0, "credentials": 0}
    for row in status_rows:
        status = str(row.get("status") or "").casefold()
        if "credential" in status:
            counts["credentials"] += 1
        elif row.get("enabled") is False or status == "disabled":
            counts["disabled"] += 1
        elif status in {"ok", "available"}:
            counts["available"] += 1
        else:
            counts["unavailable"] += 1
    chart_reason = "No provider status rows are available." if not status_rows else None
    health_insight = (
        f"{format_count(counts['available'])} providers available; "
        f"{format_count(counts['disabled'] + counts['unavailable'])} disabled or unavailable."
        if status_rows
        else None
    )
    provider_chart = ck.donut_chart(
        [
            ck.Slice("Available", counts["available"], theme.CHART_POS),
            ck.Slice("Disabled", counts["disabled"], theme.MUTED),
            ck.Slice("Unavailable", counts["unavailable"], theme.CHART_NEG),
            ck.Slice("Missing credentials", counts["credentials"], theme.AMBER),
        ],
        unit="providers",
        unavailable_reason=chart_reason,
        empty_title="No provider health",
        insight=health_insight,
    )
    plugin_tags = ft.Row(
        [
            kit.Tag(
                str(row.get("provider_id") or "Unavailable"),
                kind_for_status(row.get("status"), enabled=row.get("enabled")),
            )
            for row in built_in
        ],
        spacing=4,
        wrap=True,
    )
    health_card = kit.GlassCard(
        "Provider health",
        "by status",
        health_insight,
        body=ft.Column(
            [kit.Well(provider_chart, expand=True), kit.Note("Built-in plugins"), plugin_tags],
            spacing=8,
        ),
        expand=True,
    )

    def evidence_table(name: str, path: object, fields: tuple[str, ...]) -> kit.EvidenceTable:
        frame = trust_evidence._read_frame(path)
        columns = [kit.TableColumn(field, field.replace("_", " ")) for field in fields]
        evidence_rows: list[dict[str, object]] = []
        for record in frame.to_dict(orient="records"):
            values: dict[str, object] = {}
            details: dict[str, object] = {}
            for field in fields:
                value = record.get(field)
                if value is None or (isinstance(value, float) and value != value):
                    values[field] = None
                elif field in {"status", "resolution_status"}:
                    values[field] = kit.Tag(
                        human(value) or "Unavailable",
                        kind_for_status(value),
                    )
                elif field == "message":
                    values[field] = kit.Disclosure("Provider message", str(value))
                elif field in {"source_authority", "authority"}:
                    values[field] = human(value)
                else:
                    details[field] = value
                    values[field] = value
            if details:
                detail_field = next(
                    (field for field in fields if field in values and field not in {"status", "resolution_status"}),
                    fields[0],
                )
                current = values.get(detail_field)
                values[detail_field] = ft.Column(
                    [
                        kit.Note(str(current) if current is not None else "Unavailable"),
                        kit.Disclosure(
                            "Record detail",
                            "\n".join(f"{key}: {value}" for key, value in details.items()),
                        ),
                    ],
                    spacing=4,
                )
            evidence_rows.append(values)
        return kit.EvidenceTable(
            name,
            columns,
            evidence_rows,
            file_name=getattr(path, "name", None),
            source_path=str(path),
        )

    evidence = kit.EvidenceTableSwitcher(
        [
            evidence_table(
                "Provider probes",
                trust_evidence.PROVIDER_PROBE_PATH,
                ("dataset_type", "provider_name", "status", "source_authority", "message"),
            ),
            evidence_table(
                "Instrument identity",
                trust_evidence.IDENTITY_PATH,
                (
                    "instrument_id",
                    "analysis_tier",
                    "instrument_type",
                    "isin",
                    "yahoo_symbol",
                    "exchange",
                    "mic",
                    "currency",
                    "share_class",
                    "listing",
                    "identity_confidence",
                ),
            ),
            evidence_table(
                "Source conflicts",
                trust_evidence.SOURCE_CONFLICTS_PATH,
                (
                    "instrument_id",
                    "field_name",
                    "canonical_value",
                    "resolution_status",
                    "requires_manual_review",
                    "reason",
                ),
            ),
        ],
        title="Provider evidence",
    )

    policy_card = kit.GlassCard(
        "Policy",
        "local authority boundaries",
        body=ft.Column(
            [
                kit.ListRow("info", "Disabled capabilities are never probed"),
                kit.ListRow("info", "Restricted sources stay local or metadata-only"),
                kit.ListRow("info", "Unknown optional terms disable the capability"),
                kit.ListRow("info", "API keys are redacted and never exported", last=True),
                kit.Note("Execution remains disabled; provider status cannot authorize order transmission."),
            ],
            spacing=4,
        ),
        expand=True,
    )
    body = ft.Column(
        [
            ft.Column([main_slot, health_card], spacing=8),
            ft.Column([evidence, policy_card], spacing=8),
        ],
        spacing=8,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        PageChrome(
            "Provider Status",
            "Provider capabilities, source authority and disabled states · keys redacted",
            (
                SegmentGroup(
                    "main_table",
                    ("Capabilities", "Source tiers", "Terms"),
                    "Capabilities",
                    on_change=change_table,
                ),
            ),
        ),
        body,
    )


__all__ = ["provider_status_page"]
