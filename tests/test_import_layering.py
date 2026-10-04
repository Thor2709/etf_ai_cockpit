"""Layered import ratchet for ADR-0002 (presentation -> application -> domain -> infrastructure).

Every runtime import inside ``src/etf_cockpit`` (module-level and function-local; ``TYPE_CHECKING``
imports are type-only and ignored) is classified by layer.  Edges that break the layering rules
below fail unless they are listed in ``KNOWN_VIOLATIONS``: the documented transitional debt that
the architecture refactor removes.  The allowlist only shrinks -- a listed edge that no longer
exists must be deleted, so a fixed boundary cannot silently regress.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = "etf_cockpit"

PRESENTATION = frozenset({"app"})
APPLICATION = frozenset({"application"})
TRANSITIONAL = frozenset({"services"})
COMPOSITION = frozenset({"", "main"})
DOMAIN = frozenset({"analysis", "audit", "backtest", "features", "models", "portfolio", "signals", "trading", "validation"})
INFRASTRUCTURE = frozenset({"chatgpt_bridge", "data", "operations", "parsers", "plugins", "security"})
SHARED = frozenset({"core", "governance", "resources"})

# Infrastructure-neutral shared modules that presentation may use directly.
PRESENTATION_SHARED_KERNEL = frozenset(
    {
        "etf_cockpit.core.constants",
        "etf_cockpit.core.errors",
        "etf_cockpit.core.paths",
        "etf_cockpit.core.runtime",
        "etf_cockpit.core.session_log",
        "etf_cockpit.core.timing",
        "etf_cockpit.core.types",
        "etf_cockpit.core.ui_acceptance",
        "etf_cockpit.core.workflow",
    }
)

FORBIDDEN_TARGET_LAYERS = {
    "shared": frozenset({"presentation", "application", "transitional", "domain", "infrastructure"}),
    "domain": frozenset({"presentation", "application", "transitional"}),
    "infrastructure": frozenset({"presentation", "application", "transitional"}),
    "application": frozenset({"presentation"}),
    "transitional": frozenset({"presentation"}),
    "presentation": frozenset({"domain", "infrastructure", "transitional", "shared"}),
}

# Transitional debt at origin/main 5e501154 (2026-10-04).  Remove entries as the refactor fixes them.
KNOWN_VIOLATIONS = frozenset(
    {
        ("etf_cockpit.app.operations", "etf_cockpit.core.atomic_io"),
        ("etf_cockpit.app.operations", "etf_cockpit.data.event_calendar"),
        ("etf_cockpit.app.operations", "etf_cockpit.portfolio.event_controls"),
        ("etf_cockpit.app.pages.chatgpt_audit", "etf_cockpit.audit.local_llm"),
        ("etf_cockpit.app.pages.chatgpt_audit", "etf_cockpit.audit.thesis_diary"),
        ("etf_cockpit.app.pages.chatgpt_audit", "etf_cockpit.governance.product_scope"),
        ("etf_cockpit.app.pages.chatgpt_audit", "etf_cockpit.services"),
        ("etf_cockpit.app.pages.data_models", "etf_cockpit.plugins.builtins"),
        ("etf_cockpit.app.pages.diagnostics", "etf_cockpit.core.performance"),
        ("etf_cockpit.app.pages.diagnostics", "etf_cockpit.operations.event_store"),
        ("etf_cockpit.app.pages.diagnostics", "etf_cockpit.security.policy"),
        ("etf_cockpit.app.pages.feature_catalogue", "etf_cockpit.features.feature_store"),
        ("etf_cockpit.app.pages.forecast_lab", "etf_cockpit.features.forecast_lab"),
        ("etf_cockpit.app.pages.help_glossary", "etf_cockpit.governance.product_scope"),
        ("etf_cockpit.app.pages.onboarding", "etf_cockpit.core.atomic_io"),
        ("etf_cockpit.app.pages.onboarding", "etf_cockpit.core.config"),
        ("etf_cockpit.app.pages.settings", "etf_cockpit.core.config"),
        ("etf_cockpit.app.pages.settings", "etf_cockpit.core.secure_update"),
        ("etf_cockpit.app.pages.settings", "etf_cockpit.governance.product_scope"),
        ("etf_cockpit.app.pages.settings", "etf_cockpit.security.credentials"),
        ("etf_cockpit.app.pages.system_map", "etf_cockpit.governance.product_scope"),
        ("etf_cockpit.app.pages.training_centre", "etf_cockpit.core.job_scheduler"),
        ("etf_cockpit.app.pages.training_centre", "etf_cockpit.features.synthetic_scenarios"),
        ("etf_cockpit.app.pages.trust_evidence", "etf_cockpit.core.atomic_io"),
        ("etf_cockpit.app.pages.trust_evidence", "etf_cockpit.parsers.index_methodology"),
        ("etf_cockpit.app.pages.trust_evidence", "etf_cockpit.parsers.priips_kid"),
        ("etf_cockpit.app.pages.trust_evidence", "etf_cockpit.parsers.sfdr"),
        ("etf_cockpit.app.pages.trust_evidence", "etf_cockpit.plugins.builtins"),
        ("etf_cockpit.app.pages.universe_manager", "etf_cockpit.core.config"),
        ("etf_cockpit.app.selectors.instrument_detail", "etf_cockpit.analysis.candles"),
        ("etf_cockpit.app.selectors.instrument_detail", "etf_cockpit.audit.thesis_diary"),
        ("etf_cockpit.app.selectors.instrument_detail", "etf_cockpit.features.etf_economics"),
        ("etf_cockpit.app.selectors.instrument_detail", "etf_cockpit.services"),
        ("etf_cockpit.app.state", "etf_cockpit.core.atomic_io"),
        ("etf_cockpit.app.state", "etf_cockpit.core.config"),
        ("etf_cockpit.app.state", "etf_cockpit.core.job_scheduler"),
        ("etf_cockpit.app.state", "etf_cockpit.core.migrations"),
        ("etf_cockpit.app.state", "etf_cockpit.data.classification"),
        ("etf_cockpit.app.state", "etf_cockpit.data.esef_provider"),
        ("etf_cockpit.app.state", "etf_cockpit.data.instrument_identity"),
        ("etf_cockpit.app.state", "etf_cockpit.data.oam_adapters"),
        ("etf_cockpit.app.state", "etf_cockpit.data.sec_edgar_bulk"),
        ("etf_cockpit.app.state", "etf_cockpit.data.sec_edgar_provider"),
        ("etf_cockpit.app.state", "etf_cockpit.data.trust_artifacts"),
        ("etf_cockpit.app.state", "etf_cockpit.features.regime"),
        ("etf_cockpit.app.state", "etf_cockpit.models.calibration"),
        ("etf_cockpit.app.state", "etf_cockpit.models.forecast_scores"),
        ("etf_cockpit.app.state", "etf_cockpit.operations.event_store"),
        ("etf_cockpit.app.state", "etf_cockpit.parsers.contracts"),
        ("etf_cockpit.app.state", "etf_cockpit.parsers.esef_ixbrl"),
        ("etf_cockpit.app.state", "etf_cockpit.parsers.sec_facts"),
        ("etf_cockpit.app.state", "etf_cockpit.portfolio.review_reports"),
        ("etf_cockpit.app.state", "etf_cockpit.services"),
        ("etf_cockpit.app.state", "etf_cockpit.signals.simple_scores"),
        ("etf_cockpit.application.api", "etf_cockpit.app.operations"),
        ("etf_cockpit.application.ui_facade", "etf_cockpit.app.selectors.instrument_detail"),
        ("etf_cockpit.audit.local_llm", "etf_cockpit.services"),
        ("etf_cockpit.chatgpt_bridge.export_pack", "etf_cockpit.application.architecture"),
        ("etf_cockpit.chatgpt_bridge.export_pack", "etf_cockpit.application.settings"),
        ("etf_cockpit.core.config", "etf_cockpit.data.universe_store"),
        ("etf_cockpit.core.config", "etf_cockpit.security.credentials"),
        ("etf_cockpit.core.job_scheduler", "etf_cockpit.data.local_storage"),
        ("etf_cockpit.core.migrations", "etf_cockpit.operations.recovery"),
        ("etf_cockpit.core.session_log", "etf_cockpit.operations.event_store"),
        ("etf_cockpit.core.types", "etf_cockpit.signals.canonical_scoring"),
        ("etf_cockpit.core.types", "etf_cockpit.signals.research_states"),
        ("etf_cockpit.core.ui_acceptance", "etf_cockpit.app.command_palette"),
        ("etf_cockpit.core.ui_acceptance", "etf_cockpit.app.router"),
        ("etf_cockpit.core.versioning", "etf_cockpit.application.settings"),
        ("etf_cockpit.data.backup_restore", "etf_cockpit.application.settings"),
        ("etf_cockpit.data.sec_edgar_provider", "etf_cockpit.application.sec_bulk_import"),
        ("etf_cockpit.data.sec_edgar_provider", "etf_cockpit.application.sec_submissions_import"),
        ("etf_cockpit.governance.gate_policy", "etf_cockpit.signals.research_states"),
        ("etf_cockpit.governance.migrations", "etf_cockpit.signals.research_states"),
        ("etf_cockpit.governance.models", "etf_cockpit.signals.research_states"),
        ("etf_cockpit.governance.product_scope", "etf_cockpit.app.router"),
        ("etf_cockpit.portfolio.event_controls", "etf_cockpit.application.contracts"),
    }
)


def _layer(module: str) -> str:
    parts = module.split(".")
    top = parts[1] if len(parts) > 1 else ""
    if top in COMPOSITION:
        return "composition"
    for name, members in (
        ("presentation", PRESENTATION),
        ("application", APPLICATION),
        ("transitional", TRANSITIONAL),
        ("domain", DOMAIN),
        ("infrastructure", INFRASTRUCTURE),
        ("shared", SHARED),
    ):
        if top in members:
            return name
    raise AssertionError(f"unclassified etf_cockpit subpackage {top!r} ({module}); add it to a layer")


@lru_cache(maxsize=1)
def _modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted((SRC / PACKAGE).rglob("*.py")):
        relative = path.relative_to(SRC).with_suffix("")
        parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
        modules[".".join(parts)] = path
    return modules


def _resolve(target: str) -> str | None:
    modules = _modules()
    while target and target not in modules:
        if "." not in target:
            return None
        target = target.rsplit(".", 1)[0]
    return target or None


def _type_checking_nodes(tree: ast.AST) -> set[int]:
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.id if isinstance(test, ast.Name) else test.attr if isinstance(test, ast.Attribute) else ""
            if name == "TYPE_CHECKING":
                for child in node.body:
                    guarded.update(id(item) for item in ast.walk(child))
    return guarded


def _imports(module: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guarded = _type_checking_nodes(tree)
    is_package = path.name == "__init__.py"
    targets: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".") if is_package else module.split(".")[:-1]
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join([*base, node.module] if node.module else base)
            else:
                prefix = node.module or ""
            candidates = [f"{prefix}.{alias.name}" for alias in node.names] or [prefix]
        else:
            continue
        for candidate in candidates:
            if candidate == PACKAGE or candidate.startswith(PACKAGE + "."):
                resolved = _resolve(candidate)
                if resolved and resolved != module:
                    targets.add(resolved)
    return targets


def layering_violations() -> set[tuple[str, str]]:
    violations: set[tuple[str, str]] = set()
    for module, path in _modules().items():
        source_layer = _layer(module)
        forbidden = FORBIDDEN_TARGET_LAYERS.get(source_layer, frozenset())
        for target in _imports(module, path):
            target_layer = _layer(target)
            if target_layer not in forbidden:
                continue
            if source_layer == "presentation" and target in PRESENTATION_SHARED_KERNEL:
                continue
            violations.add((module, target))
    return violations


def test_no_new_layering_violations() -> None:
    new = sorted(layering_violations() - KNOWN_VIOLATIONS)
    assert not new, "new layer-boundary violations (ADR-0002); route them through the proper layer:\n" + "\n".join(
        f"  {source} -> {target}" for source, target in new
    )


def test_layering_allowlist_only_shrinks() -> None:
    fixed = sorted(KNOWN_VIOLATIONS - layering_violations())
    assert not fixed, "these allowlisted violations no longer exist; delete them from KNOWN_VIOLATIONS:\n" + "\n".join(
        f"  {source} -> {target}" for source, target in fixed
    )


def test_every_subpackage_is_classified() -> None:
    for module in _modules():
        _layer(module)
