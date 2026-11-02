"""Tool declaration, autodiscovery, tier enforcement, confirmation and audited dispatch.

Open defaults: tools without an explicit profile are visible only in full; calls run with
read-only access unless the server launch configuration grants additional tiers. Call context
defaults are the core profile, read tier, local client id, and an empty store revision.
Rate limits are rolling windows shared across clients and processes under the data root: 20 paper
order placements/day, 10 ticket exports/day, and 4 data refreshes/hour. Admitted attempts
count even if confirmation or the handler fails; rate refusals do not consume tokens.
Counters persist in logs/mcp_rate_limits.sqlite3; unavailable quota storage refuses the call.
Write handlers provide a side-effect-free ``preview`` callback: a call without a token returns
that preview and a 15-minute, client/revision-bound token; a call with the token commits once.
Paper and portfolio adapters own their preview/token contract; dispatch preserves their payload
and requires their token before calling the handler.
Explicit read-only preview tools use the edit tier with ``readOnlyHint=true`` and no confirmation.
Configuration-file ownership belongs to the remote lane.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import importlib
import inspect
from pathlib import Path
import pkgutil
import sqlite3
import time
from types import ModuleType
from typing import Any, Callable, Iterator, Mapping

from pydantic import BaseModel

from etf_cockpit.core.paths import LOG_DIR
from etf_cockpit.mcp.audit import AuditRecord, AuditRecorder, hash_arguments
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import (
    AuthorizationError,
    ConfirmationError,
    InvalidArgumentsError,
    MCPToolError,
    RateLimitError,
    ToolDiscoveryError,
)
from etf_cockpit.mcp.tiers import WRITE_TIERS, normalise_profile, normalise_tier, parse_tiers, profile_allows


class RateLimiter:
    """Atomically reserve an attempt before dispatching a rate-limited operation."""

    _LIMITS = {
        "paper_order_place": (20, 86400),
        "ticket_export": (10, 86400),
        "data_refresh": (4, 3600),
    }

    def __init__(
        self, *, path: Path = LOG_DIR / "mcp_rate_limits.sqlite3", clock: Callable[[], float] = time.time
    ) -> None:
        self._path = path
        self._clock = clock

    def acquire(self, name: str) -> None:
        if name not in self._LIMITS:
            return
        limit, window = self._LIMITS[name]
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._path, timeout=1.0)) as connection, connection:
                # One transaction reserves the quota across threads, clients and server restarts.
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS rate_calls (tool TEXT NOT NULL, called_at REAL NOT NULL)")
                now = self._clock()
                connection.execute("DELETE FROM rate_calls WHERE tool = ? AND called_at <= ?", (name, now - window))
                count, oldest = connection.execute(
                    "SELECT COUNT(*), MIN(called_at) FROM rate_calls WHERE tool = ?", (name,)
                ).fetchone()
                if count >= limit:
                    raise RateLimitError(oldest + window - now)
                connection.execute("INSERT INTO rate_calls (tool, called_at) VALUES (?, ?)", (name, now))
        except (OSError, sqlite3.Error):
            raise MCPToolError(
                "RATE_LIMIT_UNAVAILABLE",
                "The rate-limit store is unavailable",
                "Restore access to the local quota store before retrying.",
            ) from None


_RATE_LIMITER = RateLimiter()

# These adapters issue their own tokens, including the explicit dry_run=False argument.
_HANDLER_PREVIEW_MODULES = frozenset({
    "etf_cockpit.mcp.tools_paper",
    "etf_cockpit.mcp.tools_portfolio",
})


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    tier: str
    annotations: Mapping[str, bool]
    requires_confirmation: bool
    function: Callable[..., Any]
    output_model: type[BaseModel]
    preview_function: Callable[..., Any] | None = None
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
    rate_limiter: RateLimiter = field(default_factory=lambda: _RATE_LIMITER)

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
    preview: Callable[..., Any] | None = None,
    output_model: type[BaseModel] = Envelope,
    profiles: tuple[str, ...] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a handler for deterministic discovery; annotations remain untrusted hints."""

    normalized_tier = normalise_tier(tier)
    if not description.strip():
        raise ValueError("tool descriptions must not be empty")
    resolved_read_only = normalized_tier not in WRITE_TIERS if read_only_hint is None else bool(read_only_hint)
    resolved_confirmation = (
        normalized_tier in WRITE_TIERS and not resolved_read_only
        if requires_confirmation is None
        else bool(requires_confirmation)
    )
    resolved_destructive = resolved_confirmation if destructive_hint is None else bool(destructive_hint)
    if normalized_tier in WRITE_TIERS and not resolved_confirmation and not resolved_read_only:
        raise ValueError("write-tier tools must require confirmation")
    if normalized_tier in WRITE_TIERS and resolved_confirmation and resolved_read_only:
        raise ValueError("confirmation-required write tools cannot declare readOnlyHint=true")
    if normalized_tier in WRITE_TIERS and not resolved_confirmation and resolved_destructive:
        raise ValueError("read-only preview tools cannot declare destructiveHint=true")
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
        preview_handler = preview
        if resolved_confirmation and preview_handler is None and function.__module__ not in _HANDLER_PREVIEW_MODULES:
            if "dry_run" in signature.parameters:
                def preview_handler(**kwargs: Any) -> Any:
                    preview_args = {**kwargs, "dry_run": True}
                    if "confirm_token" in signature.parameters:
                        preview_args["confirm_token"] = None
                    return function(**preview_args)
            else:
                def preview_handler(**kwargs: Any) -> dict[str, Any]:
                    return {
                        "status": "confirmation_required",
                        "operation": name or function.__name__,
                        "arguments": dict(kwargs),
                        "execution_allowed": False,
                    }
        spec = ToolSpec(
            name=name or function.__name__,
            description=description.strip(),
            tier=normalized_tier,
            annotations=annotation_values,
            requires_confirmation=resolved_confirmation,
            function=function,
            preview_function=preview_handler,
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


def issue_confirmation_token(payload: Mapping[str, Any], *, context: CallContext | None = None) -> str:
    """Issue a confirmation bound to the current client and store revision for preview tools."""

    active = context or current_call_context()
    return active.confirmation_store.issue(
        payload,
        store_revision=active.store_revision,
        client_id=active.client_id,
    )


def _contains_execution_control(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).strip().lower() == "execution_allowed" or _contains_execution_control(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_execution_control(item) for item in value)
    return False


def invoke_tool(name: str, arguments: Mapping[str, Any], *, context: CallContext | None = None) -> Any:
    """Enforce authorization, centrally preview/confirm writes, and audit each call."""

    active = context or CallContext()
    started = time.perf_counter()
    safe_args = dict(arguments)
    args_hash = hash_arguments(safe_args)
    spec: ToolSpec | None = None
    outcome = "error"
    output_hash: str | None = None
    result: Any = None
    reason_code: str | None = None
    try:
        spec = find_tool(name)
        if spec.tier not in active.enabled_tiers or not profile_allows(spec.name, active.profile, spec.profiles):
            raise AuthorizationError()
        if _contains_execution_control(safe_args):
            raise InvalidArgumentsError("execution_allowed is fixed to false and is not a tool argument")
        signature = inspect.signature(spec.function)
        handler_args = safe_args
        if "store_revision" in safe_args and "store_revision" not in signature.parameters:
            handler_args = {key: value for key, value in safe_args.items() if key != "store_revision"}
        if "dry_run" in signature.parameters and spec.preview_function is not None:
            handler_args = {**handler_args, "dry_run": safe_args.get("confirm_token") is None}
        validation_args = handler_args
        if spec.requires_confirmation and "confirm_token" not in safe_args and "confirm_token" in signature.parameters:
            validation_args = {**handler_args, "confirm_token": None}
        try:
            signature.bind(**validation_args)
        except TypeError as exc:
            raise InvalidArgumentsError(str(exc)) from None
        active.rate_limiter.acquire(spec.name)
        write_dispatch = spec.tier in WRITE_TIERS and not bool(spec.annotations.get("readOnlyHint"))
        if write_dispatch or spec.requires_confirmation:
            token = safe_args.get("confirm_token")
            excluded = {"confirm_token", "store_revision"}
            if spec.preview_function is not None:
                excluded.add("dry_run")
            payload = {key: value for key, value in safe_args.items() if key not in excluded}
            if "store_revision" in safe_args and safe_args["store_revision"] != active.store_revision:
                raise ConfirmationError("The echoed store revision differs from the current store revision")
            if token is None:
                if spec.preview_function is None:
                    raise ConfirmationError("This write tool has no safe dry-run preview")
                try:
                    inspect.signature(spec.preview_function).bind(**payload)
                except TypeError as exc:
                    raise InvalidArgumentsError(str(exc)) from None
                with use_call_context(active):
                    preview_result = spec.preview_function(**payload)
                if isinstance(preview_result, dict):
                    preview_result = {
                        key: value for key, value in preview_result.items()
                        if key not in {"confirm_token", "confirmation_arguments"}
                    }
                issued = issue_confirmation_token(payload, context=active)
                result = {"preview": preview_result, "confirm_token": issued}
                output_hash = hash_arguments(result)
                outcome = "ok"
                return result
            if not isinstance(token, str) or not active.confirmation_store.consume(
                token,
                payload,
                store_revision=active.store_revision,
                client_id=active.client_id,
            ):
                raise ConfirmationError()
        with use_call_context(active):
            result = spec.function(**handler_args)
        output_hash = hash_arguments(result)
        outcome = "ok"
        return result
    except BaseException as exc:
        reason_code = exc.reason_code if isinstance(exc, MCPToolError) else None
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
                reason_code=reason_code,
            )
        )
