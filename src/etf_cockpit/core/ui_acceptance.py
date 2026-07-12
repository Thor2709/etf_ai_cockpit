from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from etf_cockpit.core.paths import CONFIG_DIR


@dataclass(frozen=True)
class UIAcceptance:
    key: str
    route: str
    control_label: str
    callback: str
    success_signal: str
    controlled_error_signal: str
    acceptance_test: str = ""
    control_type: str = "button"


def load_ui_acceptance_contracts(path: Path | None = None) -> tuple[UIAcceptance, ...]:
    source = path or (CONFIG_DIR / "ui_acceptance.yaml")
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    rows = payload.get("controls")
    if not isinstance(rows, list):
        raise ValueError("ui acceptance controls must be a list")
    contracts: list[UIAcceptance] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ui acceptance record must be a mapping")
        values = {str(key): value for key, value in row.items()}
        contract = UIAcceptance(
            key=_required(values, "key"),
            route=_required(values, "route"),
            control_label=_required(values, "control_label"),
            callback=_required(values, "callback"),
            success_signal=_required(values, "success_signal"),
            controlled_error_signal=_required(values, "controlled_error_signal"),
            acceptance_test=str(values.get("acceptance_test") or "").strip(),
            control_type=str(values.get("control_type") or "button").strip().lower(),
        )
        contracts.append(contract)
    if len({item.key for item in contracts}) != len(contracts):
        raise ValueError("UI acceptance keys must be unique")
    for item in contracts:
        if not item.acceptance_test:
            raise ValueError(f"missing UI acceptance field: acceptance_test ({item.key})")
        if item.control_type not in {"navigation", "button", "file_picker", "expandable", "input"}:
            raise ValueError(f"unsupported UI acceptance control type: {item.control_type}")
    return tuple(contracts)


def declared_keys(contracts: Iterable[UIAcceptance] | None = None) -> set[str]:
    return {item.key for item in contracts or load_ui_acceptance_contracts()}


def validate_ui_acceptance_inventory(
    contracts: Iterable[UIAcceptance],
    registered_routes: Iterable[str],
    *,
    source_root: Path | None = None,
) -> None:
    """Fail closed when a route or source-observable control is omitted."""
    rows = tuple(contracts)
    routes = {str(route) for route in registered_routes}
    declared_routes = {item.route for item in rows}
    missing_routes = sorted(routes - declared_routes)
    if missing_routes:
        raise ValueError(f"UI acceptance inventory missing routes: {', '.join(missing_routes)}")
    if not rows:
        raise ValueError("UI acceptance inventory is empty")
    for item in rows:
        if not item.key or not item.callback or not item.success_signal or not item.controlled_error_signal or not item.acceptance_test:
            raise ValueError(f"UI acceptance inventory incomplete: {item.key or '<unknown>'}")
    if source_root is not None:
        source_controls = discover_actionable_control_keys(source_root)
        missing_keys = sorted(source_controls.get("<missing>", ()))
        if missing_keys:
            raise ValueError("source controls missing stable keys: " + ", ".join(missing_keys))
        declared = {item.key for item in rows}
        uncovered = sorted(
            key
            for key in source_controls
            if key != "<missing>" and not _key_is_declared(key, declared)
        )
        if uncovered:
            raise ValueError("source controls missing acceptance contracts: " + ", ".join(uncovered))


def discover_actionable_control_keys(source_root: Path) -> dict[str, tuple[str, ...]]:
    """Discover keyed actionable Flet controls from the application source.

    This intentionally inspects only controls that can change state or open a
    picker: callbacks, file pickers, and the two small helpers that construct
    those controls. Dynamic f-strings are represented by a trailing ``.*`` so
    they can match the corresponding wildcard contract.
    """
    found: dict[str, list[str]] = {}
    missing: list[str] = []
    for path in sorted(Path(source_root).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = _call_name(node.func)
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            if function_name == "_workflow_button":
                expression = keywords.get("key_name")
            elif function_name == "_attach_picker":
                expression = node.args[1] if len(node.args) > 1 else None
            elif "on_click" in keywords:
                expression = keywords.get("key")
            elif function_name == "FilePicker":
                expression = keywords.get("key")
            else:
                continue
            key = _key_pattern(expression)
            location = f"{path.as_posix()}:{node.lineno}"
            if key is None:
                if isinstance(expression, ast.Name) and expression.id in {"key", "key_name"}:
                    # The helper's parameter is supplied by each keyed call
                    # site; those call sites are scanned independently below.
                    continue
                missing.append(location)
            else:
                found.setdefault(key, []).append(location)
    if missing:
        found["<missing>"] = missing
    return {key: tuple(locations) for key, locations in found.items()}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _key_pattern(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("*")
        return "".join(parts)
    return None


def _key_is_declared(key: str, declared: set[str]) -> bool:
    if key in declared:
        return True
    if key.endswith(".*"):
        return any(item.startswith(key[:-1]) for item in declared)
    return any(item.endswith(".*") and key.startswith(item[:-1]) for item in declared)


def _required(values: dict[str, object], key: str) -> str:
    value = str(values.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing UI acceptance field: {key}")
    return value
