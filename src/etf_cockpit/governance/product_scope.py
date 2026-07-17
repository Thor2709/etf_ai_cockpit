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
    AuthorityPolicy,
    AuthorityMatrixPolicy,
    FeatureRegistryPolicy,
    GatePolicy,
    GlossaryPolicy,
    GovernanceLoadResult,
    PolicyModel,
    ProductGovernancePolicy,
    REQUIRED_GATE_IDS,
    REQUIRED_GLOSSARY_TERMS,
    StrategyScopePolicy,
    SUPPORTED_SCHEMA_VERSIONS,
)


@dataclass(frozen=True)
class PolicyPaths:
    product: Path
    authority_matrix: Path
    feature_registry: Path
    strategy_scope: Path
    gate_policy: Path
    glossary: Path


DEFAULT_POLICY_PATHS = PolicyPaths(
    product=CONFIG_DIR / "product_governance.yaml",
    authority_matrix=CONFIG_DIR / "authority_matrix.yaml",
    feature_registry=CONFIG_DIR / "feature_registry.yaml",
    strategy_scope=CONFIG_DIR / "strategy_scope.yaml",
    gate_policy=CONFIG_DIR / "gate_policy.yaml",
    glossary=CONFIG_DIR / "glossary.yaml",
)

PRODUCT_GOVERNANCE_PATH = DEFAULT_POLICY_PATHS.product
AUTHORITY_MATRIX_PATH = DEFAULT_POLICY_PATHS.authority_matrix
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
    elif model_class is FeatureRegistryPolicy:
        entries = payload.pop("features", payload.get("entries", ()))
        normalised_entries = []
        for raw_entry in entries or ():
            if not isinstance(raw_entry, Mapping):
                normalised_entries.append(raw_entry)
                continue
            entry = dict(raw_entry)
            if "routes" not in entry and entry.get("route"):
                entry["routes"] = (entry["route"],)
            if "route" not in entry and entry.get("routes"):
                entry["route"] = entry["routes"][0]
            if "name" not in entry and entry.get("title"):
                entry["name"] = entry["title"]
            if "data_dependencies" not in entry and "required_data" in entry:
                entry["data_dependencies"] = entry["required_data"]
            if "required_data" not in entry and "data_dependencies" in entry:
                entry["required_data"] = entry["data_dependencies"]
            normalised_entries.append(entry)
        payload["entries"] = normalised_entries
    elif model_class is StrategyScopePolicy:
        entries = payload.pop("strategies", payload.get("entries", ()))
        normalised_entries = []
        for raw_entry in entries or ():
            if not isinstance(raw_entry, Mapping):
                normalised_entries.append(raw_entry)
                continue
            entry = dict(raw_entry)
            if "permitted_authority" not in entry and "authority" in entry:
                entry["permitted_authority"] = entry["authority"]
            if "authority" not in entry and "permitted_authority" in entry:
                entry["authority"] = entry["permitted_authority"]
            normalised_entries.append(entry)
        payload["entries"] = normalised_entries
    elif model_class is GatePolicy and "gates" not in payload:
        payload["gates"] = payload.pop("entries", ())
    elif model_class is GlossaryPolicy and "entries" not in payload:
        payload["entries"] = payload.pop("glossary", payload.pop("terms", ()))
    return payload


def _validation_is_explicitly_contradictory(error: ValidationError) -> bool:
    explicit_fields = {
        "execution_allowed",
        "executable_authority",
        "order_transmission",
        "external_upload",
        "credential_access",
        "score_authority",
        "research_promotion_allowed",
        "portfolio_review_allowed",
        "paper_authority",
        "execution_authority",
        "permitted_authority",
    }
    duplicate_messages = {
        "route values must be unique",
        "order values must be unique",
        "feature_id values must be unique",
        "strategy_id values must be unique",
        "glossary terms must be unique",
        "gate_id values must be unique",
    }
    for detail in error.errors():
        locations = {str(part) for part in detail.get("loc", ())}
        if locations & explicit_fields:
            return True
        message = str(detail.get("msg", "")).casefold()
        if any(marker in message for marker in duplicate_messages):
            return True
        if any(
            marker in message
            for marker in (
                "positive authority",
                "authority and permitted_authority must agree",
                "authority 'none' cannot",
                "execution_authority must remain none",
                "gate severity cannot allow",
                "strategies cannot have score_authority",
                "strategies cannot have research_promotion_allowed",
                "strategies cannot have portfolio_review_allowed",
                "strategies cannot have paper_authority",
                "strategies cannot have authority",
                "score_authority is not permitted",
                "research_promotion_allowed is not permitted",
                "portfolio_review_allowed is not permitted",
            )
        ):
            return True
    return False


def _substantive_section_error(model_class: type[PolicyClassT], payload: Mapping[str, Any]) -> str | None:
    """Reject metadata-only and empty policy payloads before model defaults apply."""

    if model_class is ProductGovernancePolicy:
        if not isinstance(payload.get("product"), Mapping):
            return "product governance policy requires a product block"
        if not isinstance(payload.get("authority"), Mapping):
            return "product governance policy requires an authority block"
        return None
    if model_class is AuthorityMatrixPolicy:
        capabilities = payload.get("capabilities")
        stages = payload.get("authority_stages")
        if not isinstance(capabilities, (list, tuple)) or not capabilities:
            return "authority matrix policy requires a non-empty capabilities collection"
        if not isinstance(stages, (list, tuple)) or not stages:
            return "authority matrix policy requires a non-empty authority_stages collection"
        return None
    collection_key = "gates" if model_class is GatePolicy else "entries"
    entries = payload.get(collection_key)
    if not isinstance(entries, (list, tuple)) or not entries:
        return f"{model_class.__name__} policy requires a non-empty {collection_key} collection"
    return None


def _contract_error(model_class: type[PolicyClassT], payload: Mapping[str, Any], policy: PolicyClassT) -> str | None:
    """Validate required Group A metadata after strict Pydantic parsing."""

    if model_class is ProductGovernancePolicy:
        product = payload.get("product")
        authority = payload.get("authority")
        required_product = {"canonical_name", "category", "intended_user", "default_horizon", "decision_owner"}
        required_authority = {
            "maximum_operational_authority",
            "broker_execution",
            "execution_allowed",
            "executable_authority",
            "order_transmission",
            "external_upload",
            "credential_access",
            "autonomous_portfolio_management",
            "unvalidated_ai_score_authority",
        }
        if not isinstance(product, Mapping) or not required_product <= set(product):
            return "product governance policy has an incomplete product block"
        if not isinstance(authority, Mapping) or not required_authority <= set(authority):
            return "product governance policy has an incomplete authority block"
        if not payload.get("prohibited_claims") or not payload.get("required_disclosures"):
            return "product governance policy requires prohibited_claims and required_disclosures"
        return None

    if model_class is AuthorityMatrixPolicy:
        if not policy.adr_id or not policy.adr_path:
            return "authority matrix policy requires an ADR reference"
        return None

    if model_class is FeatureRegistryPolicy:
        entries = payload.get("entries", ())
        required = {
            "feature_id",
            "name",
            "category",
            "routes",
            "data_dependencies",
            "issue_ids",
            "tests",
            "export_contracts",
            "package_gate",
            "lifecycle",
            "authority",
        }
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping) or not required <= set(entry):
                return f"feature registry entry {index} is missing required governance metadata"
            if any(not entry.get(key) for key in ("name", "category", "routes", "data_dependencies", "issue_ids", "tests", "export_contracts", "package_gate")):
                return f"feature registry entry {index} has empty required governance metadata"
        try:
            from etf_cockpit.app.router import PAGES

            expected_routes = set(PAGES)
            actual_routes = {route for item in policy.entries for route in item.canonical_routes}
            if actual_routes != expected_routes:
                return "feature registry routes must exactly match production routes"
        except (ImportError, AttributeError):
            return "feature registry route registry is unavailable"
        return None

    if model_class is StrategyScopePolicy:
        required = {
            "strategy_id",
            "name",
            "lifecycle",
            "intended_use",
            "permitted_authority",
            "execution_authority",
            "paper_authority",
            "limitations",
            "linked_issues",
            "promotion_conditions",
            "tests",
        }
        for index, entry in enumerate(payload.get("entries", ())):
            if not isinstance(entry, Mapping) or not required <= set(entry):
                return f"strategy scope entry {index} is missing required governance metadata"
            if any(not entry.get(key) for key in ("name", "intended_use", "limitations", "linked_issues", "promotion_conditions", "tests")):
                return f"strategy scope entry {index} has empty required governance metadata"
        strategy_ids = {entry.strategy_id for entry in policy.entries}
        required_inventory = {
            "baseline_simple_scores",
            "timesfm_challenger",
            "toto_challenger",
            "future_ml_challenger",
            "llm_assistance",
            "provider_news_context",
            "paper_portfolio",
            "pair_trading",
            "triple_barrier_research",
            "future_broker_architecture",
            "martingale",
            "grid",
            "rl_agents",
            "llm_only_management",
            "model_only_trading",
            "return_screenshots",
            "unvalidated_sentiment",
        }
        if not required_inventory <= strategy_ids:
            return "strategy scope inventory is missing required baseline, challenger, paper or rejected entries"
        return None

    if model_class is GatePolicy:
        identifiers = tuple(gate.gate_id for gate in policy.gates)
        orders = tuple(gate.order for gate in policy.gates)
        if identifiers != REQUIRED_GATE_IDS or orders != tuple(range(1, len(REQUIRED_GATE_IDS) + 1)):
            return "gate policy must contain the complete ordered gate set"
        if any(gate.research_promotion_allowed or gate.portfolio_review_allowed for gate in policy.gates):
            return "gate policy cannot grant promotion or portfolio review authority"
        return None

    if model_class is GlossaryPolicy:
        terms = {entry.term.casefold() for entry in policy.entries}
        missing = REQUIRED_GLOSSARY_TERMS - terms
        if missing:
            return f"glossary is missing required terms: {', '.join(sorted(missing))}"
    return None


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
    if model_class is ProductGovernancePolicy and positive_authority:
        authority_payload = payload.get("authority")
        if isinstance(authority_payload, Mapping):
            # Validate the authority block independently so a forbidden true
            # value cannot be hidden by unrelated missing product metadata.
            AuthorityPolicy.model_validate(authority_payload)
    if "schema_version" not in loaded and not positive_authority:
        return _diagnostic(
            schema_version=schema_version,
            checksum=checksum,
            message=f"{policy_name} policy is missing required metadata",
        )  # type: ignore[return-value]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return _diagnostic(
            schema_version=schema_version,
            checksum=checksum,
            message=f"{policy_name} policy uses unsupported schema version {schema_version}",
        )  # type: ignore[return-value]
    if not has_headers and not positive_authority:
        return _diagnostic(
            schema_version=schema_version,
            checksum=checksum,
            message=f"{policy_name} policy is missing required metadata",
        )  # type: ignore[return-value]
    section_error = _substantive_section_error(model_class, payload)
    if section_error and not positive_authority:
        return _diagnostic(schema_version=schema_version, checksum=checksum, message=section_error)  # type: ignore[return-value]

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

    contract_error = _contract_error(model_class, payload, policy)
    if contract_error:
        return _diagnostic(schema_version=schema_version, checksum=checksum, message=contract_error)  # type: ignore[return-value]

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


def load_authority_matrix(path: Path | None = None) -> GovernanceLoadResult[AuthorityMatrixPolicy]:
    """Load the finite authority/capability contract, fail-closed."""

    result = _load_policy(Path(path or AUTHORITY_MATRIX_PATH), AuthorityMatrixPolicy, policy_name="authority matrix")
    if result.policy is not None:
        errors = authority_matrix_coverage_errors(result.policy)
        if errors:
            return _diagnostic(schema_version=result.schema_version, checksum=result.checksum, message="authority matrix coverage failed: " + "; ".join(errors))  # type: ignore[return-value]
    return result


def authority_matrix_coverage_errors(policy: AuthorityMatrixPolicy | None = None) -> tuple[str, ...]:
    """Return deterministic omissions between runtime inventories and the matrix."""

    matrix = policy
    if matrix is None:
        loaded = _load_policy(AUTHORITY_MATRIX_PATH, AuthorityMatrixPolicy, policy_name="authority matrix")
        matrix = loaded.policy
    if matrix is None:
        return ("authority matrix is unavailable",)
    expected: set[str] = set()
    try:
        from etf_cockpit.app.router import PAGES

        expected.update(f"route:{route}" for route in PAGES)
        feature_payload = yaml.safe_load(FEATURE_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
        expected.update(
            f"dataset:{dependency}"
            for entry in feature_payload.get("features", feature_payload.get("entries", ()))
            for dependency in entry.get("data_dependencies", entry.get("required_data", ()))
        )
        model_payload = yaml.safe_load((CONFIG_DIR / "model_settings.yaml").read_text(encoding="utf-8")) or {}
        expected.update(f"model:{model_id}" for model_id in model_payload.get("models", {}))
        strategy_payload = yaml.safe_load(STRATEGY_SCOPE_PATH.read_text(encoding="utf-8")) or {}
        expected.update(
            f"strategy:{entry['strategy_id']}"
            for entry in strategy_payload.get("strategies", strategy_payload.get("entries", ()))
        )
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        return (f"runtime inventory unavailable: {exc}",)
    expected.update({"broker:paper_portfolio", "broker:future_read_only", "broker:order_transmission"})
    actual = {capability.capability_id for capability in matrix.capabilities}
    return tuple(f"missing capability: {capability_id}" for capability_id in sorted(expected - actual))


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
    "AUTHORITY_MATRIX_PATH",
    "FEATURE_REGISTRY_PATH",
    "GATE_POLICY_PATH",
    "GLOSSARY_PATH",
    "PRODUCT_GOVERNANCE_PATH",
    "PolicyPaths",
    "STRATEGY_SCOPE_PATH",
    "load_feature_registry",
    "load_authority_matrix",
    "authority_matrix_coverage_errors",
    "load_gate_policy",
    "load_glossary",
    "load_product_governance",
    "load_strategy_scope",
]
