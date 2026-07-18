from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterator

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import RAW_DIR, STATEMENT_FACTS_PATH
from etf_cockpit.application.ui_facade import (
    BENCHMARK_ATTRIBUTION_PATH,
    CORRELATION_CLUSTERS_PATH,
    ETF_DISCLOSURES_PATH,
    EVIDENCE_LEDGER_PATH,
    FEATURE_DRIVERS_PATH,
    FILINGS_STATEMENTS_PATH,
    FUNDAMENTAL_CLEAN_PATH,
    FUND_HOLDINGS_PATH,
    IDENTITY_PATH,
    INDEX_METHODOLOGY_RECORDS_PATH,
    NEWS_CONTEXT_PATH,
    NEWS_TIMESTAMP_VALIDATION_PATH,
    PRIIPS_KID_RECORDS_PATH,
    PROVIDER_PROBE_PATH,
    SCORE_COMPONENTS_PATH,
    SCORE_HISTORY_PATH,
    SCORE_METRIC_HISTORY_PATH,
    SOURCE_CONFLICTS_PATH,
    ProviderRegistry,
    build_news_contradiction_rows,
    import_etf_document,
    import_etf_holdings_with_document,
    legal_terms_rows,
    load_news_items,
    persist_index_methodology_with_document,
    persist_priips_kid_with_document,
    read_document_registry,
    sort_fundamental_evidence,
    sort_news_items,
    source_policy_rows,
)
from etf_cockpit.plugins.builtins import plugin_status_rows


@contextmanager
def _materialise_picker_file(selected: object, suffix: str) -> Iterator[Path | None]:
    """Expose a FilePicker selection as a readable local path on web and native hosts."""

    selected_path = getattr(selected, "path", None)
    candidate = Path(selected_path) if selected_path else None
    if candidate is not None and candidate.is_file():
        yield candidate
        return

    payload = getattr(selected, "bytes", None)
    if not payload:
        yield None
        return

    descriptor, temporary_name = tempfile.mkstemp(prefix="etf-cockpit-upload-", suffix=suffix)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_bytes(payload)
        yield temporary_path
    finally:
        temporary_path.unlink(missing_ok=True)


def _retain_picker_source(path: Path | None, subdirectory: str) -> Path | None:
    """Retain uploaded bytes under the raw evidence directory before parsing."""

    if path is None or not path.is_file():
        return None
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    suffix = path.suffix.lower() or ".pdf"
    destination = RAW_DIR / subdirectory / f"{digest}{suffix}"
    atomic_write_bytes(
        destination,
        payload,
        validator=lambda candidate: hashlib.sha256(candidate.read_bytes()).hexdigest() == digest,
    )
    return destination


def _latest_document_row(registry: pd.DataFrame, document_type: str) -> pd.Series | None:
    """Return the newest registered version for a document type."""

    matches = registry.loc[registry["document_type"].astype(str).eq(document_type)]
    if matches.empty:
        return None
    return matches.iloc[0]


def _document_checksum(row: pd.Series | None) -> str:
    if row is None:
        return ""
    value = row.get("sha256")
    return "" if value is None or pd.isna(value) else str(value)


def _start_disclosure_import(state: AppState, result: ft.Control, label: str) -> None:
    """Expose a durable running state before a disclosure parser begins."""

    state.begin_activity(label, "Reading selected document")
    result.value = f"{label} in progress: reading selected document..."


def provider_status_page(_page: ft.Page, state: AppState) -> ft.Control:
    registry = ProviderRegistry(state.snapshot.config.data_providers)
    capabilities = registry.probe_all()
    status_rows = registry.status_rows(capabilities) + plugin_status_rows()
    capability_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row["provider_id"]), color=theme.TEXT)),
                ft.DataCell(ft.Text(str(row["dataset_type"]), color=theme.MUTED)),
                ft.DataCell(ft.Text(f"{row['enabled']}/{row['configured']}", color=theme.MUTED)),
                ft.DataCell(ft.Text(str(row["status"]), color=theme.GREEN if row["status"] in {"ok", "available"} else theme.AMBER)),
                ft.DataCell(ft.Text(str(row["authority"]), color=theme.MUTED)),
                ft.DataCell(ft.Text(str(row["entitlement"]), color=theme.MUTED)),
                ft.DataCell(ft.Text(str(row["rate_limit_note"]), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(str(row["last_success_at"] or "N/A"), color=theme.MUTED)),
                ft.DataCell(ft.Text("yes" if row["score_eligible"] else "no", color=theme.GREEN if row["score_eligible"] else theme.MUTED)),
                ft.DataCell(ft.Text(_short(str(row["redacted_configuration"])), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(str(row["message"]), color=theme.MUTED, selectable=True)),
            ]
        )
        for row in status_rows
    ]
    capability_panel = panel(
        ft.Column(
            [
                section_header("Capability registry", "Providers, models and broker adapters share one allow-listed contract. Disabled capabilities are never probed and cannot escalate execution authority."),
                ft.Text("Fields: enabled/configured, status, authority, capabilities, entitlement, rate/limit note, last success, score eligibility and redacted configuration. Broker adapters remain disabled.", color=theme.MUTED, size=11, selectable=True),
                ft.Text("Built-in plugins: " + ", ".join(str(row["provider_id"]) for row in plugin_status_rows()), color=theme.MUTED, size=11, selectable=True),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in ("Provider/plugin", "Kind", "Enabled/configured", "Status", "Authority", "Entitlement", "Rate/limit", "Last success", "Score eligible", "Redacted configuration", "Message")],
                    rows=capability_rows,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )
    policy_rows = source_policy_rows(Path.cwd())
    terms_rows = legal_terms_rows(Path.cwd())
    source_policy_panel = panel(
        ft.Column(
            [
                section_header("Mandatory source tiers", "The mandatory path accepts local imports, official bulk files or official cached snapshots. Optional providers remain visible but cannot become required by quota or subscription."),
                ft.Text("Source policy is local-first and no-network for release replay. Cache status describes the local replay path; it does not perform a provider request.", color=theme.MUTED, size=11, selectable=True),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in ("Provider", "Dataset", "Source tier", "Optionality", "Cache", "Network", "Quota failure")],
                    rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(str(row[key]), color=theme.MUTED, selectable=True)) for key in ("provider_id", "dataset_type", "source_tier", "optionality", "cache_status", "network", "quota_failure")]) for row in policy_rows],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )
    legal_terms_panel = panel(
        ft.Column(
            [
                section_header("Legal terms and export boundaries", "Source, model and package terms are recorded locally and do not grant permission to redistribute restricted material."),
                ft.Text("Restricted sources are local-only or metadata-only in standard audit exports. Terms changes require review; unknown optional terms disable the capability and cannot affect the mandatory path.", color=theme.MUTED, size=11, selectable=True),
                ft.Text("Optional restricted entries include yfinance, stooq, RSS feeds and model weights; they remain disabled or local-only when permission is unclear.", color=theme.AMBER, size=11, selectable=True),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in ("Entry", "Kind", "Terms status", "Cache", "Redistribution", "Audit export")],
                    rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(str(row[key]), color=theme.MUTED, selectable=True)) for key in ("entry_id", "entry_kind", "terms_status", "permitted_cache", "redistribution", "audit_export")]) for row in terms_rows],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )
    return _status_page(
        "Provider Status",
        "Provider capabilities, source authority and disabled/unavailable states. API keys are redacted and never exported.",
        [
            ("Provider probes", PROVIDER_PROBE_PATH, ["dataset_type", "provider_name", "status", "source_authority", "enabled", "configured", "entitlement", "rate_limit_note", "last_success_at", "message"]),
            ("Instrument identity", IDENTITY_PATH, ["instrument_id", "analysis_tier", "instrument_type", "isin", "yahoo_symbol", "exchange", "mic", "currency", "share_class", "listing", "identity_confidence", "identity_status", "warnings"]),
            ("Source conflicts", SOURCE_CONFLICTS_PATH, ["instrument_id", "field_name", "canonical_value", "resolution_status", "requires_manual_review", "reason"]),
        ],
        extra=ft.Column([capability_panel, source_policy_panel, legal_terms_panel], spacing=10),
    )


def evidence_ledger_page(_page: ft.Page, _state) -> ft.Control:
    return _status_page(
        "Evidence Ledger",
        "Score components, evidence provenance and source conflicts. Evidence rows are advisory inputs only.",
        [
            ("Evidence ledger", EVIDENCE_LEDGER_PATH, ["instrument_id", "component", "source_id", "source_authority", "authority_rank", "as_of_date", "freshness_status", "conflict_id", "score_eligible", "reason"]),
            ("Score components", SCORE_COMPONENTS_PATH, ["instrument_id", "component", "source_id", "source_authority", "normalised_score_10", "status", "authority", "freshness_status", "conflict_id", "driver_text"]),
            ("Feature drivers", FEATURE_DRIVERS_PATH, ["instrument_id", "component", "normalised_score", "direction", "authority", "driver_text"]),
            ("Score history", SCORE_HISTORY_PATH, ["instrument_id", "run_completed_at", "final_combined_score_10", "final_label", "blocked_by"]),
            ("Score metric history", SCORE_METRIC_HISTORY_PATH, ["instrument_id", "component_name", "normalised_score_10", "score_available", "na_reason"]),
            ("Correlation clusters", CORRELATION_CLUSTERS_PATH, ["instrument_id", "cluster_label", "average_peer_correlation", "crowding_warning", "cluster_risk_contribution", "ranking_coverage", "pair_sample_size", "sector", "theme", "theme_warning", "top_ranked_theme_concentration", "top_ranked_theme_warning", "sample_size", "status", "execution_allowed"]),
            ("Benchmark attribution", BENCHMARK_ATTRIBUTION_PATH, ["instrument_id", "benchmark_id", "benchmark_beta", "benchmark_correlation", "alpha_proxy", "sector_relative_return", "sector_alpha_proxy", "sector_attribution_status", "theme_relative_return", "theme_alpha_proxy", "theme_attribution_status", "net_expected_edge_bps", "friction_status", "status", "execution_allowed"]),
        ],
    )


def filings_page(page: ft.Page, state: AppState) -> ft.Control:
    return _status_page(
        "Filings & Statements",
        "Official SEC/ESEF/local filing evidence. Missing filings remain missing; vendor fundamentals cannot outrank official matched filings.",
        [
            ("Filings inventory", FILINGS_STATEMENTS_PATH, ["instrument_id", "document_type", "source_authority", "coverage_status", "fact_count", "mapping_warnings", "checksum", "executable_authority", "path"]),
            ("SEC statement facts", STATEMENT_FACTS_PATH, ["instrument_id", "taxonomy", "concept", "canonical_metric", "mapping_status", "is_custom", "unit", "end", "filed", "form", "accession", "source_id"]),
            ("Provider probes", PROVIDER_PROBE_PATH, ["dataset_type", "provider_name", "status", "source_authority", "message"]),
            ("Identity mappings", IDENTITY_PATH, ["instrument_id", "isin", "yahoo_symbol", "exchange", "mic", "currency", "share_class", "listing", "identity_confidence", "warnings"]),
            ("Fundamental evidence", FUNDAMENTAL_CLEAN_PATH, ["instrument_id", "as_of_date", "eligibility", "missing_fields", "warnings", "source", "source_authority", "limitations", "score_eligible", "executable_authority"]),
        ],
        extra=_filing_import_controls(page, state),
    )


def etf_disclosures_page(page: ft.Page, state: AppState) -> ft.Control:
    return _status_page(
        "ETF Disclosures",
        "ETF factsheets, holdings, PRIIPs KIDs, reports and index methodology inventory. Partial coverage is shown explicitly.",
        [
            ("ETF disclosure inventory", ETF_DISCLOSURES_PATH, ["instrument_id", "document_type", "source_id", "source_url", "source_authority", "as_of_date", "checksum", "coverage_status", "path"]),
            ("Parsed PRIIPs KID evidence", PRIIPS_KID_RECORDS_PATH, ["instrument_id", "isin", "sri", "cost_fields", "holding_period_years", "document_date", "extraction_confidence", "source_pages", "warnings", "source_sha256", "parser_version", "source_authority", "freshness_status", "manual_review", "score_eligible"]),
            ("Parsed index methodology evidence", INDEX_METHODOLOGY_RECORDS_PATH, ["instrument_id", "provider", "index_series", "version", "document_date", "eligibility_rules", "weighting_rules", "review_frequency", "caps", "source_pages", "warnings", "source_sha256", "parser_version", "source_authority", "freshness_status", "manual_review", "score_eligible"]),
            ("ETF holdings evidence", FUND_HOLDINGS_PATH, ["instrument_id", "as_of_date", "source", "completeness", "freshness", "confidence", "authority", "score_eligible", "source_id"]),
            ("Source conflicts", SOURCE_CONFLICTS_PATH, ["instrument_id", "field_name", "canonical_value", "resolution_status", "requires_manual_review", "reason"]),
        ],
        extra=_disclosure_import_controls(page, state),
    )


def news_context_page(_page: ft.Page, state: AppState) -> ft.Control:
    return _status_page(
        "News & Context",
        "Free/manual news and context evidence. News is non-executable and cannot directly change scores or actions.",
        [
            ("News/context inventory", NEWS_CONTEXT_PATH, ["instrument_id", "source_url", "published_at", "ingested_at", "provider_name", "credibility", "instrument_mapping_method", "available_at_decision_time", "timestamp_status", "context_only", "executable_authority", "raw_path"]),
            ("Point-in-time validation", NEWS_TIMESTAMP_VALIDATION_PATH, ["news_id", "timestamp_status", "backtest_eligible", "reason", "available_at_decision_time", "instrument_mapping_method"]),
            ("Optional free provider status", PROVIDER_PROBE_PATH, ["dataset_type", "provider_name", "status", "message"]),
            ("Fundamental source limitations", FUNDAMENTAL_CLEAN_PATH, ["instrument_id", "source", "source_authority", "limitations", "score_eligible", "executable_authority"]),
        ],
        extra=_news_context_extra(state),
    )


def _news_context_extra(state: AppState) -> ft.Control:
    frame = load_news_items(NEWS_CONTEXT_PATH)
    prices = state.snapshot.prices if isinstance(state.snapshot.prices, pd.DataFrame) else pd.DataFrame()
    contradictions = build_news_contradiction_rows(frame, prices)
    if frame.empty:
        body: ft.Control = ft.Text("News unavailable; no canonical local items are registered. Contradictions are unavailable.", color=theme.MUTED, selectable=True)
    elif contradictions.empty:
        body = ft.Text("No deterministic contradictions detected for the dated price rows available. Unsupported or undated comparisons remain unavailable.", color=theme.MUTED, selectable=True)
    else:
        body = ft.Column(
            [ft.Text(f"{row['instrument_id']} | {row['headline']} | headline={row['headline_direction']} price={row['price_direction']} | {row['reason']}", color=theme.AMBER, selectable=True, size=11) for _, row in contradictions.iterrows()],
            spacing=4,
        )
    return panel(
        ft.Column(
            [
                section_header("News contradictions", "Explicit headline direction is compared with the next dated deterministic close; this panel is informational and cannot alter scores or actions."),
                body,
            ],
            spacing=8,
        )
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
    result = ft.Text("SEC import status: unavailable until a local fixture is selected or a CIK fetch is requested.", color=theme.MUTED, selectable=True)
    cik_field = ft.TextField(label="SEC CIK", value="789019", width=180)
    country_field = ft.TextField(label="ESEF country", value="NL", width=120)
    filing_id_field = ft.TextField(label="ESEF filing ID", width=250)
    picker = _attach_picker(page, "filings.import.file-picker")

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
            result.value = state.import_sec_companyfacts(path)
        page.update()

    async def fetch_sec(_event: ft.ControlEvent) -> None:
        cik = str(cik_field.value or "").strip()
        result.value = "SEC import status: fetching official companyfacts with bounded requests..."
        page.update()
        result.value = state.fetch_sec_companyfacts(cik)
        page.update()

    async def import_esef(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["xbri", "zip"], with_data=True)
        if not files:
            result.value = "ESEF import cancelled; no data changed."
        else:
            selected = files[0]
            path = Path(selected.path) if selected.path else None
            try:
                result.value = state.import_esef_package(path) if path and path.exists() else "ESEF import requires a readable local package."
            except Exception as exc:
                state.fail_activity("Import ESEF package", exc)
                result.value = f"ESEF import failed safely: {state.last_message}"
        page.update()

    async def discover_esef(_event: ft.ControlEvent) -> None:
        result.value = "ESEF discovery status: querying official filings.xbrl.org with a bounded request..."
        page.update()
        result.value = state.discover_esef_filings(str(country_field.value or "NL").strip(), 10)
        page.update()

    async def download_esef(_event: ft.ControlEvent) -> None:
        filing_id = str(filing_id_field.value or "").strip()
        result.value = state.download_esef_package(filing_id) if filing_id else "ESEF download requires a discovered filing ID."
        page.update()

    return panel(ft.Column([section_header("Official filing import", "SEC EDGAR and filings.xbrl.org ESEF evidence. Local fixtures remain functional offline; network failures and mapping warnings are explicit and never start scoring or broker workflows."), ft.Row([cik_field, ft.OutlinedButton("Fetch SEC companyfacts", key="filings.fetch-sec", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=fetch_sec), ft.OutlinedButton("Import SEC companyfacts", key="filings.import-sec", icon=ft.Icons.UPLOAD_FILE, on_click=import_sec)], wrap=True), ft.Row([country_field, filing_id_field, ft.OutlinedButton("Discover ESEF filings", key="filings.discover-esef", icon=ft.Icons.SEARCH, on_click=discover_esef), ft.OutlinedButton("Download ESEF package", key="filings.download-esef", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=download_esef), ft.OutlinedButton("Import ESEF package", key="filings.import-esef", icon=ft.Icons.UPLOAD_FILE, on_click=import_esef)], wrap=True), result], spacing=8))


def _disclosure_import_controls(page: ft.Page, state: AppState) -> ft.Control:
    result = ft.Text("No ETF disclosure imported in this view.", color=theme.MUTED, selectable=True)
    picker = _attach_picker(page, "etf-disclosures.import.file-picker")
    instrument_field = ft.TextField(label="ETF instrument ID", value=state.selected_etf, width=180)
    provider_field = ft.TextField(label="Index provider", value="FTSE Russell", width=180)
    document_date_field = ft.TextField(label="Document date (optional)", width=190)
    document_type_field = ft.Dropdown(
        label="Document type",
        value="factsheet",
        width=190,
        options=[ft.dropdown.Option(value) for value in ("factsheet", "kid", "prospectus_report", "methodology")],
    )
    holdings_date_field = ft.TextField(label="Holdings as-of date", width=190)
    holdings_source_field = ft.TextField(
        label="Holdings authority",
        value="manual_unverified",
        width=190,
        disabled=True,
    )

    async def import_document(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf", "csv", "xlsx", "xls"], with_data=True)
        if not files:
            result.value = "ETF document import cancelled; no data changed."
            page.update()
            return
        path = Path(files[0].path) if files[0].path else None
        try:
            if path is None or not path.exists():
                raise ValueError("a readable local path is required")
            document = import_etf_document(
                path,
                instrument_id=str(instrument_field.value or state.selected_etf or "").strip(),
                document_type=str(document_type_field.value or "factsheet"),
                document_date=str(document_date_field.value or "").strip() or None,
                authority="issuer_document",
                configured_instrument_ids=state.snapshot.config.universe.enabled_ids,
            )
            result.value = f"ETF {document.document_type} registered for {document.instrument_id}; registry persisted with checksum {document.sha256[:12]}...."
            state.last_message = result.value
        except Exception as exc:
            state.fail_activity("Import ETF document", exc)
            result.value = f"ETF document import failed safely: {state.last_message or type(exc).__name__}; no data changed."
        page.update()

    async def import_holdings(_event: ft.ControlEvent) -> None:
        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["csv", "xlsx", "xls"], with_data=True)
        if not files:
            result.value = "ETF holdings import cancelled; no data changed."
            page.update()
            return
        path = Path(files[0].path) if files[0].path else None
        try:
            if path is None or not path.exists():
                raise ValueError("a readable local holdings path is required")
            imported = import_etf_holdings_with_document(
                path,
                str(instrument_field.value or state.selected_etf or "").strip(),
                str(holdings_date_field.value or "").strip() or None,
                "manual_unverified",
                configured_instrument_ids=state.snapshot.config.universe.enabled_ids,
            )
            result.value = f"ETF holdings imported for {instrument_field.value}: completeness={imported.completeness}, freshness={imported.freshness}, confidence={imported.confidence:.2f}."
            state.last_message = result.value
        except Exception as exc:
            state.fail_activity("Import ETF holdings", exc)
            result.value = f"ETF holdings import failed safely: {state.last_message or type(exc).__name__}; existing holdings were preserved."
        page.update()

    async def import_kid(_event: ft.ControlEvent) -> None:
        from etf_cockpit.parsers.priips_kid import parse_priips_kid

        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"], with_data=True)
        if not files:
            result.value = "PRIIPs KID import cancelled; no data changed."
        else:
            try:
                _start_disclosure_import(state, result, "Import PRIIPs KID")
                page.update()
                with _materialise_picker_file(files[0], ".pdf") as path:
                    state.update_activity("Parsing PRIIPs KID", "Parsing the selected KID PDF.", completed_units=1, total_units=3)
                    result.value = "Import PRIIPs KID in progress: parsing selected PDF..."
                    page.update()
                    path = _retain_picker_source(path, "priips_kids")
                    instrument_id = str(instrument_field.value or state.selected_etf or "").strip()
                    etf = next((item for item in state.snapshot.config.universe.etfs if item.id == instrument_id), None)
                    expected_isin = etf.isin if etf is not None else None
                    parsed = parse_priips_kid(path, expected_isin=expected_isin) if path and path.exists() else None
                    if parsed is None:
                        raise ValueError("PRIIPs import requires a readable PDF")
                    else:
                        record = parsed.records[0] if parsed.records else None
                        document_date = record.document_date if record is not None else str(document_date_field.value or "").strip() or None
                        state.update_activity("Registering KID evidence", "Persisting parsed KID and checksum-backed provenance.", completed_units=2, total_units=3)
                        result.value = "Import PRIIPs KID in progress: registering evidence..."
                        page.update()
                        document = persist_priips_kid_with_document(
                            parsed,
                            instrument_id,
                            path,
                            document_date=document_date,
                            configured_instrument_ids=state.snapshot.config.universe.configured_enabled_ids,
                        )
                        registry = read_document_registry(path=document.with_name("fund_documents.parquet"))
                        registered = registry.loc[registry["instrument_id"].astype(str).eq(instrument_id)]
                        document_row = _latest_document_row(registered, "kid")
                        document_checksum = _document_checksum(document_row)
                        warning_text = ", ".join(item.code for item in parsed.warnings) or "none"
                        result.value = f"PRIIPs KID {instrument_id}: records={len(parsed.records)}, confidence={record.extraction_confidence if record else 'unavailable'}, pages={record.source_pages if record else ()}, warnings={warning_text}, checksum={document_checksum[:12]}..., success={parsed.success}."
                state.finish_activity(result.value)
                state.last_message = result.value
            except Exception as exc:
                state.fail_activity("Import PRIIPs KID", exc)
                result.value = f"PRIIPs import failed safely: {state.last_message}"
        page.update()

    async def import_methodology(_event: ft.ControlEvent) -> None:
        from etf_cockpit.parsers.index_methodology import parse_index_methodology

        files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"], with_data=True)
        if not files:
            result.value = "Methodology import cancelled; no data changed."
        else:
            try:
                _start_disclosure_import(state, result, "Import index methodology")
                page.update()
                with _materialise_picker_file(files[0], ".pdf") as path:
                    state.update_activity("Parsing index methodology", "Parsing the selected methodology PDF.", completed_units=1, total_units=3)
                    result.value = "Import index methodology in progress: parsing selected PDF..."
                    page.update()
                    path = _retain_picker_source(path, "index_methodology")
                    instrument_id = str(instrument_field.value or state.selected_etf or "").strip()
                    provider = str(provider_field.value or "").strip()
                    parsed = parse_index_methodology(path, provider) if path and path.exists() else None
                    if parsed is None:
                        raise ValueError("Methodology import requires a readable PDF")
                    else:
                        stored_holdings = _read_frame(FUND_HOLDINGS_PATH)
                        holdings = pd.DataFrame()
                        if "instrument_id" in stored_holdings.columns:
                            holdings = stored_holdings.loc[stored_holdings["instrument_id"].astype(str).eq(instrument_id)].copy()
                        from etf_cockpit.parsers.index_methodology import apply_methodology_holdings_assessment

                        parsed = apply_methodology_holdings_assessment(parsed, holdings)
                        record = parsed.records[0] if parsed.records else None
                        state.update_activity("Registering methodology evidence", "Persisting parsed methodology and checksum-backed provenance.", completed_units=2, total_units=3)
                        result.value = "Import index methodology in progress: registering evidence..."
                        page.update()
                        document = persist_index_methodology_with_document(
                            parsed,
                            instrument_id,
                            path,
                            configured_instrument_ids=state.snapshot.config.universe.configured_enabled_ids,
                        )
                        registry = read_document_registry(path=document.with_name("fund_documents.parquet"))
                        registered = registry.loc[registry["instrument_id"].astype(str).eq(instrument_id)]
                        document_row = _latest_document_row(registered, "methodology")
                        document_checksum = _document_checksum(document_row)
                        warning_text = ", ".join(item.code for item in parsed.warnings) or "none"
                        result.value = f"Methodology {instrument_id}/{provider or 'unknown provider'}: records={len(parsed.records)}, version={record.version if record else 'unavailable'}, pages={record.source_pages if record else ()}, warnings={warning_text}, checksum={document_checksum[:12]}..., success={parsed.success}."
                state.finish_activity(result.value)
                state.last_message = result.value
            except Exception as exc:
                state.fail_activity("Import index methodology", exc)
                result.value = f"Methodology import failed safely: {state.last_message}"
        page.update()

    return panel(
        ft.Column(
            [
                section_header("ETF disclosure import", "Local factsheets, KIDs, prospectuses/reports, holdings and methodologies are registered with checksums and explicit missing/invalid states. Parser controls remain available for KIDs and methodologies."),
                ft.Row([instrument_field, document_type_field, document_date_field, ft.OutlinedButton("Register ETF document", key="etf-disclosures.import-document", icon=ft.Icons.UPLOAD_FILE, on_click=import_document)], wrap=True),
                ft.Row([holdings_date_field, holdings_source_field, ft.OutlinedButton("Import ETF holdings", key="etf-disclosures.import-holdings", icon=ft.Icons.UPLOAD_FILE, on_click=import_holdings)], wrap=True),
                ft.Row([provider_field, ft.OutlinedButton("Import PRIIPs KID", key="etf-disclosures.import-kid", icon=ft.Icons.UPLOAD_FILE, on_click=import_kid), ft.OutlinedButton("Import index methodology", key="etf-disclosures.import-methodology", icon=ft.Icons.UPLOAD_FILE, on_click=import_methodology)], wrap=True),
                result,
            ],
            spacing=8,
        )
    )


def _attach_picker(page: ft.Page, key: str) -> ft.FilePicker:
    picker = ft.FilePicker(key=key)
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
    candidates = [path, path.with_suffix(".csv")]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            frame = pd.read_parquet(candidate) if candidate.suffix.lower() == ".parquet" else pd.read_csv(candidate)
            if frame.empty and candidate.suffix.lower() == ".parquet":
                continue
            if "published_at" in frame.columns or "ingested_at" in frame.columns:
                return sort_news_items(frame).iloc[::-1].reset_index(drop=True)
            if "as_of_date" in frame.columns and "instrument_id" in frame.columns:
                return sort_fundamental_evidence(frame).iloc[::-1].reset_index(drop=True)
            return frame
        except Exception:
            continue
    return pd.DataFrame()


def _short(value: object, max_len: int = 96) -> str:
    text = str(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."
