"""Read-only MCP resources backed by canonical local tool and application readers.

Open defaults: the scoreboard resource requests 50 rows; journal resources request
20 rows; export resources are limited to root-local JSON, CSV, Markdown or text
files no larger than 1 MiB. Policy and methodology topics use fixed allowlists.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from etf_cockpit.mcp.envelope import Envelope
from etf_cockpit.mcp.errors import MCPToolError
from etf_cockpit.mcp.registry import CallContext, find_tool, use_call_context
from etf_cockpit.mcp.serialise import build_envelope, envelope_dict, to_json


@dataclass(frozen=True)
class ResourceSpec:
    uri: str
    name: str
    description: str
    parameters: tuple[str, ...] = ()
    tool_name: str | None = None
    tool_arguments: Mapping[str, object] | None = None


RESOURCE_SPECS = (
    ResourceSpec("cockpit://status", "Cockpit status", "Current freshness, readiness and status card.", tool_name="cockpit_status", tool_arguments={"detail": "brief"}),
    ResourceSpec("cockpit://scoreboard/latest", "Latest scoreboard", "The latest published ranked scores and binding.", tool_name="scores_ranked", tool_arguments={"top_n": 50}),
    ResourceSpec("cockpit://instrument/{id}", "Instrument view", "Identity and key instrument evidence.", ("id",), "instrument_detail"),
    ResourceSpec("cockpit://universe", "Universe", "Configured universe records and revision.", tool_name="universe_search"),
    ResourceSpec("cockpit://data/health", "Data health", "Dataset freshness and availability.", tool_name="data_health"),
    ResourceSpec("cockpit://gates", "Gate status", "Readiness, quality and safety gate status.", tool_name="gates_status"),
    ResourceSpec("cockpit://paper/bots", "Paper bots", "Local paper bot status and evidence.", tool_name="paper_bots_status"),
    ResourceSpec("cockpit://portfolio/current", "Current portfolio", "Current portfolio overview.", tool_name="portfolio_overview"),
    ResourceSpec("cockpit://research/{id}", "Research findings", "Local findings for one research subject.", ("id",), "research_findings"),
    ResourceSpec("cockpit://journal/recent", "Recent journal", "The last 20 verified decision-journal entries.", tool_name="journal_entries", tool_arguments={"limit": 20}),
    ResourceSpec("cockpit://policy/{name}", "Policy", "One allow-listed local policy bundle.", ("name",), "settings_get"),
    ResourceSpec("cockpit://methodology/{topic}", "Methodology", "One allow-listed local methodology source.", ("topic",)),
    ResourceSpec("cockpit://exports/{path}", "Local export", "A bounded root-local report or export file.", ("path",)),
)

_POLICY_NAMES = frozenset({
    "portfolio_policy_v1", "risk_limits", "pre_trade_limits_v1", "gate_policy",
    "authority_matrix", "paper_bots_v1", "strategy_templates_v1",
})
_METHODOLOGY_TOPICS = frozenset({"score_engine_v3", "forecast_promotion", "glossary", "forward_evidence_diary"})
_EXPORT_PREFIXES = (Path("exports"), Path("data") / "chatgpt_exports", Path("data") / "reports", Path("data") / "derived")
_EXPORT_EXTENSIONS = frozenset({".json", ".csv", ".md", ".txt"})
_EXPORT_LIMIT_BYTES = 1_048_576


def resource_specs() -> tuple[ResourceSpec, ...]:
    return RESOURCE_SPECS


def read_resource(spec: ResourceSpec, arguments: Mapping[str, Any], context: CallContext) -> str:
    """Read a resource with the same service implementation and launch session as its mirrored tool."""

    if spec.tool_name:
        tool_spec = find_tool(spec.tool_name)
        values = dict(spec.tool_arguments or {})
        if spec.tool_name == "instrument_detail":
            values.update({"instrument_id": arguments["id"], "sections": ("overview", "score")})
        elif spec.tool_name == "research_findings":
            values["subject"] = arguments["id"]
        elif spec.tool_name == "settings_get":
            values["section"] = arguments["name"]
        with use_call_context(context):
            result = tool_spec.function(**values)
        return to_json(envelope_dict(result if isinstance(result, Envelope) else build_envelope(result)))
    if spec.uri == "cockpit://methodology/{topic}":
        result = _read_methodology(str(arguments.get("topic", "")), context)
        return to_json(envelope_dict(build_envelope(result)))
    if spec.uri == "cockpit://exports/{path}":
        result = _read_export(str(arguments.get("path", "")), context)
        return to_json(envelope_dict(build_envelope(result)))
    raise MCPToolError("RESOURCE_NOT_FOUND", "The requested MCP resource is unavailable", "List the configured resources and retry.")


def _root(context: CallContext) -> Path:
    from etf_cockpit.core.paths import ROOT

    return Path(getattr(context.session, "root", None) or ROOT).resolve()


def _read_methodology(topic: str, context: CallContext) -> dict[str, object]:
    from etf_cockpit.application.status_views import read_methodology_resource

    try:
        return read_methodology_resource(_root(context), topic)
    except ValueError:
        raise MCPToolError("RESOURCE_TOPIC_UNAVAILABLE", "The methodology topic is not allow-listed", "Use score_engine_v3, forecast_promotion, glossary, or forward_evidence_diary.") from None
    except Exception as exc:
        return {"status": "unavailable", "topic": topic, "unavailable_reason": f"methodology unavailable ({type(exc).__name__})", "execution_allowed": False}


def _read_export(raw_path: str, context: CallContext) -> dict[str, object]:
    relative = Path(raw_path)
    if relative.is_absolute() or not raw_path or any(part in {"..", ""} for part in relative.parts):
        raise MCPToolError("RESOURCE_PATH_INVALID", "The export path is not a safe root-relative path", "Use a path returned by a local report or export tool.")
    root = _root(context)
    allowed = False
    path = (root / relative).resolve()
    for prefix in _EXPORT_PREFIXES:
        try:
            path.relative_to((root / prefix).resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed or path.suffix.casefold() not in _EXPORT_EXTENSIONS:
        raise MCPToolError("RESOURCE_PATH_INVALID", "Only allow-listed text exports can be read", "Use a JSON, CSV, Markdown or text export under an approved local export directory.")
    try:
        if not path.is_file() or path.stat().st_size > _EXPORT_LIMIT_BYTES:
            return {"status": "unavailable", "unavailable_reason": "export is missing or exceeds the 1 MiB resource limit", "execution_allowed": False}
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {"status": "unavailable", "unavailable_reason": f"export could not be read ({type(exc).__name__})", "execution_allowed": False}
    if path.suffix.casefold() == ".json":
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return {"status": "unavailable", "unavailable_reason": "export JSON is invalid", "execution_allowed": False}
    return {"status": "available", "path": relative.as_posix(), "content": content, "execution_allowed": False}


__all__ = ["RESOURCE_SPECS", "ResourceSpec", "read_resource", "resource_specs"]
