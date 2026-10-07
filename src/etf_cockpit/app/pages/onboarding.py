from __future__ import annotations

from typing import Callable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.kit import status_tag
from etf_cockpit.app.pages._l1a_common import page_view
from etf_cockpit.app.state import AppState
from etf_cockpit.application.settings import ANALYSIS_DEPTHS, HORIZONS, load_config, OUTPUT_CURRENCIES, RISK_PROFILES
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.ui_facade import legal_terms_report, resource_profile_report, source_policy_rows
from etf_cockpit.application.onboarding_profile import (
    _BACKUP_PREFERENCES,
    _BOOTSTRAP_MODES,
    _ENCRYPTION_PREFERENCES,
    _HARDWARE_PROFILES,
    _MANDATORY_PROVIDERS,
    complete_onboarding,
    load_onboarding,
    OnboardingProfile,
    overlay_universe_config,
    TickerValidationResult,
)


def _as_of_strip(state: AppState | None) -> ft.Control:
    """Same as-of date and price-basis tags the dashboard and shell as-of bar show."""

    as_of = getattr(getattr(getattr(state, "snapshot", None), "data_report", None), "as_of_date", None)
    if as_of in (None, ""):
        date_tag = status_tag("As of: Unavailable", "w", key="onboarding.as-of.date")
        date_tag.tooltip = "No snapshot as-of date is available until data has been loaded."
    else:
        date_tag = status_tag(f"As of: {as_of}", "g", key="onboarding.as-of.date")
    return ft.Row(
        [date_tag, status_tag("Price basis: adjusted", "g", key="onboarding.as-of.basis")],
        spacing=8,
        wrap=True,
        key="onboarding.as-of",
    )


def _disclosure(title: str, subtitle: str, content: ft.Control, *, key: str) -> ft.Control:
    """Keep the heading and one-line summary visible; fold the detail behind an expander."""

    return ft.Column(
        [
            section_header(title, subtitle),
            ft.ExpansionTile(
                title=ft.Text("Show details", size=12, color=theme.MUTED),
                controls=[content],
                expanded=False,
                key=key,
                tooltip=f"Show or hide: {title}",
            ),
        ],
        spacing=2,
    )


def onboarding_page(
    page: ft.Page,
    state: AppState,
    *,
    validator: Callable[[str], bool | TickerValidationResult] | None = None,
) -> ft.Control:
    base_currency = ft.Dropdown(label="Output currency", value="EUR", options=[ft.dropdown.Option(item) for item in OUTPUT_CURRENCIES], width=180, dense=True)
    region = ft.TextField(label="Region", value="Europe", width=220, dense=True)
    scope = ft.Dropdown(label="Asset scope", value="stock+etf", options=[ft.dropdown.Option(item) for item in ("stock", "etf", "fund", "bond", "stock+etf", "all")], width=180, dense=True)
    risk = ft.Dropdown(label="Risk profile", value="medium", options=[ft.dropdown.Option(item) for item in RISK_PROFILES], width=220, dense=True)
    horizon = ft.Dropdown(label="Target horizon", value="3M", options=[ft.dropdown.Option(item) for item in HORIZONS], width=180, dense=True)
    analysis_depth = ft.Dropdown(label="Analysis depth", value="medium", options=[ft.dropdown.Option(item) for item in ANALYSIS_DEPTHS], width=180, dense=True)
    storage_location = ft.Dropdown(
        label="Storage location",
        value="project_local",
        options=[ft.dropdown.Option("project_local", "Project-local")],
        width=220,
        dense=True,
    )
    hardware_profile = ft.Dropdown(label="Hardware profile", value="auto", options=[ft.dropdown.Option(item) for item in sorted(_HARDWARE_PROFILES)], width=180, dense=True)
    mandatory_provider = ft.Dropdown(label="Mandatory provider", value="manual_local", options=[ft.dropdown.Option(item) for item in sorted(_MANDATORY_PROVIDERS)], width=220, dense=True)
    optional_providers = ft.TextField(label="Optional providers (comma separated)", hint_text="yfinance, fred", width=280, dense=True)
    bootstrap_mode = ft.Dropdown(label="Offline bootstrap", value="sample", options=[ft.dropdown.Option(item) for item in sorted(_BOOTSTRAP_MODES)], width=180, dense=True)
    bulk_source_path = ft.TextField(label="Local bulk price file", hint_text="data/import/prices.csv", width=280, dense=True, key="onboarding.bulk-source")
    encryption_preference = ft.Dropdown(label="Encryption", value="disabled", options=[ft.dropdown.Option(item) for item in sorted(_ENCRYPTION_PREFERENCES)], width=180, dense=True)
    backup_preference = ft.Dropdown(label="Backups (unavailable during onboarding)", value="local", options=[ft.dropdown.Option(item) for item in sorted(_BACKUP_PREFERENCES)], width=180, dense=True)
    tickers = ft.TextField(
        label="Initial tickers (comma separated)",
        hint_text="VWCE.DE, MSFT",
        dense=True,
    )
    online_validation = ft.Checkbox(
        label="Validate tickers online (optional)" if validator is not None else "Online validation unavailable (no validator configured)",
        value=False,
        disabled=validator is None,
        key="onboarding.online-validation",
    )
    status = ft.Text("", color=theme.MUTED, selectable=True, key="onboarding.status")
    project_root = ROOT.resolve()
    try:
        source_rows = source_policy_rows(project_root, project_root / "configs" / "data_source_policy.yaml")
        source_summary = "\n".join(
            f"{row['provider_id']}: tier={row['source_tier']} | {row['optionality']} | cache={row['cache_status']} | network={row['network']}"
            for row in source_rows
        )
    except (OSError, ValueError):
        try:
            source_rows = source_policy_rows(project_root, project_root / "configs" / "data_source_policy.yaml")
            source_summary = (
                "Current-directory policy unavailable; using bundled local policy.\n"
                + "\n".join(
                    f"{row['provider_id']}: tier={row['source_tier']} | {row['optionality']} | cache={row['cache_status']} | network={row['network']}"
                    for row in source_rows
                )
            )
        except (OSError, ValueError) as exc:
            source_summary = f"Data source policy unavailable: {type(exc).__name__}; mandatory policy choices require explicit local action."
    try:
        legal_report = legal_terms_report(project_root, project_root / "configs" / "legal_terms_registry.yaml")
    except (OSError, ValueError):
        try:
            legal_report = legal_terms_report(project_root, project_root / "configs" / "legal_terms_registry.yaml")
        except (OSError, ValueError):
            legal_report = {
                "jurisdictions": [{"disclaimer": "Legal terms registry unavailable; review local terms before use."}],
                "review_status": "unavailable",
                "registry_sha256": "unavailable",
            }
    jurisdiction_disclaimer = str(legal_report["jurisdictions"][0]["disclaimer"])
    selected_profile_id = "auto"
    try:
        selected_profile_id = load_onboarding(ROOT).hardware_profile
    except ValueError:
        pass
    resource_report = resource_profile_report(ROOT, requested_profile=selected_profile_id)
    selected_profile = resource_report["selected_profile"]
    resource_lines = [
        f"Selected profile: {selected_profile['profile_id']} ({resource_report['selected_status']}) | CPU {resource_report['snapshot']['cpu_cores']} core(s) | memory {resource_report['snapshot'].get('memory_available_mb') or resource_report['snapshot'].get('memory_total_mb') or 'n/a'} MB available/total | disk {resource_report['snapshot'].get('disk_free_mb') or 'n/a'} MB free",
        f"Per-job quota: {selected_profile['job_memory_limit_mb']} MB memory | {selected_profile['job_disk_limit_mb']} MB disk | {selected_profile['job_cpu_limit']} CPU core(s)",
        "Profiles: " + "; ".join(f"{row['profile_id']}={row['status']}" for row in resource_report["profiles"]),
        f"Performance evidence: {resource_report['benchmarks']['status']} from {resource_report['benchmarks']['timing_record_count']} local timing record(s); generated-cache cleanup: {resource_report['generated_cache']['status']}",
        "Limitations: " + " ".join(resource_report["limitations"]),
    ]

    def submit(_event: ft.ControlEvent) -> None:
        values = tuple(value.strip() for value in (tickers.value or "").split(",") if value.strip())
        selected_optional = tuple(value.strip() for value in (optional_providers.value or "").split(",") if value.strip())
        if online_validation.value and validator is not None and "yfinance" not in {item.casefold() for item in selected_optional}:
            selected_optional = (*selected_optional, "yfinance")
        profile = OnboardingProfile(
            base_currency.value or "",
            region.value or "",
            (scope.value or "stock+etf",),
            risk.value or "",
            horizon.value or "",
            values,
            analysis_depth.value or "medium",
            storage_location.value or "",
            hardware_profile.value or "",
            (mandatory_provider.value or "",),
            selected_optional,
            bootstrap_mode.value or "",
            encryption_preference.value or "",
            backup_preference.value or "",
            False,
            False,
            bulk_source_path=bulk_source_path.value or "",
        )
        try:
            result = complete_onboarding(
                profile,
                ROOT,
                online=bool(online_validation.value),
                validator=validator,
            )
            if result.revision and state is not None:
                refreshed_config = load_config(ROOT / "configs") if result.storage_root else load_config()
                if result.storage_root and getattr(state, "snapshot", None) is not None:
                    refreshed_config = overlay_universe_config(state.snapshot.config, refreshed_config)
                apply_method = getattr(state, "apply_universe_config", None)
                if callable(apply_method):
                    apply_method(refreshed_config, result.revision)
                else:
                    state.snapshot.config = refreshed_config
                    state.snapshot.universe_revision = result.revision
                    state.universe_cache_revision = result.revision
            if state is not None:
                refresh_profile = getattr(state, "refresh_runtime_profile", None)
                if callable(refresh_profile):
                    refresh_profile(profile.hardware_profile)
            optional_status = ", ".join(f"{provider}: {state}" for provider, state in result.optional_provider_status if state == "quota_exceeded")
            suffix = f" Optional provider status: {optional_status}; mandatory setup was not blocked." if optional_status else ""
            bootstrap_status = f" Bootstrap {result.bootstrap.mode}: {result.bootstrap.status} — {result.bootstrap.message}" if result.bootstrap else ""
            status.value = f"Saved locally at {result.storage_root}. {len(result.unresolved_symbols)} unresolved ticker(s) remain disabled; no refresh or model run was started.{bootstrap_status}{suffix}"
        except Exception as exc:
            status.value = f"Setup not saved: {exc}"
        page.update()

    body = ft.Column(
        [
            panel(ft.Column([_as_of_strip(state), section_header("First-run setup", "Create a local watchlist without requiring network access."), ft.Text(f"{jurisdiction_disclaimer} Offline or unresolved tickers remain disabled until validated. Online validation is opt-in and requires an injected provider callback.", color=theme.MUTED), ft.Row([base_currency, region, scope, risk, horizon, analysis_depth], wrap=True), _disclosure("Advanced setup options", "Storage, hardware profile, providers, bootstrap, encryption and backups; defaults are safe and offline.", ft.Column([ft.Row([storage_location, ft.Text(f"Project-local runtime root: {ROOT}", color=theme.MUTED), hardware_profile, mandatory_provider, optional_providers, bootstrap_mode, bulk_source_path, encryption_preference, backup_preference], wrap=True), ft.Text("Sample creates a shipped identity-only universe without fabricated prices. Bulk accepts only an explicit local price file and remains visibly unavailable when absent or invalid.", color=theme.MUTED, size=11), ft.Text("Mandatory providers are offline-compatible. Optional provider absence or quota failure is recorded visibly and never blocks setup.", color=theme.MUTED, size=11), ft.Text("Quick/Medium/High/Full are versioned analysis-effort selections; warm/cold timing effects remain unavailable until ISSUE-0175.", color=theme.MUTED, size=11)], spacing=8), key="onboarding.details.advanced"), ft.ResponsiveRow([ft.Container(content=tickers, col={"xs": 12, "md": 9}), ft.Container(content=ft.Button("Save setup", key="onboarding.save", icon=ft.Icons.SAVE, on_click=submit), col={"xs": 12, "md": 3})], spacing=8, run_spacing=8), online_validation, status], spacing=10)),
            panel(ft.Column([section_header("Authority boundary", "Setup stores preferences only. It never grants broker/provider write authority or starts execution."), ft.Text("execution_allowed=false | staged_execution_enabled=false | paper_enabled=false | broker_write_enabled=false", color=theme.AMBER)])),
            _disclosure("Hardware and resource readiness", "Local profile selection, pre-job limits and graceful degradation. No telemetry or cloud compute is used.", ft.Column([ft.SelectionArea(ft.Text("\n".join(resource_lines), color=theme.MUTED)), ft.SelectionArea(ft.Text("CPU-only baseline remains available; optional foundation models are never required.", color=theme.GREEN))], spacing=6), key="onboarding.details.resources"),
            _disclosure("Data source policy", "Choose local imports or replayable official evidence for the mandatory path. Online validation is optional and never required for setup.", ft.Column([ft.Text(source_summary, color=theme.MUTED, size=11, selectable=True), ft.Text(f"Terms acknowledgement: {legal_report['review_status']}; restricted sources are not redistributed. Registry checksum: {legal_report['registry_sha256']}", color=theme.AMBER, size=11, selectable=True)], spacing=6), key="onboarding.details.sources"),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return page_view(
        "First-run Setup",
        "Create a local watchlist without network access",
        body,
    )
