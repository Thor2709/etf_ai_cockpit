"""Layered import ratchet for ADR-0002 (presentation -> application -> domain -> infrastructure).

Every runtime import inside ``src/etf_cockpit`` (module-level and function-local; ``TYPE_CHECKING``
imports are type-only and ignored) is classified by layer.  Edges that break the layering rules
below fail unless they are listed in ``ACCEPTED_EXCEPTIONS`` (reviewed by-design seams, each with a
reason) or ``KNOWN_VIOLATIONS`` (remaining compatibility debt).  Both only shrink -- a listed edge
that no longer exists must be deleted, so a fixed boundary cannot silently regress.  Production code
may not import the compatibility modules in ``COMPAT_ONLY_MODULES``.
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
        "etf_cockpit.core.navigation",
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
    "application": frozenset({"presentation", "transitional"}),
    "transitional": frozenset({"presentation"}),
    "presentation": frozenset({"domain", "infrastructure", "transitional", "shared"}),
}

# By-design exceptions (reviewed 2026-10-04): shared/infrastructure modules that own a persistence or session seam.
# Each needs a reason; the set only shrinks.
ACCEPTED_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("etf_cockpit.core.config", "etf_cockpit.data.universe_store"): "config loader overlays the persisted universe revision",
    ("etf_cockpit.core.config", "etf_cockpit.security.credentials"): "provider settings resolve vault-held credentials",
    ("etf_cockpit.core.job_scheduler", "etf_cockpit.data.local_storage"): "durable scheduler persists jobs in local storage",
    ("etf_cockpit.core.migrations", "etf_cockpit.operations.recovery"): "startup migrations run the recovery journal",
    ("etf_cockpit.core.session_log", "etf_cockpit.operations.event_store"): "session trace is written through the event store",
    ("etf_cockpit.data.sec_edgar_provider", "etf_cockpit.application.sec_bulk_import"): "provider-owned SEC session seam (lazy)",
    ("etf_cockpit.data.sec_edgar_provider", "etf_cockpit.application.sec_submissions_import"): "provider-owned SEC session seam (lazy)",
}

# Remaining transitional debt: compatibility re-exports that tests still import or patch through the old module.
# Remove entries as consumers migrate; the set only shrinks.
KNOWN_VIOLATIONS = frozenset(
    {
        ("etf_cockpit.app.pages.onboarding", "etf_cockpit.core.atomic_io"),
        ("etf_cockpit.app.pages.onboarding", "etf_cockpit.core.config"),
        ("etf_cockpit.app.state", "etf_cockpit.data.classification"),
        ("etf_cockpit.app.state", "etf_cockpit.data.esef_provider"),
        ("etf_cockpit.app.state", "etf_cockpit.data.oam_adapters"),
        ("etf_cockpit.app.state", "etf_cockpit.data.sec_edgar_provider"),
        ("etf_cockpit.app.state", "etf_cockpit.data.trust_artifacts"),
        ("etf_cockpit.app.state", "etf_cockpit.features.regime"),
        ("etf_cockpit.app.state", "etf_cockpit.models.calibration"),
        ("etf_cockpit.app.state", "etf_cockpit.parsers.esef_ixbrl"),
        ("etf_cockpit.app.state", "etf_cockpit.parsers.sec_facts"),
        ("etf_cockpit.app.state", "etf_cockpit.signals.simple_scores"),
    }
)

# Compatibility modules kept only for tests/scripts during the refactor: production code must import the canonical
# module instead.
COMPAT_ONLY_MODULES = frozenset(
    {
        "etf_cockpit.app.operations",
        "etf_cockpit.app.selectors.instrument_detail",
        "etf_cockpit.application.screening",
        "etf_cockpit.services",
        "etf_cockpit.signals.research_states",
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
    new = sorted(layering_violations() - KNOWN_VIOLATIONS - ACCEPTED_EXCEPTIONS.keys())
    assert not new, "new layer-boundary violations (ADR-0002); route them through the proper layer:\n" + "\n".join(
        f"  {source} -> {target}" for source, target in new
    )


def test_layering_allowlist_only_shrinks() -> None:
    fixed = sorted((KNOWN_VIOLATIONS | ACCEPTED_EXCEPTIONS.keys()) - layering_violations())
    assert not fixed, "these allowlisted violations no longer exist; delete them from KNOWN_VIOLATIONS / ACCEPTED_EXCEPTIONS:\n" + "\n".join(
        f"  {source} -> {target}" for source, target in fixed
    )


def test_every_subpackage_is_classified() -> None:
    for module in _modules():
        _layer(module)


def test_allowlists_are_disjoint_and_explained() -> None:
    assert not KNOWN_VIOLATIONS & ACCEPTED_EXCEPTIONS.keys()
    assert all(reason.strip() for reason in ACCEPTED_EXCEPTIONS.values())


def test_production_code_does_not_import_compatibility_modules() -> None:
    offenders = sorted(
        (module, target)
        for module, path in _modules().items()
        if module not in COMPAT_ONLY_MODULES
        for target in _imports(module, path)
        if target in COMPAT_ONLY_MODULES
    )
    assert not offenders, "import the canonical module instead of a compatibility re-export:\n" + "\n".join(
        f"  {source} -> {target}" for source, target in offenders
    )
