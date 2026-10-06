"""Focused edge cases for fix group S."""

from __future__ import annotations

import json
from types import SimpleNamespace


def test_s13_02_list_manifest_is_blocked(tmp_path):
    from etf_cockpit.governance.release_certification import _signed_manifest_status

    release = tmp_path / "artifacts" / "release" / "issue-0152"
    release.mkdir(parents=True)
    (release / "release-manifest.json").write_text("[]", encoding="utf-8")
    (release / "release-manifest.sig.json").write_text('{"status":"signed"}', encoding="utf-8")
    assert _signed_manifest_status(tmp_path, "abc")[0] == "blocked"


def test_s13_04_schema_validation_errors_are_wrapped():
    import pytest

    from etf_cockpit.chatgpt_bridge.validation import validate_audit_text
    from etf_cockpit.core.exceptions import AuditImportError

    with pytest.raises(AuditImportError):
        validate_audit_text("{}", set())


def test_s13_05_same_date_imports_keep_both_audits(tmp_path, monkeypatch):
    import etf_cockpit.chatgpt_bridge.import_audit as import_audit

    imports_dir = tmp_path / "imports"
    monkeypatch.setattr(import_audit, "CHATGPT_IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(import_audit, "append_jsonl", lambda *args, **kwargs: None)
    audit = {
        "schema_version": "1.0",
        "review_date": "2026-10-05",
        "overall_view": "neutral",
        "portfolio_actions": [],
        "model_audit": {
            "toto_usefulness": "n/a",
            "timesfm_usefulness": "n/a",
            "baseline_comparison": "n/a",
            "overfitting_concerns": [],
        },
    }
    source = tmp_path / "audit.json"
    source.write_text(json.dumps(audit), encoding="utf-8")
    config = SimpleNamespace(universe=SimpleNamespace(enabled_ids=[]))

    import_audit.import_audit_json(source, config)
    import_audit.import_audit_json(source, config)

    assert {path.name for path in imports_dir.glob("*.json")} == {
        "chatgpt_audit_2026-10-05.json",
        "chatgpt_audit_2026-10-05_1.json",
    }


def test_s13_06_non_ascii_csrf_is_denied():
    from etf_cockpit.security.policy import verify_local_api_request

    decision = verify_local_api_request(
        "token", "token", presented_csrf="töken", expected_csrf="csrf"
    )
    assert decision.ok is False


def test_s13_07_non_list_allowlist_reports_failure(tmp_path):
    from etf_cockpit.security.policy import POLICY_PATH, build_security_report

    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "security_policy.yaml").write_bytes(POLICY_PATH.read_bytes())
    (configs / "plugin_registry.yaml").write_text(
        "execution_allowed: false\nallowlist: invalid\n", encoding="utf-8"
    )
    report = build_security_report(tmp_path, findings=[])
    assert report["status"] == "failed"
    assert "plugin allowlist must be a list" in report["failures"]
