"""Versioned, local-first security policy and bounded input helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import importlib
import json
from pathlib import Path
import secrets
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from etf_cockpit.core.paths import CONFIG_DIR, ROOT
from etf_cockpit.core.session_log import redact_text


POLICY_SCHEMA_VERSION = "security-policy.v1"
POLICY_PATH = CONFIG_DIR / "security_policy.yaml"
_SECRET_KEY_WORDS = frozenset({"api_key", "apikey", "authorization", "bearer", "password", "passwd", "secret", "token"})
_REDACTED = "***redacted***"
_ACTIVE_FINDING_STATUSES = frozenset({"active", "new", "open", "unresolved"})


class SecurityPolicyError(ValueError):
    """Raised when a security policy or untrusted input is unsafe."""


@dataclass(frozen=True)
class SecurityPolicy:
    schema_version: str
    default_deny: bool
    allowed_schemes: tuple[str, ...]
    local_ui_host: str
    http_api_exposed: bool
    require_authentication_if_exposed: bool
    require_csrf_if_exposed: bool
    parser_limits: Mapping[str, int]
    persistent_storage: str
    export_allowed: bool
    log_allowed: bool
    blocking_severities: tuple[str, ...]


@dataclass(frozen=True)
class ApiAuthDecision:
    ok: bool
    reason: str


def load_security_policy(path: Path = POLICY_PATH) -> SecurityPolicy:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SecurityPolicyError(f"could not load security policy: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise SecurityPolicyError("security policy schema_version is invalid")
    network = payload.get("network")
    limits = payload.get("parser_limits")
    credentials = payload.get("credentials")
    findings = payload.get("security_findings")
    if not all(isinstance(value, dict) for value in (network, limits, credentials, findings)):
        raise SecurityPolicyError("security policy sections are invalid")
    schemes = tuple(str(value).strip().lower() for value in network.get("allowed_schemes", ()))
    if not schemes or any(value != "https" for value in schemes):
        raise SecurityPolicyError("only HTTPS may be allow-listed for remote access")
    local_host = str(network.get("local_ui_host", "")).strip().lower()
    if local_host not in {"127.0.0.1", "::1", "localhost"}:
        raise SecurityPolicyError("local_ui_host must be loopback-only")
    parser_limits: dict[str, int] = {}
    for key, value in limits.items():
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise SecurityPolicyError(f"parser limit {key!r} is not an integer") from exc
        if parsed <= 0:
            raise SecurityPolicyError(f"parser limit {key!r} must be positive")
        parser_limits[str(key)] = parsed
    blocking = tuple(str(value).strip().lower() for value in findings.get("blocking_severities", ()))
    if not blocking:
        raise SecurityPolicyError("at least one blocking security severity is required")
    return SecurityPolicy(
        schema_version=POLICY_SCHEMA_VERSION,
        default_deny=bool(network.get("default_deny")),
        allowed_schemes=schemes,
        local_ui_host=local_host,
        http_api_exposed=bool(network.get("http_api_exposed")),
        require_authentication_if_exposed=bool(network.get("require_authentication_if_exposed")),
        require_csrf_if_exposed=bool(network.get("require_csrf_if_exposed")),
        parser_limits=parser_limits,
        persistent_storage=str(credentials.get("persistent_storage", "")),
        export_allowed=bool(credentials.get("export_allowed")),
        log_allowed=bool(credentials.get("log_allowed")),
        blocking_severities=blocking,
    )


def redact_secrets(value: Any) -> Any:
    """Redact secret-shaped keys and values recursively before persistence."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalised = key_text.casefold().replace("-", "_").replace(" ", "_")
            result[key_text] = _REDACTED if normalised in _SECRET_KEY_WORDS else redact_secrets(item)
        return result
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def read_bounded_file(path: Path, *, max_bytes: int, root: Path | None = None) -> bytes:
    """Read a regular, non-symlink file without allowing path or size escapes."""

    candidate = Path(path)
    resolved = candidate.resolve()
    if root is not None:
        allowed_root = Path(root).resolve()
        if resolved != allowed_root and allowed_root not in resolved.parents:
            raise SecurityPolicyError("file path escapes the permitted root")
    if candidate.is_symlink() or not resolved.is_file():
        raise SecurityPolicyError("only regular non-symlink files may be read")
    if max_bytes <= 0:
        raise SecurityPolicyError("max_bytes must be positive")
    try:
        size = resolved.stat().st_size
        if size > max_bytes:
            raise SecurityPolicyError(f"file exceeds the {max_bytes}-byte safety limit")
        payload = resolved.read_bytes()
    except OSError as exc:
        raise SecurityPolicyError(f"file could not be read safely: {exc}") from exc
    if len(payload) > max_bytes:
        raise SecurityPolicyError(f"file exceeds the {max_bytes}-byte safety limit")
    return payload


def validate_network_url(url: str, *, allowlisted_hosts: tuple[str, ...] = (), allow_loopback: bool = False) -> str:
    """Validate a URL before any network transport is permitted."""

    parsed = urlparse(str(url).strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    allowed = {str(item).strip().lower().rstrip(".") for item in allowlisted_hosts if str(item).strip()}
    loopback = host in {"127.0.0.1", "::1", "localhost"}
    if parsed.username or parsed.password or parsed.fragment:
        raise SecurityPolicyError("URL credentials and fragments are not permitted")
    if scheme not in {"https"} and not (allow_loopback and loopback and scheme == "http"):
        raise SecurityPolicyError("network access requires HTTPS")
    if not host or (host not in allowed and not (allow_loopback and loopback)):
        raise SecurityPolicyError("host is not explicitly allow-listed")
    return parsed.geturl()


def verify_local_api_request(
    presented_token: str | None,
    expected_token: str | None,
    *,
    presented_csrf: str | None = None,
    expected_csrf: str | None = None,
) -> ApiAuthDecision:
    """Verify bearer and CSRF tokens without disclosing which check failed."""

    if not presented_token or not expected_token or not hmac.compare_digest(str(presented_token), str(expected_token)):
        return ApiAuthDecision(False, "authentication required")
    if expected_csrf is not None and (
        not presented_csrf or not hmac.compare_digest(str(presented_csrf), str(expected_csrf))
    ):
        return ApiAuthDecision(False, "CSRF validation failed")
    return ApiAuthDecision(True, "authenticated")


class CredentialStore:
    """OS keychain adapter; absence of keyring fails closed."""

    def __init__(self, *, service: str = "etf-ai-cockpit") -> None:
        self.service = service

    def get(self, account: str) -> str | None:
        keyring = _keyring()
        return keyring.get_password(self.service, str(account))

    def set(self, account: str, value: str) -> None:
        keyring = _keyring()
        keyring.set_password(self.service, str(account), str(value))

    def delete(self, account: str) -> None:
        keyring = _keyring()
        try:
            keyring.delete_password(self.service, str(account))
        except Exception as exc:
            if type(exc).__name__ != "PasswordDeleteError":
                raise


def build_security_report(root: Path = ROOT, *, findings: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Return safe, deterministic security status suitable for UI and release gates."""

    root = Path(root).resolve()
    failures: list[str] = []
    try:
        policy = load_security_policy(root / "configs" / "security_policy.yaml")
    except SecurityPolicyError as exc:
        return {"schema_version": POLICY_SCHEMA_VERSION, "status": "failed", "failures": [str(exc)], "network_calls": False}
    plugin_path = root / "configs" / "plugin_registry.yaml"
    try:
        plugin_payload = yaml.safe_load(plugin_path.read_text(encoding="utf-8"))
        rows = plugin_payload.get("allowlist", []) if isinstance(plugin_payload, dict) else []
        if not isinstance(plugin_payload, dict) or plugin_payload.get("execution_allowed") is not False:
            failures.append("plugin execution policy must remain disabled")
        for row in rows:
            if not isinstance(row, dict) or row.get("network_access") is not False:
                failures.append("every plugin must declare network_access=false")
    except (OSError, yaml.YAMLError, AttributeError):
        failures.append("plugin registry could not be inspected")
    for finding in findings if findings is not None else _load_findings(root / "artifacts" / "security" / "findings.json"):
        severity = str(finding.get("severity", "")).strip().lower()
        status = str(finding.get("status", "open")).strip().lower()
        if severity in policy.blocking_severities and status in _ACTIVE_FINDING_STATUSES:
            failures.append(f"active {severity} security finding blocks release: {str(finding.get('id', 'unidentified'))}")
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "failures": sorted(set(failures)),
        "network_calls": False,
        "default_deny": policy.default_deny,
        "local_ui_host": policy.local_ui_host,
        "http_api_exposed": policy.http_api_exposed,
        "http_api_auth_required_if_exposed": policy.require_authentication_if_exposed,
        "http_api_csrf_required_if_exposed": policy.require_csrf_if_exposed,
        "persistent_credential_storage": policy.persistent_storage,
        "secret_export_allowed": policy.export_allowed,
        "secret_log_allowed": policy.log_allowed,
        "parser_limits": dict(sorted(policy.parser_limits.items())),
        "blocking_severities": list(policy.blocking_severities),
    }


def create_ephemeral_token() -> str:
    """Create an in-memory token; callers must not persist or log it."""

    return secrets.token_urlsafe(32)


def _load_findings(path: Path) -> list[Mapping[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [{"id": "security-findings-file", "severity": "high", "status": "open"}]
    return [item for item in payload if isinstance(item, Mapping)] if isinstance(payload, list) else []


def _keyring() -> Any:
    try:
        return importlib.import_module("keyring")
    except ImportError as exc:
        raise SecurityPolicyError("OS credential store is unavailable; persistent secrets remain disabled") from exc


__all__ = [
    "ApiAuthDecision",
    "CredentialStore",
    "POLICY_PATH",
    "POLICY_SCHEMA_VERSION",
    "SecurityPolicy",
    "SecurityPolicyError",
    "build_security_report",
    "create_ephemeral_token",
    "load_security_policy",
    "read_bounded_file",
    "redact_secrets",
    "validate_network_url",
    "verify_local_api_request",
]
