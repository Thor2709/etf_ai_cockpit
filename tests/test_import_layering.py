"""Layered import ratchet for ADR-0002 (presentation -> application -> domain -> infrastructure).

Every runtime import inside ``src/etf_cockpit`` (module-level and function-local; ``TYPE_CHECKING``
imports are type-only and ignored) is classified by layer.  Edges that break the layering rules
below fail unless they are listed in ``ACCEPTED_EXCEPTIONS`` (reviewed by-design seams, each with a
reason) or ``KNOWN_VIOLATIONS`` (remaining compatibility debt).  Both only shrink -- a listed edge
that no longer exists must be deleted, so a fixed boundary cannot silently regress.
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
        "etf_cockpit.core.values",
        "etf_cockpit.core.workflow",
    }
)

FORBIDDEN_TARGET_LAYERS = {
    "shared": frozenset({"presentation", "application", "domain", "infrastructure"}),
    "domain": frozenset({"presentation", "application"}),
    "infrastructure": frozenset({"presentation", "application"}),
    "application": frozenset({"presentation"}),
    "presentation": frozenset({"domain", "infrastructure", "shared"}),
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
        ("etf_cockpit.app.pages.onboarding", "etf_cockpit.core.config"),
        ("etf_cockpit.app.state", "etf_cockpit.signals.simple_scores"),
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
            # only the typing flag itself: `TYPE_CHECKING` or `typing.TYPE_CHECKING` (any other object attribute is runtime)
            is_flag = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                isinstance(test, ast.Attribute)
                and test.attr == "TYPE_CHECKING"
                and isinstance(test.value, ast.Name)
                and test.value.id in {"typing", "typing_extensions"}
            )
            if is_flag:
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


def test_type_checking_guard_only_matches_the_typing_flag() -> None:
    source = (
        "if TYPE_CHECKING:\n    import a\n"
        "if typing.TYPE_CHECKING:\n    import b\n"
        "if flags.TYPE_CHECKING:\n    import c\n"
    )
    tree = ast.parse(source)
    guarded = _type_checking_nodes(tree)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import) and id(node) in guarded
        for alias in node.names
    }
    assert imported == {"a", "b"}


def test_document_parser_facade_loads_only_the_requested_parser() -> None:
    import os
    import subprocess
    import sys

    code = (
        "import sys; import etf_cockpit.application.document_parsers as d; d.parse_priips_kid; "
        "print(sorted(m for m in ('etf_cockpit.parsers.sfdr', 'etf_cockpit.parsers.index_methodology') if m in sys.modules))"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert result.stdout.strip() == "[]"
