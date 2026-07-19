from __future__ import annotations

from pathlib import Path

from etf_cockpit.application.ui_facade import ForwardEvidenceDiary


def test_forward_evidence_is_exposed_through_the_presentation_facade(tmp_path: Path) -> None:
    summary = ForwardEvidenceDiary().export_summary(root=tmp_path)
    assert summary["schema_version"] == "forward-evidence.v1"
    assert summary["row_count"] == 0
