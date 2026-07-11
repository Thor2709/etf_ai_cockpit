from __future__ import annotations

from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.provider_registry import ProviderRegistry
from etf_cockpit.parsers.esef_ixbrl import parse_esef_package
from etf_cockpit.parsers.priips_kid import parse_priips_kid
from etf_cockpit.parsers.index_methodology import parse_index_methodology
from etf_cockpit.parsers.sec_facts import parse_companyfacts
from etf_cockpit.data.trust_artifacts import (
    BENCHMARK_ATTRIBUTION_PATH,
    CORRELATION_CLUSTERS_PATH,
    ETF_DISCLOSURES_PATH,
    EVIDENCE_LEDGER_PATH,
    FEATURE_DRIVERS_PATH,
    FILINGS_STATEMENTS_PATH,
    IDENTITY_PATH,
    NEWS_CONTEXT_PATH,
    NEWS_TIMESTAMP_VALIDATION_PATH,
    PROVIDER_PROBE_PATH,
    SCORE_COMPONENTS_PATH,
    SCORE_HISTORY_PATH,
    SCORE_METRIC_HISTORY_PATH,
    SOURCE_CONFLICTS_PATH,
)


def provider_status_page(_page: ft.Page, state: AppState) -> ft.Control:
    capabilities = ProviderRegistry(state.snapshot.config.data_providers).probe_all()
    capability_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(item.provider_id, color=theme.TEXT)),
                ft.DataCell(ft.Text(item.status, color=theme.GREEN if item.status == "ok" else theme.AMBER)),
                ft.DataCell(ft.Text(item.authority.value, color=theme.MUTED)),
                ft.DataCell(ft.Text("yes" if item.score_eligible else "no", color=theme.GREEN if item.score_eligible else theme.MUTED)),
                ft.DataCell(ft.Text(item.message, color=theme.MUTED, selectable=True)),
            ]
        )
        for item in capabilities
    ]
    capability_panel = panel(
        ft.Column(
            [
                section_header("Capability registry", "Disabled providers are not probed. Missing keys and optional entitlements remain unavailable and cannot feed scoring."),
                ft.DataTable(columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in ("Provider", "Status", "Authority", "Score eligible", "Message")], rows=capability_rows),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )
    return _status_page(
        "Provider Status",
        "Provider capabilities, source authority and disabled/unavailable states. API keys are redacted and never exported.",
        [
            ("Provider probes", PROVIDER_PROBE_PATH, ["dataset_type", "provider_name", "status", "source_authority", "enabled", "message"]),
            ("Instrument identity", IDENTITY_PATH, ["instrument_id", "analysis_tier", "instrument_type", "isin", "yahoo_symbol", "identity_confidence", "warnings"]),
            ("Source conflicts", SOURCE_CONFLICTS_PATH, ["instrument_id", "field_name", "resolution_status", "requires_manual_review"]),
        ],
        extra=capability_panel,
    )


def evidence_ledger_page(_page: ft.Page, _state) -> ft.Control:
    return _status_page(
        "Evidence Ledger",
        "Score components, evidence provenance and source conflicts. Evidence rows are advisory inputs only.",
        [
            ("Evidence ledger", EVIDENCE_LEDGER_PATH, ["instrument_id", "component", "source_authority", "freshness_status", "score_eligible", "reason"]),
            ("Score components", SCORE_COMPONENTS_PATH, ["instrument_id", "component", "normalised_score_10", "status", "authority", "driver_text"]),
            ("Feature drivers", FEATURE_DRIVERS_PATH, ["instrument_id", "component", "normalised_score", "direction", "authority", "driver_text"]),
            ("Score history", SCORE_HISTORY_PATH, ["instrument_id", "run_completed_at", "final_combined_score_10", "final_label", "blocked_by"]),
            ("Score metric history", SCORE_METRIC_HISTORY_PATH, ["instrument_id", "component_name", "normalised_score_10", "score_available", "na_reason"]),
            ("Correlation clusters", CORRELATION_CLUSTERS_PATH, ["instrument_id", "cluster_label", "average_peer_correlation", "crowding_warning"]),
            ("Benchmark attribution", BENCHMARK_ATTRIBUTION_PATH, ["instrument_id", "benchmark_id", "benchmark_beta", "benchmark_correlation", "alpha_proxy", "sector_theme_warning"]),
        ],
    )


def filings_page(page: ft.Page, state: AppState) -> ft.Control:
    return _status_page(
        "Filings & Statements",
        "Official SEC/ESEF/local filing evidence. Missing filings remain missing; vendor fundamentals cannot outrank official matched filings.",
        [
            ("Filings inventory", FILINGS_STATEMENTS_PATH, ["instrument_id", "document_type", "source_authority", "coverage_status", "path"]),
            ("Provider probes", PROVIDER_PROBE_PATH, ["dataset_type", "provider_name", "status", "source_authority", "message"]),
            ("Identity mappings", IDENTITY_PATH, ["instrument_id", "isin", "yahoo_symbol", "exchange", "identity_confidence", "warnings"]),
        ],
        extra=_filing_import_controls(page, state),
    )


def etf_disclosures_page(page: ft.Page, state: AppState) -> ft.Control:
    return _status_page(
        "ETF Disclosures",
        "ETF factsheets, holdings, PRIIPs KIDs, reports and index methodology inventory. Partial coverage is shown explicitly.",
        [
            ("ETF disclosure inventory", ETF_DISCLOSURES_PATH, ["instrument_id", "document_type", "source_authority", "coverage_status", "path"]),
            ("Source conflicts", SOURCE_CONFLICTS_PATH, ["instrument_id", "field_name", "resolution_status", "requires_manual_review"]),
        ],
        extra=_disclosure_import_controls(page, state),
    )


def news_context_page(_page: ft.Page, _state) -> ft.Control:
    return _status_page(
        "News & Context",
        "Free/manual news and context evidence. News is non-executable and cannot directly change scores or actions.",
        [
            ("News/context inventory", NEWS_CONTEXT_PATH, ["instrument_id", "provider_name", "published_at", "timestamp_confidence", "context_only", "path"]),
            ("Point-in-time validation", NEWS_TIMESTAMP_VALIDATION_PATH, ["news_id", "timestamp_status", "backtest_eligible", "reason"]),
            ("Optional free provider status", PROVIDER_PROBE_PATH, ["dataset_type", "provider_name", "status", "message"]),
        ],
    )


def _status_page(title: str, subtitle: str, tables: list[tuple[str, Path, list[str]]], *, extra: ft.Control | None = None) -> ft.Control:
    controls: list[ft.Control] = [
        panel(
            ft.Column(
                [
                    section_header(title, subtitle),
                    ft.Row(
                        [
                            evidence_chip("Authority", "advisory/context only", theme.CYAN),
                            evidence_chip("Missing data", "N/A, not invented", theme.AMBER),
                            evidence_chip("Broker execution", "disabled", theme.GREEN),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=10,
            )
        )
    ]
    if extra is not None:
        controls.append(extra)
    controls.extend(_table_panel(label, path, columns) for label, path, columns in tables)
    return ft.Column(
        controls,
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _filing_import_controls(page: ft.Page, state: AppState) -> ft.Control:
    result = ft.Text("No official filing imported in this view.", color=theme.MUTED, selectable=True)
    picker = _attach_picker(page)

    async def import_sec(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["json"], with_data=True)
        if not files:
            result.value = "SEC import cancelled; no data changed."
            page.update()
            return
        selected = files[0]
        path = Path(selected.path) if selected.path else None
        if path is None or not path.exists():
            result.value = "SEC import requires a readable local JSON path."
        else:
            identity = CanonicalIdentity("imported_sec", "Imported SEC entity", None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), None)
            parsed = parse_companyfacts(path, identity)
            result.value = f"SEC parser {parsed.parser_name}: {len(parsed.records)} facts, {len(parsed.warnings)} warnings, success={parsed.success}."
            state.last_message = result.value
        page.update()

    async def import_esef(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["xbri", "zip"], with_data=True)
        if not files:
            result.value = "ESEF import cancelled; no data changed."
        else:
            selected = files[0]
            path = Path(selected.path) if selected.path else None
            parsed = parse_esef_package(path) if path and path.exists() else None
            result.value = "ESEF import requires a readable local package." if parsed is None else f"ESEF parser {parsed.parser_name}: {len(parsed.records)} facts, {len(parsed.warnings)} warnings, success={parsed.success}."
            state.last_message = result.value
        page.update()

    return panel(ft.Column([section_header("Official filing import", "Local SEC companyfacts JSON and ESEF report packages are parsed with checksum/provenance warnings; unavailable network remains controlled."), ft.Row([ft.OutlinedButton("Import SEC companyfacts", key="filings.import-sec", icon=ft.Icons.UPLOAD_FILE, on_click=import_sec), ft.OutlinedButton("Import ESEF package", key="filings.import-esef", icon=ft.Icons.UPLOAD_FILE, on_click=import_esef)], wrap=True), result], spacing=8))


def _disclosure_import_controls(page: ft.Page, state: AppState) -> ft.Control:
    result = ft.Text("No ETF disclosure imported in this view.", color=theme.MUTED, selectable=True)
    picker = _attach_picker(page)

    async def import_kid(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"], with_data=True)
        if not files:
            result.value = "PRIIPs KID import cancelled; no data changed."
        else:
            path = Path(files[0].path) if files[0].path else None
            parsed = parse_priips_kid(path) if path and path.exists() else None
            result.value = "PRIIPs import requires a readable PDF." if parsed is None else f"PRIIPs parser {parsed.parser_name}: {len(parsed.records)} record(s), {len(parsed.warnings)} warnings, success={parsed.success}."
            state.last_message = result.value
        page.update()

    async def import_methodology(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"], with_data=True)
        if not files:
            result.value = "Methodology import cancelled; no data changed."
        else:
            path = Path(files[0].path) if files[0].path else None
            parsed = parse_index_methodology(path, "Imported index provider") if path and path.exists() else None
            result.value = "Methodology import requires a readable PDF." if parsed is None else f"Methodology parser {parsed.parser_name}: {len(parsed.records)} record(s), {len(parsed.warnings)} warnings, success={parsed.success}."
            state.last_message = result.value
        page.update()

    return panel(ft.Column([section_header("ETF disclosure import", "PRIIPs KIDs and index methodology PDFs are extracted deterministically with page/checksum warnings. Missing fields stay unavailable."), ft.Row([ft.OutlinedButton("Import PRIIPs KID", key="etf-disclosures.import-kid", icon=ft.Icons.UPLOAD_FILE, on_click=import_kid), ft.OutlinedButton("Import index methodology", key="etf-disclosures.import-methodology", icon=ft.Icons.UPLOAD_FILE, on_click=import_methodology)], wrap=True), result], spacing=8))


def _attach_picker(page: ft.Page) -> ft.FilePicker:
    picker = ft.FilePicker()
    try:
        page.services.append(picker)
    except Exception:
        try:
            page.overlay.append(picker)
        except Exception:
            pass
    return picker


def _table_panel(label: str, path: Path, columns: list[str]) -> ft.Control:
    frame = _read_frame(path)
    selected_columns = [column for column in columns if column in frame.columns]
    if frame.empty:
        body: ft.Control = ft.Text(
            f"No rows in {path}. This is an explicit unavailable/missing state, not inferred evidence.",
            color=theme.MUTED,
            selectable=True,
        )
    elif not selected_columns:
        body = ft.Text(
            f"{len(frame)} rows available at {path}, but requested preview columns are missing. Columns: {', '.join(frame.columns)}",
            color=theme.MUTED,
            selectable=True,
        )
    else:
        preview = frame[selected_columns].head(12).fillna("")
        body = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(column, color=theme.TEXT, size=11)) for column in selected_columns],
            rows=[
                ft.DataRow(
                    cells=[ft.DataCell(ft.Text(_short(value), color=theme.MUTED, size=11, selectable=True)) for value in row]
                )
                for row in preview.itertuples(index=False, name=None)
            ],
        )
    return panel(
        ft.Column(
            [
                section_header(label, f"{path}"),
                body,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
    )


def _read_frame(path: Path) -> pd.DataFrame:
    try:
        if path.exists():
            return pd.read_parquet(path)
    except Exception:
        pass
    return pd.DataFrame()


def _short(value: object, max_len: int = 96) -> str:
    text = str(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."
