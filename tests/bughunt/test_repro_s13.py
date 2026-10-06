"""Slice S13 repros: security policy, release certification and ChatGPT audit bridge."""

from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest



def _release_dir(tmp_path):
    release = tmp_path / "artifacts" / "release" / "issue-0152"
    release.mkdir(parents=True)
    return release


def test_s13_01_unavailable_git_not_passed(tmp_path):
    from etf_cockpit.governance.release_certification import _signed_manifest_status

    release = _release_dir(tmp_path)
    (release / "release-manifest.json").write_text(json.dumps({"git": {"head": "deadbeef"}}), encoding="utf-8")
    (release / "release-manifest.sig.json").write_text(json.dumps({"status": "signed"}), encoding="utf-8")
    status, _detail = _signed_manifest_status(tmp_path, "unavailable")
    assert status == "blocked"


def test_s13_02_list_signature_is_blocked(tmp_path):
    from etf_cockpit.governance.release_certification import _signed_manifest_status

    release = _release_dir(tmp_path)
    (release / "release-manifest.json").write_text("{}", encoding="utf-8")
    (release / "release-manifest.sig.json").write_text("[]", encoding="utf-8")
    try:
        status, _detail = _signed_manifest_status(tmp_path, "abc")
    except Exception as exc:
        raise AssertionError(f"certification crashed with {type(exc).__name__} instead of blocking") from exc
    assert status == "blocked"


def test_s13_03_list_audit_manifest_is_invalid(tmp_path):
    from etf_cockpit.chatgpt_bridge.audit_packet import validate_audit_archive

    archive_path = tmp_path / "audit.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("audit_manifest.json", "[]")
    try:
        report = validate_audit_archive(archive_path)
    except Exception as exc:
        raise AssertionError(f"validator crashed with {type(exc).__name__} instead of reporting invalid") from exc
    assert report.valid is False


def test_s13_04_list_payload_raises_audit_import_error():
    from etf_cockpit.chatgpt_bridge.validation import validate_audit_text
    from etf_cockpit.core.exceptions import AuditImportError

    try:
        validate_audit_text("[]", set())
    except AuditImportError:
        return
    except Exception as exc:
        raise AssertionError(f"raw {type(exc).__name__} escaped instead of AuditImportError") from exc
    raise AssertionError("no AuditImportError raised for non-object audit JSON")


def test_s13_05_slash_review_date_rejected(tmp_path, monkeypatch):
    import etf_cockpit.chatgpt_bridge.import_audit as import_audit
    from etf_cockpit.core.exceptions import AuditImportError

    imports_dir = tmp_path / "imports"
    monkeypatch.setattr(import_audit, "CHATGPT_IMPORTS_DIR", imports_dir)
    audit = {
        "schema_version": "1.0",
        "review_date": "2026/10/05",
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
    with pytest.raises(AuditImportError):
        import_audit.import_audit_json(source, config)


def test_s13_06_non_ascii_token_denied():
    from etf_cockpit.security.policy import verify_local_api_request

    decision = verify_local_api_request("t\u00f6k\u00e9n", "abc")
    assert decision.ok is False


def test_s13_07_null_allowlist_reports_failure(tmp_path):
    from etf_cockpit.security.policy import POLICY_PATH, build_security_report

    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "security_policy.yaml").write_bytes(POLICY_PATH.read_bytes())
    (configs / "plugin_registry.yaml").write_text("execution_allowed: false\nallowlist:\n", encoding="utf-8")
    report = build_security_report(tmp_path, findings=[])
    assert report["status"] == "failed"
