"""ETF disclosures evidence and local import page."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l2_common import (
    display_value,
    evidence_table,
    legacy_action_panel,
    read_frame,
)
from etf_cockpit.app.state import AppState


def etf_disclosures_page(page: ft.Page, state: AppState) -> PageView:
    from etf_cockpit.app.pages import trust_evidence

    registry = read_frame(trust_evidence.ETF_DISCLOSURES_PATH)
    fields = (
        ("instrument_id", "Instrument"),
        ("document_type", "Document type"),
        ("source_id", "Source"),
        ("source_authority", "Authority"),
        ("as_of_date", "As of"),
        ("coverage_status", "Status"),
    )
    rows = [
        {
            key: (
                kit.Disclosure("Source detail", display_value(row.get(source)))
                if source in {"source_id", "source_authority"} and display_value(row.get(source)) != "—"
                else (
                    kit.Tag(display_value(row.get(source)).replace("_", " ").title(), "warn")
                    if source == "coverage_status" and display_value(row.get(source)) != "—"
                    else display_value(row.get(source))
                )
            )
            for key, source in fields
        }
        for row in registry.to_dict(orient="records")
    ]
    inventory = kit.GlassCard(
        "ETF disclosure inventory",
        f"{len(rows)} documents" if rows else "Unavailable",
        body=(
            kit.DataTable(
                [kit.TableColumn(key, label) for key, label in fields],
                rows,
            )
            if rows
            else kit.EmptyState("Unavailable", "No ETF disclosure document is registered locally.")
        ),
        key="etf-disclosures.inventory",
    )
    importer = legacy_action_panel(
        page,
        trust_evidence._disclosure_import_controls(page, state),
        "ETF disclosure import",
        "Local factsheets, holdings, KIDs, reports, methodologies and SFDR evidence.",
    )
    document_types = ("Factsheet", "KID", "Methodology", "SFDR", "Prospectus", "Annual", "Half-year", "Holdings")
    raw_records = registry.to_dict(orient="records")
    typed_records = {
        label: [
            row for row in raw_records
            if str(row.get("document_type") or "").casefold().replace("_", " ") in _type_aliases(label)
        ]
        for label in document_types
    }
    available_counts = [
        sum(str(row.get("coverage_status") or "").casefold() not in {"missing", "unavailable", "none"} for row in typed_records[label])
        if typed_records[label] else None
        for label in document_types
    ]
    missing_counts = [
        sum(str(row.get("coverage_status") or "").casefold() == "missing" for row in typed_records[label])
        if any(str(row.get("coverage_status") or "").casefold() == "missing" for row in typed_records[label])
        else None
        for label in document_types
    ]
    coverage_chart = ck.grouped_bar_chart(
        document_types,
        [
            ck.BarSeries("Available", available_counts, kind="pos"),
            ck.BarSeries("Missing", missing_counts, kind="neg"),
        ],
        x_name="Document type",
        y_name="ETFs (count)",
        unit="ETFs",
        unavailable_reason="No ETF document coverage is registered locally." if not raw_records else None,
        empty_title="Unavailable",
    )
    coverage = kit.GlassCard(
        "Coverage by document type",
        "ETFs with each document",
        body=kit.Well(coverage_chart),
    )
    view_note = kit.Note("Documents import controls")
    evidence = kit.EvidenceTableSwitcher(
        [
            evidence_table(
                "ETF report evidence (prospectus / annual / half-year)",
                trust_evidence.ETF_REPORT_RECORDS_PATH,
                ("instrument_id", "document_kind", "fund_name", "isin", "document_date", "reporting_period_end", "legal_structure", "securities_lending", "collateral_policy", "ongoing_costs", "holdings_count", "operational_risks", "source_authority", "extraction_status", "verification_status", "evidence_eligible", "score_eligible", "execution_allowed"),
                technical=("source_sha256", "extraction_sha256", "execution_allowed"),
            ),
            evidence_table(
                "ETF report conflicts",
                trust_evidence.ETF_REPORT_CONFLICTS_PATH,
                ("instrument_id", "field_name", "document_kind_a", "document_kind_b", "document_date_a", "document_date_b", "value_a", "value_b", "resolution_status", "requires_manual_review", "execution_allowed"),
                technical=("source_id_a", "source_id_b", "pages_a", "pages_b", "execution_allowed"),
            ),
            evidence_table(
                "Parsed PRIIPs KID evidence",
                trust_evidence.PRIIPS_KID_RECORDS_PATH,
                ("instrument_id", "isin", "sri", "cost_fields", "holding_period_years", "document_date", "extraction_confidence", "source_pages", "warnings", "source_authority", "freshness_status", "manual_review", "score_eligible"),
                technical=("cost_fields", "source_pages", "warnings", "source_sha256"),
            ),
            evidence_table(
                "Parsed index methodology evidence",
                trust_evidence.INDEX_METHODOLOGY_RECORDS_PATH,
                ("instrument_id", "provider", "index_series", "version", "document_date", "eligibility_rules", "weighting_rules", "review_frequency", "caps", "source_authority", "freshness_status", "manual_review", "score_eligible"),
                technical=("eligibility_rules", "weighting_rules", "caps", "source_pages", "warnings", "source_sha256"),
            ),
            evidence_table(
                "Parsed SFDR disclosure evidence",
                trust_evidence.SFDR_RECORDS_PATH,
                ("instrument_id", "classification", "document_type", "document_date", "sustainable_characteristics", "taxonomy_alignment_pct", "source_authority", "manual_review", "score_eligible", "execution_allowed"),
                technical=("warnings", "source_sha256", "execution_allowed"),
            ),
            evidence_table(
                "ETF holdings evidence",
                trust_evidence.FUND_HOLDINGS_PATH,
                ("instrument_id", "as_of_date", "source", "completeness", "freshness", "confidence", "authority", "score_eligible", "source_id"),
                technical=("source_id",),
            ),
            evidence_table(
                "Source conflicts",
                trust_evidence.SOURCE_CONFLICTS_PATH,
                ("instrument_id", "field_name", "canonical_value", "resolution_status", "requires_manual_review", "reason"),
                technical=("reason",),
            ),
        ],
        title="Disclosure evidence",
        key="etf-disclosures.evidence",
    )
    sfdr_note = kit.GlassCard(
        "SFDR disclosure",
        "evidence only",
        body=ft.Column(
            [
                kit.Note(
                    "SFDR classifications and sustainability disclosures remain evidence only. They do not contribute return alpha, scores or execution authority."
                ),
                kit.Disclosure(
                    "Authority boundary",
                    "score_eligible=false; execution_allowed=false.",
                ),
            ],
            spacing=8,
        ),
        key="disclosures.sfdr",
    )
    sections = {
        "Documents": (importer, inventory, coverage),
        "Reports": (evidence,),
        "Holdings": (evidence,),
        "SFDR": (sfdr_note,),
    }

    def _apply_filter(value: str) -> None:
        view_note.value = f"{value} import controls"
        for card in (importer, inventory, coverage, sfdr_note, evidence):
            card.visible = any(card is shown for shown in sections[value])

    def select_view(value: str) -> None:
        _apply_filter(value)
        if getattr(page, "update", None):
            page.update()

    _apply_filter("Documents")
    body = ft.Column(
        [view_note, importer, inventory, coverage, sfdr_note, evidence],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        PageChrome(
            "ETF Disclosures",
            "Factsheets, holdings, KIDs, SFDR, reports and methodology · advisory only",
            segment_groups=(
                SegmentGroup("disclosure_view", ("Documents", "Reports", "Holdings", "SFDR"), "Documents", on_change=select_view),
            ),
        ),
        body,
    )


__all__ = ["etf_disclosures_page"]


def _type_aliases(label: str) -> set[str]:
    aliases = {label.casefold()}
    aliases.add({"kid": "priips kid", "annual": "annual report", "half-year": "half year report"}.get(label.casefold(), label.casefold()))
    return aliases
