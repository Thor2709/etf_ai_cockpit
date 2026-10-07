"""ETF disclosures evidence and local import page."""

from __future__ import annotations

import flet as ft

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
        ("coverage_status", "Coverage"),
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
        "registered document evidence",
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
    evidence = kit.EvidenceTableSwitcher(
        [
            evidence_table(
                "ETF report evidence",
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
                "SFDR disclosure evidence",
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
    body = ft.Column(
        [importer, inventory, sfdr_note, evidence],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        PageChrome(
            "ETF Disclosures",
            "ETF factsheets, holdings, PRIIPs KIDs, SFDR disclosures, reports and index methodology inventory. Disclosure reviews are advisory only; score eligibility and execution authority remain disabled.",
            segment_groups=(
                SegmentGroup("disclosure_view", ("Documents", "Reports", "Holdings", "SFDR"), "Documents"),
            ),
        ),
        body,
    )


__all__ = ["etf_disclosures_page"]
