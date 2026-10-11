"""News and context evidence page."""

from __future__ import annotations

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
from etf_cockpit.application.digest import contradiction_digest_records
from etf_cockpit.application.ui_facade import headline_direction, normalise_event_decision_time


def news_context_page(page: ft.Page, state: AppState) -> PageView:
    from etf_cockpit.app.pages import trust_evidence

    frame = read_frame(trust_evidence.NEWS_CONTEXT_PATH)
    dated_rows = [
        row
        for row in frame.to_dict(orient="records")
        if row.get("published_at") not in (None, "")
    ]
    timeline = ck.horizontal_stacked_bar(
        [str(row["published_at"]) for row in dated_rows],
        [[ck.Segment("News items", 1, theme.BAR_BLUE)] for _row in dated_rows],
        x_name="News items",
        unit="items",
        unavailable_reason=None if dated_rows else "No timestamped local news items are available.",
        empty_title="Unavailable",
        insight="Local news items by published time.",
    )
    timeline_card = kit.GlassCard(
        "News timeline",
        "local published timestamps",
        body=kit.Well(timeline, expand=True),
    )

    prices = state.snapshot.prices
    decision_time = normalise_event_decision_time(
        getattr(getattr(state.snapshot, "data_report", None), "as_of_date", None)
    )
    contradictions = contradiction_digest_records(
        trust_evidence.load_news_items(trust_evidence.NEWS_CONTEXT_PATH),
        prices=prices,
        cutoff=decision_time,
    )
    contradiction_rows = [
        {
            "title": str(row.get("title") or "Contradiction rule"),
            "status": kit.Tag(
                str(row.get("status") or "Unavailable").replace("_", " ").title(),
                "warn" if row.get("status") not in {"clear", "available"} else "ok",
            ),
            "detail": f"{row.get('rule_status', row.get('status', 'Unavailable'))}: {row.get('detail', 'Unavailable')}",
        }
        for row in contradictions
    ]
    contradiction_card = kit.GlassCard(
        "News/macro contradictions",
        "context rules",
        body=(
            kit.DataTable(
                [
                    kit.TableColumn("title", "Rule"),
                    kit.TableColumn("status", "Status"),
                    kit.TableColumn("detail", "Result", flex=2),
                ],
                contradiction_rows,
                row_height=48,
                empty_title="Unavailable",
                empty_reason="Contradiction results are unavailable; no rule result is inferred.",
            )
            if contradiction_rows
            else kit.EmptyState("Unavailable", "Contradiction results are unavailable; no rule result is inferred.")
        ),
    )

    inventory_columns = (
        ("published_at", "Date"),
        ("instrument_id", "Instrument"),
        ("title", "Headline"),
        ("provider_name", "Source"),
        ("instrument_mapping_method", "Mapping confidence"),
        ("direction", "Direction"),
    )
    def sentiment(row: dict[str, object]) -> str:
        explicit = str(row.get("direction") or "").strip().casefold()
        if explicit in {"positive", "negative"}:
            return explicit
        return {"up": "positive", "down": "negative"}.get(headline_direction(row.get("headline")), "")

    inventory_rows = [
        (
            sentiment(row),
            {
                field: (
                    kit.Tag(sentiment(row).title(), "mute")
                    if field == "direction" and sentiment(row)
                    else "—" if field in {"instrument_mapping_method", "direction"}
                    else display_value(row.get(source)) if source in row else "—"
                )
                for field, source in inventory_columns
            },
        )
        for row in frame.to_dict(orient="records")
    ]
    inventory_slot = ft.Container()
    inventory = kit.GlassCard("News/context inventory", "point-in-time context", body=inventory_slot)
    filter_note = kit.Note("Showing all news and context")

    def _apply_filter(value: str) -> None:
        selected = [row for tone, row in inventory_rows if value in {"All", "Contradictions"} or tone == value.casefold()]
        inventory_slot.content = (
            kit.DataTable([kit.TableColumn(field, label) for field, label in inventory_columns], selected)
            if selected
            else kit.EmptyState(
                "Unavailable",
                "No local news or context rows are registered."
                if not inventory_rows
                else f"No {value.casefold()} news rows are available.",
            )
        )
        inventory.visible = value != "Contradictions"
        contradiction_card.visible = value in {"All", "Contradictions"}
        filter_note.value = f"Showing {value.casefold()} news and context ({len(selected) if inventory.visible else len(contradiction_rows)} rows)"

    def select_filter(value: str) -> None:
        _apply_filter(value)
        if getattr(page, "update", None):
            page.update()

    _apply_filter("All")
    note_review = legacy_action_panel(
        page,
        trust_evidence._news_context_extra(state, page),
        "Manual note credibility",
        "Local manual notes remain reviewable context evidence.",
    )
    evidence = kit.EvidenceTableSwitcher(
        [
            evidence_table(
                "News/context inventory",
                trust_evidence.NEWS_CONTEXT_PATH,
                ("instrument_id", "title", "source_url", "published_at", "ingested_at", "provider_name", "credibility", "instrument_mapping_method", "available_at_decision_time", "timestamp_status", "context_only", "executable_authority"),
                technical=("source_url", "raw_path", "executable_authority"),
            ),
            evidence_table(
                "Manual note credibility evidence",
                trust_evidence.MANUAL_NEWS_CLEAN_PATH,
                ("as_of_date", "etf_id", "title", "credibility_flag_status", "credibility_flags", "credibility_reason_codes", "executable_authority"),
                technical=("credibility_flags", "credibility_reason_codes", "executable_authority"),
            ),
            evidence_table(
                "Point-in-time validation",
                trust_evidence.NEWS_TIMESTAMP_VALIDATION_PATH,
                ("news_id", "timestamp_status", "backtest_eligible", "reason", "available_at_decision_time", "instrument_mapping_method"),
                technical=("news_id", "reason"),
            ),
            evidence_table(
                "Optional free provider status",
                trust_evidence.PROVIDER_PROBE_PATH,
                ("dataset_type", "provider_name", "status", "message"),
                technical=("message",),
            ),
            evidence_table(
                "Fundamental source limitations",
                trust_evidence.FUNDAMENTAL_CLEAN_PATH,
                ("instrument_id", "source", "source_authority", "limitations", "score_eligible", "executable_authority"),
                technical=("limitations", "executable_authority"),
            ),
        ],
        title="News evidence",
        key="news-context.evidence",
    )
    return PageView(
        PageChrome(
            "News & Context",
            "Dated news and context evidence · never changes scores or actions",
            segment_groups=(
                SegmentGroup(
                    "news_filter",
                    ("All", "Positive", "Negative", "Contradictions"),
                    "All",
                    on_change=select_filter,
                ),
            ),
        ),
        ft.Column(
            [filter_note, timeline_card, contradiction_card, inventory, note_review, evidence],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
    )


__all__ = ["news_context_page"]
