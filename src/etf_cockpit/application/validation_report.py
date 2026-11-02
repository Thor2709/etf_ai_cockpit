"""Read the latest validation evidence without running or writing validation.

Open defaults: only ``artifacts/validation/latest/validation.json`` is read; returned
check and failure details are capped at 50 and 20 rows respectively.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping


def load_validation_report(root: Path, path: Path | None = None) -> dict[str, Any]:
    """Return a compact, fail-closed projection of the last local validation report."""

    report_path = Path(path) if path is not None else Path(root) / "artifacts" / "validation" / "latest" / "validation.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "status": "unavailable",
            "reason": f"latest validation report unavailable ({type(exc).__name__})",
            "generated_at": None,
            "checks": [],
            "failures": [],
            "execution_allowed": False,
        }
    if not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "reason": "latest validation report root is not an object",
            "generated_at": None,
            "checks": [],
            "failures": [],
            "execution_allowed": False,
        }

    raw_checks = payload.get("checks")
    checks = [
        {key: row.get(key) for key in ("name", "status", "required") if key in row}
        for row in raw_checks[:50]
        if isinstance(row, dict)
    ] if isinstance(raw_checks, list) else []
    raw_failures = payload.get("failures")
    failures = [str(item)[:240] for item in raw_failures[:20]] if isinstance(raw_failures, list) else []
    required_failure = isinstance(raw_checks, list) and any(
        not isinstance(row, dict) or (row.get("required") is True and row.get("status") != "passed")
        for row in raw_checks
    )
    if failures or required_failure:
        status = "failed"
    elif isinstance(raw_checks, list) and raw_checks:
        status = "passed"
    else:
        status = "incomplete"
    return {
        "status": status,
        "reason": None if status != "incomplete" else "validation report contains no complete required-check result",
        "mode": payload.get("mode"),
        "generated_at": payload.get("finished_at") or payload.get("generated_at"),
        "check_count": len(raw_checks) if isinstance(raw_checks, list) else None,
        "checks": checks,
        "failures": failures,
        "execution_allowed": False,
    }


def validate_audit_input(root: Path, *, path: str | None = None, text: str | None = None) -> dict[str, Any]:
    """Validate a JSON note or audit archive using the canonical bridge validators."""

    from etf_cockpit.chatgpt_bridge.audit_packet import validate_audit_archive
    from etf_cockpit.chatgpt_bridge.audit_packet import _contains_unredacted_secret
    from etf_cockpit.chatgpt_bridge.validation import validate_audit_file, validate_audit_text
    from etf_cockpit.core.config import load_config

    if path is not None and Path(path).suffix.casefold() == ".zip":
        report = validate_audit_archive(Path(path))
        return {
            "status": "valid" if report.valid else "invalid",
            "findings": {"missing": report.missing, "checksum_errors": report.checksum_errors, "secret_findings": report.secret_findings},
            "confirmable": False,
            "execution_allowed": False,
        }
    if path is not None:
        raw_text = Path(path).read_text(encoding="utf-8")
    else:
        raw_text = text or ""
    if _contains_unredacted_secret(raw_text):
        raise ValueError("audit JSON contains unredacted secret material")
    config = load_config(Path(root) / "configs")
    audit = validate_audit_file(Path(path), set(config.universe.enabled_ids)) if path is not None else validate_audit_text(raw_text, set(config.universe.enabled_ids))
    return {
        "status": "valid",
        "audit": audit.model_dump(mode="json"),
        "findings": [],
        "confirmable": path is not None,
        "execution_allowed": False,
    }


def import_audit_input(root: Path, path: str) -> dict[str, object]:
    """Import one note through the established ChatGPT application bridge."""

    from etf_cockpit.application.chatgpt_review import ChatGPTBridge
    from etf_cockpit.core.config import load_config
    from etf_cockpit.core.paths import ROOT

    base = Path(root).resolve()
    if base != Path(ROOT).resolve():
        raise ValueError("audit import is bound to the configured data root")
    result = ChatGPTBridge(load_config(base / "configs")).import_audit_json(Path(path))
    return {"status": "imported", "schema_version": result.schema_version, "review_date": result.review_date, "execution_allowed": False}


def load_settings_view(root: Path, section: str | None = None) -> dict[str, object]:
    """Read the safe settings bundle or one allow-listed local policy file."""

    from etf_cockpit.core.settings_bundle import load_settings_bundle, settings_export

    if section == "ui":
        return {
            "status": "unsupported",
            "section": "ui",
            "reason": "UI settings are not represented by the canonical settings bundle",
            "execution_allowed": False,
        }
    if section in {
        "portfolio_policy_v1", "risk_limits", "pre_trade_limits_v1", "gate_policy",
        "authority_matrix", "paper_bots_v1", "strategy_templates_v1",
    }:
        import yaml

        try:
            policy = yaml.safe_load((Path(root) / "configs" / f"{section}.yaml").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f"policy {section} unavailable ({type(exc).__name__})") from None
        return {"section": section, "policy": policy, "execution_allowed": False}
    if section is not None and section not in {"controls", "universe", "targets", "risks", "costs", "models", "providers"}:
        raise ValueError("section is not a supported settings bundle section")
    bundle = load_settings_bundle(Path(root))
    exported = settings_export(bundle)
    if section is None:
        return exported
    return {section: exported.get(section), "revision": bundle.revision, "settings_version": bundle.settings_version}


def preview_settings_changes(root: Path, changes: Mapping[str, object]) -> dict[str, object]:
    """Preview only allow-listed secret-free provider metadata through SettingsBundle."""

    from etf_cockpit.core.settings_bundle import SettingsBundle, load_settings_bundle, preview_settings

    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("changes must be a non-empty object")
    base = Path(root)
    current = load_settings_bundle(base)
    candidate_data = current.model_dump(mode="json")
    for key, value in changes.items():
        _apply_provider_setting(candidate_data, str(key), value)
    candidate = SettingsBundle.from_mapping(candidate_data)
    preview = preview_settings(candidate, expected_revision=current.revision, root=base)
    return {
        "valid": preview.valid,
        "before_revision": preview.before_revision,
        "after_revision": preview.after_revision,
        "expected_revision": current.revision,
        "changed_fields": preview.changed_fields,
        "warnings": preview.warnings,
        "execution_allowed": False,
    }


def save_settings_changes(root: Path, changes: Mapping[str, object], expected_revision: str) -> dict[str, object]:
    """Revalidate and atomically save the exact provider metadata preview."""

    from etf_cockpit.core.settings_bundle import SettingsBundle, SettingsError, load_settings_bundle, save_settings

    base = Path(root)
    current = load_settings_bundle(base)
    if current.revision != expected_revision:
        raise SettingsError("SETTINGS_REVISION_CONFLICT", "settings changed since the preview")
    candidate_data = current.model_dump(mode="json")
    for key, value in changes.items():
        _apply_provider_setting(candidate_data, str(key), value)
    candidate = SettingsBundle.from_mapping(candidate_data)
    result = save_settings(candidate, expected_revision=expected_revision, root=base)
    return {
        "saved": result.saved,
        "revision": result.revision,
        "settings_version": result.settings_version,
        "changed_fields": tuple(changes),
        "execution_allowed": False,
    }


def _apply_provider_setting(candidate: dict[str, Any], path: str, value: object) -> None:
    prefix = "providers.providers."
    allowed_fields = {"active_provider", "base_url", "symbols_map"}
    if not path.startswith(prefix):
        raise ValueError("only providers.providers.<name> metadata keys are writable")
    parts = path.split(".")
    if len(parts) < 4 or not parts[2] or parts[3] not in allowed_fields:
        raise ValueError("provider setting path is not allow-listed")
    if any(re.search(r"secret|token|password|credential|api[_-]?key", item, flags=re.IGNORECASE) for item in parts):
        raise ValueError("secret provider settings are never writable")
    providers = candidate.setdefault("providers", {}).setdefault("providers", {})
    provider = providers.setdefault(parts[2], {})
    field = parts[3]
    if field == "symbols_map":
        if len(parts) != 5 or not parts[4] or not isinstance(value, str):
            raise ValueError("symbols_map changes require a provider symbol key and string value")
        provider.setdefault(field, {})[parts[4]] = value
    elif len(parts) == 4:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        provider[field] = value
    else:
        raise ValueError("provider setting path has unsupported depth")


__all__ = [
    "import_audit_input", "load_settings_view", "load_validation_report", "preview_settings_changes",
    "save_settings_changes", "validate_audit_input",
]
