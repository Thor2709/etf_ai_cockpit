"""Reviewed ESEF extension-concept and equity-member mappings (data-driven, SB2).

The mappings live in ``configs/esef_extension_concepts.yaml``; nothing here is issuer-specific code.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
import re

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "esef_extension_concepts.yaml"
_COMPONENTS_AXIS = "ifrs-full:ComponentsOfEquityAxis"
_MAX_MEMBER_NAME = 70


def load_config(path: Path | None = None) -> dict[str, object]:
    try:
        payload = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def issuer_extension(instrument_id: str, records: Iterable[object], *, path: Path | None = None) -> tuple[str | None, dict[str, dict[str, object]]]:
    """(namespace, {local concept name: rule}) for one issuer; the namespace is the one the filing actually uses."""

    issuers = load_config(path).get("issuers")
    entry = issuers.get(str(instrument_id).upper()) if isinstance(issuers, Mapping) else None
    if not isinstance(entry, Mapping) or not isinstance(entry.get("concepts"), Mapping):
        return None, {}
    prefix = str(entry.get("namespace_prefix") or "").casefold()
    counts = Counter(
        str(getattr(record, "namespace", "") or "")
        for record in records
        if prefix and str(getattr(record, "namespace", "") or "").casefold().startswith(prefix)
    )
    if not counts:
        return None, {}
    rules = {str(name): dict(rule) for name, rule in entry["concepts"].items() if isinstance(rule, Mapping) and rule.get("metric")}
    return counts.most_common(1)[0][0], rules


def _member_local_name(member: str) -> str:
    return str(member).rsplit(":", 1)[-1]


def equity_member_facts(records: Iterable[object], period: str, *, path: Path | None = None) -> dict[str, dict[str, object]]:
    """EC pool facts from equity-component members at the period end (one match per pool, else none)."""

    rules = load_config(path).get("equity_member_rules")
    if not isinstance(rules, Mapping):
        return {}
    compiled = {str(name): re.compile(str(pattern)) for name, pattern in rules.items()}
    found: dict[str, list[tuple[object, str]]] = {}
    for record in records:
        if getattr(record, "concept", "") != "Equity" or not getattr(record, "is_numeric", True):
            continue
        if str(getattr(record, "period_end", "") or "") != period or getattr(record, "period_start", None):
            continue
        if str(getattr(record, "consolidation_scope", "") or "").casefold() != "consolidated":
            continue
        dimensions = tuple(getattr(record, "context_dimensions", ()) or ())
        if len(dimensions) != 1 or dimensions[0][0] != _COMPONENTS_AXIS:
            continue
        local = _member_local_name(dimensions[0][1])
        if len(local) > _MAX_MEMBER_NAME:
            continue
        matches = [name for name, pattern in compiled.items() if pattern.search(local)]
        if len(matches) == 1:
            found.setdefault(matches[0], []).append((record, local))
    facts: dict[str, dict[str, object]] = {}
    for name, items in found.items():
        if len(items) != 1:
            continue
        record, local = items[0]
        context_id = str(getattr(record, "context_id", "") or "") or None
        facts[name] = {
            "value": getattr(record, "value", None),
            "source_locator": f"{getattr(record, 'source_location', '')}#fact=ifrs-full:Equity;member={local};context={context_id or 'unavailable'}",
            "concept": f"ifrs-full:Equity[{local}]",
            "context": context_id,
            "unit": str(getattr(record, "unit", "")),
            "period": period,
            "start": None,
            "end": period,
            "dimensions": tuple(getattr(record, "context_dimensions", ()) or ()),
            "consolidation_scope": str(getattr(record, "consolidation_scope", "")),
        }
    return facts
