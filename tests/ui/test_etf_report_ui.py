from __future__ import annotations

import inspect

import etf_cockpit.app.pages.trust_evidence as trust_evidence
from etf_cockpit.app.pages.trust_evidence import etf_disclosures_page
from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


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
    assert {"etf-disclosures.import-report", "etf-disclosures.verify-report", "etf-disclosures.reject-report"} <= keys
    assert "execution_allowed" in text or "execution_allowed" in inspect.getsource(trust_evidence.etf_disclosures_page)
