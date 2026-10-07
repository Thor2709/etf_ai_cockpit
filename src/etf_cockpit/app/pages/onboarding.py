from __future__ import annotations

from typing import Callable

import flet as ft

from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    Field,
    GlassCard,
    KpiTile,
    ListRow,
    Note,
    Segmented,
    StepSpec,
    Stepper,
    TableColumn,
    Tag,
    Toggle,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_count
from etf_cockpit.app.state import AppState
from etf_cockpit.application.onboarding_profile import (
    _BACKUP_PREFERENCES,
    _BOOTSTRAP_MODES,
    _ENCRYPTION_PREFERENCES,
    _HARDWARE_PROFILES,
    _MANDATORY_PROVIDERS,
    OnboardingProfile,
    TickerValidationResult,
    complete_onboarding,
    load_onboarding,
    overlay_universe_config,
)
from etf_cockpit.application.settings import (
    ANALYSIS_DEPTHS,
    HORIZONS,
    OUTPUT_CURRENCIES,
    RISK_PROFILES,
    load_config,
)
from etf_cockpit.application.ui_facade import (
    legal_terms_report,
    resource_profile_report,
    source_policy_rows,
)
from etf_cockpit.core.paths import ROOT


def _label(value: object) -> str:
    text = str(value or "").replace("_", " ").strip()
    known = {
        "auto": "Automatic",
        "ready": "Available",
        "supported": "Supported",
        "unavailable": "Unavailable",
        "unavailable during onboarding": "Unavailable during onboarding",
        "optional": "Optional",
        "required": "Required",
        "fresh": "Fresh",
        "stale": "Stale",
        "missing": "Missing",
        "available": "Available",
        "not available": "Unavailable",
    }
    return known.get(text.casefold(), text.title()) if text else "—"


def _field(label: str, *, value: str = "", placeholder: str = "", multiline: bool = False) -> ft.Control:
    control = ft.TextField(value=value, **field_input_style(multiline=multiline, placeholder=placeholder))
    return Field(label, control=control, expand=True, multiline=multiline)


def onboarding_page(
    page: ft.Page | None,
    state: AppState | None,
    *,
    validator: Callable[[str], bool | TickerValidationResult] | None = None,
) -> PageView:
    try:
        profile = load_onboarding(ROOT)
    except ValueError:
        profile = None

    selected_values: dict[str, str] = {}

    def remember(key: str) -> Callable[[str], None]:
        return lambda value: selected_values.__setitem__(key, value)

    selected_values["currency"] = profile.base_currency if profile else "EUR"
    selected_values["scope"] = profile.asset_scope[0] if profile and profile.asset_scope else "stock+etf"
    base_currency = Field(
        "Output currency",
        options=OUTPUT_CURRENCIES,
        value=selected_values["currency"],
        on_change=remember("currency"),
        expand=True,
    )
    region_control = ft.TextField(
        value=profile.region if profile else "Europe",
        **field_input_style(),
    )
    region = Field("Region", control=region_control, expand=True)
    asset_scope = Field(
        "Asset scope",
        options=("stock", "etf", "fund", "bond", "stock+etf", "all"),
        value=selected_values["scope"],
        on_change=remember("scope"),
        expand=True,
    )

    risk_items = ("Safe", "Safe-Medium", "Medium", "Medium-Aggressive", "Aggressive")
    risk_ids = dict(zip(risk_items, RISK_PROFILES, strict=True))
    risk_selected = next(
        (label for label, value in risk_ids.items() if profile and profile.risk_profile == value),
        "Medium",
    )
    selected_values["risk"] = risk_ids[risk_selected]
    risk = Segmented(risk_items, risk_selected, on_change=lambda value: remember("risk")(risk_ids[value]))
    risk_field = ft.Column([Note("Risk profile"), risk], spacing=8)

    horizon_items = tuple(str(value).upper() for value in HORIZONS)
    horizon_ids = dict(zip(horizon_items, HORIZONS, strict=True))
    horizon_selected = next(
        (label for label, value in horizon_ids.items() if profile and profile.horizon == value),
        horizon_items[0],
    )
    selected_values["horizon"] = horizon_ids[horizon_selected]
    horizon = Segmented(horizon_items, horizon_selected, on_change=lambda value: remember("horizon")(horizon_ids[value]))
    horizon_field = ft.Column([Note("Target horizon"), horizon], spacing=8)

    depth_items = tuple(str(value).title() for value in ANALYSIS_DEPTHS)
    depth_ids = dict(zip(depth_items, ANALYSIS_DEPTHS, strict=True))
    depth_selected = next(
        (label for label, value in depth_ids.items() if profile and profile.analysis_depth == value),
        depth_items[0],
    )
    selected_values["depth"] = depth_ids[depth_selected]
    analysis_depth = Segmented(depth_items, depth_selected, on_change=lambda value: remember("depth")(depth_ids[value]))
    analysis_field = ft.Column([Note("Analysis depth"), analysis_depth], spacing=8)

    storage_location = Field("Storage location", options=("Project-local",), value="Project-local", expand=True)
    hardware_ids = tuple(sorted(_HARDWARE_PROFILES))
    hardware_labels = tuple(_label(value) for value in hardware_ids)
    hardware_map = dict(zip(hardware_labels, hardware_ids, strict=True))
    hardware_selected = next(
        (label for label, value in hardware_map.items() if profile and profile.hardware_profile == value),
        _label(profile.hardware_profile) if profile else "Automatic",
    )
    selected_values["hardware"] = hardware_map.get(hardware_selected, hardware_ids[0])
    hardware = Field(
        "Hardware profile", options=hardware_labels, value=hardware_selected,
        on_change=lambda value: remember("hardware")(hardware_map[value]), expand=True,
    )

    provider_ids = tuple(sorted(_MANDATORY_PROVIDERS))
    provider_labels = tuple(_label(value) for value in provider_ids)
    provider_map = dict(zip(provider_labels, provider_ids, strict=True))
    selected_provider_id = profile.mandatory_providers[0] if profile and profile.mandatory_providers else "manual_local"
    selected_provider = next(
        (label for label, value in provider_map.items() if value == selected_provider_id),
        provider_labels[0],
    )
    selected_values["provider"] = selected_provider_id
    mandatory_provider = Field(
        "Mandatory provider", options=provider_labels, value=selected_provider,
        on_change=lambda value: remember("provider")(provider_map[value]), expand=True,
    )

    optional_providers_control = ft.TextField(
        value=", ".join(profile.optional_providers) if profile else "",
        **field_input_style(placeholder="Optional source names"),
    )
    optional_providers = Field("Optional providers (comma separated)", control=optional_providers_control, expand=True)
    bootstrap_ids = tuple(sorted(_BOOTSTRAP_MODES))
    bootstrap_labels = tuple(_label(value) for value in bootstrap_ids)
    bootstrap_map = dict(zip(bootstrap_labels, bootstrap_ids, strict=True))
    bootstrap_selected = next(
        (label for label, value in bootstrap_map.items() if profile and profile.bootstrap_mode == value),
        _label(profile.bootstrap_mode) if profile else _label(bootstrap_ids[0]),
    )
    selected_values["bootstrap"] = bootstrap_map[bootstrap_selected]
    bootstrap = Segmented(
        bootstrap_labels, bootstrap_selected,
        on_change=lambda value: remember("bootstrap")(bootstrap_map[value]),
    )
    bootstrap_field = ft.Column([Note("Offline bootstrap"), bootstrap], spacing=8)

    bulk_path_control = ft.TextField(
        value=profile.bulk_source_path if profile else "",
        **field_input_style(placeholder="Choose a local price file"),
    )
    bulk_path = Field("Local bulk price file", control=bulk_path_control, expand=True)
    encryption_ids = tuple(sorted(_ENCRYPTION_PREFERENCES))
    encryption_labels = tuple(_label(value) for value in encryption_ids)
    encryption_map = dict(zip(encryption_labels, encryption_ids, strict=True))
    encryption_selected = next(
        (label for label, value in encryption_map.items() if profile and profile.encryption_preference == value),
        encryption_labels[0],
    )
    selected_values["encryption"] = encryption_map[encryption_selected]
    encryption = Field(
        "Encryption", options=encryption_labels, value=encryption_selected,
        on_change=lambda value: remember("encryption")(encryption_map[value]), expand=True,
    )
    backup_ids = tuple(sorted(_BACKUP_PREFERENCES))
    backup_labels = tuple(_label(value) for value in backup_ids)
    backup_map = dict(zip(backup_labels, backup_ids, strict=True))
    backup_selected = next(
        (label for label, value in backup_map.items() if profile and profile.backup_preference == value),
        _label("local"),
    )
    selected_values["backup"] = backup_map[backup_selected]
    backup_field = Field(
        "Backups", options=backup_labels, value=backup_selected,
        on_change=lambda value: remember("backup")(backup_map[value]), expand=True,
    )
    backups = ft.Row(
        [
            backup_field,
            Toggle(disabled=True, disabled_reason="Unavailable during onboarding"),
            Note("Unavailable during onboarding"),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    tickers_control = ft.TextField(
        value=", ".join(profile.tickers) if profile else "",
        **field_input_style(multiline=True, placeholder="Enter tickers separated by commas"),
    )
    tickers = Field("Initial tickers (comma separated)", control=tickers_control, multiline=True, expand=True)
    validation = Toggle(
        disabled=validator is None,
        disabled_reason="No ticker validator is configured",
        key="onboarding.online-validation",
    )

    status = ft.Text("", key="onboarding.status")
    technical_details = ft.Text("")

    try:
        if state is None:
            raise ValueError("No onboarding state is available.")
        resource_report = resource_profile_report(ROOT, requested_profile=profile.hardware_profile if profile else "auto")
        selected_profile = resource_report.get("selected_profile") or {}
        snapshot = resource_report.get("snapshot") or {}
        cpu_count = snapshot.get("cpu_cores")
        memory_mb = snapshot.get("memory_available_mb") or snapshot.get("memory_total_mb")
        disk_mb = snapshot.get("disk_free_mb")
        profile_value = _label(selected_profile.get("profile_id")) if selected_profile else None
        resource_reason = "Local resource readiness is unavailable."
        cpu_value = f"{format_count(cpu_count, unavailable='—')} cores" if cpu_count is not None else None
        memory_value = f"{format_count(memory_mb, unavailable='—')} MB" if memory_mb is not None else None
        disk_value = f"{format_count(disk_mb, unavailable='—')} MB" if disk_mb is not None else None
    except (OSError, ValueError, KeyError, TypeError):
        resource_report = None
        selected_profile = {}
        profile_value = None
        cpu_value = memory_value = disk_value = None
        resource_reason = "Local resource readiness is unavailable because no runtime profile data is available."

    try:
        if state is None:
            raise ValueError("No policy data is available.")
        policy_rows = source_policy_rows(ROOT, ROOT / "configs" / "data_source_policy.yaml")
    except (OSError, ValueError):
        policy_rows = []

    try:
        if state is None:
            raise ValueError("No terms data is available.")
        legal_report = legal_terms_report(ROOT, ROOT / "configs" / "legal_terms_registry.yaml")
        terms_status = _label(legal_report.get("review_status"))
        checksum = str(legal_report.get("registry_sha256") or "Unavailable")
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        legal_report = {}
        terms_status = "Unavailable"
        checksum = "Unavailable"

    policy_table = DataTable(
        [
            TableColumn("provider", "Provider"),
            TableColumn("tier", "Tier"),
            TableColumn("optional", "Optional"),
            TableColumn("cache", "Cache"),
            TableColumn("network", "Network"),
        ],
        [
            {
                "provider": _label(row.get("provider_id")),
                "tier": _label(row.get("source_tier")),
                "optional": _label(row.get("optionality")),
                "cache": _label(row.get("cache_status")),
                "network": "Opt-in" if row.get("network") else "No",
            }
            for row in policy_rows
        ],
        empty_title="Unavailable",
        empty_reason="Data source policy rows are unavailable until policy data is loaded.",
        expand=True,
    )

    profile_table = DataTable(
        [
            TableColumn("profile", "Profile"),
            TableColumn("status", "Status"),
            TableColumn("cpu", "CPU quota"),
            TableColumn("memory", "Memory quota"),
            TableColumn("disk", "Disk quota"),
        ],
        [
            {
                "profile": row.get("profile_id"),
                "status": row.get("status"),
                "cpu": row.get("job_cpu_limit"),
                "memory": row.get("job_memory_limit_mb"),
                "disk": row.get("job_disk_limit_mb"),
            }
            for row in (resource_report or {}).get("profiles", ())
        ],
        empty_title="Unavailable",
        empty_reason="Profile limits are unavailable because no runtime profile data is available.",
    )

    project_path = Disclosure("Runtime root path", str(ROOT.resolve()) if state is not None else "Unavailable")
    policy_details = Disclosure(
        "Policy and terms details",
        ft.Column(
            [
                Note(f"Registry checksum: {checksum}"),
                Note("Data source provider identifiers and raw policy status are shown in the table below."),
            ],
            spacing=8,
        ),
    )
    resource_details = Disclosure(
        "Full profile table and diagnostics",
        ft.Column([profile_table, Note("CPU-only baseline remains available; optional foundation models are never required.")], spacing=12),
    )

    current_step = 0
    step_names = ("Preferences", "Data source", "Watchlist", "Review & save")
    step_status = ft.Text("")

    def update_page() -> None:
        if page is not None:
            page.update()

    def step_contents() -> tuple[ft.Control, ...]:
        preferences = ft.Column(
            [
                ft.Row([base_currency, region, asset_scope], spacing=12),
                ft.Row([risk_field, horizon_field, analysis_field], spacing=12),
                Note("Quick, Medium, High and Full are versioned analysis effort selections; warm and cold timing effects remain unavailable until the related timing work is complete."),
            ],
            spacing=16,
            expand=True,
        )
        data_source = ft.Column(
            [
                ft.Row([storage_location, hardware, mandatory_provider], spacing=12),
                ft.Row([optional_providers, bootstrap_field], spacing=12),
                ft.Row([bulk_path, encryption], spacing=12),
                backups,
                project_path,
                Note("Sample creates an identity-only universe without fabricated prices."),
                Note("Mandatory providers are offline-compatible; optional provider absence does not block setup."),
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        watchlist = ft.Column(
            [
                tickers,
                ft.Row([validation, Note("Online validation is unavailable without a configured validator.")], spacing=12),
            ],
            spacing=16,
            expand=True,
        )
        summary_rows = (
            ("Preferences", lambda: select_step(0)),
            ("Data source", lambda: select_step(1)),
            ("Watchlist", lambda: select_step(2)),
        )
        review = ft.Column(
            [
                ft.Row(
                    [
                        ListRow(
                            "info",
                            title,
                            sub="Edit the saved choices for this section.",
                            last=index == len(summary_rows) - 1,
                        ),
                        Button.secondary("Edit", on_click=lambda _event, action=action: action(), key=f"onboarding.edit.{index}"),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for index, (title, action) in enumerate(summary_rows)
            ]
            + [Note("Setup stores local preferences only; it does not start refresh or analysis.")],
            spacing=8,
            expand=True,
        )
        return preferences, data_source, watchlist, review

    content = step_contents()
    active_content = ft.Container(content=content[current_step], expand=True)
    stepper_slot = ft.Container(expand=True)
    active_card = ft.Container(expand=True)

    def select_step(index: int) -> None:
        nonlocal current_step
        current_step = max(0, min(index, len(step_names) - 1))
        active_content.content = content[current_step]
        stepper_slot.content = Stepper(
            [
                StepSpec(
                    title=name,
                    status="Current step" if position == current_step else "",
                    state="running" if position == current_step else "done" if position < current_step else "pending",
                    action=Button.secondary("Open", on_click=lambda _event, selected=position: select_step(selected), key=f"onboarding.step.{position}"),
                )
                for position, name in enumerate(step_names)
            ]
        )
        buttons: list[ft.Control] = []
        if current_step > 0:
            buttons.append(Button.secondary("Back", on_click=lambda _event: select_step(current_step - 1), key="onboarding.back"))
        if current_step < len(step_names) - 1:
            buttons.append(Button.primary("Next", on_click=lambda _event: select_step(current_step + 1), key="onboarding.next"))
        else:
            buttons.append(Button.primary("Save setup", on_click=submit, key="onboarding.save"))
        active_card.content = GlassCard(
            title=step_names[current_step],
            body=ft.Column(
                [active_content, ft.Row(buttons, alignment=ft.MainAxisAlignment.END, spacing=12), step_status],
                spacing=16,
                expand=True,
            ),
            expand=True,
        )
        update_page()

    def submit(_event: ft.ControlEvent) -> None:
        selected_optional = tuple(value.strip() for value in (optional_providers_control.value or "").split(",") if value.strip())
        if validation.data.get("on") and validator is not None and "yfinance" not in {value.casefold() for value in selected_optional}:
            selected_optional = (*selected_optional, "yfinance")
        setup_profile = OnboardingProfile(
            selected_values["currency"],
            region_control.value or "",
            (selected_values["scope"],),
            selected_values["risk"],
            selected_values["horizon"],
            tuple(value.strip() for value in (tickers_control.value or "").split(",") if value.strip()),
            selected_values["depth"],
            "project_local",
            selected_values["hardware"],
            (selected_values["provider"],),
            selected_optional,
            selected_values["bootstrap"],
            selected_values["encryption"],
            selected_values["backup"],
            False,
            False,
            bulk_source_path=bulk_path_control.value or "",
        )
        try:
            result = complete_onboarding(setup_profile, ROOT, online=bool(validation.data.get("on")), validator=validator)
            if result.revision and state is not None:
                refreshed_config = load_config(ROOT / "configs") if result.storage_root else load_config()
                if result.storage_root and getattr(state, "snapshot", None) is not None:
                    refreshed_config = overlay_universe_config(state.snapshot.config, refreshed_config)
                apply_method = getattr(state, "apply_universe_config", None)
                if callable(apply_method):
                    apply_method(refreshed_config, result.revision)
                elif getattr(state, "snapshot", None) is not None:
                    state.snapshot.config = refreshed_config
                    state.snapshot.universe_revision = result.revision
                    state.universe_cache_revision = result.revision
            if state is not None:
                refresh_profile = getattr(state, "refresh_runtime_profile", None)
                if callable(refresh_profile):
                    refresh_profile(setup_profile.hardware_profile)
            optional_status = ", ".join(
                f"{provider}: {provider_state}"
                for provider, provider_state in result.optional_provider_status
                if provider_state == "quota_exceeded"
            )
            suffix = f" Optional provider status: {optional_status}; mandatory setup was not blocked." if optional_status else ""
            status.value = "Setup saved locally. Unresolved tickers remain disabled; no refresh or model run was started." + suffix
            technical_details.value = (
                f"Storage path: {result.storage_root}; revision: {result.revision}; "
                f"unresolved symbols: {result.unresolved_symbols}; bootstrap: {result.bootstrap}"
            )
            step_status.value = status.value
        except Exception as exc:
            status.value = "Setup could not be saved."
            technical_details.value = str(exc)
            step_status.value = status.value
        update_page()

    select_step(0)

    authority = GlassCard(
        "Authority boundary",
        note="fixed in this build",
        body=ft.Column(
            [
                Note("Setup stores preferences only. It never grants broker or provider write authority or starts execution."),
                ListRow("bad", "Execution authority", sub="Off", tag=Tag("off", "bad")),
                ListRow("bad", "Staged execution", sub="Off", tag=Tag("off", "bad")),
                ListRow("bad", "Paper trading", sub="Off", tag=Tag("off", "bad")),
                ListRow("bad", "Broker write access", sub="Off", tag=Tag("off", "bad"), last=True),
                Disclosure("Raw authority flags", "execution_allowed=false; staged_execution_enabled=false; paper_enabled=false; broker_write_enabled=false"),
            ],
            spacing=8,
        ),
        expand=True,
    )
    readiness = GlassCard(
        "Hardware and resource readiness",
        note="local profile · no telemetry",
        body=ft.Column(
            [
                ft.Row(
                    [
                        KpiTile("Profile", profile_value, sub=resource_reason),
                        KpiTile("CPU", cpu_value, sub=resource_reason),
                    ],
                    spacing=12,
                ),
                ft.Row(
                    [
                        KpiTile("Memory", memory_value, sub=resource_reason),
                        KpiTile("Disk", disk_value, sub=resource_reason),
                    ],
                    spacing=12,
                ),
                Note("CPU-only baseline remains available; optional foundation models are never required."),
                resource_details,
            ],
            spacing=12,
        ),
        expand=True,
    )
    policy = GlassCard(
        "Data source policy",
        note="local imports or replayable official evidence",
        body=ft.Column(
            [
                policy_table,
                Note(f"Terms acknowledgement: {terms_status}; restricted sources are not redistributed."),
                policy_details,
            ],
            spacing=12,
        ),
        expand=True,
    )

    setup_steps = GlassCard(
        "Setup steps",
        note="4 steps · nothing leaves this computer",
        body=ft.Column(
            [
                stepper_slot,
                Note("Research and education only. Not financial or tax advice. No broker execution or order transmission. Offline or unresolved tickers remain disabled until validated."),
                Disclosure("Save status", ft.Column([status, technical_details], spacing=8)),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )

    row_a = ft.Row(
        [setup_steps, active_card],
        spacing=24,
        expand=6,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    row_b = ft.Row(
        [authority, readiness, policy],
        spacing=24,
        expand=4,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    body = ft.Column([row_a, row_b], spacing=24, expand=True, scroll=ft.ScrollMode.AUTO)
    return PageView(
        chrome=PageChrome(
            title="First-run Setup",
            subtitle="Create a local watchlist without network access",
        ),
        body=body,
    )
