from __future__ import annotations

import json
from unittest.mock import Mock

def test_s13_08_local_llm_disables_redirects_for_both_requests(monkeypatch):
    import etf_cockpit.audit.local_llm as llm

    get = Mock()
    get.return_value.json.return_value = {"data": [{"id": "fixture-model"}]}
    post = Mock()
    post.return_value.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"summary": "fixture", "confidence": 0.5, "executable_authority": False}
                    )
                }
            }
        ]
    }
    monkeypatch.setattr(llm.requests, "get", get)
    monkeypatch.setattr(llm.requests, "post", post)

    llm.generate_local_audit_commentary({}, llm.LocalLLMSettings(base_url="http://localhost:1234/v1"))

    assert get.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["allow_redirects"] is False


def test_s13_09_snapshot_without_row_cutoff_cannot_grant_authority():
    from etf_cockpit.governance.migrations import migrate_legacy_action

    row = {
        "schema_version": "1.0",
        "action": "hold",
        "portfolio_snapshot": {
            "as_of_date": "2026-10-06",
            "portfolio_review_state": "reduce_exposure_review",
            "holdings": [{"instrument_id": "VWCE", "weight": 0.5}],
        },
    }

    assert not migrate_legacy_action(row).portfolio_review_allowed


def test_hunt_s13c_3_top_level_package_import_is_reported(tmp_path):
    from etf_cockpit.governance.architecture_boundaries import find_violations

    page = tmp_path / "src" / "etf_cockpit" / "app" / "pages" / "boundary_probe.py"
    page.parent.mkdir(parents=True)
    page.write_text("from etf_cockpit import data\n", encoding="utf-8")

    violations = find_violations(tmp_path)

    assert any(violation.file.endswith("boundary_probe.py") for violation in violations)

    page.write_text("from ... import data\n", encoding="utf-8")
    violations = find_violations(tmp_path)

    assert any(violation.file.endswith("boundary_probe.py") for violation in violations)
