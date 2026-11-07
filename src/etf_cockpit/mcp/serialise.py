"""JSON-safe MCP output conversion.

Open defaults: dataframes are capped at 500 rows; naive datetimes are treated as UTC.
All values use the shared session-log redaction implementation before JSON encoding.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from etf_cockpit.core.session_log import _redact as redact_secrets
from etf_cockpit.mcp.envelope import Envelope, Provenance


DEFAULT_DATAFRAME_ROW_CAP = 500
RESPONSE_CHAR_LIMIT = 32_000


def response_char_limit() -> int:
    """Read and validate the complete tools/call result budget."""
    variable = "ETF_COCKPIT_MCP_MAX_CHARS"
    try:
        limit = int(os.environ.get(variable, str(RESPONSE_CHAR_LIMIT)))
    except ValueError:
        raise ValueError(f"{variable} must be an integer from 4000 to 200000") from None
    if not 4000 <= limit <= 200_000:
        raise ValueError(f"{variable} must be an integer from 4000 to 200000")
    return limit


def normalise(value: Any, *, dataframe_row_cap: int = DEFAULT_DATAFRAME_ROW_CAP) -> Any:
    """Convert supported domain values into JSON-safe primitives without replacing gaps with zero."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return normalise(value.model_dump(mode="python"), dataframe_row_cap=dataframe_row_cap)
    if is_dataclass(value) and not isinstance(value, type):
        return normalise(asdict(value), dataframe_row_cap=dataframe_row_cap)
    if isinstance(value, Mapping):
        return {str(key): normalise(item, dataframe_row_cap=dataframe_row_cap) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalise(item, dataframe_row_cap=dataframe_row_cap) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((normalise(item, dataframe_row_cap=dataframe_row_cap) for item in value), key=repr)

    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            return [normalise(row, dataframe_row_cap=dataframe_row_cap) for row in value.head(dataframe_row_cap).to_dict("records")]
        if value is pd.NA or value is pd.NaT:
            return None
    except ImportError:
        pass

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return normalise(item_method(), dataframe_row_cap=dataframe_row_cap)
        except (TypeError, ValueError):
            pass
    return str(value)


def canonical_json(value: Any) -> str:
    safe_value = redact_secrets(normalise(value))
    return json.dumps(safe_value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def to_json(value: Any) -> str:
    return json.dumps(redact_secrets(normalise(value)), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def build_envelope(
    data: Any,
    *,
    data_as_of: datetime | str | None = None,
    freshness: str | None = None,
    gate_summary: Any = None,
    warnings: list[str] | None = None,
    unavailable_reason: str | None = None,
    provenance: Provenance | Mapping[str, Any] | None = None,
    next_cursor: str | None = None,
) -> Envelope:
    """Wrap one tool result; a returned next_cursor is promoted into the envelope."""

    payload = normalise(data)
    if isinstance(payload, Mapping):
        payload = dict(payload)
        if next_cursor is None:
            candidate = payload.pop("next_cursor", None)
            next_cursor = candidate if isinstance(candidate, str) else None
        if unavailable_reason is None:
            candidate = payload.pop("unavailable_reason", None)
            unavailable_reason = candidate if isinstance(candidate, str) else None
    safe_provenance = provenance if isinstance(provenance, Provenance) else Provenance(**(dict(provenance) if provenance else {}))
    return Envelope(
        data_as_of=data_as_of,
        freshness=freshness,
        gate_summary=normalise(gate_summary),
        warnings=list(warnings or ()),
        unavailable_reason=unavailable_reason,
        provenance=safe_provenance,
        next_cursor=next_cursor,
        data=redact_secrets(payload),
    )


def envelope_dict(envelope: Envelope) -> dict[str, Any]:
    """Return the full contract shape, preserving explicit null metadata fields."""

    return redact_secrets(normalise(envelope.model_dump(mode="python")))


def tool_result_dict(result: Any) -> dict[str, Any]:
    """Build both protocol representations without the optional SDK's pretty JSON."""
    envelope = result if isinstance(result, Envelope) else build_envelope(result)
    structured = envelope_dict(envelope)
    return {
        "content": [{"type": "text", "text": to_json(structured)}],
        "structuredContent": structured,
        "isError": False,
    }


def enforce_response_budget(result: Any, *, root: Path) -> Any:
    """Budget the complete tools/call result once, after natural pagination.

    Oversized results retain their full redacted envelope in a root-local JSON
    resource, available for 24 hours. The inline result contains only bounded
    summaries and a preview; it never substitutes values for missing evidence.
    """
    limit = response_char_limit()

    def fits(value: Any) -> bool:
        # Plain values are enveloped again by the transport. Allow for the
        # fractional timestamp growing by seven characters in each copy.
        timestamp_margin = 0 if isinstance(value, Envelope) else 14
        encoded_result = json.dumps(tool_result_dict(value), ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        return len(encoded_result) + timestamp_margin <= limit

    envelope = result if isinstance(result, Envelope) else build_envelope(result)
    full = envelope_dict(envelope)
    encoded = to_json(full)
    if fits(result):
        return result

    from etf_cockpit.mcp.resources import write_overflow

    link = write_overflow(root, encoded)
    payload = full["data"]
    collections = []

    def count_rows(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                count_rows(item)
        elif isinstance(value, list):
            collections.append(len(value))

    count_rows(payload)
    rows_total = max(collections, default=0)
    if isinstance(payload, dict) and isinstance(payload.get("rows_total"), int):
        rows_total = payload["rows_total"]
    summary = {
        key[:80]: _bounded_preview(value)
        for key, value in list(payload.items())[:20]
        if not isinstance(value, (dict, list))
    } if isinstance(payload, dict) else {}
    compact = {
        **summary,
        "rows_total": rows_total,
        "preview": _bounded_preview(payload),
        "truncated": True,
        "resource_link": link,
        "execution_allowed": False,
        "next_cursor": envelope.next_cursor if envelope.next_cursor and len(envelope.next_cursor) <= 2048 else None,
    }
    if not fits(compact):
        compact["preview"] = _bounded_preview(payload, depth=2)
    if not fits(compact):
        compact["preview"] = None
    if not fits(compact):
        compact = {key: compact[key] for key in ("rows_total", "truncated", "resource_link", "execution_allowed", "next_cursor")}
    if not fits(compact):
        compact["next_cursor"] = None
    if not fits(compact):
        from etf_cockpit.mcp.errors import MCPToolError

        raise MCPToolError("RESPONSE_BUDGET_EXCEEDED", "The overflow summary exceeds the response budget", "Read the overflow resource.")
    if isinstance(result, Envelope):
        # Oversized metadata is available in the full resource as well.
        return build_envelope(compact)
    return compact


def _bounded_preview(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {key[:80]: _bounded_preview(item, depth + 1) for key, item in list(value.items())[:5]} if depth < 3 else {}
    if isinstance(value, list):
        return [_bounded_preview(item, depth + 1) for item in value[:3]] if depth < 3 else []
    return value[:160] if isinstance(value, str) else value
