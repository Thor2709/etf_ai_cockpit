"""Runtime import-boundary checks used by Diagnostics, CI and the audit export (governance)."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib.util import resolve_name
from pathlib import Path
import re

from etf_cockpit.core.session_log import redact_text


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


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DIAGNOSTIC_MAX_CHARS = 200


def _safe_text(value: object) -> str:
    """Redact secret-shaped values and control characters before text enters a diagnostic."""

    text = _CONTROL_RE.sub("?", redact_text(str(value)))
    return text[:_DIAGNOSTIC_MAX_CHARS]


def _imports(path: Path) -> list[tuple[int, str, str]]:
    return list(_imports_of_source(path.read_text(encoding="utf-8"), str(path)))


@lru_cache(maxsize=512)
def _imports_of_source(source: str, filename: str) -> tuple[tuple[int, str, str], ...]:
    """Parse once per distinct source text (Diagnostics rebuilds this report on every visit)."""

    tree = ast.parse(source, filename=filename)
    result: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name, alias.asname or alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                imported_module = module
                if node.level and not node.module:
                    imported_module += alias.name
                result.append((node.lineno, imported_module, alias.name))
    return tuple(result)


def _presentation_files(root: Path) -> tuple[Path, ...]:
    """Every Python module below the presentation directories, including nested packages."""

    files: list[Path] = []
    for relative_dir in PRESENTATION_DIRS:
        directory = root / relative_dir
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*.py") if path.is_file())
    return tuple(sorted(files))


def _scan(root: Path) -> tuple[tuple[BoundaryViolation, ...], tuple[str, ...], int]:
    """Return (violations, scan errors, scanned file count); errors and an empty scan fail closed."""

    violations: list[BoundaryViolation] = []
    errors: list[str] = []
    files = _presentation_files(root)
    if not files:
        errors.append("no presentation modules found under the configured presentation directories")
    for path in files:
        relative = path.relative_to(root)
        try:
            imports = _imports(path)
        except (SyntaxError, ValueError, UnicodeError, OSError) as exc:
            errors.append(f"{_safe_text(relative)}: could not be analysed ({type(exc).__name__})")
            continue
        for line, module, imported_name in imports:
            if module.startswith("."):
                package_parts = path.relative_to(root).with_suffix("").parts[:-1]
                try:
                    package_start = package_parts.index("etf_cockpit")
                    package = ".".join(package_parts[package_start:])
                    module = resolve_name(module, package)
                except (ValueError, ImportError) as exc:
                    errors.append(
                        f"{_safe_text(relative)}:{line}: could not resolve relative import ({type(exc).__name__})"
                    )
                    continue
            if module == "etf_cockpit" and imported_name != "*":
                module = f"{module}.{imported_name}"
            if module in ALLOWED_IMPLEMENTATION_MODULES:
                continue
            if any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES):
                violations.append(
                    BoundaryViolation(_safe_text(relative), line, _safe_text(module), _safe_text(imported_name))
                )
    return tuple(violations), tuple(errors), len(files)


def find_violations(root: Path) -> tuple[BoundaryViolation, ...]:
    return _scan(root)[0]


def build_report(root: Path) -> dict[str, object]:
    violations, errors, scanned = _scan(root)
    return {
        "schema_version": "1.0",
        "boundary": "presentation-to-application",
        "presentation_directories": [str(directory) for directory in PRESENTATION_DIRS],
        "allowed_implementation_modules": sorted(ALLOWED_IMPLEMENTATION_MODULES),
        "violation_count": len(violations),
        "violations": [asdict(item) for item in violations],
        "scanned_file_count": scanned,
        "errors": list(errors),
        "status": "passed" if not violations and not errors else "failed",
    }
