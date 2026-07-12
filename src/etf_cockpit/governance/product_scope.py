"""Fail-closed loaders for the local governance policy set."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, TypeVar

import yaml
from pydantic import ValidationError

from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.governance.models import (
    FeatureRegistryPolicy,
    GatePolicy,
    GlossaryPolicy,
    GovernanceLoadResult,
    PolicyModel,
    ProductGovernancePolicy,
    StrategyScopePolicy,
)


@dataclass(frozen=True)
class PolicyPaths:
    product: Path
    feature_registry: Path
    strategy_scope: Path
    gate_policy: Path
    glossary: Path


DEFAULT_POLICY_PATHS = PolicyPaths(
    product=CONFIG_DIR / "product_governance.yaml",
    feature_registry=CONFIG_DIR / "feature_registry.yaml",
    strategy_scope=CONFIG_DIR / "strategy_scope.yaml",
    gate_policy=CONFIG_DIR / "gate_policy.yaml",
    glossary=CONFIG_DIR / "glossary.yaml",
)

PRODUCT_GOVERNANCE_PATH = DEFAULT_POLICY_PATHS.product
FEATURE_REGISTRY_PATH = DEFAULT_POLICY_PATHS.feature_registry
STRATEGY_SCOPE_PATH = DEFAULT_POLICY_PATHS.strategy_scope
GATE_POLICY_PATH = DEFAULT_POLICY_PATHS.gate_policy
GLOSSARY_PATH = DEFAULT_POLICY_PATHS.glossary

PolicyClassT = TypeVar("PolicyClassT", bound=PolicyModel)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _diagnostic(
    *,
    schema_version: str,
    checksum: str,
    message: str,
) -> GovernanceLoadResult[PolicyModel]:
    return GovernanceLoadResult(
        policy=None,
        schema_version=schema_version,
        checksum=checksum,
        diagnostic_mode=True,
        diagnostics=(message,),
        research_state="manual_review",
        score_state="not_scoreable",
        research_promotion_allowed=False,
        portfolio_review_allowed=False,
        execution_allowed=False,
        executable_authority=False,
    )


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "on", "1"}
    return False


def _has_positive_authority(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in {
                "execution_allowed",
                "executable_authority",
                "order_transmission",
                "external_upload",
                "credential_access",
            } and _truthy(item):
                return True
            if _has_positive_authority(item):
                return True
    elif isinstance(value, list):
        return any(_has_positive_authority(item) for item in value)
    return False


def _normalise_payload(model_class: type[PolicyClassT], raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    if model_class is ProductGovernancePolicy:
        authority = payload.get("authority")
        if isinstance(authority, Mapping):
            authority_payload = dict(authority)
            payload["authority"] = authority_payload
            for key in ("execution_allowed", "executable_authority"):
                if key not in payload and key in authority_payload:
                    payload[key] = authority_payload[key]
    elif model_class is FeatureRegistryPolicy and "entries" not in payload:
        payload["entries"] = payload.pop("features", ())
    elif model_class is StrategyScopePolicy and "entries" not in payload:
        payload["entries"] = payload.pop("strategies", ())
    elif model_class is GatePolicy and "gates" not in payload:
        payload["gates"] = payload.pop("entries", ())
    elif model_class is GlossaryPolicy and "entries" not in payload:
        payload["entries"] = payload.pop("glossary", payload.pop("terms", ()))
    return payload


def _validation_is_explicitly_contradictory(error: ValidationError) -> bool:
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "execution_allowed",
            "executable_authority",
            "order_transmission",
            "external_upload",
            "credential_access",
            "score_authority",
            "research_promotion_allowed",
            "portfolio_review_allowed",
            "authority",
            "route values must be unique",
            "order values must be unique",
            "feature_id values must be unique",
            "strategy_id values must be unique",
        )
    )


def _load_policy(
    path: Path,
    model_class: type[PolicyClassT],
    *,
    policy_name: str,
) -> GovernanceLoadResult[PolicyClassT]:
    source = Path(path)
    try:
        raw_bytes = source.read_bytes()
    except OSError as exc:
        return _diagnostic(schema_version="unknown", checksum="unavailable", message=f"{policy_name} policy unavailable: {exc}")  # type: ignore[return-value]

    checksum = _sha256_bytes(raw_bytes)
    try:
        loaded = yaml.safe_load(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return _diagnostic(schema_version="unknown", checksum=checksum, message=f"{policy_name} policy could not be parsed: {exc}")  # type: ignore[return-value]
    if not isinstance(loaded, Mapping):
        return _diagnostic(schema_version="unknown", checksum=checksum, message=f"{policy_name} policy must be a mapping")  # type: ignore[return-value]

    schema_version = str(loaded.get("schema_version") or "unknown")
    required_headers = {"schema_version", "policy_id", "policy_version"}
    has_headers = required_headers.issubset(loaded)
    positive_authority = _has_positive_authority(loaded)
    payload = _normalise_payload(model_class, loaded)
    if not has_headers and not positive_authority:
        return _diagnostic(
            schema_version=schema_version,
            checksum=checksum,
            message=f"{policy_name} policy is missing required metadata",
        )  # type: ignore[return-value]

    try:
        policy = model_class.model_validate(payload)
        policy = policy.model_copy(update={"checksum": checksum})
    except ValidationError as exc:
        if _validation_is_explicitly_contradictory(exc):
            raise
        return _diagnostic(
            schema_version=schema_version,
            checksum=checksum,
            message=f"{policy_name} policy failed validation: {exc}",
        )  # type: ignore[return-value]

    return GovernanceLoadResult(
        policy=policy,
        schema_version=policy.schema_version,
        checksum=checksum,
        diagnostic_mode=False,
        diagnostics=(),
        research_state="manual_review",
        score_state="not_scoreable",
        research_promotion_allowed=False,
        portfolio_review_allowed=False,
        execution_allowed=False,
        executable_authority=False,
    )


def load_product_governance(path: Path | None = None) -> GovernanceLoadResult[ProductGovernancePolicy]:
    """Load product authority policy, remaining diagnostic-only on absence."""

    return _load_policy(Path(path or PRODUCT_GOVERNANCE_PATH), ProductGovernancePolicy, policy_name="product governance")


def load_feature_registry(path: Path | None = None) -> GovernanceLoadResult[FeatureRegistryPolicy]:
    """Load the route/feature registry."""

    return _load_policy(Path(path or FEATURE_REGISTRY_PATH), FeatureRegistryPolicy, policy_name="feature registry")


def load_strategy_scope(path: Path | None = None) -> GovernanceLoadResult[StrategyScopePolicy]:
    """Load strategy lifecycle and authority scope."""

    return _load_policy(Path(path or STRATEGY_SCOPE_PATH), StrategyScopePolicy, policy_name="strategy scope")


def load_gate_policy(path: Path | None = None) -> GovernanceLoadResult[GatePolicy]:
    """Load the ordered fail-closed gate policy."""

    return _load_policy(Path(path or GATE_POLICY_PATH), GatePolicy, policy_name="gate policy")


def load_glossary(path: Path | None = None) -> GovernanceLoadResult[GlossaryPolicy]:
    """Load explanatory glossary terms used by later governance surfaces."""

    return _load_policy(Path(path or GLOSSARY_PATH), GlossaryPolicy, policy_name="glossary")


__all__ = [
    "DEFAULT_POLICY_PATHS",
    "FEATURE_REGISTRY_PATH",
    "GATE_POLICY_PATH",
    "GLOSSARY_PATH",
    "PRODUCT_GOVERNANCE_PATH",
    "PolicyPaths",
    "STRATEGY_SCOPE_PATH",
    "load_feature_registry",
    "load_gate_policy",
    "load_glossary",
    "load_product_governance",
    "load_strategy_scope",
]
