"""Filings and statements evidence page."""

from __future__ import annotations

import pandas as pd
import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck, kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l2_common import (
    display_value,
    evidence_table,
    legacy_action_panel,
    read_frame,
)
from etf_cockpit.app.state import AppState


def filings_page(page: ft.Page, state: AppState) -> PageView:
    from etf_cockpit.app.pages import trust_evidence

    registry = read_frame(trust_evidence.FILINGS_STATEMENTS_PATH)
    coverage = read_frame(trust_evidence.FILING_COVERAGE_PATH)
    inventory_columns = [
        ("instrument_id", "Instrument"),
        ("document_type", "Form / type"),
        ("period", "Period"),
        ("published_at", "Published"),
        ("available_at", "Available at"),
        ("source", "Source"),
        ("source_authority", "Authority"),
    ]
    table_rows = []
    for row in registry.to_dict(orient="records"):
        table_rows.append(
            {
                field: display_value(row.get(source)) if source in row else "—"
                for field, source in inventory_columns
            }
        )
    inventory = kit.GlassCard(
        "Filings inventory",
        "official filing evidence",
        body=(
            kit.DataTable(
                [kit.TableColumn(field, label) for field, label in inventory_columns],
                table_rows,
            )
            if table_rows
            else kit.EmptyState("Unavailable", "No filing inventory is registered locally.")
        ),
        key="filings.inventory",
    )

    coverage_rows = coverage.to_dict(orient="records")
    countries = [str(row.get("country") or "Unavailable") for row in coverage_rows]
    matched = [
        ck.Segment("Matched", _number(row.get("matched_records")), theme.CHART_POS)
        for row in coverage_rows
    ]
    queued = [
        ck.Segment(
            "Queued / unmatched",
            _unmatched(row.get("official_records"), row.get("matched_records")),
            theme.AMBER,
        )
        for row in coverage_rows
    ]
    coverage_chart = ck.horizontal_stacked_bar(
        countries,
        [[matched[index], queued[index]] for index in range(len(countries))],
        x_name="Filings",
        unit="filings",
        unavailable_reason=None if coverage_rows else "Filing jurisdiction coverage is unavailable.",
        empty_title="Unavailable",
        insight="Matched and queued or unmatched official filing records by jurisdiction.",
    )
    coverage_card = kit.GlassCard(
        "Jurisdiction coverage",
        "matched and queued / unmatched",
        body=kit.Well(coverage_chart, expand=True),
    )

    submissions_result = getattr(state, "sec_submissions_result", None)
    submissions_fields = ("cik", "accession", "form", "filing_date", "available_at", "source_sha256")
    submission_rows = [
        {
            field: (
                kit.Disclosure("Source checksum", str(getattr(record, field)))
                if field == "source_sha256" and getattr(record, field, None)
                else str(getattr(record, field, None) or "—")
            )
            for field in submissions_fields
        }
        for record in getattr(submissions_result, "records", ())
    ]
    submission_table = kit.EvidenceTable(
        "Submissions",
        [kit.TableColumn(field, field.replace("_", " ").title()) for field in submissions_fields],
        submission_rows,
        file_name="Submissions",
    )
    evidence = kit.EvidenceTableSwitcher(
        [
            evidence_table(
                "Official filing discovery",
                trust_evidence.OAM_DISCOVERY_PATH,
                ("provider_id", "country", "issuer", "isin", "title", "document_type", "published_at", "available_at", "identity_status", "source_authority", "coverage_status", "adapter_status", "manual_review", "execution_allowed"),
                technical=("source_url", "document_url", "terms_url", "snapshot_sha256", "execution_allowed"),
            ),
            evidence_table(
                "Manual official filing queue",
                trust_evidence.MANUAL_FILING_QUEUE_PATH,
                ("jurisdiction", "instrument_id", "document_type", "published_at", "available_at", "source_authority", "identity_status", "coverage_status", "manual_review", "execution_allowed"),
                technical=("source_url", "raw_path", "sha256", "execution_allowed"),
            ),
            evidence_table(
                "SEC statement facts",
                trust_evidence.STATEMENT_FACTS_PATH,
                ("instrument_id", "taxonomy", "concept", "canonical_metric", "mapping_status", "unit", "end", "filed", "form", "accession", "source_id"),
                technical=("accession", "source_id"),
            ),
            submission_table,
            evidence_table(
                "Provider probes",
                trust_evidence.PROVIDER_PROBE_PATH,
                ("dataset_type", "provider_name", "status", "source_authority", "message"),
                technical=("message",),
            ),
            evidence_table(
                "Identity mappings",
                trust_evidence.IDENTITY_PATH,
                ("instrument_id", "isin", "yahoo_symbol", "exchange", "mic", "currency", "share_class", "listing", "identity_confidence", "warnings"),
                technical=("warnings",),
            ),
            evidence_table(
                "Fundamental evidence",
                trust_evidence.FUNDAMENTAL_CLEAN_PATH,
                ("instrument_id", "as_of_date", "eligibility", "missing_fields", "warnings", "source", "source_authority", "limitations", "score_eligible", "executable_authority"),
                technical=("missing_fields", "warnings", "limitations", "executable_authority"),
            ),
        ],
        title="Filing evidence",
        key="filings.evidence",
    )
    actions = legacy_action_panel(
        page,
        trust_evidence._filing_import_controls(page, state),
        "Official filing import",
        "SEC, ESEF, national OAM and manual official filing actions.",
    )
    body = ft.Column(
        [actions, inventory, coverage_card, evidence],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        PageChrome(
            "Filings & Statements",
            "Official SEC, ESEF and national filing evidence. Missing filings remain missing; vendor fundamentals cannot outrank official matched filings.",
            segment_groups=(
                SegmentGroup("filing_source", ("SEC", "ESEF", "National OAM", "Manual"), "SEC"),
            ),
        ),
        body,
    )


def _number(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        parsed = float(value)
        return parsed if parsed >= 0 and pd.notna(parsed) else None
    except (TypeError, ValueError):
        return None


def _unmatched(official: object, matched: object) -> float | None:
    official_count = _number(official)
    matched_count = _number(matched)
    if official_count is None or matched_count is None:
        return None
    return max(official_count - matched_count, 0.0)


__all__ = ["filings_page"]
