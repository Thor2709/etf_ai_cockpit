from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.security.policy import (
    SecurityPolicyError,
    build_security_report,
    read_bounded_file,
    redact_secrets,
    validate_network_url,
    verify_local_api_request,
)


def test_redaction_removes_nested_secret_values_and_text_secrets() -> None:
    value = redact_secrets({"provider": {"api_key": "do-not-leak"}, "message": "token=do-not-leak"})

    assert value["provider"]["api_key"] == "***redacted***"
    assert "do-not-leak" not in json.dumps(value)
    assert "do-not-leak" not in value["message"]


def test_network_access_requires_https_and_exact_allowlist() -> None:
    assert validate_network_url("https://data.example.test/prices", allowlisted_hosts=("data.example.test",)) == "https://data.example.test/prices"
    with pytest.raises(SecurityPolicyError, match="HTTPS"):
        validate_network_url("http://data.example.test/prices", allowlisted_hosts=("data.example.test",))
    with pytest.raises(SecurityPolicyError, match="allow-listed"):
        validate_network_url("https://evil.example.test/prices", allowlisted_hosts=("data.example.test",))
    assert validate_network_url("http://127.0.0.1:8550/", allow_loopback=True) == "http://127.0.0.1:8550/"


def test_local_api_auth_requires_bearer_and_csrf_tokens() -> None:
    assert not verify_local_api_request("wrong", "right").ok
    assert not verify_local_api_request("right", "right", presented_csrf="wrong", expected_csrf="csrf").ok
    assert verify_local_api_request("right", "right", presented_csrf="csrf", expected_csrf="csrf").ok


def test_bounded_file_read_rejects_escape_symlink_and_oversized_input(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    source = root / "payload.csv"
    source.write_bytes(b"a,b\n1,2\n")
    assert read_bounded_file(source, root=root, max_bytes=32).startswith(b"a,b")
    with pytest.raises(SecurityPolicyError, match="exceeds"):
        read_bounded_file(source, root=root, max_bytes=2)
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"secret")
    with pytest.raises(SecurityPolicyError, match="escapes"):
        read_bounded_file(outside, root=root, max_bytes=32)
    link = root / "link.csv"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(SecurityPolicyError, match="symlink"):
        read_bounded_file(link, root=root, max_bytes=32)


def test_security_report_blocks_active_high_findings_without_exposing_values(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "security_policy.yaml").write_text(Path("configs/security_policy.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "configs" / "plugin_registry.yaml").write_text(Path("configs/plugin_registry.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    report = build_security_report(tmp_path, findings=[{"id": "SEC-1", "severity": "high", "status": "open", "secret": "never-display"}])

    assert report["status"] == "failed"
    assert "SEC-1" in report["failures"][0]
    assert "never-display" not in json.dumps(report)
