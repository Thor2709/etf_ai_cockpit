"""Small, fail-closed ESEF/iXBRL report-package parser.

The parser deliberately extracts only facts that are present in the retained
XHTML instance.  Taxonomy validation is optional (Arelle is imported lazily)
and never promotes an extension concept to an IFRS canonical metric.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import multiprocessing
import queue
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # The parser remains usable in the base install without parser extras.
    from defusedxml import ElementTree
except ImportError:  # pragma: no cover - exercised in the base test environment
    from xml.etree import ElementTree  # noqa: S405

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_MEMBER_BYTES = 100 * 1024 * 1024
PARSER_VERSION = "1.1"
_ALLOWED_MEMBER_SUFFIXES = frozenset({".json", ".xhtml", ".html", ".xml", ".xsd", ".css", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".txt"})


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
    context_dimensions: tuple[tuple[str, str], ...] = ()
    namespace: str | None = None


_IFRS_MAPPING = {
    "Revenue": "revenue",
    "ProfitLoss": "profit_loss",
    "Assets": "assets",
    "Equity": "equity",
    "NetIncomeLoss": "net_income",
    "CashAndCashEquivalents": "cash",
}
_IFRS_PREFIXES = frozenset({"ifrs-full", "ifrs"})


def parse_esef_package(path: Path) -> ParseResult[XbrlFact]:
    """Parse a local ESEF ``.xbri``/ZIP package without extracting it to disk."""

    source_sha = _safe_sha(path)
    warnings: list[ParseWarning] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            unsafe = [info.filename for info in infos if _unsafe_name(info.filename)]
            if unsafe:
                return _failure(source_sha, "unsafe_archive", "ESEF package contains traversal, absolute or backslash paths")
            total_size = sum(max(0, info.file_size) for info in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES or any(info.file_size > MAX_MEMBER_BYTES for info in infos):
                return _failure(source_sha, "archive_too_large", "ESEF package exceeds the uncompressed size limit")
            names = [info.filename for info in infos]
            unsupported = [name for name in names if Path(name).suffix and Path(name).suffix.lower() not in _ALLOWED_MEMBER_SUFFIXES]
            if unsupported:
                return _failure(source_sha, "unsupported_member", "ESEF package contains unsupported member types")
            report_package = _first_member(names, "reportpackage.json")
            xhtml_name = next((name for name in names if name.lower().endswith((".xhtml", ".html"))), None)
            if report_package is None or xhtml_name is None:
                return _failure(source_sha, "unsupported_package", "ESEF package lacks reportPackage.json or XHTML report")
            try:
                metadata = json.loads(archive.read(report_package).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return _failure(source_sha, "malformed_archive", f"Could not parse ESEF package metadata: {type(exc).__name__}")
            if not isinstance(metadata, dict):
                return _failure(source_sha, "malformed_archive", "ESEF reportPackage.json must contain an object")
            if not any(name.lower().endswith("taxonomypackage.xml") for name in names):
                warnings.append(ParseWarning("missing_taxonomy_package", "ESEF taxonomyPackage.xml is missing; facts remain retained with bounded local parsing", "warning", report_package))
            xhtml_payload = archive.read(xhtml_name)
            if b"<!DOCTYPE" in xhtml_payload.upper() or b"<!ENTITY" in xhtml_payload.upper():
                return _failure(source_sha, "unsafe_xml", "ESEF XHTML contains a disallowed document type or entity declaration")
            namespace_map = _extract_namespaces(xhtml_payload)
            root = ElementTree.fromstring(xhtml_payload)
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, ElementTree.ParseError) as exc:
        return _failure(source_sha, "malformed_archive", f"Could not parse ESEF package: {type(exc).__name__}")

    contexts = _contexts(root)
    default_lei = _extract_lei(metadata, names) or next((item["entity_lei"] for item in contexts.values() if item["entity_lei"] != "unknown"), "unknown")
    period_hint = _extract_period(metadata, names)
    facts: list[XbrlFact] = []
    seen: set[tuple[object, ...]] = set()
    warned_extensions: set[str] = set()
    for element in root.iter():
        local_name = _local_name(element.tag)
        if local_name not in {"nonFraction", "nonNumeric"}:
            continue
        raw_name = str(element.attrib.get("name") or "").strip()
        concept, prefix = _split_qname(raw_name)
        value = "".join(element.itertext()).strip()
        if not concept or not value:
            continue
        context_id = _optional_text(element.attrib.get("contextRef"))
        context = contexts.get(context_id or "", {})
        unit = _optional_text(element.attrib.get("unitRef"))
        decimals = _optional_text(element.attrib.get("decimals"))
        duplicate_key = (raw_name, value, unit, decimals, context_id, context.get("period_start"), context.get("period_end"))
        if duplicate_key in seen:
            warnings.append(ParseWarning("duplicate_fact", f"Duplicate ESEF fact ignored: {raw_name}", "warning", xhtml_name))
            continue
        seen.add(duplicate_key)
        namespace = namespace_map.get(prefix or "") or _namespace_for_prefix(prefix)
        mapping = map_ifrs_fact(raw_name, namespace)
        is_extension = bool(prefix and prefix.lower() not in _IFRS_PREFIXES)
        if is_extension:
            mapping_status = "unmapped_extension"
            if raw_name not in warned_extensions:
                warnings.append(ParseWarning("unmapped_extension", f"Extension fact retained without canonical mapping: {raw_name}", "warning", xhtml_name))
                warned_extensions.add(raw_name)
        else:
            mapping_status = "mapped" if mapping else "unmapped"
        facts.append(
            XbrlFact(
                default_lei if context.get("entity_lei", "unknown") == "unknown" else str(context["entity_lei"]),
                concept,
                value,
                unit,
                decimals,
                context_id,
                context.get("period_start"),
                context.get("period_end") or period_hint,
                xhtml_name,
                mapping_status,
                tuple(context.get("dimensions", ())),
                namespace,
            )
        )

    arelle_ok = True
    if not _arelle_available():
        warnings.append(ParseWarning("arelle_unavailable", "Arelle validation adapter is unavailable; XML facts were parsed locally without invented authority", "warning"))
    else:
        try:
            validation_messages = _run_arelle_validation(path, 8.0)
        except TimeoutError as exc:
            arelle_ok = False
            warnings.append(ParseWarning("arelle_timeout", str(exc), "error"))
            validation_messages = ()
        except Exception as exc:
            arelle_ok = False
            warnings.append(ParseWarning("arelle_validation", f"Arelle validation failed: {type(exc).__name__}: {exc}", "error"))
            validation_messages = ()
        loader_limitation = _has_arelle_loader_limitation(validation_messages)
        for message in validation_messages:
            severity = str(message.get("severity") or "warning")
            code = str(message.get("code") or "arelle_validation")
            text = str(message.get("message") or "Arelle validation message")
            if _is_nonfatal_arelle_diagnostic(code, text, loader_limitation=loader_limitation):
                severity = "warning"
            if severity.lower() in {"error", "fatal"}:
                code = "arelle_validation"
            warnings.append(ParseWarning(code, text, severity))
            if severity.lower() in {"error", "fatal"}:
                arelle_ok = False
    return ParseResult(tuple(facts), tuple(warnings), "esef_ixbrl", PARSER_VERSION, source_sha, bool(facts) and arelle_ok)


def map_ifrs_fact(concept: str, namespace: str | None = None) -> str | None:
    """Return a canonical metric only for explicit IFRS concepts."""

    local, prefix = _split_qname(str(concept))
    if prefix and prefix.lower() not in _IFRS_PREFIXES:
        return None
    if namespace and "ifrs" not in namespace.lower():
        return None
    return _IFRS_MAPPING.get(local)


def _failure(source_sha: str, code: str, message: str) -> ParseResult[XbrlFact]:
    return ParseResult((), (ParseWarning(code, message, "error"),), "esef_ixbrl", PARSER_VERSION, source_sha, False)


def _unsafe_name(name: str) -> bool:
    if "\\" in name or "\x00" in name:
        return True
    normal = name.replace("\\", "/")
    return normal.startswith("/") or re.match(r"^[A-Za-z]:/", normal) is not None or ".." in Path(normal).parts


def _first_member(names: list[str], suffix: str) -> str | None:
    return next((name for name in names if name.lower().endswith(suffix)), None)


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _split_qname(value: str) -> tuple[str, str | None]:
    if ":" not in value:
        return value, None
    prefix, local = value.split(":", 1)
    return local, prefix


def _namespace_for_prefix(prefix: str | None) -> str | None:
    if prefix and prefix.lower() in _IFRS_PREFIXES:
        return "https://xbrl.ifrs.org/taxonomy/ifrs-full"
    return None


def _extract_namespaces(payload: bytes) -> dict[str, str]:
    text = payload.decode("utf-8", errors="ignore")
    return {prefix: uri for prefix, uri in re.findall(r"xmlns:([A-Za-z_][\w.-]*)\s*=\s*['\"]([^'\"]+)['\"]", text)}


def _contexts(root: Any) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for element in root.iter():
        if _local_name(element.tag) != "context":
            continue
        context_id = _optional_text(element.attrib.get("id"))
        if not context_id:
            continue
        entity_lei = "unknown"
        period_start: str | None = None
        period_end: str | None = None
        dimensions: list[tuple[str, str]] = []
        for child in element.iter():
            name = _local_name(child.tag)
            text = _optional_text("".join(child.itertext()))
            if name == "identifier" and text:
                entity_lei = text
            elif name == "startDate":
                period_start = text
            elif name in {"endDate", "instant"}:
                period_end = text
            elif name in {"explicitMember", "typedMember"} and text:
                dimensions.append((_optional_text(child.attrib.get("dimension")) or "unknown", text))
        contexts[context_id] = {"entity_lei": entity_lei, "period_start": period_start, "period_end": period_end, "dimensions": tuple(dimensions)}
    return contexts


def _extract_lei(metadata: Any, names: list[str]) -> str | None:
    text = json.dumps(metadata) + " " + " ".join(names)
    match = re.search(r"\b[A-Z0-9]{20}\b", text)
    return match.group(0) if match else None


def _extract_period(metadata: Any, names: list[str]) -> str | None:
    text = json.dumps(metadata) + " " + " ".join(names)
    match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    return match.group(0) if match else None


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_sha(path: Path) -> str:
    try:
        return _sha256_file(path)
    except OSError:
        return ""


def _has_arelle_loader_limitation(messages: tuple[dict[str, str], ...]) -> bool:
    """Return whether this validation run recorded a bounded loader limitation."""

    for message in messages:
        code = str(message.get("code") or "").strip().lower()
        text = str(message.get("message") or "")
        if code in {"ioerror", "filenotloadable", "webcache:retrievalerror", "arelle:notvalidated"}:
            return True
        if code == "exception:attributeerror" and "formulaoptions" in text.lower():
            return True
    return False


def _is_nonfatal_arelle_diagnostic(code: str, message: str, *, loader_limitation: bool = False) -> bool:
    """Classify validator limitations that do not invalidate local facts.

    Arelle is optional and its report-package/XHTML loader can emit errors for
    missing remote taxonomy references or package formats it cannot validate as
    a standalone instance.  The bounded local parser has already validated the
    archive and extracted facts, so these diagnostics remain visible as
    warnings rather than discarding otherwise usable offline evidence.  Other
    validation errors remain blocking.
    """

    normalised_code = code.strip().lower()
    if normalised_code in {
        "ioerror",
        "filenotloadable",
        "webcache:retrievalerror",
        "arelle:notvalidated",
    }:
        return True
    if normalised_code == "ix11.12.1.2:missingreferences":
        # A report package can be parsed locally while Arelle cannot retrieve
        # an external taxonomy in offline mode.  Only a correlated loader
        # diagnostic permits this rule to become a warning; a standalone
        # conformance error remains blocking.
        lowered_message = message.lower()
        explicit_conformance = any(
            marker in lowered_message
            for marker in ("required reference", "submitted report", "local reference", "schema definition")
        )
        return loader_limitation and not explicit_conformance
    return normalised_code == "exception:attributeerror" and "formulaoptions" in message.lower()


def _arelle_available() -> bool:
    return importlib.util.find_spec("arelle") is not None


def _run_arelle_validation(path: Path, timeout_seconds: float = 8.0) -> tuple[dict[str, str], ...]:
    """Run optional Arelle validation in a bounded child process."""

    context = multiprocessing.get_context("spawn")
    messages: multiprocessing.Queue[dict[str, object]] = context.Queue()
    process = context.Process(target=_arelle_worker, args=(str(path), messages))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(1.0)
        raise TimeoutError("Arelle validation exceeded the bounded timeout")
    try:
        result = messages.get(timeout=1.0)
    except queue.Empty:
        return ({"code": "arelle_validation", "severity": "error", "message": "Arelle exited without a validation result"},)
    status = str(result.get("status", "error"))
    if status in {"ok", "validation_error"}:
        normalised: list[dict[str, str]] = []
        for message in result.get("messages", ()) or ():
            if isinstance(message, dict):
                normalised.append(
                    {
                        "code": str(message.get("code") or "arelle_validation"),
                        "severity": str(message.get("severity") or ("error" if status == "validation_error" else "warning")),
                        "message": str(message.get("message") or "Arelle validation message"),
                    }
                )
            else:
                normalised.append({"code": "arelle_message", "severity": "warning", "message": str(message)})
        return tuple(normalised)
    return (
        {
            "code": str(result.get("code") or "arelle_validation"),
            "severity": "error",
            "message": str(result.get("message", "Arelle validation failed")),
        },
    )


def _arelle_worker(path: str, messages: multiprocessing.Queue[dict[str, object]]) -> None:
    try:
        from arelle import Cntlr

        controller = Cntlr.Cntlr(logFileName="logToPrint")
        logger = getattr(controller, "logger", None)
        logger = logger if isinstance(logger, logging.Logger) else logging.getLogger("arelle")
        capture = _ArelleLogHandler()
        logger.addHandler(capture)
        logger.setLevel(min(logger.level or logging.WARNING, logging.INFO))
        try:
            model = controller.modelManager.load(path)
            if model is None:
                raise RuntimeError("Arelle did not load the report package")
            validator = getattr(controller.modelManager, "validate", None)
            if callable(validator):
                validator()
            else:
                validator = getattr(model, "validate", None)
                if callable(validator):
                    validator()
        finally:
            logger.removeHandler(capture)
        captured = tuple(capture.messages)
        if not captured:
            fallback_errors = getattr(model, "errors", ())
            captured = tuple({"code": "arelle_validation", "severity": "error", "message": str(error)} for error in fallback_errors or ())
        if any(message["severity"] in {"error", "fatal"} for message in captured):
            messages.put(
                {
                    "status": "validation_error",
                    "messages": captured,
                }
            )
        else:
            messages.put({"status": "ok", "messages": captured})
    except Exception as exc:
        messages.put(
            {
                "status": "error",
                "code": f"exception:{type(exc).__name__}",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )


class _ArelleLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        severity = "error" if record.levelno >= logging.ERROR else "warning"
        self.messages.append(
            {
                "code": str(getattr(record, "messageCode", None) or getattr(record, "code", None) or "arelle_validation"),
                "severity": severity,
                "message": record.getMessage(),
            }
        )
