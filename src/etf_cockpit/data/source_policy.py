"""Versioned local-first source tiers and offline replay policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any

import yaml


SOURCE_POLICY_SCHEMA_VERSION = "data-source-policy.v1"
DEFAULT_SOURCE_POLICY_PATH = Path("configs/data_source_policy.yaml")
MANDATORY_SOURCE_TIERS = frozenset({"local_user_import", "official_bulk", "official_cached_api"})
SOURCE_TIERS = frozenset(MANDATORY_SOURCE_TIERS | {"best_effort_unofficial", "optional_commercial"})


class SourcePolicyError(ValueError):
    """Raised when the source-tier policy is unavailable or unsafe."""


class SourceTier(StrEnum):
    LOCAL_USER_IMPORT = "local_user_import"
    OFFICIAL_BULK = "official_bulk"
    OFFICIAL_CACHED_API = "official_cached_api"
    BEST_EFFORT_UNOFFICIAL = "best_effort_unofficial"
    OPTIONAL_COMMERCIAL = "optional_commercial"


@dataclass(frozen=True)
class SourcePolicy:
    provider_id: str
    dataset_type: str
    source_tier: SourceTier
    mandatory_allowed: bool
    optional_provider: bool
    cache_path: str
    licence: str
    fair_use_note: str
    network_required: bool
    quota_failure: str

    def cache_status(self, root: Path) -> str:
        candidate = (Path(root).resolve() / self.cache_path).resolve()
        root = Path(root).resolve()
        if not candidate.is_relative_to(root):
            return "invalid_path"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return "available"
        if candidate.is_dir():
            try:
                next(candidate.iterdir())
            except (OSError, StopIteration):
                return "missing"
            return "available"
        return "missing"

    def to_row(self, root: Path) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "dataset_type": self.dataset_type,
            "source_tier": self.source_tier.value,
            "optionality": "optional" if self.optional_provider else "mandatory-compatible",
            "cache_status": self.cache_status(root),
            "cache_path": self.cache_path,
            "network": "opt-in" if self.network_required else "not required",
            "quota_failure": self.quota_failure,
            "licence": self.licence,
            "fair_use_note": self.fair_use_note,
            "mandatory_allowed": self.mandatory_allowed,
        }


def load_source_policies(path: Path | None = None) -> tuple[SourcePolicy, ...]:
    source = Path(path or DEFAULT_SOURCE_POLICY_PATH)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourcePolicyError(f"Could not load source policy: {source}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SOURCE_POLICY_SCHEMA_VERSION:
        raise SourcePolicyError("source policy must use schema data-source-policy.v1")
    if payload.get("quota_failure") != "non_blocking":
        raise SourcePolicyError("source policy must make remote quota failure non-blocking")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise SourcePolicyError("source policy must contain source rows")
    rows: list[SourcePolicy] = []
    seen: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise SourcePolicyError("each source policy row must be an object")
        provider_id = str(raw.get("provider_id", "")).strip().lower()
        dataset_type = str(raw.get("dataset_type", "")).strip().lower()
        tier = str(raw.get("source_tier", "")).strip().lower()
        key = f"{provider_id}:{dataset_type}"
        if not provider_id or not dataset_type or key in seen or tier not in SOURCE_TIERS:
            raise SourcePolicyError(f"invalid or duplicate source policy row: {key}")
        mandatory_allowed = bool(raw.get("mandatory_allowed", False))
        network_required = bool(raw.get("network_required", False))
        if mandatory_allowed and tier not in MANDATORY_SOURCE_TIERS:
            raise SourcePolicyError(f"mandatory workflows cannot use source tier: {tier}")
        if mandatory_allowed and network_required:
            raise SourcePolicyError(f"mandatory source cannot require network access: {key}")
        cache_path = str(raw.get("cache_path", "")).strip()
        if not cache_path or Path(cache_path).is_absolute() or ".." in Path(cache_path).parts:
            raise SourcePolicyError(f"source cache path must be a safe relative path: {key}")
        quota_failure = str(raw.get("quota_failure", payload.get("quota_failure", ""))).strip().lower()
        if quota_failure != "non_blocking":
            raise SourcePolicyError(f"quota failure must be non-blocking: {key}")
        seen.add(key)
        rows.append(
            SourcePolicy(
                provider_id=provider_id,
                dataset_type=dataset_type,
                source_tier=SourceTier(tier),
                mandatory_allowed=mandatory_allowed,
                optional_provider=bool(raw.get("optional_provider", True)),
                cache_path=cache_path,
                licence=str(raw.get("licence", "unspecified")).strip() or "unspecified",
                fair_use_note=str(raw.get("fair_use_note", "")).strip(),
                network_required=network_required,
                quota_failure=quota_failure,
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.provider_id, item.dataset_type)))


def source_policy_rows(root: Path, path: Path | None = None) -> tuple[dict[str, object], ...]:
    return tuple(policy.to_row(root) for policy in load_source_policies(path))


def source_policy_report(root: Path, path: Path | None = None) -> dict[str, Any]:
    policies = load_source_policies(path)
    rows = [policy.to_row(root) for policy in policies]
    return {
        "schema_version": SOURCE_POLICY_SCHEMA_VERSION,
        "status": "passed",
        "network_calls": False,
        "mandatory_tiers": sorted(MANDATORY_SOURCE_TIERS),
        "rows": rows,
        "failures": [],
    }


def write_source_policy_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# Source policy report",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Status: `{report['status']}`",
        "- Network calls: `false`",
        "",
        "| Provider | Dataset | Tier | Optionality | Cache | Network | Quota failure |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        lines.append("| " + " | ".join(f"`{row[key]}`" for key in ("provider_id", "dataset_type", "source_tier", "optionality", "cache_status", "network", "quota_failure")) + " |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


__all__ = [
    "DEFAULT_SOURCE_POLICY_PATH",
    "MANDATORY_SOURCE_TIERS",
    "SOURCE_POLICY_SCHEMA_VERSION",
    "SourcePolicy",
    "SourcePolicyError",
    "SourceTier",
    "load_source_policies",
    "source_policy_report",
    "source_policy_rows",
    "write_source_policy_report",
]
