from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Iterable, Literal

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
    lane: str = ""

    @property
    def action_id(self) -> str:
        return f"control:{self.key}"

    @property
    def command_id(self) -> str:
        return f"control-command:{self.key}"

    @property
    def resolved_lane(self) -> str:
        return self.lane or _lane_for(self.key, self.route)


UI_LANES: tuple[str, ...] = (
    "research",
    "training",
    "paper",
    "broker_read_only",
    "recovery",
    "live_stage",
)


@dataclass(frozen=True)
class UIAction:
    """One deterministic, source-observable action in the main UI inventory."""

    action_id: str
    key: str
    route: str
    control_label: str
    control_type: str
    callback: str
    command_id: str
    success_signal: str
    controlled_error_signal: str
    lane: str
    source: Literal["control", "route", "command"]
    execution_allowed: Literal[False] = False

    @property
    def failure_state(self) -> str:
        """The visible, controlled failure signal used by source/package tests."""

        return self.controlled_error_signal


@dataclass(frozen=True)
class UICommandContract:
    command_id: str
    action_id: str
    route: str
    callback: str
    success_signal: str
    controlled_error_signal: str
    idempotency_key: str
    execution_allowed: Literal[False] = False


_STABLE_KEY = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9*]+)+$")


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
            lane=str(values.get("lane") or "").strip().lower(),
        )
        contracts.append(contract)
    if len({item.key for item in contracts}) != len(contracts):
        raise ValueError("UI acceptance keys must be unique")
    for item in contracts:
        if not item.acceptance_test:
            raise ValueError(f"missing UI acceptance field: acceptance_test ({item.key})")
        if item.control_type not in {"navigation", "button", "file_picker", "expandable", "input", "evidence"}:
            raise ValueError(f"unsupported UI acceptance control type: {item.control_type}")
        if item.lane and item.lane not in UI_LANES:
            raise ValueError(f"unsupported UI acceptance lane: {item.lane}")
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


def build_main_ui_action_inventory(
    contracts: Iterable[UIAcceptance] | None = None,
) -> tuple[UIAction, ...]:
    """Generate the complete main-UI inventory from route/command/control metadata.

    Imports are deliberately local: the acceptance layer can validate temporary
    metadata in isolation without importing the Flet application shell.
    """

    from etf_cockpit.app.command_palette import all_commands
    from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS

    controls = tuple(contracts or load_ui_acceptance_contracts())
    return generate_ui_action_inventory(
        controls,
        PAGES,
        all_commands(PAGES, WORKSPACE_GROUPS),
    )


def generate_ui_action_inventory(
    contracts: Iterable[UIAcceptance],
    registered_routes: Mapping[str, object] | Iterable[str],
    command_metadata: Iterable[object] = (),
) -> tuple[UIAction, ...]:
    """Return a stable inventory for route, command-palette and control actions.

    The inputs are metadata only. No callbacks are invoked, no files are
    written and no clock/random source is consulted, so repeated generation is
    byte-for-byte equivalent after serialisation.
    """

    rows = tuple(contracts)
    routes = tuple(registered_routes.keys()) if isinstance(registered_routes, Mapping) else tuple(registered_routes)
    missing_control_routes = sorted({item.route for item in rows} - {str(route) for route in routes})
    if missing_control_routes:
        raise ValueError("UI controls reference unregistered routes: " + ", ".join(missing_control_routes))
    actions: list[UIAction] = []
    for item in rows:
        actions.append(
            UIAction(
                action_id=item.action_id,
                key=item.key,
                route=item.route,
                control_label=item.control_label,
                control_type=item.control_type,
                callback=item.callback,
                command_id=item.command_id,
                success_signal=item.success_signal,
                controlled_error_signal=item.controlled_error_signal,
                lane=item.resolved_lane,
                source="control",
            )
        )

    page_titles = {
        str(route): str(value[0])
        for route, value in registered_routes.items()
    } if isinstance(registered_routes, Mapping) else {str(route): str(route) for route in routes}
    for route in routes:
        route = str(route)
        actions.append(
            UIAction(
                action_id=f"route:{route}",
                key=f"route:{route}",
                route=route,
                control_label=page_titles[route],
                control_type="route",
                callback="navigate_to",
                command_id=f"route-command:{route}",
                success_signal=f"route={route}",
                controlled_error_signal="route_render_error_visible",
                lane=_lane_for("", route),
                source="route",
            )
        )

    for command in command_metadata:
        route = str(getattr(command, "route", "")).strip()
        if not route:
            raise ValueError("UI command metadata requires a route")
        title = str(getattr(command, "title", route)).strip() or route
        command_id = str(getattr(command, "command_id", f"palette-command:{route}")).strip()
        callback = str(getattr(command, "callback", "navigate_to")).strip()
        success_signal = str(getattr(command, "success_signal", "route_changed")).strip()
        controlled_error_signal = str(getattr(command, "controlled_error_signal", "no_matching_workspace")).strip()
        actions.append(
            UIAction(
                action_id=f"command:{command_id}",
                key=f"shell.command.{_route_slug(route)}",
                route=route,
                control_label=title,
                control_type="command",
                callback=callback,
                command_id=command_id,
                success_signal=success_signal,
                controlled_error_signal=controlled_error_signal,
                lane=_lane_for("", route),
                source="command",
            )
        )

    inventory = tuple(sorted(actions, key=lambda item: item.action_id))
    validate_generated_ui_action_inventory(inventory, routes)
    return inventory


def validate_generated_ui_action_inventory(
    inventory: Iterable[UIAction],
    registered_routes: Iterable[str] = (),
    *,
    required_lanes: Iterable[str] = UI_LANES,
) -> None:
    """Fail closed on unstable IDs, unbound commands or silent failures."""

    rows = tuple(inventory)
    if not rows:
        raise ValueError("generated UI action inventory is empty")
    action_ids = [item.action_id for item in rows]
    command_ids = [item.command_id for item in rows]
    if len(set(action_ids)) != len(action_ids):
        raise ValueError("generated UI action IDs must be unique")
    if len(set(command_ids)) != len(command_ids):
        raise ValueError("generated UI command IDs must be unique")
    for item in rows:
        if item.source == "control" and not _STABLE_KEY.fullmatch(item.key):
            raise ValueError(f"unstable UI control ID: {item.key}")
        if not item.route or not item.callback or not item.command_id:
            raise ValueError(f"UI action command is not bound: {item.action_id}")
        if not item.success_signal or not item.controlled_error_signal:
            raise ValueError(f"UI action lacks visible failure coverage: {item.action_id}")
        if item.execution_allowed is not False:
            raise ValueError(f"UI action cannot grant execution: {item.action_id}")
    expected_routes = {str(route) for route in registered_routes}
    generated_routes = {item.route for item in rows if item.source == "route"}
    if expected_routes - generated_routes:
        missing = ", ".join(sorted(expected_routes - generated_routes))
        raise ValueError(f"generated UI inventory missing routes: {missing}")
    unregistered_action_routes = sorted({item.route for item in rows} - expected_routes)
    if unregistered_action_routes:
        raise ValueError("generated UI inventory references unregistered routes: " + ", ".join(unregistered_action_routes))
    missing_lanes = sorted(set(required_lanes) - {item.lane for item in rows})
    if missing_lanes:
        raise ValueError("generated UI inventory missing lanes: " + ", ".join(missing_lanes))


def ui_command_contracts(inventory: Iterable[UIAction]) -> tuple[UICommandContract, ...]:
    """Project generated actions into contracts suitable for callback tests."""

    return tuple(
        UICommandContract(
            command_id=item.command_id,
            action_id=item.action_id,
            route=item.route,
            callback=item.callback,
            success_signal=item.success_signal,
            controlled_error_signal=item.controlled_error_signal,
            idempotency_key=f"ui:{item.action_id}",
        )
        for item in sorted(inventory, key=lambda row: row.command_id)
    )


def serialise_ui_action_inventory(inventory: Iterable[UIAction]) -> str:
    """Return canonical JSON for packaged/source evidence without filesystem I/O."""

    return json.dumps(
        [asdict(item) for item in sorted(inventory, key=lambda row: row.action_id)],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


serialize_ui_action_inventory = serialise_ui_action_inventory


def _route_slug(route: str) -> str:
    return route.strip("/").replace("/", "-") or "home"


def _lane_for(key: str, route: str) -> str:
    value = f"{key} {route}".casefold()
    if "training" in value:
        return "training"
    if key in {"operations.environment", "operations.preview", "operations.confirm", "operations.cancel"}:
        return "live_stage"
    if "paper" in value or "forward-evidence" in value or route == "/operations":
        return "paper"
    if "broker" in value or route == "/providers":
        return "broker_read_only"
    if any(token in value for token in ("recover", "restore", "backup", "retry", "/errors", "/jobs")):
        return "recovery"
    if "live" in value:
        return "live_stage"
    return "research"


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
