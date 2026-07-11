"""Static checks for the local-only, no-execution boundary.

The checker deliberately works on source and configuration context rather than
searching for every occurrence of words such as ``broker`` or ``order``.  The
application already contains harmless data-import and back-test vocabulary, so
only executable symbols, known SDKs, order endpoints, authority flags and
credential resources are rejected.
"""

from __future__ import annotations

import ast
import configparser
import hashlib
import json
import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0"
REJECTION_REGISTRY_RELATIVE_PATH = Path("configs") / "rejection_registry.yaml"
MAX_TEXT_FILE_BYTES = 4 * 1024 * 1024

_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
    }
)
_EXCLUDED_ROOT_DIRECTORIES = frozenset(
    {
        "backups",
        "data",
        "evidence",
        "exports",
        "issues",
        "logs",
        "models",
    }
)
_TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".env",
        ".ini",
        ".json",
        ".key",
        ".markdown",
        ".md",
        ".p12",
        ".pem",
        ".pfx",
        ".py",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_MANIFEST_NAMES = frozenset(
    {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-models.txt",
        "requirements-parsers.txt",
        "setup.cfg",
        "setup.py",
        "package.json",
    }
)
_CONFIG_SUFFIXES = frozenset({".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"})
_ENV_FILE_NAMES = frozenset({".env", ".env.local"})
_CREDENTIAL_SUFFIXES = frozenset({".key", ".p12", ".pem", ".pfx"})
_FUTURE_DOCUMENT_SUFFIXES = frozenset({".md", ".markdown"})
_PROHIBITED_ORDER_SYMBOLS = frozenset(
    {
        "broker_adapter",
        "broker_client",
        "broker_order",
        "cancel_order",
        "create_order",
        "execute_order",
        "execute_trade",
        "modify_order",
        "order_request",
        "order_router",
        "order_routing",
        "order_submission",
        "place_order",
        "place_trade",
        "replace_order",
        "route_order",
        "send_order",
        "send_trade",
        "submit_order",
        "submit_trade",
        "trade_execution",
        "transmit_order",
    }
)
_PROHIBITED_IMPORTS = frozenset(
    {
        "alpaca_trade_api",
        "broker_sdk",
        "ccxt",
        "ib_async",
        "ib_insync",
        "interactive_brokers",
        "kiteconnect",
        "oandapy",
        "robin_stocks",
        "tda_api",
        "tradeapi",
        "tradier",
    }
)
_PROHIBITED_DEPENDENCIES = frozenset(
    {
        "alpaca-trade-api",
        "alpaca_trade_api",
        "broker-sdk",
        "broker_sdk",
        "ccxt",
        "ib-async",
        "ib_async",
        "ib-insync",
        "ib_insync",
        "interactive-brokers",
        "interactive_brokers",
        "kiteconnect",
        "oandapy",
        "robin-stocks",
        "robin_stocks",
        "tda-api",
        "tda_api",
        "tradeapi",
        "tradier",
    }
)
_ORDER_ENDPOINT_RE = re.compile(r"(?i)(?:^|/)(?:orders?|order-entry)(?:[/?#]|$)")
_UI_ORDER_CONTROL_RE = re.compile(
    r"(?i)^\s*(?:place|submit|execute|send|cancel|replace)\s+(?:a\s+)?(?:broker\s+)?order\b"
    r"|^\s*(?:buy|sell)\s+(?:now|order)\b"
    r"|^\s*(?:buy|submit|cancel|replace)\s*$"
)
_UI_SHORT_ORDER_CONTROL_RE = re.compile(r"(?i)^\s*(?:buy|submit|cancel|replace)\s*$")
_PROHIBITED_CREDENTIAL_NAME_RE = re.compile(
    r"(?i)(?:broker|order|execution).*(?:api[_-]?key|secret|token|password|private[_-]?key)"
    r"|(?:api[_-]?key|secret|token|password|private[_-]?key).*(?:broker|order|execution)"
)
_ENDPOINT_NAME_RE = re.compile(r"(?i)(?:broker|order|execution).*(?:endpoint|url)")
_PLACEHOLDER_VALUES = frozenset({"", "none", "null", "example", "changeme", "placeholder", "***"})


_POLICY = {
    "schema_version": SCHEMA_VERSION,
    "allow_list": ["docs/architecture/future/*.md", "docs/architecture/future/*.markdown", "tests/**"],
    "excluded_directories": sorted(_EXCLUDED_DIRECTORIES),
    "excluded_runtime_roots": sorted(_EXCLUDED_ROOT_DIRECTORIES),
    "prohibited_order_symbols": sorted(_PROHIBITED_ORDER_SYMBOLS),
    "prohibited_imports": sorted(_PROHIBITED_IMPORTS),
    "prohibited_dependencies": sorted(_PROHIBITED_DEPENDENCIES),
    "authority_flags": ["execution_allowed", "executable_authority"],
    "violation_codes": [
        "EXECUTION_AUTHORITY_ENABLED",
        "PROHIBITED_BROKER_DEPENDENCY",
        "PROHIBITED_CREDENTIAL_RESOURCE",
        "PROHIBITED_ORDER_ENDPOINT",
        "PROHIBITED_ORDER_SYMBOL",
        "PROHIBITED_UI_ORDER_CONTROL",
        "REJECTION_REGISTRY_INVALID",
    ],
}
POLICY_CHECKSUM = hashlib.sha256(
    json.dumps(_POLICY, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


class BoundaryViolation(BaseModel):
    """One deterministic, source-located violation of the execution policy."""

    model_config = ConfigDict(extra="forbid")

    code: str
    path: str
    line: int | None = None
    column: int | None = None
    message: str
    evidence: str | None = None

    @property
    def file(self) -> str:
        """Compatibility alias for callers that use ``file`` terminology."""

        return self.path


class ExecutionBoundaryReport(BaseModel):
    """Machine-readable result of a deterministic boundary scan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    result: Literal["pass", "fail"]
    violations: list[BoundaryViolation] = Field(default_factory=list)
    scanned_files: int = Field(ge=0)
    policy_checksum: str = POLICY_CHECKSUM
    generated_at: datetime
    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_allow_listed(root: Path, path: Path) -> bool:
    relative = _relative_path(root, path).lower()
    if relative == "tests" or relative.startswith("tests/"):
        return True
    if relative == "docs/architecture/future" or relative.startswith("docs/architecture/future/"):
        return path.suffix.lower() in _FUTURE_DOCUMENT_SUFFIXES
    return False


def _is_dependency_manifest(path: Path) -> bool:
    name = path.name.lower()
    if name in _MANIFEST_NAMES:
        return True
    return name.startswith("requirements") and path.suffix.lower() in {".in", ".txt"}


def _iter_scannable_files(root: Path) -> Iterator[Path]:
    if not root.exists() or not root.is_dir():
        return
    candidates = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().lower())
    for path in candidates:
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if (
            any(part.lower() in _EXCLUDED_DIRECTORIES for part in relative_parts)
            or (relative_parts and relative_parts[0].lower() in _EXCLUDED_ROOT_DIRECTORIES)
        ):
            continue
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            continue
        if _is_dependency_manifest(path) or path.name.lower() in _ENV_FILE_NAMES or path.suffix.lower() in _TEXT_SUFFIXES:
            yield path


def _violation(
    root: Path,
    path: Path,
    code: str,
    message: str,
    *,
    node: ast.AST | None = None,
    evidence: str | None = None,
    line: int | None = None,
    column: int | None = None,
) -> BoundaryViolation:
    return BoundaryViolation(
        code=code,
        path=_relative_path(root, path),
        line=line if line is not None else getattr(node, "lineno", None),
        column=column if column is not None else getattr(node, "col_offset", None),
        message=message,
        evidence=evidence,
    )


def _normalise_symbol(value: str) -> str:
    separated = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    return re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in node.elts:
            names.extend(_target_names(element))
        return names
    if isinstance(node, ast.Attribute):
        return [node.attr]
    return []


def _literal_strings(node: ast.AST) -> Iterator[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def _ui_control_target(targets: Sequence[str]) -> bool:
    for target in targets:
        normalised = _normalise_symbol(target)
        if normalised in {"button", "control", "label", "submit", "cancel", "replace", "buy", "sell"}:
            return True
        if normalised.endswith(("_button", "_control", "_label")):
            return True
    return False


def _scan_python(root: Path, path: Path, text: str) -> list[BoundaryViolation]:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [
            _violation(
                root,
                path,
                "PYTHON_PARSE_ERROR",
                "Python source could not be parsed for boundary inspection.",
                line=exc.lineno,
                column=exc.offset,
                evidence=exc.msg,
            )
        ]

    violations: list[BoundaryViolation] = []
    ui_path = "app" in {part.lower() for part in path.relative_to(root).parts} or path.stem.lower().endswith("ui") or "ui" in path.stem.lower()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol = _normalise_symbol(node.name)
            if symbol in _PROHIBITED_ORDER_SYMBOLS:
                violations.append(
                    _violation(
                        root,
                        path,
                        "PROHIBITED_ORDER_SYMBOL",
                        f"Order-routing symbol {node.name!r} is not permitted in production source.",
                        node=node,
                        evidence=node.name,
                    )
                )
        elif isinstance(node, (ast.Name, ast.Attribute)):
            raw_name = node.id if isinstance(node, ast.Name) else node.attr
            if _normalise_symbol(raw_name) in _PROHIBITED_ORDER_SYMBOLS:
                violations.append(
                    _violation(
                        root,
                        path,
                        "PROHIBITED_ORDER_SYMBOL",
                        f"Order-routing symbol {raw_name!r} is not permitted in production source.",
                        node=node,
                        evidence=raw_name,
                    )
                )

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            aliases = node.names
            for alias in aliases:
                module = alias.name.split(".", 1)[0].lower()
                if module in _PROHIBITED_IMPORTS:
                    violations.append(
                        _violation(
                            root,
                            path,
                            "PROHIBITED_BROKER_DEPENDENCY",
                            f"Broker SDK import {alias.name!r} is not permitted.",
                            node=node,
                            evidence=alias.name,
                        )
                    )

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets: list[str] = []
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    targets.extend(_target_names(target))
                value = node.value
            else:
                targets.extend(_target_names(node.target))
                value = node.value
            for target in targets:
                normalised = _normalise_symbol(target)
                if (normalised.endswith("_endpoint") or normalised.endswith("_url")) and any(
                    part in normalised for part in ("broker", "order", "execution")
                ):
                    violations.append(
                        _violation(
                            root,
                            path,
                            "PROHIBITED_ORDER_ENDPOINT",
                            f"Order endpoint resource {target!r} is not permitted.",
                            node=node,
                            evidence=target,
                        )
                    )
                if _PROHIBITED_CREDENTIAL_NAME_RE.fullmatch(normalised.replace("_", " ")) or _PROHIBITED_CREDENTIAL_NAME_RE.search(normalised):
                    violations.append(
                        _violation(
                            root,
                            path,
                            "PROHIBITED_CREDENTIAL_RESOURCE",
                            f"Broker/order credential resource {target!r} is not permitted.",
                            node=node,
                            evidence=target,
                        )
                    )
            if ui_path and value is not None:
                for literal in _literal_strings(value):
                    if _UI_ORDER_CONTROL_RE.search(literal) and (
                        not _UI_SHORT_ORDER_CONTROL_RE.search(literal) or _ui_control_target(targets)
                    ):
                        violations.append(
                            _violation(
                                root,
                                path,
                                "PROHIBITED_UI_ORDER_CONTROL",
                                "Current UI source must not expose an order-routing control.",
                                node=node,
                                evidence=literal,
                            )
                        )

        if isinstance(node, ast.Call):
            function_name = _dotted_name(node.func).lower()
            if function_name in {"importlib.import_module", "import_module"} and node.args:
                for literal in _literal_strings(node.args[0]):
                    module = literal.split(".", 1)[0].lower()
                    if module in _PROHIBITED_IMPORTS:
                        violations.append(
                            _violation(
                                root,
                                path,
                                "PROHIBITED_BROKER_DEPENDENCY",
                                f"Broker SDK import {literal!r} is not permitted.",
                                node=node,
                                evidence=literal,
                            )
                        )
                        break
            if ui_path and any(
                marker in _normalise_symbol(function_name)
                for marker in ("button", "order_control", "trade_control")
            ):
                for literal in _literal_strings(node):
                    if _UI_SHORT_ORDER_CONTROL_RE.search(literal):
                        violations.append(
                            _violation(
                                root,
                                path,
                                "PROHIBITED_UI_ORDER_CONTROL",
                                "Current UI source must not expose an order-routing control.",
                                node=node,
                                evidence=literal,
                            )
                        )
            if any(_ORDER_ENDPOINT_RE.search(value) for value in _literal_strings(node)):
                if function_name.rsplit(".", 1)[-1] in {"post", "put", "patch", "request", "send", "get"}:
                    violations.append(
                        _violation(
                            root,
                            path,
                            "PROHIBITED_ORDER_ENDPOINT",
                            "HTTP client call targets an order endpoint.",
                            node=node,
                            evidence=function_name,
                        )
                    )

        if (
            ui_path
            and isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _UI_ORDER_CONTROL_RE.search(node.value)
            and not _UI_SHORT_ORDER_CONTROL_RE.search(node.value)
        ):
            violations.append(
                _violation(
                    root,
                    path,
                    "PROHIBITED_UI_ORDER_CONTROL",
                    "Current UI source must not expose an order-routing control.",
                    node=node,
                    evidence=node.value,
                )
            )

    return violations


def _read_config(path: Path, text: str) -> Any:
    suffix = path.suffix.lower()
    if path.name.lower() in _ENV_FILE_NAMES:
        values: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            if not separator or not key.strip():
                continue
            values[key.strip()] = value.strip().strip("\"'")
        return values
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    if suffix == ".json":
        return json.loads(text)
    if suffix == ".toml":
        return tomllib.loads(text)
    if suffix in {".ini", ".cfg"}:
        parser = configparser.ConfigParser()
        parser.read_string(text)
        parsed: dict[str, dict[str, str]] = {}
        if parser.defaults():
            parsed["DEFAULT"] = dict(parser.defaults())
        for section in parser.sections():
            explicit = parser._sections.get(section, {})
            parsed[section] = {
                key: value
                for key, value in parser.items(section, raw=True)
                if key in explicit
            }
        return parsed
    return None


def _walk_mappings(value: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = (*prefix, str(key))
            yield key_path, item
            yield from _walk_mappings(item, key_path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            yield from _walk_mappings(item, (*prefix, str(index)))


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if isinstance(value, (int, float)) else False


def _scan_config(root: Path, path: Path, text: str) -> list[BoundaryViolation]:
    try:
        parsed = _read_config(path, text)
    except (ValueError, TypeError, configparser.Error, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        return [
            _violation(root, path, "RESOURCE_PARSE_ERROR", "Configuration could not be parsed for boundary inspection.", evidence=str(exc))
        ]
    if parsed is None:
        return []
    violations: list[BoundaryViolation] = []
    for key_path, value in _walk_mappings(parsed):
        key = _normalise_symbol(key_path[-1]) if key_path else ""
        dotted = ".".join(key_path)
        if key == "execution_allowed" and _is_truthy(value):
            violations.append(
                _violation(
                    root,
                    path,
                    "EXECUTION_AUTHORITY_ENABLED",
                    "Configuration must keep execution_allowed=false.",
                    evidence=f"{dotted}={value!r}",
                )
            )
        if key == "executable_authority" and _is_truthy(value):
            violations.append(
                _violation(
                    root,
                    path,
                    "EXECUTION_AUTHORITY_ENABLED",
                    "Configuration must keep executable_authority=false.",
                    evidence=f"{dotted}={value!r}",
                )
            )
        if isinstance(value, str) and _ORDER_ENDPOINT_RE.search(value):
            violations.append(
                _violation(
                    root,
                    path,
                    "PROHIBITED_ORDER_ENDPOINT",
                    "Configuration must not define a broker/order endpoint URL.",
                    evidence=f"{dotted}={value!r}",
                )
            )
        if _ENDPOINT_NAME_RE.search(key.replace("_", " ")):
            violations.append(
                _violation(
                    root,
                    path,
                    "PROHIBITED_ORDER_ENDPOINT",
                    "Configuration must not define a broker/order endpoint.",
                    evidence=dotted,
                )
            )
        if _PROHIBITED_CREDENTIAL_NAME_RE.search(key):
            violations.append(
                _violation(
                    root,
                    path,
                    "PROHIBITED_CREDENTIAL_RESOURCE",
                    "Configuration must not define broker/order credentials.",
                    evidence=dotted,
                )
            )
    return violations


def _scan_dependency_manifest(root: Path, path: Path, text: str) -> list[BoundaryViolation]:
    lowered = text.lower()
    violations: list[BoundaryViolation] = []
    for dependency in sorted(_PROHIBITED_DEPENDENCIES):
        pattern = rf"(?<![a-z0-9_-]){re.escape(dependency.lower())}(?![a-z0-9_-])"
        match = re.search(pattern, lowered)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            violations.append(
                _violation(
                    root,
                    path,
                    "PROHIBITED_BROKER_DEPENDENCY",
                    f"Broker SDK dependency {dependency!r} is not permitted.",
                    evidence=dependency,
                    line=line,
                )
            )
    return violations


def _scan_credential_resource(root: Path, path: Path, text: str) -> list[BoundaryViolation]:
    name = path.name.lower()
    if name == ".env.example":
        return []
    suspicious_name = (
        name in {".env", ".env.local", "secrets.json", "credentials.json"}
        or "secret" in name
        or "credential" in name
        or any(
        name.endswith(suffix) for suffix in (".pem", ".key", ".p12", ".pfx")
        )
    )
    violations: list[BoundaryViolation] = []
    if suspicious_name:
        for index, line in enumerate(text.splitlines(), 1):
            if _PROHIBITED_CREDENTIAL_NAME_RE.search(line) or _ENDPOINT_NAME_RE.search(line):
                violations.append(
                    _violation(
                        root,
                        path,
                        "PROHIBITED_CREDENTIAL_RESOURCE",
                        "Broker/order credential resources are not permitted.",
                        evidence=line.strip(),
                        line=index,
                    )
                )
    return violations


def _deduplicate(violations: Sequence[BoundaryViolation]) -> list[BoundaryViolation]:
    unique: dict[tuple[Any, ...], BoundaryViolation] = {}
    for item in violations:
        key = (item.path, item.line or 0, item.column or 0, item.code, item.message, item.evidence or "")
        unique[key] = item
    return sorted(
        unique.values(),
        key=lambda item: (item.path, item.line or 0, item.column or 0, item.code, item.message, item.evidence or ""),
    )


def _registry_path(path_or_root: Path) -> Path:
    path = Path(path_or_root)
    return path / REJECTION_REGISTRY_RELATIVE_PATH if path.is_dir() else path


def _load_registry_data(path_or_root: Path) -> dict[str, Any] | None:
    path = _registry_path(path_or_root)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evidence_reference_path(reference: str) -> str:
    return reference.split("#", 1)[0].strip()


def validate_rejection_registry(path_or_root: Path | Mapping[str, Any]) -> list[str]:
    """Return auditable validation errors for a rejection registry."""

    if isinstance(path_or_root, Mapping):
        data: Mapping[str, Any] | None = path_or_root
        base_dir: Path | None = None
    else:
        source = Path(path_or_root)
        data = _load_registry_data(source)
        if source.is_dir():
            base_dir = source
        elif source.parent.name.lower() == "configs":
            base_dir = source.parent.parent
        else:
            base_dir = source.parent
    if data is None:
        return ["registry is missing or is not a mapping"]

    errors: list[str] = []
    top_level_required = (
        "schema_version",
        "registry_id",
        "policy_version",
        "last_reviewed",
        "execution_allowed",
        "executable_authority",
        "rejections",
    )
    for field_name in top_level_required:
        value = data.get(field_name)
        if field_name in {"registry_id", "policy_version", "last_reviewed"}:
            missing = not _non_empty_text(value)
        else:
            missing = value is None
        if missing:
            errors.append(f"{field_name} is required")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("execution_allowed") is not False:
        errors.append("execution_allowed must be false")
    if data.get("executable_authority") is not False:
        errors.append("executable_authority must be false")
    records = data.get("rejections")
    if not isinstance(records, list) or not records:
        return [*errors, "rejections must be a non-empty list"]

    seen: set[str] = set()
    required = (
        "rejection_id",
        "status",
        "scope",
        "decision_owner",
        "rationale",
        "created_at",
        "reviewed_at",
        "evidence_refs",
    )
    for index, record in enumerate(records):
        prefix = f"rejections[{index}]"
        if not isinstance(record, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        identifier_value = record.get("rejection_id")
        identifier = identifier_value.strip() if isinstance(identifier_value, str) else ""
        if not identifier:
            errors.append(f"{prefix}.rejection_id is required")
        elif identifier in seen:
            errors.append(f"duplicate rejection_id: {identifier}")
        seen.add(identifier)
        for field_name in required:
            value = record.get(field_name)
            if field_name == "evidence_refs":
                if not isinstance(value, list) or not value:
                    errors.append(f"{prefix}.{field_name} is required")
                else:
                    for ref_index, reference in enumerate(value):
                        if not _non_empty_text(reference):
                            errors.append(
                                f"{prefix}.evidence_refs[{ref_index}] must be a non-empty string"
                            )
                            continue
                        if base_dir is None:
                            continue
                        target = _evidence_reference_path(reference)
                        target_path = Path(target)
                        if not target or target_path.is_absolute():
                            errors.append(
                                f"{prefix}.evidence_refs[{ref_index}] must reference a relative evidence path"
                            )
                            continue
                        root_path = base_dir.resolve()
                        resolved = (base_dir / target_path).resolve()
                        try:
                            resolved.relative_to(root_path)
                        except ValueError:
                            errors.append(
                                f"{prefix}.evidence_refs[{ref_index}] escapes the registry root"
                            )
                        if resolved.exists() is False:
                            errors.append(
                                f"{prefix}.evidence_refs[{ref_index}] path does not exist: {target}"
                            )
                continue
            if not _non_empty_text(value):
                errors.append(f"{prefix}.{field_name} is required")
        if record.get("status") != "permanent":
            errors.append(f"{prefix}.status must be permanent")
        if record.get("execution_allowed") is not False:
            errors.append(f"{prefix}.execution_allowed must be false")
        if record.get("executable_authority") is not False:
            errors.append(f"{prefix}.executable_authority must be false")
    return errors


def load_rejection_registry(root: Path) -> dict[str, Any]:
    """Load and validate ``configs/rejection_registry.yaml`` below *root*."""

    path = _registry_path(Path(root))
    data = _load_registry_data(path)
    errors = validate_rejection_registry(path)
    if errors:
        raise ValueError("; ".join(errors))
    assert data is not None
    return data


def _registry_violations(root: Path) -> list[BoundaryViolation]:
    path = root / REJECTION_REGISTRY_RELATIVE_PATH
    if not path.exists() or _is_allow_listed(root, path):
        return []
    errors = validate_rejection_registry(path)
    return [
        _violation(
            root,
            path,
            "REJECTION_REGISTRY_INVALID",
            "Rejection registry failed its schema and authority checks.",
            evidence=error,
        )
        for error in errors
    ]


def run_static_execution_boundary_check(root: Path) -> ExecutionBoundaryReport:
    """Scan *root* and return a deterministic, non-executable boundary report."""

    root = Path(root).resolve()
    files = list(_iter_scannable_files(root))
    violations: list[BoundaryViolation] = []
    if not root.exists() or not root.is_dir():
        violations.append(
            BoundaryViolation(
                code="ROOT_NOT_FOUND",
                path=".",
                message="Boundary scan root does not exist or is not a directory.",
            )
        )

    for path in files:
        if _is_allow_listed(root, path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(_violation(root, path, "RESOURCE_READ_ERROR", "Resource could not be read for boundary inspection.", evidence=str(exc)))
            continue
        if path.suffix.lower() == ".py":
            violations.extend(_scan_python(root, path, text))
        if path.suffix.lower() in _CONFIG_SUFFIXES or path.name.lower() in _ENV_FILE_NAMES:
            violations.extend(_scan_config(root, path, text))
        if _is_dependency_manifest(path):
            violations.extend(_scan_dependency_manifest(root, path, text))
        if (
            path.suffix.lower() in {".env", ".ini", ".cfg", ".json", ".yaml", ".yml"}
            or path.suffix.lower() in _CREDENTIAL_SUFFIXES
            or path.name.lower() in {*_ENV_FILE_NAMES, "secrets.json", "credentials.json"}
        ):
            violations.extend(_scan_credential_resource(root, path, text))

    violations.extend(_registry_violations(root))
    canonical = _deduplicate(violations)
    return ExecutionBoundaryReport(
        result="fail" if canonical else "pass",
        violations=canonical,
        scanned_files=len(files),
        policy_checksum=POLICY_CHECKSUM,
        generated_at=datetime.now(timezone.utc),
    )


__all__ = [
    "BoundaryViolation",
    "ExecutionBoundaryReport",
    "POLICY_CHECKSUM",
    "REJECTION_REGISTRY_RELATIVE_PATH",
    "load_rejection_registry",
    "run_static_execution_boundary_check",
    "validate_rejection_registry",
]
