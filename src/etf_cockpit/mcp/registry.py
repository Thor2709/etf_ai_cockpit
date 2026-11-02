"""Tool declaration, autodiscovery, tier enforcement, confirmation and audited dispatch.

Open defaults: tools without an explicit profile are visible only in full; calls run with
read-only access unless the server launch configuration grants additional tiers. Call context
defaults are the core profile, read tier, local client id, and an empty store revision.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import importlib
import inspect
import pkgutil
import time
from types import ModuleType
from typing import Any, Callable, Iterator, Mapping

from pydantic import BaseModel

from etf_cockpit.mcp.audit import AuditRecord, AuditRecorder, hash_arguments
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import (
    AuthorizationError,
    ConfirmationError,
    InvalidArgumentsError,
    MCPToolError,
    ToolDiscoveryError,
)
from etf_cockpit.mcp.tiers import WRITE_TIERS, normalise_profile, normalise_tier, parse_tiers, profile_allows


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    tier: str
    annotations: Mapping[str, bool]
    requires_confirmation: bool
    function: Callable[..., Any]
    output_model: type[BaseModel]
    profiles: frozenset[str] | None = None


@dataclass
class CallContext:
    enabled_tiers: frozenset[str] = field(default_factory=parse_tiers)
    profile: str = "core"
    client_id: str = "local"
    confirmation_store: ConfirmationStore = field(default_factory=ConfirmationStore)
    audit: AuditRecorder = field(default_factory=AuditRecorder)
    session: Any = None
    store_revision: str = ""

    def __post_init__(self) -> None:
        self.enabled_tiers = parse_tiers(self.enabled_tiers)
        self.profile = normalise_profile(self.profile)
        if not self.client_id.strip():
            raise ValueError("client_id must not be empty")


_ACTIVE_CONTEXT: ContextVar[CallContext | None] = ContextVar("mcp_call_context", default=None)


@contextmanager
def use_call_context(context: CallContext) -> Iterator[None]:
    token = _ACTIVE_CONTEXT.set(context)
    try:
        yield
    finally:
        _ACTIVE_CONTEXT.reset(token)


def current_call_context() -> CallContext:
    context = _ACTIVE_CONTEXT.get()
    if context is None:
        raise MCPToolError("TOOL_CONTEXT_UNAVAILABLE", "No MCP call context is active", "Call this tool through the MCP server.")
    return context


def tool(
    *,
    tier: str,
    description: str,
    name: str | None = None,
    read_only_hint: bool | None = None,
    destructive_hint: bool | None = None,
    idempotent_hint: bool = False,
    open_world_hint: bool = False,
    requires_confirmation: bool | None = None,
    output_model: type[BaseModel] = Envelope,
    profiles: tuple[str, ...] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a handler for deterministic discovery; annotations remain untrusted hints."""

    normalized_tier = normalise_tier(tier)
    if not description.strip():
        raise ValueError("tool descriptions must not be empty")
    resolved_read_only = normalized_tier not in WRITE_TIERS if read_only_hint is None else bool(read_only_hint)
    resolved_confirmation = normalized_tier in WRITE_TIERS if requires_confirmation is None else bool(requires_confirmation)
    resolved_destructive = resolved_confirmation if destructive_hint is None else bool(destructive_hint)
    if normalized_tier in WRITE_TIERS and resolved_read_only:
        raise ValueError("write-tier tools cannot declare readOnlyHint=true")
    if resolved_confirmation and not resolved_destructive:
        raise ValueError("confirmation-required tools must declare destructiveHint=true")
    declared_profiles = frozenset(profiles) if profiles is not None else None
    if declared_profiles is not None and not declared_profiles <= {"core", "full"}:
        raise ValueError("tool profiles must be core and/or full")
    annotation_values = {
        "readOnlyHint": resolved_read_only,
        "destructiveHint": resolved_destructive,
        "idempotentHint": bool(idempotent_hint),
        "openWorldHint": bool(open_world_hint),
    }

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(function)
        if "execution_allowed" in signature.parameters:
            raise ValueError("MCP tools may not accept execution_allowed")
        if any(param in signature.parameters for param in ("broker", "broker_client", "broker_api")):
            raise ValueError("MCP tools may not receive broker objects")
        if inspect.iscoroutinefunction(function):
            raise ValueError("MCP tool handlers must be synchronous")
        spec = ToolSpec(
            name=name or function.__name__,
            description=description.strip(),
            tier=normalized_tier,
            annotations=annotation_values,
            requires_confirmation=resolved_confirmation,
            function=function,
            output_model=output_model,
            profiles=declared_profiles,
        )
        setattr(function, "__mcp_tool_spec__", spec)
        return function

    return decorate


def discover_tools(*, package_name: str = "etf_cockpit.mcp") -> tuple[ToolSpec, ...]:
    """Import every tools_*.py module under this package and return its declarations in name order."""

    try:
        package = importlib.import_module(package_name)
        paths = tuple(package.__path__)
        module_names = sorted(
            name
            for _, name, is_package in pkgutil.iter_modules(paths)
            if name.startswith("tools_") and not is_package
        )
        modules = [importlib.import_module(f"{package_name}.{name}") for name in module_names]
    except Exception as exc:
        raise ToolDiscoveryError(f"MCP tools could not be discovered ({type(exc).__name__})") from exc

    specs: list[ToolSpec] = []
    for module in modules:
        specs.extend(_module_specs(module))
    specs.sort(key=lambda item: item.name)
    names = [item.name for item in specs]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise ToolDiscoveryError(f"duplicate MCP tool names: {', '.join(duplicates)}")
    return tuple(specs)


def _module_specs(module: ModuleType) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for value in vars(module).values():
        spec = getattr(value, "__mcp_tool_spec__", None)
        if isinstance(spec, ToolSpec) and spec.function.__module__ == module.__name__:
            specs.append(spec)
    return specs


def list_tools(*, profile: str = "core", tiers: str | tuple[str, ...] | frozenset[str] | None = None) -> tuple[ToolSpec, ...]:
    selected_profile = normalise_profile(profile)
    selected_tiers = parse_tiers(tiers)
    return tuple(
        spec
        for spec in discover_tools()
        if spec.tier in selected_tiers and profile_allows(spec.name, selected_profile, spec.profiles)
    )


def find_tool(name: str) -> ToolSpec:
    for spec in discover_tools():
        if spec.name == name:
            return spec
    raise MCPToolError("TOOL_NOT_FOUND", "The requested tool is not available", "List the tools enabled for this launch profile.")


def _contains_execution_control(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).strip().lower() == "execution_allowed" or _contains_execution_control(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_execution_control(item) for item in value)
    return False


def invoke_tool(name: str, arguments: Mapping[str, Any], *, context: CallContext | None = None) -> Any:
    """Enforce launch authorization and confirmation, invoke once, then append one audit record."""

    active = context or CallContext()
    started = time.perf_counter()
    safe_args = dict(arguments)
    args_hash = hash_arguments(safe_args)
    spec: ToolSpec | None = None
    outcome = "error"
    output_hash: str | None = None
    result: Any = None
    error: BaseException | None = None
    try:
        spec = find_tool(name)
        if spec.tier not in active.enabled_tiers or not profile_allows(spec.name, active.profile, spec.profiles):
            raise AuthorizationError()
        if _contains_execution_control(safe_args):
            raise InvalidArgumentsError("execution_allowed is fixed to false and is not a tool argument")
        signature = inspect.signature(spec.function)
        try:
            signature.bind(**safe_args)
        except TypeError as exc:
            raise InvalidArgumentsError(str(exc)) from None
        if spec.requires_confirmation:
            token = safe_args.get("confirm_token")
            payload = {key: value for key, value in safe_args.items() if key not in {"confirm_token", "store_revision"}}
            revision = str(safe_args.get("store_revision", active.store_revision))
            if not isinstance(token, str) or not active.confirmation_store.consume(
                token,
                payload,
                store_revision=revision,
                client_id=active.client_id,
            ):
                raise ConfirmationError()
        with use_call_context(active):
            result = spec.function(**safe_args)
        output_hash = hash_arguments(result)
        outcome = "ok"
        return result
    except BaseException as exc:
        error = exc
        outcome = "refused" if isinstance(exc, MCPToolError) else "error"
        raise
    finally:
        active.audit.record(
            AuditRecord(
                tool=name,
                tier=spec.tier if spec is not None else "unknown",
                args_hash=args_hash,
                outcome=outcome,
                output_hash=output_hash,
                duration_ms=(time.perf_counter() - started) * 1000,
                client_id=active.client_id,
            )
        )
