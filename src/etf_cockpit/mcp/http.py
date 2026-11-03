"""Authenticated Streamable HTTP transport for the remote MCP profile.

Conservative defaults: remote HTTP is disabled; when enabled it binds to
127.0.0.1:8000 at ``/mcp``, uses the ``core`` profile, and permits only read,
research, and paper tiers. OAuth issuer and resource URLs must be supplied by
the deployment as HTTPS URLs. A token receives only the tiers mapped to its
explicit scopes; scopes do not imply one another. Tool output remains governed
by each canonical tool's existing paging defaults (25 rows, maximum 100).
"""

from __future__ import annotations

from dataclasses import replace
import ipaddress
import inspect
import os
from pathlib import Path
from functools import wraps
from typing import Any, Mapping, get_type_hints
from urllib.parse import urlsplit

from etf_cockpit.core.paths import CODE_CONFIG_DIR, CONFIG_DIR, ROOT
from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import AuthorizationError, MCPServerUnavailable, MCPToolError
from etf_cockpit.mcp.registry import CallContext, ToolSpec, invoke_tool, list_tools
from etf_cockpit.mcp.serialise import build_envelope, envelope_dict
from etf_cockpit.mcp.server import SERVER_INSTRUCTIONS, SERVER_NAME
from etf_cockpit.mcp.tiers import normalise_profile
from etf_cockpit.mcp.worker import start_server_worker


REMOTE_ALLOWED_TIERS = frozenset({"read", "research", "paper"})
DEFAULT_SCOPE_TIERS: dict[str, tuple[str, ...]] = {
    "cockpit:read": ("read",),
    "cockpit:research": ("research",),
    "cockpit:paper": ("paper",),
}
DEFAULT_CONFIG_PATH = CONFIG_DIR / "mcp_v1.yaml"
CODE_CONFIG_PATH = CODE_CONFIG_DIR / "mcp_v1.yaml"


def load_mcp_config(path: Path | None = None) -> dict[str, Any]:
    """Load the MCP policy from the data root, falling back to the shipped config."""

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if path is None and not config_path.is_file():
        config_path = CODE_CONFIG_PATH
    try:
        import yaml
    except ImportError as exc:
        raise MCPServerUnavailable("PyYAML is required to load the MCP configuration") from exc
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise MCPServerUnavailable("The MCP configuration is unavailable or invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("mcp"), dict):
        raise MCPServerUnavailable("The MCP configuration must contain an mcp mapping")
    return payload["mcp"]


def _remote_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    remote = config.get("remote")
    if not isinstance(remote, Mapping):
        raise MCPServerUnavailable("The MCP remote configuration is missing")
    if remote.get("enabled") is not True:
        raise MCPServerUnavailable("Remote MCP is disabled; enable it in configs/mcp_v1.yaml")
    try:
        profile = normalise_profile(str(remote.get("profile", "core")))
    except ValueError as exc:
        raise MCPServerUnavailable("Remote MCP is restricted to the core profile") from exc
    if profile != "core":
        raise MCPServerUnavailable("Remote MCP is restricted to the core profile")
    allowed = remote.get("allowed_tiers", ("read", "research", "paper"))
    if not isinstance(allowed, (list, tuple)) or frozenset(allowed) != REMOTE_ALLOWED_TIERS:
        raise MCPServerUnavailable("Remote MCP may expose only read, research, and paper tiers")
    return remote


def scope_tier_map(config: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """Return validated scope grants, excluding any tier outside the remote policy."""

    raw = config.get("scope_tiers", DEFAULT_SCOPE_TIERS)
    if not isinstance(raw, Mapping):
        raise MCPServerUnavailable("The MCP scope_tiers setting must be a mapping")
    grants: dict[str, frozenset[str]] = {}
    for scope, values in raw.items():
        if not isinstance(scope, str) or not scope.strip() or not isinstance(values, (list, tuple)):
            raise MCPServerUnavailable("Every MCP scope must map to a tier list")
        tiers = frozenset(str(value).strip().lower() for value in values)
        if not tiers or not tiers <= REMOTE_ALLOWED_TIERS:
            raise MCPServerUnavailable("A remote MCP scope contains a disallowed or empty tier grant")
        grants[scope] = tiers
    return grants


def tiers_for_scopes(scopes: object, *, grants: Mapping[str, frozenset[str]]) -> frozenset[str]:
    """Resolve verified OAuth scopes to the least-privilege remote tier set."""

    if isinstance(scopes, str):
        scope_values = scopes.split()
    elif isinstance(scopes, (list, tuple, set, frozenset)):
        scope_values = [scope for scope in scopes if isinstance(scope, str)]
    else:
        scope_values = []
    tiers = frozenset(tier for scope in scope_values for tier in grants.get(scope, ()))
    if not tiers:
        raise AuthorizationError("The bearer token has no MCP scopes enabled for remote access")
    return tiers


def _required_https_url(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MCPServerUnavailable(f"The OAuth {label} URL must be configured")
    parts = urlsplit(value.strip())
    if parts.scheme.lower() != "https" or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise MCPServerUnavailable(f"The OAuth {label} URL must be an HTTPS URL without credentials or a fragment")
    return value.strip()


def _oauth_urls(remote: Mapping[str, Any], issuer_url: str | None, resource_url: str | None) -> tuple[str, str]:
    oauth = remote.get("oauth", {})
    if not isinstance(oauth, Mapping):
        raise MCPServerUnavailable("The MCP OAuth configuration must be a mapping")
    issuer_env = str(oauth.get("issuer_url_env", "ETF_COCKPIT_MCP_ISSUER_URL"))
    resource_env = str(oauth.get("resource_url_env", "ETF_COCKPIT_MCP_RESOURCE_URL"))
    issuer = issuer_url if issuer_url is not None else os.environ.get(issuer_env)
    resource = resource_url if resource_url is not None else os.environ.get(resource_env)
    return _required_https_url(issuer, "issuer"), _required_https_url(resource, "resource")


def _headless_session() -> Any:
    from etf_cockpit.application.headless_session import HeadlessSession, require_storage_root
    from etf_cockpit.application.snapshot_builder import build_snapshot

    root = require_storage_root(ROOT)
    return HeadlessSession(build_snapshot(force_sample=False), root=root)


def _verified_context(
    access_token: Any,
    *,
    template: CallContext,
    grants: Mapping[str, frozenset[str]],
) -> CallContext:
    if access_token is None:
        raise AuthorizationError("A verified OAuth bearer token is required")
    client_id = getattr(access_token, "client_id", None)
    if not isinstance(client_id, str) or not client_id.strip():
        raise AuthorizationError("The verified bearer token has no client identity")
    tiers = tiers_for_scopes(getattr(access_token, "scopes", None), grants=grants)
    return replace(template, enabled_tiers=tiers, profile="core", client_id=client_id)


def _dispatch_http_tool(
    spec: ToolSpec,
    arguments: Mapping[str, Any],
    access_token: Any,
    *,
    template: CallContext,
    grants: Mapping[str, frozenset[str]],
) -> Any:
    context = _verified_context(access_token, template=template, grants=grants)
    return invoke_tool(spec.name, arguments, context=context)


def _access_token_getter():
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except (ImportError, ModuleNotFoundError) as exc:
        raise MCPServerUnavailable("The installed MCP SDK does not expose bearer auth context") from exc
    return get_access_token


def _tool_handler(spec: ToolSpec, *, template: CallContext, grants: Mapping[str, frozenset[str]], tool_error: type[Exception]):
    get_access_token = _access_token_getter()

    @wraps(spec.function)
    def invoke(**arguments: Any) -> Any:
        try:
            result = _dispatch_http_tool(
                spec,
                arguments,
                get_access_token(),
                template=template,
                grants=grants,
            )
        except MCPToolError as exc:
            raise tool_error(f"{exc.reason_code}: {exc.message}. {exc.next_step}") from None
        envelope = result if isinstance(result, Envelope) else build_envelope(result)
        return envelope_dict(envelope)

    signature = inspect.signature(spec.function)
    try:
        type_hints = get_type_hints(spec.function, include_extras=True)
    except Exception as exc:
        raise MCPServerUnavailable(f"Could not resolve annotations for MCP tool {spec.name!r}") from exc
    parameters = [
        parameter.replace(annotation=type_hints.get(name, parameter.annotation))
        for name, parameter in signature.parameters.items()
    ]
    invoke.__signature__ = signature.replace(parameters=parameters, return_annotation=spec.output_model)  # type: ignore[attr-defined]
    invoke.__annotations__ = type_hints
    invoke.__annotations__["return"] = spec.output_model
    return invoke


def create_http_server(
    *,
    token_verifier: Any,
    issuer_url: str | None = None,
    resource_url: str | None = None,
    config: Mapping[str, Any] | None = None,
    config_path: Path | None = None,
    session: Any = None,
):
    """Build an OAuth-protected Streamable HTTP server without starting it."""

    selected_config = dict(config) if config is not None else load_mcp_config(config_path)
    remote = _remote_config(selected_config)
    grants = scope_tier_map(selected_config)
    if token_verifier is None or not callable(getattr(token_verifier, "verify_token", None)):
        raise MCPServerUnavailable("A verified OAuth TokenVerifier is required for remote MCP")
    selected_issuer, selected_resource = _oauth_urls(remote, issuer_url, resource_url)
    try:
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.exceptions import ToolError
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import ToolAnnotations
    except (ImportError, ModuleNotFoundError) as exc:
        raise MCPServerUnavailable("Install etf-ai-cockpit[mcp] with the supported MCP SDK") from exc

    resource_host = urlsplit(selected_resource).hostname
    if not resource_host:
        raise MCPServerUnavailable("The OAuth resource URL must include a host")
    host = str(remote.get("host", "127.0.0.1"))
    try:
        loopback_host = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback_host = False
    if not loopback_host:
        raise MCPServerUnavailable("The remote MCP server must bind to a loopback address")
    try:
        port = int(remote.get("port", 8000))
    except (TypeError, ValueError) as exc:
        raise MCPServerUnavailable("The remote MCP port must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise MCPServerUnavailable("The remote MCP port must be an integer from 1 to 65535")
    path = str(remote.get("path", "/mcp"))
    if not path.startswith("/") or ".." in path.split("/"):
        raise MCPServerUnavailable("The remote MCP path must be an absolute safe path")
    resource_parts = urlsplit(selected_resource)
    if resource_parts.path.rstrip("/") != path.rstrip("/") or resource_parts.query:
        raise MCPServerUnavailable("The OAuth resource URL must match the configured MCP path exactly")
    selected_session = session if session is not None else _headless_session()
    if Path(getattr(selected_session, "root", ROOT)).resolve() != ROOT.resolve():
        raise MCPServerUnavailable("The remote MCP session must use the configured data root")

    server = FastMCP(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path=path,
        stateless_http=True,
        auth=AuthSettings(
            issuer_url=selected_issuer,
            resource_server_url=selected_resource,
            required_scopes=[],
        ),
        token_verifier=token_verifier,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[resource_host, f"{resource_host}:*"],
            allowed_origins=[],
        ),
    )
    template_context = CallContext(
        enabled_tiers=REMOTE_ALLOWED_TIERS,
        profile="core",
        client_id="remote-bootstrap",
        session=selected_session,
    )
    specs = list_tools(profile="core", tiers=REMOTE_ALLOWED_TIERS)
    for spec in specs:
        server.add_tool(
            _tool_handler(spec, template=template_context, grants=grants, tool_error=ToolError),
            name=spec.name,
            description=spec.description,
            annotations=ToolAnnotations(**dict(spec.annotations)),
            structured_output=True,
        )

    # The SDK's low-level list-tools registration is request scoped, so the tool
    # list follows the verified token's scopes while calls still pass the same
    # tier checks in the registry.
    get_access_token = _access_token_getter()

    async def list_authorized_tools():
        token = get_access_token()
        if token is None:
            return []
        try:
            granted = tiers_for_scopes(getattr(token, "scopes", None), grants=grants)
        except MCPToolError:
            return []
        names = {spec.name for spec in list_tools(profile="core", tiers=granted)}
        return [item for item in await server.list_tools() if item.name in names]

    try:
        server._mcp_server.list_tools()(list_authorized_tools)
    except (AttributeError, TypeError) as exc:
        raise MCPServerUnavailable("The installed MCP SDK cannot register scope-filtered tools/list") from exc
    start_server_worker(server, selected_session)
    return server


def run_http_server(
    *,
    token_verifier: Any,
    issuer_url: str | None = None,
    resource_url: str | None = None,
    config: Mapping[str, Any] | None = None,
    config_path: Path | None = None,
    session: Any = None,
) -> None:
    """Start the configured remote HTTP server; the caller owns OAuth verification."""

    server = create_http_server(
        token_verifier=token_verifier,
        issuer_url=issuer_url,
        resource_url=resource_url,
        config=config,
        config_path=config_path,
        session=session,
    )
    server.run(transport="streamable-http")
