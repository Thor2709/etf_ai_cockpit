from __future__ import annotations

import inspect

from etf_cockpit.app.pages.decision_journal import decision_journal_page


def test_decision_journal_ui_exposes_review_and_lineage_fields() -> None:
    source = inspect.getsource(decision_journal_page)

    for label in (
        "Decision state",
        "Evidence references",
        "Alternatives considered",
        "Confidence",
        "Invalidation rules",
        "Review date",
        "Model run IDs",
        "Proposal IDs",
        "Order IDs",
        "Portfolio context",
    ):
        assert label in source
    assert "No broker execution" in source
