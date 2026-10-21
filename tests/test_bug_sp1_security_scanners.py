"""Bughunt E (issue #988): security policy, architecture scanner and plugin boundary regressions."""

from __future__ import annotations

import json
from pathlib import Path
import pathlib
import socket
from types import SimpleNamespace

import pytest

from etf_cockpit.chatgpt_bridge.audit_packet import _contains_unredacted_secret
from etf_cockpit.chatgpt_bridge.validation import validate_audit_text
from etf_cockpit.core.exceptions import AuditImportError
from etf_cockpit.governance.architecture_boundaries import build_report, find_violations
from etf_cockpit.plugins.contracts import PluginContext, PluginHealth, PluginManifest, PluginResult
from etf_cockpit.plugins.registry import PluginRegistrationError, PluginRegistry
from etf_cockpit.security.policy import build_security_report, load_security_policy

REPO = Path(__file__).resolve().parents[1]


def _security_root(tmp_path: Path, blocking: list[str] | None = None) -> Path:
    configs = tmp_path / "configs"
    configs.mkdir()
    policy = (REPO / "configs" / "security_policy.yaml").read_text(encoding="utf-8")
    if blocking is not None:
        head, _ = policy.split("security_findings:")
        policy = head + "security_findings:\n  blocking_severities:\n" + "".join(f"    - {item}\n" for item in blocking)
    (configs / "security_policy.yaml").write_text(policy, encoding="utf-8")
    (configs / "plugin_registry.yaml").write_text((REPO / "configs" / "plugin_registry.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


# --- E017 -----------------------------------------------------------------------------------------


def test_findings_evidence_unavailable_fails_closed(tmp_path: Path, monkeypatch) -> None:
    root = _security_root(tmp_path)
    path = root / "artifacts" / "security" / "findings.json"
    path.parent.mkdir(parents=True)
    original = Path.read_text

    def unreadable(self, *args, **kwargs):
        if self == path:
            raise PermissionError("private evidence location")
        return original(self, *args, **kwargs)

    for evidence in ("missing", "unreadable", "invalid_json", "invalid_encoding", "invalid_schema"):
        if evidence != "missing":
            path.write_bytes({"invalid_json": b"[", "invalid_encoding": b"\xff", "invalid_schema": b"[null]"}.get(evidence, b"[]"))
        with monkeypatch.context() as patch:
            if evidence == "unreadable":
                patch.setattr(Path, "read_text", unreadable)

            report = build_security_report(root)

        assert report["status"] == "failed", evidence
        assert "evidence_unavailable" in report["failures"], evidence
        assert "private evidence location" not in json.dumps(report)


def test_existing_valid_empty_findings_inventory_may_pass(tmp_path: Path) -> None:
    root = _security_root(tmp_path)
    path = root / "artifacts" / "security" / "findings.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")

    report = build_security_report(root)

    assert report["status"] == "passed"
    assert report["failures"] == []


def test_critical_finding_cannot_be_filtered_out(tmp_path: Path) -> None:  # E017-N001
    root = _security_root(tmp_path, blocking=["low"])

    policy = load_security_policy(root / "configs" / "security_policy.yaml")
    assert {"critical", "high"} <= set(policy.blocking_severities)

    for severity in ("critical", "high"):
        report = build_security_report(root, findings=[{"id": "SEC-9", "severity": severity, "status": "open"}])
        assert report["status"] == "failed", severity


@pytest.mark.parametrize("status", ["pending-triage", "", "OPEN ", None, 7, "reopened"])
def test_unknown_finding_status_blocks(tmp_path: Path, status: object) -> None:  # E017-N002
    root = _security_root(tmp_path)
    finding = {"id": "SEC-2", "severity": "critical", "status": status}
    assert build_security_report(root, findings=[finding])["status"] == "failed"


def test_explicitly_closed_findings_and_low_severity_do_not_block(tmp_path: Path) -> None:
    root = _security_root(tmp_path)
    findings = [
        {"id": "SEC-3", "severity": "critical", "status": "resolved"},
        {"id": "SEC-4", "severity": "low", "status": "open"},
    ]
    assert build_security_report(root, findings=findings)["status"] == "passed"


def test_unknown_severity_with_active_status_blocks(tmp_path: Path) -> None:
    root = _security_root(tmp_path)
    assert build_security_report(root, findings=[{"id": "SEC-5", "severity": "catastrophic", "status": "open"}])["status"] == "failed"
    assert build_security_report(root, findings=[{"id": "SEC-6", "status": "open"}])["status"] == "failed"


def test_finding_identifier_is_sanitised_in_failure_report(tmp_path: Path) -> None:  # E017-N003
    root = _security_root(tmp_path)
    hostile = "SEC-7\n- Status: `passed`\x1b[31m token=hunter2value " + "x" * 500
    report = build_security_report(root, findings=[{"id": hostile, "severity": "high", "status": "open"}])

    text = json.dumps(report)
    assert report["status"] == "failed"
    assert "\n" not in "".join(report["failures"]) and "\x1b" not in text
    assert "hunter2value" not in text
    assert all(len(item) < 200 for item in report["failures"])


# --- E024 -----------------------------------------------------------------------------------------


def _write(root: Path, relative: str, source: str) -> Path:
    path = root / "src" / "etf_cockpit" / "app" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_nested_ui_module_is_scanned(tmp_path: Path) -> None:  # E024-N002
    _write(tmp_path, "pages/sub/deep/probe.py", "from etf_cockpit.data import store\n")

    violations = find_violations(tmp_path)

    assert any(item.file.endswith("probe.py") for item in violations)
    assert build_report(tmp_path)["status"] == "failed"


def test_empty_root_fails_the_architecture_scan(tmp_path: Path) -> None:  # E024-N003
    report = build_report(tmp_path)

    assert report["status"] == "failed"
    assert report["scanned_file_count"] == 0
    assert report["errors"]


def test_unparseable_module_is_a_clean_failure(tmp_path: Path) -> None:
    # Separate source-parsing guard; E024-N004 names an unidentified policy inventory.
    _write(tmp_path, "pages/ok.py", "import os\n")
    _write(tmp_path, "pages/broken.py", "def (:\n")
    _write(tmp_path, "pages/binary.py", "x = 1\x00\n")

    report = build_report(tmp_path)

    assert report["status"] == "failed"
    assert len(report["errors"]) == 2
    assert report["scanned_file_count"] == 3


def test_boundary_diagnostics_are_redacted(tmp_path: Path) -> None:  # E024-N001
    _write(tmp_path, "pages/password=hunter2value.py", "from etf_cockpit.data import store\n")

    report = build_report(tmp_path)

    assert report["status"] == "failed"
    assert "hunter2value" not in json.dumps(report)


def test_unresolved_relative_import_is_a_sanitised_scan_failure(tmp_path: Path) -> None:
    _write(tmp_path, "pages/password=hunter2value.py", "from ........data import store\n")

    report = build_report(tmp_path)

    assert report["status"] == "failed"
    assert report["scanned_file_count"] == 1
    assert report["violation_count"] == 0
    assert len(report["errors"]) == 1
    assert ":1: could not resolve relative import (ImportError)" in report["errors"][0]
    assert "hunter2value" not in json.dumps(report)


# --- E016 -----------------------------------------------------------------------------------------


class _Plugin:
    def __init__(self, plugin_id: str = "fixture.plugin", *, authority: str = "evidence_only", capabilities=("health", "fetch"), network: bool = False) -> None:
        self.manifest = PluginManifest(
            plugin_id=plugin_id,
            version="1.0.0",
            kind="provider",
            capabilities=capabilities,
            licence="MIT",
            authority=authority,
            network_access=network,
        )
        self.fetch_calls = 0
        self.health_calls = 0
        self.seen: dict | None = None

    def health(self, context: PluginContext) -> PluginHealth:
        from etf_cockpit.plugins.contracts import PluginStatus

        self.health_calls += 1
        return PluginHealth(status=PluginStatus.AVAILABLE, message="ok")

    def fetch(self, payload, context: PluginContext) -> PluginResult:
        self.fetch_calls += 1
        self.seen = payload
        context.record_audit("fetched", "detail")
        return PluginResult(status="ok", message="done")


def test_disabled_authority_plugin_is_not_dispatched() -> None:  # E016-N003
    plugin = _Plugin(authority="disabled")
    registry = PluginRegistry(allowlist={"fixture.plugin"})
    registry.register(plugin, enabled=True)

    assert registry.invoke("fixture.plugin", "fetch", {}).status == "unavailable"
    assert registry.health("fixture.plugin").status.value == "disabled"
    assert plugin.fetch_calls == 0 and plugin.health_calls == 0
    assert registry.status_rows()[0]["enabled"] is False
    with pytest.raises(PluginRegistrationError, match="disabled"):
        registry.enable("fixture.plugin")
    assert registry.invoke("fixture.plugin", "fetch", {}).status == "unavailable"


@pytest.mark.parametrize(
    "text",
    [
        'token = "abc123supersecret"',
        '{"refreshToken": "abc123supersecret"}',
        '{"privateKey": "abc123supersecret"}',
        "signing_key=abc123supersecret",
        "signingKey: abc123supersecret",
    ],
)
def test_camel_case_secret_keys_are_detected(text: str) -> None:  # E016-N005
    assert _contains_unredacted_secret(text) is True


@pytest.mark.parametrize("text", ['{"refreshToken": "***redacted***"}', "privateKey: ***redacted***", "no secrets here"])
def test_redacted_secret_keys_pass(text: str) -> None:
    assert _contains_unredacted_secret(text) is False


def test_plugin_context_inputs_are_deeply_frozen() -> None:  # E016-N002
    source = {"rows": [1, {"a": [2]}], "nested": {"k": {"z": 1}}, "tags": {"x"}}
    context = PluginContext(request_id="r", inputs=source)

    with pytest.raises(TypeError):
        context.inputs["nested"]["k"]["z"] = 2  # type: ignore[index]
    assert isinstance(context.inputs["rows"], tuple)
    with pytest.raises(TypeError):
        context.inputs["rows"][1]["a"] = 0  # type: ignore[index]
    source["nested"]["k"]["z"] = 99
    assert context.inputs["nested"]["k"]["z"] == 1


def test_invoke_gives_plugin_a_private_copy_of_nested_input() -> None:  # E016-N002
    plugin = _Plugin()
    registry = PluginRegistry(allowlist={"fixture.plugin"})
    registry.register(plugin)
    payload = {"nested": {"values": [1, 2]}}

    assert registry.invoke("fixture.plugin", "fetch", payload).status == "ok"
    plugin.seen["nested"]["values"].append(3)  # type: ignore[index]

    assert payload == {"nested": {"values": [1, 2]}}


def test_conformance_measures_network_calls() -> None:  # E016-N004
    class Chatty(_Plugin):
        def health(self, context):
            try:
                socket.create_connection(("example.invalid", 9), timeout=0.1)
            except OSError:
                pass
            return super().health(context)

    registry = PluginRegistry(allowlist={"fixture.plugin"})
    registry.register(Chatty())

    report = registry.conformance_report()

    assert report["checks"][0]["network_calls"] is True
    assert report["failures"] == ["fixture.plugin"]
    # the probe must restore the real socket functions
    assert socket.create_connection.__module__ == "socket"


def test_audit_import_reads_the_file_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # E016-N001
    import etf_cockpit.chatgpt_bridge.import_audit as import_audit

    monkeypatch.setattr(import_audit, "CHATGPT_IMPORTS_DIR", tmp_path / "imports")
    monkeypatch.setattr(import_audit, "append_jsonl", lambda *args, **kwargs: None)
    audit = {
        "schema_version": "1.0",
        "review_date": "2026-10-05",
        "overall_view": "neutral",
        "portfolio_actions": [],
        "model_audit": {"toto_usefulness": "n/a", "timesfm_usefulness": "n/a", "baseline_comparison": "n/a", "overfitting_concerns": []},
    }
    source = tmp_path / "audit.json"
    source.write_text(json.dumps(audit), encoding="utf-8")
    reads: list[Path] = []
    original = pathlib.Path.read_text

    def counting(self, *args, **kwargs):
        if self == source:
            reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", counting)
    config = SimpleNamespace(universe=SimpleNamespace(enabled_ids=[]))

    import_audit.import_audit_json(source, config)

    assert len(reads) == 1


@pytest.mark.parametrize(
    "text",
    [
        "This note does not recommend automatic execution.",
        "There is no auto trade, and the broker should not act on it.",
        "Never place the order without review.",
        "Automatic execution is not permitted.",
        "To execute automatically is not allowed.",
        "The instruction to place the order is prohibited.",
        "The instruction to submit order is forbidden.",
        "Auto trade is never authorised.",
        "Autotrade must not be enabled.",
    ],
)
def test_negated_anti_execution_commentary_is_not_a_banned_phrase(text: str) -> None:  # E016-N006
    audit = {
        "schema_version": "1.0",
        "review_date": "2026-10-05",
        "overall_view": "neutral",
        "portfolio_actions": [],
        "model_audit": {"toto_usefulness": "n/a", "timesfm_usefulness": "n/a", "baseline_comparison": text, "overfitting_concerns": []},
    }
    assert validate_audit_text(json.dumps(audit), set()).review_date == "2026-10-05"


@pytest.mark.parametrize("text", [
    "Please place the order now.", "The broker should buy VWCE.", "Enable automatic execution.",
    "Automatic execution is not only permitted but encouraged.",
    "Automatic execution is not prohibited.",
    "Autotrade must not be disabled.",
])
def test_affirmative_execution_commentary_is_still_rejected(text: str) -> None:
    with pytest.raises(AuditImportError, match="automatic trading"):
        validate_audit_text(json.dumps({"overall_view": text}), set())


def test_execution_commentary_requires_a_whole_clause_prohibition() -> None:
    audit = {
        "schema_version": "1.0", "review_date": "2026-10-05", "overall_view": "neutral",
        "portfolio_actions": [],
        "model_audit": {"toto_usefulness": "n/a", "timesfm_usefulness": "n/a",
                        "baseline_comparison": "", "overfitting_concerns": []},
    }
    for text in ("Do not place any orders.", "Never execute trades automatically."):
        audit["model_audit"]["baseline_comparison"] = text
        assert validate_audit_text(json.dumps(audit), set()).review_date == "2026-10-05"
    for text in (
        "You must not proceed without automatic execution.",
        "Do not allow delays before automatic execution.",
        "No automatic execution unless the broker should buy shares.",
        "Automatic execution is not permitted but execute automatically anyway.",
        'The rule "no automatic execution" does not apply.',
        "Except as noted: automatic execution is not permitted.",
    ):
        audit["model_audit"]["baseline_comparison"] = text
        with pytest.raises(AuditImportError, match="automatic trading"):
            validate_audit_text(json.dumps(audit), set())
        with pytest.raises(AuditImportError, match="automatic trading"):
            validate_audit_text(json.dumps(audit).replace("automatic execution", r"automatic\u0020execution"), set())
