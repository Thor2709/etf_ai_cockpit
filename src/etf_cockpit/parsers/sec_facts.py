from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


@dataclass(frozen=True)
class StatementFact:
    instrument_id: str
    cik: str
    taxonomy: str
    concept: str
    unit: str
    value: float | int | str
    start: str | None
    end: str | None
    instant: str | None
    filed: str | None
    form: str | None
    accession: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    source_id: str


_CONCEPTS = {"Revenue", "Revenues", "Assets", "AssetsCurrent", "NetIncomeLoss", "StockholdersEquity"}


def parse_companyfacts(path: Path, identity: CanonicalIdentity) -> ParseResult[StatementFact]:
    source_sha = _sha256_file(path)
    warnings: list[ParseWarning] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ParseResult((), (ParseWarning("malformed_json", f"Could not read SEC companyfacts: {type(exc).__name__}", "error"),), "sec_companyfacts", "1.0", source_sha, False)
    cik = str(payload.get("cik") or payload.get("cik_str") or "").lstrip("0") or "0"
    expected_cik = str(getattr(identity, "cik", "") or "").lstrip("0") or "0"
    if expected_cik not in {"0", cik}:
        return ParseResult((), (ParseWarning("identity_mismatch", f"SEC CIK {cik} does not match requested identity", "error"),), "sec_companyfacts", "1.0", source_sha, False)
    facts_root = payload.get("facts")
    if not isinstance(facts_root, dict):
        return ParseResult((), (ParseWarning("schema_error", "SEC facts object is missing", "error"),), "sec_companyfacts", "1.0", source_sha, False)
    records: list[StatementFact] = []
    for taxonomy, concepts in facts_root.items():
        if not isinstance(concepts, dict):
            continue
        for concept, definition in concepts.items():
            if concept not in _CONCEPTS or not isinstance(definition, dict):
                continue
            units = definition.get("units")
            if not isinstance(units, dict) or not units:
                warnings.append(ParseWarning("missing_unit", f"{concept} has no unit records", "warning"))
                continue
            if len(units) != 1:
                warnings.append(ParseWarning("ambiguous_unit", f"{concept} has multiple unit types", "warning", concept))
                continue
            unit, entries = next(iter(units.items()))
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or "val" not in entry:
                    continue
                value = entry["val"]
                source_id = f"sec:{entry.get('accn') or entry.get('filed') or concept}:{concept}:{entry.get('end') or entry.get('fy') or ''}"
                records.append(
                    StatementFact(
                        instrument_id=identity.instrument_id,
                        cik=cik,
                        taxonomy=str(taxonomy),
                        concept=str(concept),
                        unit=str(unit),
                        value=value,
                        start=_string(entry.get("start")),
                        end=_string(entry.get("end")),
                        instant=_string(entry.get("instant")),
                        filed=_string(entry.get("filed")),
                        form=_string(entry.get("form")),
                        accession=_string(entry.get("accn")),
                        fiscal_year=_int(entry.get("fy")),
                        fiscal_period=_string(entry.get("fp")),
                        source_id=source_id,
                    )
                )
    return ParseResult(tuple(records), tuple(warnings), "sec_companyfacts", "1.0", source_sha, True)


def _string(value: Any) -> str | None:
    return None if value is None else str(value)


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
