from __future__ import annotations

import inspect

import etf_cockpit.app.pages.trust_evidence as trust_evidence
from etf_cockpit.app.pages.trust_evidence import etf_disclosures_page
from etf_cockpit.app.pages.instrument_detail import render_etf_disclosure_panel
from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.application.instrument_detail_view import InstrumentDetailViewModel
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_trust_evidence_exposes_bounded_report_kinds_fields_review_and_conflicts() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    controls = list(_walk(etf_disclosures_page(None, state)))
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in controls)
    keys = {getattr(item, "key", "") for item in controls}

    assert PAGES["/etf-disclosures"][0] == "ETF Disclosures"
    source = inspect.getsource(trust_evidence._disclosure_import_controls)
    assert all(kind in source for kind in ("prospectus", "annual_report", "half_year_report"))
    assert "ETF report evidence" in text
    assert "ETF report conflicts" in text
    assert "SFDR disclosure" in text
    assert "SFDR disclosure" in inspect.getsource(trust_evidence._disclosure_import_controls)
    assert {"etf-disclosures.import-report", "etf-disclosures.verify-report", "etf-disclosures.reject-report"} <= keys
    assert "etf-disclosures.import-sfdr" in keys
    assert "execution_allowed" in text or "execution_allowed" in inspect.getsource(trust_evidence.etf_disclosures_page)


def test_instrument_detail_renders_sfdr_metadata_and_badges() -> None:
    model = InstrumentDetailViewModel(
        "VWCE",
        "Vanguard",
        "ready",
        {},
        {
            "etf_disclosures": {
                "status": "available",
                "document_inventory": [],
                "holdings": {"status": "unavailable"},
                "kid": {"status": "unavailable"},
                "methodology": {"status": "unavailable"},
                "sfdr": {
                    "status": "manual_review",
                    "classification": "article_8",
                    "document_type": "factsheet",
                    "document_date": "2026-09-01",
                    "manual_review": True,
                    "score_eligible": False,
                    "execution_allowed": False,
                    "source_id": "parsed:sfdr:test",
                    "source_authority": "issuer_document",
                    "conflict_id": "",
                },
            }
        },
    )
    controls = list(_walk(render_etf_disclosure_panel(model)))
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in controls)
    assert "SFDR evidence metadata" in text
    assert "classification=article_8" in text
    assert "SFDR: status=manual_review" in text
