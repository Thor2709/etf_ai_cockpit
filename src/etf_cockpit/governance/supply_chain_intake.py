"""Deterministic local supply-chain intake and provenance evidence."""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION = "supply-chain-intake.v1"
DEFAULT_SUPPLY_CHAIN_INTAKE_PATH = Path("configs/supply_chain_intake.yaml")
REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s#]+)")
EXTERNAL_PATH_MARKERS = ("vendor/", "third_party/", "third-party/", "external/")


class SupplyChainIntakeError(ValueError):
    """Raised when the local supply-chain intake contract is unavailable."""


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip() or "unavailable"
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _canonical_checksum(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _licence_class(licence: str) -> str:
    value = licence.casefold()
    tokens = set(re.findall(r"[a-z0-9]+", value))
    if {"agpl", "gpl"} & tokens or "strong copyleft" in value:
        return "strong_copyleft"
    if {"lgpl", "mpl", "epl", "eupl"} & tokens or "weak copyleft" in value:
        return "weak_copyleft"
    if {"apache", "bsd", "mit", "isc", "permissive"} & tokens:
        return "permissive"
    return "unknown"


def load_supply_chain_intake(path: Path | None = None) -> dict[str, Any]:
    source = Path(path or DEFAULT_SUPPLY_CHAIN_INTAKE_PATH)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SupplyChainIntakeError(f"Could not load supply-chain intake registry: {source}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION:
        raise SupplyChainIntakeError(f"supply-chain intake registry must use schema {SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION}")
    if not isinstance(payload.get("policy"), dict) or not isinstance(payload.get("components"), list) or not payload["components"]:
        raise SupplyChainIntakeError("supply-chain intake registry requires policy and components")
    required = set(payload["policy"].get("required_record_fields", ()))
    if not required:
        raise SupplyChainIntakeError("supply-chain intake registry requires record fields")
    for row in payload["components"]:
        if not isinstance(row, dict) or not row.get("component_id"):
            raise SupplyChainIntakeError("every intake component requires component_id")
        missing = sorted(
            field
            for field in required
            if field not in row or row[field] is None or row[field] == ""
        )
        if missing:
            raise SupplyChainIntakeError(f"{row.get('component_id', 'unknown')} missing intake fields: {', '.join(missing)}")
        boundary = str(row.get("integration_boundary", ""))
        if boundary not in set(payload["policy"].get("allowed_boundaries", ())):
            raise SupplyChainIntakeError(f"{row.get('component_id', 'unknown')} uses an unapproved integration boundary: {boundary}")
        licence_class = str(row.get("licence_class", ""))
        if licence_class not in set(payload["policy"].get("allowed_licence_classes", ())):
            raise SupplyChainIntakeError(f"{row.get('component_id', 'unknown')} uses an unapproved licence class: {licence_class}")
    return payload


def _locked_dependencies(root: Path, lock_path: Path) -> tuple[dict[str, object], ...]:
    if not lock_path.is_file():
        return ()
    rows: list[dict[str, object]] = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_RE.match(line)
        if not match:
            continue
        name, version = match.groups()
        try:
            metadata = importlib.metadata.metadata(name)
            licence = str(metadata.get("License") or metadata.get("License-Expression") or "").strip()
            repository = str(metadata.get("Home-page") or "").strip()
            maintainer = str(metadata.get("Maintainer") or metadata.get("Author") or "").strip()
        except importlib.metadata.PackageNotFoundError:
            licence = repository = maintainer = ""
        rows.append(
            {
                "package": name,
                "version": version,
                "licence": licence or "unavailable",
                "licence_class": _licence_class(licence),
                "repository": repository or "unavailable",
                "maintainer": maintainer or "unavailable",
                "exact_ref": f"{name}=={version}",
                "integration_boundary": "dependency",
                "copied_files": [],
                "security_policy": "configs/supply_chain_policy.yaml",
                "upstream_update_policy": "pinned-lock-review-and-sbom-diff",
            }
        )
    return tuple(rows)


def _tracked_external_paths(root: Path) -> tuple[str, ...]:
    try:
        output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    except (OSError, subprocess.CalledProcessError):
        return ()
    paths = output.decode("utf-8", errors="replace").split("\0")
    return tuple(sorted(path for path in paths if any(marker in f"{path.lower()}/" for marker in EXTERNAL_PATH_MARKERS)))


def _verify_registry_signature(root: Path, registry: dict[str, Any], registry_sha256: str) -> str:
    signature_config = registry.get("signature")
    if not isinstance(signature_config, dict):
        return "unconfigured"
    signature_path = root / str(signature_config.get("path", ""))
    if not signature_path.is_file():
        return "missing"
    try:
        signature = json.loads(signature_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "invalid"
    if not isinstance(signature, dict) or signature.get("status") != "signed":
        return "invalid"
    key = os.getenv(str(signature_config.get("key_env", "")), "").encode("utf-8")
    if not key:
        return "unverifiable"
    payload = registry_sha256.encode("ascii")
    expected_payload_sha256 = hashlib.sha256(payload).hexdigest()
    expected_signature = hmac.new(key, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(signature.get("payload_sha256", "")), expected_payload_sha256):
        return "invalid"
    if not hmac.compare_digest(str(signature.get("signature", "")), expected_signature):
        return "invalid"
    return "signed"


def sign_supply_chain_registry(registry_sha256: str, key: bytes, *, key_id: str) -> dict[str, str]:
    """Create a detached HMAC signature without persisting or returning the key."""

    if len(key) < 16:
        raise ValueError("supply-chain signing key must contain at least 16 bytes")
    payload = registry_sha256.encode("ascii")
    return {
        "schema_version": SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION,
        "algorithm": "HMAC-SHA256",
        "status": "signed",
        "key_id": key_id,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signature": hmac.new(key, payload, hashlib.sha256).hexdigest(),
    }


def supply_chain_intake_report(root: Path, path: Path | None = None) -> dict[str, Any]:
    """Return local intake evidence without network access or package mutation."""

    root = Path(root).resolve()
    registry = load_supply_chain_intake(path or root / DEFAULT_SUPPLY_CHAIN_INTAKE_PATH)
    lock_path = root / str(registry.get("dependency_lock", "requirements-release.txt"))
    components = [dict(row) for row in registry["components"] if isinstance(row, dict)]
    dependencies = list(_locked_dependencies(root, lock_path))
    failures: list[str] = []
    notices = root / str(registry.get("third_party_notices", ""))
    if not notices.is_file():
        failures.append(f"third-party notices file is missing: {notices}")
    missing_provenance = []
    missing_copied_files = []
    for row in components:
        licence = str(row.get("licence", ""))
        if "/" in licence and not licence.startswith(("http://", "https://")) and not (root / licence).is_file():
            missing_provenance.append(str(row.get("component_id", "unknown")))
        for copied_file in row.get("copied_files", []) or []:
            if not (root / str(copied_file)).exists():
                missing_copied_files.append(str(copied_file))
    if missing_provenance:
        failures.append("licence evidence is missing for intake components: " + ", ".join(sorted(missing_provenance)))
    if missing_copied_files:
        failures.append("declared copied files are missing: " + ", ".join(sorted(missing_copied_files)))
    external_paths = list(_tracked_external_paths(root))
    if external_paths and bool(registry["policy"].get("copied_code_requires_approved_record", True)):
        failures.append("tracked external/vendor paths require an explicit intake record: " + ", ".join(external_paths))
    if not dependencies:
        failures.append(f"dependency lock is missing or contains no exact pins: {lock_path}")
    missing_metadata = [str(row["package"]) for row in dependencies if "unavailable" in {row["licence"], row["repository"], row["maintainer"]}]
    review_status = str(registry.get("review_status", "hardening_required"))
    hardening = []
    if review_status != "approved":
        hardening.append("upstream repository, maintainer, cadence and licence evidence still require human approval")
    if any(str(row.get("review_status")) != "approved" for row in components):
        hardening.append("one or more intake records remain hardening_required")
    if any(str(row.get("licence_class")) == "unknown" for row in components):
        hardening.append("one or more component licence classes remain unclassified")
    copied_components = [str(row.get("component_id")) for row in components if row.get("copied_files")]
    if copied_components:
        hardening.append("copied source archives remain subject to approved provenance and upstream-diff review: " + ", ".join(copied_components))
    if missing_metadata:
        hardening.append("locked dependencies require licence, repository or maintainer metadata review: " + ", ".join(sorted(missing_metadata)))
    canonical_payload = {
        "schema_version": registry["schema_version"],
        "registry_version": registry.get("registry_version"),
        "policy": registry["policy"],
        "components": components,
        "dependency_lock": str(registry.get("dependency_lock")),
        "third_party_notices": str(registry.get("third_party_notices")),
    }
    registry_sha256 = _canonical_checksum(canonical_payload)
    signature_status = _verify_registry_signature(root, registry, registry_sha256)
    if signature_status != "signed":
        hardening.append(f"detached intake signature status is {signature_status}")
    if signature_status == "invalid":
        failures.append("detached intake signature is invalid")
    return {
        "schema_version": SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION,
        "registry_version": registry.get("registry_version", "unavailable"),
        "status": "failed" if failures else "passed",
        "review_status": review_status,
        "network_calls": False,
        "execution_allowed": False,
        "release_commit": _git_head(root),
        "registry_sha256": registry_sha256,
        "component_count": len(components),
        "dependency_count": len(dependencies),
        "missing_dependency_metadata": sorted(missing_metadata),
        "tracked_external_paths": external_paths,
        "third_party_notices": str(registry.get("third_party_notices")),
        "components": components,
        "dependencies": dependencies,
        "hardening_required": hardening,
        "signature_status": signature_status,
        "failures": failures,
    }


def write_supply_chain_intake_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# Supply-chain intake report",
        "",
        f"- Schema: `{report.get('schema_version', SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION)}`",
        f"- Status: `{report.get('status', 'failed')}`",
        f"- Review status: `{report.get('review_status', 'hardening_required')}`",
        f"- Registry SHA-256: `{report.get('registry_sha256', 'unavailable')}`",
        f"- Components: `{report.get('component_count', 0)}`; locked dependencies: `{report.get('dependency_count', 0)}`",
        "- Network calls: `false`",
        "- Execution allowed: `false`",
        f"- Duration: `{report.get('duration_ms', 'unavailable')} ms`",
        "",
        "## Failures",
        "",
    ]
    lines.extend(f"- {item}" for item in (report.get("failures") or ["None"]))
    lines.extend(["", "## Hardening required", ""])
    lines.extend(f"- {item}" for item in (report.get("hardening_required") or ["None"]))
    lines.extend(["", "## Locked dependency metadata", "", "| Package | Version | Licence | Class | Repository | Maintainer |", "|---|---|---|---|---|---|"])
    def markdown_cell(value: object) -> str:
        return str(value).replace("\n", " ").replace("|", "\\|")

    lines.extend(
        f"| `{row['package']}` | `{row['version']}` | `{markdown_cell(row['licence'])}` | `{row['licence_class']}` | `{markdown_cell(row['repository'])}` | `{markdown_cell(row['maintainer'])}` |"
        for row in report.get("dependencies", [])
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


__all__ = [
    "DEFAULT_SUPPLY_CHAIN_INTAKE_PATH",
    "SUPPLY_CHAIN_INTAKE_SCHEMA_VERSION",
    "SupplyChainIntakeError",
    "load_supply_chain_intake",
    "sign_supply_chain_registry",
    "supply_chain_intake_report",
    "write_supply_chain_intake_report",
]
