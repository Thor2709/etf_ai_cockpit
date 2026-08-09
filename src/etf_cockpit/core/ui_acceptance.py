from __future__ import annotations

import ast
import builtins
import importlib.metadata
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Callable, Iterable, Literal

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
        return self.lane or _lane_for_control(self.key, self.route, self.control_type)


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

    def invoke(
        self,
        callback: Callable[..., object],
        event: object | None = None,
        *,
        invoked: dict[str, UIInvocationResult],
        show_failure: Callable[[str], None],
    ) -> UIInvocationResult:
        """Execute one bound callback with deterministic duplicate/failure evidence."""

        actual_callback = getattr(callback, "__name__", "")
        if actual_callback != self.callback:
            raise ValueError(
                f"UI command callback mismatch: {self.command_id} "
                f"expects {self.callback}, got {actual_callback or '<anonymous>'}"
            )
        prior = invoked.get(self.idempotency_key)
        if prior is not None:
            replay = replace(prior, replayed=True)
            if replay.status == "failed":
                show_failure(replay.visible_message)
            return replay
        try:
            callback(event)
        except Exception as exc:  # the contract converts callback failure into visible UI state
            message = f"Action failed safely: {type(exc).__name__}: {exc}"
            show_failure(message)
            result = UIInvocationResult(status="failed", signal=self.controlled_error_signal, visible_message=message)
        else:
            result = UIInvocationResult(
                status="completed",
                signal=self.success_signal,
                visible_message="Action completed.",
            )
        invoked[self.idempotency_key] = result
        return result


@dataclass(frozen=True)
class UIInvocationResult:
    status: Literal["completed", "failed"]
    signal: str
    visible_message: str
    replayed: bool = False
    execution_allowed: Literal[False] = False


@dataclass(frozen=True)
class DiscoveredControl:
    key: str
    callbacks: tuple[str, ...]
    events: tuple[str, ...]
    locations: tuple[str, ...]


_STABLE_KEY = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9*]+)+$")
_ACTIONABLE_CONTROL_TYPES = frozenset({"navigation", "button", "file_picker", "expandable"})
_EVENT_BINDINGS = frozenset({"on_click", "on_select", "on_change", "on_submit"})
_ACTION_CONTROL_CALLS = frozenset({
    "Button",
    "CupertinoButton",
    "Dropdown",
    "ElevatedButton",
    "FilledButton",
    "IconButton",
    "OutlinedButton",
    "SegmentedButton",
    "TextButton",
    "TextField",
})
_LIVE_STAGE_KEYS = frozenset({
    "operations.environment",
    "operations.preview",
    "operations.confirm",
    "operations.cancel",
})
_ROUTE_LANES = {
    "/training-centre": "training",
    "/forward-evidence": "paper",
    "/operations": "live_stage",
    "/providers": "broker_read_only",
    "/errors": "recovery",
    "/jobs": "recovery",
}


def load_ui_acceptance_contracts(path: Path | None = None) -> tuple[UIAcceptance, ...]:
    source = path or _default_contract_path()
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if payload.get("version") != 3:
        raise ValueError("ui acceptance contract must use version 3")
    rows = payload.get("controls")
    if not isinstance(rows, list):
        raise ValueError("ui acceptance controls must be a list")
    contracts: list[UIAcceptance] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ui acceptance record must be a mapping")
        values = {str(key): value for key, value in row.items()}
        key = _required(values, "key")
        control_type = str(values.get("control_type") or "button").strip().lower()
        declared_lane = str(values.get("lane") or "").strip().lower()
        if declared_lane not in {"", "auto"}:
            raise ValueError(f"UI acceptance lane is authoritative and must be auto: {key}")
        if _required(values, "success_signal") != "auto" or _required(values, "controlled_error_signal") != "auto":
            raise ValueError(f"UI acceptance signals are authoritative and must be auto: {key}")
        contract = UIAcceptance(
            key=key,
            route=_required(values, "route"),
            control_label=_required(values, "control_label"),
            callback=_required(values, "callback"),
            success_signal=_signal_id("success", key),
            controlled_error_signal=_signal_id("failure", key),
            acceptance_test=str(values.get("acceptance_test") or "").strip(),
            control_type=control_type,
            lane=_lane_for_control(key, _required(values, "route"), control_type),
        )
        contracts.append(contract)
    if len({item.key for item in contracts}) != len(contracts):
        raise ValueError("UI acceptance keys must be unique")
    for item in contracts:
        if not item.acceptance_test:
            raise ValueError(f"missing UI acceptance field: acceptance_test ({item.key})")
        if item.control_type not in {"navigation", "button", "file_picker", "expandable", "input", "evidence"}:
            raise ValueError(f"unsupported UI acceptance control type: {item.control_type}")
        acceptance_path = Path(item.acceptance_test)
        source_root = source.parents[1]
        if (source_root / "tests").is_dir() and not acceptance_path.is_absolute() and not (source_root / acceptance_path).is_file():
            raise ValueError(f"UI acceptance test does not exist: {item.acceptance_test} ({item.key})")
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
        source_controls = discover_actionable_controls(source_root)
        missing_keys = sorted(source_controls.get("<missing>", DiscoveredControl("<missing>", (), (), ())).locations)
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
        unresolved_callbacks = sorted(
            key
            for key, discovered in source_controls.items()
            if key != "<missing>" and not discovered.callbacks
        )
        if unresolved_callbacks:
            raise ValueError("source actions have unresolved callbacks: " + ", ".join(unresolved_callbacks))
        configured_without_source = sorted(
            item.key
            for item in rows
            if (item.control_type in _ACTIONABLE_CONTROL_TYPES or item.control_type == "input")
            and not any(key != "<missing>" and _keys_match(item.key, key) for key in source_controls)
        )
        if configured_without_source:
            raise ValueError("UI acceptance controls missing source actions: " + ", ".join(configured_without_source))
        callback_mismatches: list[str] = []
        for item in rows:
            matches = [
                discovered
                for key, discovered in source_controls.items()
                if key != "<missing>" and _keys_match(item.key, key)
            ]
            known_callbacks = {callback for match in matches for callback in match.callbacks if callback}
            if known_callbacks and item.callback not in known_callbacks:
                callback_mismatches.append(
                    f"{item.key} configured={item.callback} source={','.join(sorted(known_callbacks))}"
                )
        if callback_mismatches:
            raise ValueError("UI acceptance callback mismatch: " + "; ".join(callback_mismatches))


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
    source_root = Path(__file__).resolve().parents[1] / "app"
    validate_ui_acceptance_inventory(controls, PAGES, source_root=source_root)
    discovered = discover_actionable_controls(source_root)
    actionable_controls = tuple(
        item
        for item in controls
        if any(key != "<missing>" and _keys_match(item.key, key) for key in discovered)
    )
    return generate_ui_action_inventory(
        actionable_controls,
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
        authoritative_lane = _lane_for_control(item.key, item.route, item.control_type)
        if item.resolved_lane != authoritative_lane:
            raise ValueError(
                f"UI action lane mismatch: {item.key} expected {authoritative_lane}, got {item.resolved_lane}"
            )
        if item.success_signal != _signal_id("success", item.key):
            raise ValueError(f"UI action success contract mismatch: {item.key}")
        if item.controlled_error_signal != _signal_id("failure", item.key):
            raise ValueError(f"UI action failure contract mismatch: {item.key}")
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
                success_signal=_signal_id("success", f"route:{route}"),
                controlled_error_signal=_signal_id("failure", f"route:{route}"),
                lane=_lane_for_route(route),
                source="route",
            )
        )

    for command in command_metadata:
        contract = command_contract_from_metadata(command)
        route = contract.route
        title = str(getattr(command, "title", route)).strip() or route
        actions.append(
            UIAction(
                action_id=contract.action_id,
                key=f"shell.command.{_route_slug(route)}",
                route=route,
                control_label=title,
                control_type="command",
                callback=contract.callback,
                command_id=contract.command_id,
                success_signal=contract.success_signal,
                controlled_error_signal=contract.controlled_error_signal,
                lane=_lane_for_route(route),
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
        expected_lane = (
            _lane_for_control(item.key, item.route, item.control_type)
            if item.source == "control"
            else _lane_for_route(item.route)
        )
        if item.lane != expected_lane:
            raise ValueError(f"UI action lane mismatch: {item.action_id} expected {expected_lane}, got {item.lane}")
        signal_key = (
            item.key
            if item.source == "control"
            else f"route:{item.route}"
            if item.source == "route"
            else f"command:{item.command_id}"
        )
        if item.success_signal != _signal_id("success", signal_key):
            raise ValueError(f"UI action success contract mismatch: {item.action_id}")
        if item.controlled_error_signal != _signal_id("failure", signal_key):
            raise ValueError(f"UI action failure contract mismatch: {item.action_id}")
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


def command_contract_from_metadata(command: object) -> UICommandContract:
    """Build the one runtime contract used by a palette command result."""

    route = str(getattr(command, "route", "")).strip()
    if not route:
        raise ValueError("UI command metadata requires a route")
    command_id = str(getattr(command, "command_id", f"palette-command:{route}")).strip()
    callback = str(getattr(command, "callback", "navigate_palette_command")).strip()
    action_id = f"command:{command_id}"
    return UICommandContract(
        command_id=command_id,
        action_id=action_id,
        route=route,
        callback=callback,
        success_signal=_signal_id("success", action_id),
        controlled_error_signal=_signal_id("failure", action_id),
        idempotency_key=f"ui:{action_id}",
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


def _lane_for_control(key: str, route: str, control_type: str) -> str:
    """Return the fixed lane for a declared control without label inference."""

    if key in _LIVE_STAGE_KEYS:
        return "live_stage"
    if key == "navigation.training-centre" or key.startswith("training-centre."):
        return "training"
    if key.startswith("operations.paper-") or key.startswith("forward-evidence."):
        return "paper"
    if key == "navigation.providers" or key.startswith("providers."):
        return "broker_read_only"
    if (
        key.startswith("errors.")
        or key.startswith("jobs.")
        or key.startswith("settings.backup-")
        or key == "settings.recovery-drill"
        or key.startswith("import-export.restore-")
        or key == "import-export.create-backup"
    ):
        return "recovery"
    if control_type == "navigation":
        return _lane_for_route(route)
    return "research"


def _lane_for_route(route: str) -> str:
    return _ROUTE_LANES.get(str(route), "research")


def _signal_id(outcome: Literal["success", "failure"], key: str) -> str:
    stable_key = str(key).replace("*", "wildcard").replace(":", ".").replace("/", ".").strip(".") or "home"
    return f"ui.{outcome}.{stable_key}"


def _default_contract_path() -> Path:
    source_path = CONFIG_DIR / "ui_acceptance.yaml"
    if source_path.is_file():
        return source_path
    try:
        distribution = importlib.metadata.distribution("etf-ai-cockpit")
    except importlib.metadata.PackageNotFoundError as exc:
        raise FileNotFoundError("ui_acceptance.yaml is unavailable from source and installed package") from exc
    installed_candidates = (
        Path(distribution.locate_file("")) / "configs" / "ui_acceptance.yaml",
        Path(sys.prefix) / "configs" / "ui_acceptance.yaml",
    )
    for candidate in installed_candidates:
        if candidate.is_file():
            return candidate
    for item in distribution.files or ():
        candidate = Path(str(item).replace("\\", "/"))
        if candidate.as_posix().endswith("/configs/ui_acceptance.yaml"):
            resolved = Path(distribution.locate_file(item))
            if resolved.is_file():
                return resolved
    raise FileNotFoundError("installed package does not contain configs/ui_acceptance.yaml")


def discover_actionable_controls(source_root: Path) -> dict[str, DiscoveredControl]:
    """Discover constructor and post-construction event bindings by stable key."""

    found: dict[str, dict[str, list[str]]] = {}
    missing: list[str] = []
    for path in sorted(Path(source_root).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        assigned_controls: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0] if len(node.targets) == 1 else None
            if not isinstance(target, ast.Name):
                continue
            keywords = {item.arg: item.value for item in value.keywords if item.arg}
            key = _key_pattern(keywords.get("key"))
            if key:
                assigned_controls[target.id] = (key, f"{path.as_posix()}:{node.lineno}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = _call_name(node.func)
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            if function_name == "_workflow_button":
                expression = keywords.get("key_name")
                event_nodes = {"on_click": keywords.get("on_click")}
            elif function_name == "_attach_picker":
                expression = node.args[1] if len(node.args) > 1 else None
                event_nodes = {"file_picker": ast.Name(id="pick_files")}
            elif function_name in _ACTION_CONTROL_CALLS and any(name in _EVENT_BINDINGS for name in keywords):
                expression = keywords.get("key")
                event_nodes = {name: value for name, value in keywords.items() if name in _EVENT_BINDINGS}
            elif function_name == "FilePicker":
                expression = keywords.get("key")
                event_nodes = {"file_picker": ast.Name(id="pick_files")}
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
                _record_discovered(
                    found,
                    key,
                    event_nodes,
                    location,
                    available_symbols=_available_callback_symbols(tree, node, parents),
                )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0] if len(node.targets) == 1 else None
            if not isinstance(target, ast.Attribute) or target.attr not in _EVENT_BINDINGS:
                continue
            if not isinstance(target.value, ast.Name) or target.value.id not in assigned_controls:
                continue
            key, construction_location = assigned_controls[target.value.id]
            location = f"{path.as_posix()}:{node.lineno}"
            _record_discovered(
                found,
                key,
                {target.attr: node.value},
                f"{construction_location},{location}",
                available_symbols=_available_callback_symbols(tree, node, parents),
            )
    if missing:
        found["<missing>"] = {"callbacks": [], "events": [], "locations": missing}
    return {
        key: DiscoveredControl(
            key=key,
            callbacks=tuple(sorted(set(values["callbacks"]))),
            events=tuple(sorted(set(values["events"]))),
            locations=tuple(sorted(set(values["locations"]))),
        )
        for key, values in found.items()
    }


def discover_actionable_control_keys(source_root: Path) -> dict[str, tuple[str, ...]]:
    """Compatibility projection of actionable keys to source locations."""

    return {key: item.locations for key, item in discover_actionable_controls(source_root).items()}


def _record_discovered(
    found: dict[str, dict[str, list[str]]],
    key: str,
    event_nodes: Mapping[str, ast.AST | None],
    location: str,
    *,
    available_symbols: set[str],
) -> None:
    if key == "shell.command-palette" and {"on_change", "on_submit"} <= event_nodes.keys():
        for event_name, callback_node in event_nodes.items():
            event_key = f"{key}.{event_name.replace('_', '-')}"
            _record_discovered(
                found,
                event_key,
                {event_name: callback_node},
                location,
                available_symbols=available_symbols,
            )
        return
    row = found.setdefault(key, {"callbacks": [], "events": [], "locations": []})
    row["locations"].append(location)
    for event_name, callback_node in event_nodes.items():
        row["events"].append(event_name)
        callback = _callback_name(callback_node, available_symbols=available_symbols)
        if callback:
            row["callbacks"].append(callback)


def _callback_name(node: ast.AST | None, *, available_symbols: set[str]) -> str:
    if isinstance(node, ast.Name):
        if hasattr(node, "lineno") and node.id not in available_symbols:
            return ""
        return node.id
    if isinstance(node, ast.Attribute):
        return _call_name(node)
    if isinstance(node, ast.IfExp):
        return _callback_name(node.body, available_symbols=available_symbols) or _callback_name(
            node.orelse,
            available_symbols=available_symbols,
        )
    if isinstance(node, ast.Lambda):
        for child in ast.walk(node.body):
            if isinstance(child, ast.Call):
                name = _call_name(child.func)
                if name not in {"getattr", "setattr", "str", "list", "tuple"}:
                    return name
    return ""


def _available_callback_symbols(
    tree: ast.Module,
    node: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> set[str]:
    """Return names bound in the source scopes enclosing one event binding."""

    scopes: list[ast.AST] = [tree]
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            scopes.append(current)
        current = parents.get(current)
    symbols = set(dir(builtins))
    for scope in reversed(scopes):
        symbols.update(_scope_bindings(scope))
    return symbols


def _scope_bindings(scope: ast.AST) -> set[str]:
    collector = _BindingCollector()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        collector.names.update(argument.arg for argument in scope.args.posonlyargs)
        collector.names.update(argument.arg for argument in scope.args.args)
        collector.names.update(argument.arg for argument in scope.args.kwonlyargs)
        if scope.args.vararg is not None:
            collector.names.add(scope.args.vararg.arg)
        if scope.args.kwarg is not None:
            collector.names.add(scope.args.kwarg.arg)
    statements = (
        scope.body
        if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        else ()
    )
    for statement in statements:
        collector.visit(statement)
    return collector.names


class _BindingCollector(ast.NodeVisitor):
    """Collect bindings in one scope without descending into child scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")


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
    return any(fnmatchcase(key, item) or fnmatchcase(item, key) for item in declared)


def _keys_match(left: str, right: str) -> bool:
    return _key_is_declared(left, {right}) or _key_is_declared(right, {left})


def _required(values: dict[str, object], key: str) -> str:
    value = str(values.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing UI acceptance field: {key}")
    return value
