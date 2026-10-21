"""Select the focused pytest files for a pull request that skips the package gate.

Deterministic and read-only: the selection depends only on the Git diff between two
exact SHAs and a static (``ast``) import scan of ``tests/``. It never executes tests
and never imports product code.

Selection rules (union, printed one repository-relative POSIX path per line):

* test files under ``tests/`` changed by the diff (``fixtures`` directories excluded);
* test files that import a changed ``src/etf_cockpit`` module (``import a.b.c``,
  ``from a.b import c`` and ``from a.b.c import x`` forms, plus string constants that
  name the module such as ``importlib.import_module`` or ``monkeypatch.setattr``
  targets) or a changed non-test helper module under ``tests/``; the changed set is first
  closed over the product import graph, so a test that reaches the change only through
  other ``src/etf_cockpit`` modules is selected too;
* the UI contract sweep when anything under ``src/etf_cockpit/app/`` changed.

An empty selection (documentation or configuration only) prints nothing and exits 0.
Every unavailable input (bad SHA, failed Git diff, missing sweep file) exits non-zero
with an explicit reason; the selection is never silently truncated or zero-filled.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

SHA_RE = re.compile(r"[0-9a-f]{40}")
SRC_PREFIX = "src/"
PACKAGE = "etf_cockpit"
APP_PREFIX = "src/etf_cockpit/app/"
TESTS_PREFIX = "tests/"
UI_CONTRACT_SWEEP = (
    "tests/test_issue_0012_progress.py",
    "tests/test_button_contracts.py",
    "tests/test_architecture_boundaries.py",
    "tests/test_flet_layout_contracts.py",
    "tests/test_accessibility_contracts.py",
)
LARGE_SELECTION = 150
UI_ACCEPTANCE_CONFIG = "configs/ui_acceptance.yaml"


class SelectionError(RuntimeError):
    """Raised when the selection cannot be computed; the caller must fail closed."""


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    """Return paths changed from ``base`` to ``head`` (renames reported as delete + add)."""

    for label, value in (("base", base), ("head", head)):
        if not SHA_RE.fullmatch(value):
            raise SelectionError(f"unavailable: {label} must be a full lowercase Git SHA")
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", base, head, "--"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SelectionError(f"unavailable: git diff {base[:8]}..{head[:8]} failed: {exc}") from exc
    return sorted(
        {
            item.decode("utf-8", "surrogateescape")
            for item in completed.stdout.split(b"\0")
            if item
        }
    )


def _is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    return (
        path.startswith(TESTS_PREFIX)
        and pure.suffix == ".py"
        and "fixtures" not in pure.parts
        and (pure.name.startswith("test_") or pure.name.endswith("_test.py"))
    )


def _dotted(parts: tuple[str, ...]) -> str:
    return ".".join(parts)


def changed_module_names(paths: list[str]) -> set[str]:
    """Dotted names whose importers are affected by ``paths``."""

    names: set[str] = set()
    for path in paths:
        pure = PurePosixPath(path)
        if path.startswith(SRC_PREFIX + PACKAGE + "/"):
            relative = pure.relative_to(SRC_PREFIX)
            if pure.suffix == ".py":
                parts = relative.with_suffix("").parts
                if parts[-1] == "__init__":
                    parts = parts[:-1]
            else:
                parts = relative.parent.parts  # package data: importers of the owning package
            names.add(_dotted(parts))
        elif (
            path.startswith(TESTS_PREFIX)
            and pure.suffix == ".py"
            and "fixtures" not in pure.parts
            and not _is_test_file(path)
            and pure.name != "conftest.py"
        ):
            parts = pure.relative_to(TESTS_PREFIX).with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                names.add(_dotted(("tests", *parts)))
                names.add(_dotted(parts))
    return names


def imported_names(source: str) -> set[str]:
    """Dotted names a test file imports or references as module strings."""

    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value.startswith(PACKAGE + ".") or value.startswith("tests."):
                names.add(value)
    return names


def _matches(imported: set[str], changed: set[str]) -> bool:
    return any(
        name == module or name.startswith(module + ".")
        for name in imported
        for module in changed
    )


def _all_test_files(root: Path) -> list[str]:
    tests_root = root / "tests"
    return sorted(
        path.relative_to(root).as_posix()
        for path in tests_root.rglob("*.py")
        if _is_test_file(path.relative_to(root).as_posix())
    )


def _tests_naming(root: Path, needle: str) -> set[str]:
    """Test files whose source mentions ``needle`` (unreadable files are selected, never skipped)."""

    found: set[str] = set()
    for test_path in _all_test_files(root):
        try:
            if needle in (root / test_path).read_text(encoding="utf-8"):
                found.add(test_path)
        except (OSError, UnicodeDecodeError):
            found.add(test_path)
    return found


def _module_name(relative: PurePosixPath) -> str:
    parts = relative.with_suffix("").parts
    return _dotted(parts[:-1] if parts[-1] == "__init__" else parts)


def _src_imports(source: str, module: str, is_package: bool) -> set[str]:
    """Dotted names one product module imports (relative imports resolved) or names as strings."""

    tree = ast.parse(source)
    package = module if is_package else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".") if package else []
                anchor = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(PACKAGE + "."):
            names.add(node.value)
    return names


def close_over_product_imports(root: Path, changed: set[str]) -> set[str]:
    """Add every ``src/etf_cockpit`` module that (transitively) imports a changed product module."""

    product = {name for name in changed if name == PACKAGE or name.startswith(PACKAGE + ".")}
    if not product:
        return changed
    graph: dict[str, set[str]] = {}
    package_root = root / SRC_PREFIX / PACKAGE
    for path in sorted(package_root.rglob("*.py")):
        relative = PurePosixPath(path.relative_to(root / SRC_PREFIX).as_posix())
        module = _module_name(relative)
        try:
            graph[module] = _src_imports(path.read_text(encoding="utf-8"), module, relative.name == "__init__.py")
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            raise SelectionError(f"unavailable: cannot resolve product imports of {path.relative_to(root).as_posix()}: {exc}") from exc
    affected = set(product)
    frontier = set(product)
    while frontier:
        found = {module for module, imported in graph.items() if module not in affected and _matches(imported, frontier)}
        affected |= found
        frontier = found
    return changed | affected


def select_tests(root: Path, paths: list[str]) -> list[str]:
    """Return the sorted focused test selection for the changed ``paths``."""

    selected = {path for path in paths if _is_test_file(path) and (root / path).is_file()}
    modules = close_over_product_imports(root, changed_module_names(paths))
    if modules:
        for test_path in _all_test_files(root):
            if test_path in selected:
                continue
            try:
                source = (root / test_path).read_text(encoding="utf-8")
                imported = imported_names(source)
            except (OSError, UnicodeDecodeError, SyntaxError):
                selected.add(test_path)  # unreadable test: run it so collection reports it
                continue
            if _matches(imported, modules):
                selected.add(test_path)
    if any(PurePosixPath(path).name == "conftest.py" and path.startswith(TESTS_PREFIX) for path in paths):
        selected.update(_all_test_files(root))  # shared fixtures/hooks can change every test
    if UI_ACCEPTANCE_CONFIG in paths:
        selected.update(_tests_naming(root, "ui_acceptance"))
    if any(path.startswith(APP_PREFIX) or path == UI_ACCEPTANCE_CONFIG for path in paths):
        for sweep in UI_CONTRACT_SWEEP:
            if not (root / sweep).is_file():
                raise SelectionError(f"unavailable: UI contract sweep file {sweep} is missing")
            selected.add(sweep)
    if len(selected) > LARGE_SELECTION:
        return _all_test_files(root)  # "running all" must actually expand to the whole suite
    return sorted(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        selected = select_tests(root, changed_paths(root, args.base, args.head))
    except SelectionError as exc:
        print(f"select_focused_tests: {exc}", file=sys.stderr)
        return 2
    if len(selected) > LARGE_SELECTION:
        print(
            f"select_focused_tests: {len(selected)} files selected (> {LARGE_SELECTION}); running all",
            file=sys.stderr,
        )
    for path in selected:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
