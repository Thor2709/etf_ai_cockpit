"""Runtime import-boundary checks used by Diagnostics and CI."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path


PRESENTATION_DIRS = (Path("src/etf_cockpit/app/pages"), Path("src/etf_cockpit/app/components"), Path("src/etf_cockpit/app/selectors"))
ALLOWED_IMPLEMENTATION_MODULES = {
    "etf_cockpit.application.ui_facade",
    "etf_cockpit.app.state",
}
FORBIDDEN_PREFIXES = (
    "etf_cockpit.data",
    "etf_cockpit.models",
    "etf_cockpit.portfolio",
    "etf_cockpit.backtest",
    "etf_cockpit.signals",
    "etf_cockpit.chatgpt_bridge",
)


@dataclass(frozen=True)
class BoundaryViolation:
    file: str
    line: int
    module: str
    imported_name: str


def _imports(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name, alias.asname or alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.extend((node.lineno, node.module, alias.name) for alias in node.names)
    return result


def find_violations(root: Path) -> tuple[BoundaryViolation, ...]:
    violations: list[BoundaryViolation] = []
    for relative_dir in PRESENTATION_DIRS:
        directory = root / relative_dir
        for path in sorted(directory.glob("*.py")):
            for line, module, imported_name in _imports(path):
                if module in ALLOWED_IMPLEMENTATION_MODULES:
                    continue
                if module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(BoundaryViolation(str(path.relative_to(root)), line, module, imported_name))
    return tuple(violations)


def build_report(root: Path) -> dict[str, object]:
    violations = find_violations(root)
    return {
        "schema_version": "1.0",
        "boundary": "presentation-to-application",
        "presentation_directories": [str(directory) for directory in PRESENTATION_DIRS],
        "allowed_implementation_modules": sorted(ALLOWED_IMPLEMENTATION_MODULES),
        "violation_count": len(violations),
        "violations": [asdict(item) for item in violations],
        "status": "passed" if not violations else "failed",
    }
