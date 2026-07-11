from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defusedxml import ElementTree

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


@dataclass(frozen=True)
class XbrlFact:
    entity_lei: str
    concept: str
    value: str
    unit: str | None
    decimals: str | None
    context_id: str | None
    period_start: str | None
    period_end: str | None
    source_location: str
    mapping_status: str


_IFRS_MAPPING = {
    "Revenue": "revenue",
    "ProfitLoss": "profit_loss",
    "Assets": "assets",
    "Equity": "equity",
}


def parse_esef_package(path: Path) -> ParseResult[XbrlFact]:
    source_sha = _sha256_file(path) if path.exists() else ""
    warnings: list[ParseWarning] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            unsafe = [name for name in names if _unsafe_name(name)]
            if unsafe:
                return _failure(source_sha, "unsafe_archive", "ESEF package contains traversal or absolute paths")
            if sum(info.file_size for info in archive.infolist()) > 250 * 1024 * 1024:
                return _failure(source_sha, "archive_too_large", "ESEF package exceeds the uncompressed size limit")
            report_package = next((name for name in names if name.endswith("reportPackage.json")), None)
            xhtml_name = next((name for name in names if name.lower().endswith((".xhtml", ".html"))), None)
            if report_package is None or xhtml_name is None:
                return _failure(source_sha, "unsupported_package", "ESEF package lacks reportPackage.json or XHTML report")
            metadata = json.loads(archive.read(report_package).decode("utf-8"))
            entity_lei = _extract_lei(metadata, names)
            period_end = _extract_period(metadata, names)
            root = ElementTree.fromstring(archive.read(xhtml_name))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError, ElementTree.ParseError) as exc:
        return _failure(source_sha, "malformed_archive", f"Could not parse ESEF package: {type(exc).__name__}")

    facts: list[XbrlFact] = []
    for element in root.iter():
        local_name = _local_name(element.tag)
        if local_name not in {"nonFraction", "nonNumeric"}:
            continue
        concept = str(element.attrib.get("name") or "").split(":")[-1]
        value = "".join(element.itertext()).strip()
        if not concept or not value:
            continue
        context_id = element.attrib.get("contextRef")
        mapping = map_ifrs_fact(concept)
        if mapping is None and ":" in str(element.attrib.get("name") or ""):
            mapping_status = "unmapped_extension"
            warnings.append(ParseWarning("unmapped_extension", f"Extension fact retained without canonical mapping: {concept}", "warning", xhtml_name))
        else:
            mapping_status = mapping or "unmapped"
        facts.append(XbrlFact(entity_lei, concept, value, element.attrib.get("unitRef"), element.attrib.get("decimals"), context_id, None, period_end, xhtml_name, mapping_status))
    try:
        import arelle  # noqa: F401
    except Exception:
        warnings.append(ParseWarning("arelle_unavailable", "Arelle validation adapter is unavailable; XML facts were still parsed locally", "warning"))
    return ParseResult(tuple(facts), tuple(warnings), "esef_ixbrl", "1.0", source_sha, bool(facts))


def map_ifrs_fact(concept: str) -> str | None:
    return _IFRS_MAPPING.get(str(concept).split(":")[-1])


def _failure(source_sha: str, code: str, message: str) -> ParseResult[XbrlFact]:
    return ParseResult((), (ParseWarning(code, message, "error"),), "esef_ixbrl", "1.0", source_sha, False)


def _unsafe_name(name: str) -> bool:
    normal = name.replace("\\", "/")
    return normal.startswith("/") or re.match(r"^[A-Za-z]:/", normal) is not None or ".." in Path(normal).parts


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _extract_lei(metadata: Any, names: list[str]) -> str:
    text = json.dumps(metadata) + " " + " ".join(names)
    match = re.search(r"\b[A-Z0-9]{20}\b", text)
    return match.group(0) if match else "unknown"


def _extract_period(metadata: Any, names: list[str]) -> str | None:
    text = json.dumps(metadata) + " " + " ".join(names)
    match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    return match.group(0) if match else None
