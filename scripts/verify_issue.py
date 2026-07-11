"""Deterministic, read-only issue evidence verification.

The verifier consumes a local closure matrix and a local verification manifest.
It deliberately has no tracker writer and does not infer closure from source
changes, skipped commands, live/informational observations or an incomplete
evidence package.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Iterable, Literal, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from etf_cockpit.core.closure import ClosureMatrix, load_closure_matrix  # noqa: E402
from etf_cockpit.operations.models import VerificationRun  # noqa: E402


VerificationStatus = Literal["pass", "fail", "blocked"]
DEFAULT_MATRIX_PATH = ROOT / "configs" / "closure_matrix.yaml"
DEFAULT_REQUIREMENT_VERSION = "2"
DEFAULT_MAX_AGE_HOURS = 168
GATE_ORDER = (
    "source",
    "schema",
    "tests",
    "ui",
    "audit",
    "export",
    "package",
    "build",
    "browser",
)

# This is intentionally a tuple rather than a set or a filesystem discovery
# result.  Package-mode selection is part of the evidence contract and must be
# stable between runs and platforms.
PACKAGE_MODES: tuple[str, ...] = (
    "baseline",
    "display_125_150_percent",
    "empty_first_run",
    "lm_studio_offline",
    "long_unicode_path",
    "migrated_existing_data",
    "offline_cached_data",
    "optional_models_missing",
    "read_only_permission_failure",
    "source_package",
)

_GATE_ALIASES = {
    "focused": "tests",
    "focused_tests": "tests",
    "full": "tests",
    "full_tests": "tests",
    "source_smoke": "source",
    "source_review": "source",
    "schema_check": "schema",
    "migration": "schema",
    "migrations": "schema",
    "ui_smoke": "ui",
    "audit_export": "audit",
    "package_smoke": "package",
    "build_package": "build",
    "browser_smoke": "browser",
    "computer_use": "browser",
}
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token)\b\s*([:=])\s*([^\s,;]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})


class IssueVerificationResultBase:
    """Marker used only for documentation and static tooling."""


try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover - project requirements include pydantic
    BaseModel = object  # type: ignore[assignment,misc]
    ConfigDict = dict  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment,misc]


class IssueVerificationResult(BaseModel, IssueVerificationResultBase):
    """Typed outcome of a read-only verification attempt."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    status: VerificationStatus
    limitations: list[str] = Field(default_factory=list)
    missing_gates: list[str] = Field(default_factory=list)
    tracker_mutated: bool = False
    source_hash: str | None = None
    environment_hash: str | None = None
    requirement_version: str | None = None
    verification_runs: list[VerificationRun] = Field(default_factory=list)
    manifest_path: str | None = None


@dataclass(frozen=True)
class VerificationCommand:
    """One fixed, shell-free command in the evidence plan."""

    gate: str
    argv: tuple[str, ...]


def _python_command(python_executable: str | Path | None = None) -> str:
    return str(python_executable or sys.executable)


def fixed_command_plan(
    gates: Iterable[str], *, python_executable: str | Path | None = None
) -> tuple[VerificationCommand, ...]:
    """Return the deterministic command plan for ``gates``.

    The verifier never discovers commands from issue text.  Unknown gates are
    retained as an explicit command placeholder so a reviewer can see the
    unsupported layer rather than receiving an accidental pass.
    """

    python = _python_command(python_executable)
    commands: dict[str, tuple[str, ...]] = {
        "source": (python, "-m", "compileall", "-q", "src"),
        "schema": (python, "-m", "pytest", "tests/test_closure_matrix.py", "-q"),
        "tests": (python, "-m", "pytest", "tests", "-q"),
        "ui": (python, "-m", "pytest", "tests/test_flet_startup.py", "-q"),
        "audit": (python, "-m", "pytest", "tests/test_trust_critical_artifacts.py", "-q"),
        "export": (python, "-m", "pytest", "tests/test_trust_critical_artifacts.py", "-q"),
        "package": ("cmd.exe", "/d", "/c", "scripts\\build_windows.bat"),
        "build": ("cmd.exe", "/d", "/c", "scripts\\build_windows.bat"),
        "browser": (python, "scripts/smoke_app.py", "--mode", "source"),
    }
    normalised = {str(gate).strip() for gate in gates if str(gate).strip()}
    ordered = [gate for gate in GATE_ORDER if gate in normalised]
    ordered.extend(sorted(normalised - set(GATE_ORDER)))
    return tuple(VerificationCommand(gate, commands.get(gate, ())) for gate in ordered)


def command_plan_for(
    issue_id: str,
    *,
    matrix_path: Path = DEFAULT_MATRIX_PATH,
    python_executable: str | Path | None = None,
) -> tuple[VerificationCommand, ...]:
    """Build the fixed plan from the matrix's required gates."""

    matrix = load_closure_matrix(Path(matrix_path))
    record = matrix.record_for(issue_id)
    gates = _required_gates(record)
    return fixed_command_plan(gates, python_executable=python_executable)


# Compatibility-friendly name for callers that describe the plan as a build.
build_command_plan = command_plan_for


def redact_text(value: str) -> str:
    """Redact common secret-shaped values before local evidence is written."""

    redacted = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    return _BEARER_VALUE.sub("Bearer [REDACTED]", redacted)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_source_hash(root: Path = ROOT) -> str:
    """Hash source/configuration inputs in a stable path-and-content order."""

    root = Path(root).resolve()
    included: list[Path] = []
    for base_name in ("src", "scripts", "configs"):
        base = root / base_name
        if base.exists():
            included.extend(
                path
                for path in base.rglob("*")
                if path.is_file()
                and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)
            )
    for pattern in ("pyproject.toml", "requirements*.txt", "README_FIRST_RUN.md"):
        included.extend(path for path in root.glob(pattern) if path.is_file())

    digest = hashlib.sha256()
    for path in sorted(set(included), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content_hash = bytes.fromhex(sha256_file(path))
        digest.update(content_hash)
    return digest.hexdigest()


def compute_environment_hash(root: Path = ROOT, python_executable: str | Path | None = None) -> str:
    """Hash the interpreter identity and declared dependency inputs."""

    root = Path(root).resolve()
    records = [f"python={python_executable or sys.executable}", f"version={sys.version}"]
    for pattern in ("pyproject.toml", "requirements*.txt"):
        for path in sorted(root.glob(pattern), key=lambda item: item.name):
            if path.is_file():
                records.append(f"{path.name}={sha256_file(path)}")
    return _hash_bytes("\n".join(records).encode("utf-8"))


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _safe_relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalised = value.strip().replace("\\", "/")
    parsed = PurePosixPath(normalised)
    if parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:/", normalised):
        return None
    return parsed.as_posix()


def _required_gates(record: Any) -> tuple[str, ...]:
    required = {
        str(gate)
        for criterion in record.criteria
        for gate in criterion.required_gates
        if str(gate).strip()
    }
    return tuple(gate for gate in GATE_ORDER if gate in required) + tuple(
        sorted(required - set(GATE_ORDER))
    )


def _manifest_path(evidence_root: Path, issue_id: str) -> Path | None:
    root = Path(evidence_root)
    candidates = (
        root / issue_id / "verification_manifest.json",
        root / "verification_manifest.json",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _policy(matrix: ClosureMatrix) -> Mapping[str, Any]:
    value = matrix.verification_policy
    return value if isinstance(value, Mapping) else {}


def _policy_requirement_version(matrix: ClosureMatrix) -> str:
    policy = _policy(matrix)
    value = policy.get("requirement_version", DEFAULT_REQUIREMENT_VERSION)
    return str(value)


def _policy_max_age_hours(matrix: ClosureMatrix) -> float:
    policy = _policy(matrix)
    raw = policy.get("max_age_hours")
    if raw is None:
        raw = float(policy.get("max_age_days", DEFAULT_MAX_AGE_HOURS / 24)) * 24
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return float(DEFAULT_MAX_AGE_HOURS)


def _normalise_gate(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not value:
        return None
    return _GATE_ALIASES.get(value, value)


def _run_gates(raw: Mapping[str, Any]) -> tuple[str, ...]:
    values: object = raw.get("gates", ())
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        values = []
    gates = {_normalise_gate(value) for value in values}
    gates.discard(None)
    if not gates:
        fallback = _normalise_gate(raw.get("verification_type"))
        if fallback:
            gates.add(fallback)
    return tuple(gate for gate in GATE_ORDER if gate in gates) + tuple(
        sorted(gates - set(GATE_ORDER))
    )


def _string_list(raw: object) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    if not all(isinstance(value, str) for value in raw):
        return None
    return [value for value in raw]


def _validate_output_files(
    *,
    evidence_root: Path,
    paths: list[str] | None,
    checksums: list[str] | None,
    limitation_prefix: str,
) -> tuple[bool, list[str]]:
    limitations: list[str] = []
    if paths is None or checksums is None:
        limitations.append(f"{limitation_prefix} output paths/checksums must be lists")
        return False, limitations
    if len(paths) != len(checksums):
        limitations.append(f"{limitation_prefix} output paths/checksums length mismatch")
        return False, limitations
    valid = True
    root = evidence_root.resolve()
    for relative, expected in zip(paths, checksums, strict=True):
        safe = _safe_relative_path(relative)
        if safe is None:
            limitations.append(f"{limitation_prefix} output path is unsafe: {relative}")
            valid = False
            continue
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected.strip()):
            limitations.append(f"{limitation_prefix} output checksum is invalid: {safe}")
            valid = False
            continue
        candidate = evidence_root / safe
        checksum_file = candidate.with_name(candidate.name + ".sha256")
        try:
            resolved = candidate.resolve(strict=True)
            if candidate.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
                raise OSError("not a contained regular file")
            actual = sha256_file(resolved)
        except (OSError, ValueError):
            limitations.append(f"{limitation_prefix} output file is missing or escapes evidence root: {safe}")
            valid = False
            continue
        if actual.lower() != expected.strip().lower():
            limitations.append(f"{limitation_prefix} output checksum mismatch: {safe}")
            valid = False
        # A sidecar is optional for the manifest format, but if one exists it
        # must agree as well.  This prevents a stale sidecar being mistaken for
        # fresh evidence by the older closure evaluator.
        if checksum_file.exists() and not checksum_file.is_symlink():
            try:
                sidecar = checksum_file.read_text(encoding="ascii").strip().lower()
            except (OSError, UnicodeError):
                sidecar = ""
            if sidecar != actual.lower():
                limitations.append(f"{limitation_prefix} sidecar checksum mismatch: {safe}")
                valid = False
    return valid, limitations


def _validate_screenshot(
    *,
    raw: Mapping[str, Any] | None,
    evidence_root: Path,
    limitation_prefix: str,
) -> tuple[bool, list[str]]:
    limitations: list[str] = []
    if not isinstance(raw, Mapping):
        return False, [f"{limitation_prefix} screenshot metadata is missing"]
    path_value = raw.get("path")
    safe = _safe_relative_path(path_value)
    expected = raw.get("sha256", raw.get("checksum"))
    width = raw.get("width")
    height = raw.get("height")
    if safe is None:
        limitations.append(f"{limitation_prefix} screenshot path is unsafe or missing")
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected.strip()):
        limitations.append(f"{limitation_prefix} screenshot checksum metadata is invalid")
    if isinstance(width, bool) or not isinstance(width, (int, float)) or width <= 0:
        limitations.append(f"{limitation_prefix} screenshot width metadata is invalid")
    if isinstance(height, bool) or not isinstance(height, (int, float)) or height <= 0:
        limitations.append(f"{limitation_prefix} screenshot height metadata is invalid")
    if safe is None or not isinstance(expected, str) or not _SHA256.fullmatch(expected.strip()):
        return False, limitations
    candidate = evidence_root / safe
    try:
        resolved = candidate.resolve(strict=True)
        if candidate.is_symlink() or not resolved.is_relative_to(evidence_root.resolve()):
            raise OSError("not contained")
        if resolved.suffix.lower() not in _IMAGE_SUFFIXES:
            limitations.append(f"{limitation_prefix} screenshot is not an image file")
        actual = sha256_file(resolved)
        if actual.lower() != expected.strip().lower():
            limitations.append(f"{limitation_prefix} screenshot checksum mismatch")
    except (OSError, ValueError):
        limitations.append(f"{limitation_prefix} screenshot file is missing or escapes evidence root")
    return not limitations, limitations


def _make_run(
    raw: Mapping[str, Any],
    *,
    issue_id: str,
    expected_source_hash: str,
    expected_environment_hash: str,
    index: int,
) -> tuple[VerificationRun | None, tuple[str, ...], tuple[str, ...], bool]:
    """Parse one raw record and return (typed run, gates, limitations, valid)."""

    limitations: list[str] = []
    run_id = raw.get("verification_run_id")
    verification_type = raw.get("verification_type")
    command = raw.get("command")
    if not isinstance(run_id, str) or not run_id.strip():
        limitations.append(f"run {index} has no verification_run_id")
        run_id = f"invalid-{index}"
    if not isinstance(verification_type, str) or not verification_type.strip():
        limitations.append(f"run {index} has no verification_type")
        verification_type = "unknown"
    if not isinstance(command, str):
        limitations.append(f"run {index} has no command")
        command = ""

    result_raw = raw.get("result")
    result = result_raw if result_raw in {"pass", "fail", "blocked"} else "blocked"
    if result_raw not in {"pass", "fail", "blocked"}:
        limitations.append(f"run {index} has an unsupported result")
    try:
        exit_code = int(raw.get("exit_code", 0 if result == "pass" else 1))
    except (TypeError, ValueError):
        exit_code = 1
        limitations.append(f"run {index} exit_code is invalid")

    output_paths = _string_list(raw.get("output_paths", []))
    output_checksums = _string_list(raw.get("output_checksums", []))
    gates = _run_gates(raw)
    if not gates:
        limitations.append(f"run {index} declares no closure gate")
    issue_ids = _string_list(raw.get("issue_ids", [issue_id]))
    if issue_ids is None:
        limitations.append(f"run {index} issue_ids must be a list")
        issue_ids = []
    elif issue_id not in issue_ids:
        limitations.append(f"run {index} does not identify issue {issue_id}")

    run_source_hash = raw.get("source_hash")
    if not isinstance(run_source_hash, str) or run_source_hash != expected_source_hash:
        limitations.append(f"run {index} source hash does not match the verification request")
        run_source_hash = str(run_source_hash or "")
    run_environment_hash = raw.get("environment_hash", expected_environment_hash)
    if run_environment_hash is not None and run_environment_hash != expected_environment_hash:
        limitations.append(f"run {index} environment hash does not match the verification request")
    skipped = bool(raw.get("skipped", False))
    informational = bool(raw.get("informational", False))
    verification_type_lower = str(verification_type).strip().lower()
    if skipped:
        limitations.append(f"run {index} is skipped and cannot satisfy a gate")
    if informational or verification_type_lower.startswith("live_") or verification_type_lower == "informational":
        informational = True
        limitations.append(f"run {index} is live/informational and cannot satisfy a deterministic gate")
    if result != "pass":
        limitations.append(f"run {index} result is {result}")
    if result == "pass" and exit_code != 0:
        limitations.append(f"run {index} passed with non-zero exit_code")

    screenshot = raw.get("screenshot")
    try:
        typed = VerificationRun(
            verification_run_id=str(run_id).strip(),
            verification_type=str(verification_type).strip(),
            command=command,
            source_hash=run_source_hash,
            result=result,
            exit_code=exit_code,
            output_paths=output_paths or [],
            output_checksums=output_checksums or [],
            issue_ids=issue_ids,
            environment_hash=(str(run_environment_hash) if run_environment_hash is not None else None),
            gates=list(gates),
            skipped=skipped,
            informational=informational,
            screenshot=dict(screenshot) if isinstance(screenshot, Mapping) else None,
        )
    except Exception as exc:  # pydantic validation errors are evidence failures
        limitations.append(f"run {index} cannot be represented as VerificationRun: {exc}")
        return None, gates, tuple(limitations), False

    valid = not limitations
    return typed, gates, tuple(limitations), valid


def verify_issue(
    issue_id: str,
    *,
    source_hash: str | None = None,
    environment_hash: str | None = None,
    evidence_root: Path | None = None,
    matrix_path: Path = DEFAULT_MATRIX_PATH,
    now: datetime | None = None,
) -> IssueVerificationResult:
    """Validate one issue's evidence package without changing tracker state."""

    issue_id = str(issue_id).strip()
    limitations: list[str] = []
    missing_gates: list[str] = []
    runs: list[VerificationRun] = []
    manifest_path: Path | None = None
    expected_source_hash = source_hash or compute_source_hash(ROOT)
    expected_environment_hash = environment_hash or compute_environment_hash(ROOT)
    requirement_version: str | None = None
    hard_block = False
    failure_seen = False

    try:
        matrix = load_closure_matrix(Path(matrix_path))
        record = matrix.record_for(issue_id)
    except (OSError, ValueError, KeyError) as exc:
        return IssueVerificationResult(
            issue_id=issue_id,
            status="blocked",
            limitations=[f"closure matrix cannot be read for {issue_id}: {exc}"],
            missing_gates=[],
            tracker_mutated=False,
            source_hash=expected_source_hash,
            environment_hash=expected_environment_hash,
            verification_runs=[],
        )

    policy = _policy(matrix)
    required_version = _policy_requirement_version(matrix)
    requirement_version = str(required_version)
    manifest_root = Path(evidence_root or (ROOT / "evidence"))
    manifest_path = _manifest_path(manifest_root, issue_id)
    if manifest_path is None:
        return IssueVerificationResult(
            issue_id=issue_id,
            status="blocked",
            limitations=["verification manifest is missing"],
            missing_gates=list(_required_gates(record)),
            tracker_mutated=False,
            source_hash=expected_source_hash,
            environment_hash=expected_environment_hash,
            requirement_version=requirement_version,
        )

    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return IssueVerificationResult(
            issue_id=issue_id,
            status="blocked",
            limitations=[f"verification manifest cannot be read: {exc}"],
            missing_gates=list(_required_gates(record)),
            tracker_mutated=False,
            source_hash=expected_source_hash,
            environment_hash=expected_environment_hash,
            requirement_version=requirement_version,
            manifest_path=manifest_path.as_posix(),
        )
    if not isinstance(raw_manifest, Mapping):
        raw_manifest = {}
        limitations.append("verification manifest must be a JSON object")
        hard_block = True

    manifest_issue = raw_manifest.get("issue_id")
    if manifest_issue != issue_id:
        limitations.append("verification manifest issue_id does not match the request")
        hard_block = True
    manifest_requirement = raw_manifest.get("requirement_version")
    if str(manifest_requirement) != required_version:
        limitations.append(
            f"requirement version mismatch: expected {required_version}, got {manifest_requirement!r}"
        )
        hard_block = True
    manifest_source = raw_manifest.get("source_hash")
    if manifest_source != expected_source_hash:
        limitations.append(
            f"source hash mismatch: expected {expected_source_hash}, got {manifest_source!r}"
        )
        hard_block = True
    manifest_environment = raw_manifest.get("environment_hash")
    if manifest_environment != expected_environment_hash:
        limitations.append(
            f"environment hash mismatch: expected {expected_environment_hash}, got {manifest_environment!r}"
        )
        hard_block = True

    generated_at = _parse_datetime(raw_manifest.get("generated_at"))
    current = _utc(now)
    if generated_at is None:
        limitations.append("verification manifest generated_at is missing or invalid")
        hard_block = True
    else:
        age_hours = (current - generated_at).total_seconds() / 3600
        if age_hours < -5 / 60:
            limitations.append("verification manifest is from the future")
            hard_block = True
        elif age_hours > _policy_max_age_hours(matrix):
            limitations.append("verification manifest is not fresh enough for REL-03")
            hard_block = True

    policy_version = policy.get("version")
    if raw_manifest.get("verification_policy_version") is not None and str(
        raw_manifest.get("verification_policy_version")
    ) != str(policy_version):
        limitations.append("verification policy version mismatch")
        hard_block = True

    raw_runs = raw_manifest.get("runs", [])
    if not isinstance(raw_runs, list):
        raw_runs = []
        limitations.append("verification manifest runs must be a list")
        hard_block = True

    gate_validity: dict[str, bool] = {}
    for index, raw_run in enumerate(raw_runs):
        if not isinstance(raw_run, Mapping):
            limitations.append(f"run {index} must be a JSON object")
            hard_block = True
            continue
        typed, gates, run_limitations, valid = _make_run(
            raw_run,
            issue_id=issue_id,
            expected_source_hash=expected_source_hash,
            expected_environment_hash=expected_environment_hash,
            index=index,
        )
        if typed is not None:
            runs.append(typed)
            if typed.result == "fail":
                failure_seen = True
        if run_limitations:
            limitations.extend(run_limitations)
            hard_block = True

        output_paths = _string_list(raw_run.get("output_paths", []))
        output_checksums = _string_list(raw_run.get("output_checksums", []))
        output_valid, output_limitations = _validate_output_files(
            evidence_root=manifest_root,
            paths=output_paths,
            checksums=output_checksums,
            limitation_prefix=f"run {index}",
        )
        if output_limitations:
            limitations.extend(output_limitations)
        if not output_valid:
            hard_block = True
            valid = False

        screenshot = raw_run.get("screenshot")
        if any(gate in {"browser", "ui"} for gate in gates):
            screenshot_valid, screenshot_limitations = _validate_screenshot(
                raw=screenshot,
                evidence_root=manifest_root,
                limitation_prefix=f"run {index}",
            )
            if screenshot_limitations:
                limitations.extend(screenshot_limitations)
            if not screenshot_valid:
                hard_block = True
                valid = False

        for gate in gates:
            gate_validity[gate] = gate_validity.get(gate, False) or (valid and output_valid)

    required_gates = _required_gates(record)
    policy_gate_layers = policy.get("gate_layers", policy.get("layers", {}))
    if isinstance(policy_gate_layers, Mapping):
        for gate in required_gates:
            if gate not in policy_gate_layers:
                limitations.append(f"verification policy does not map required gate {gate}")
                hard_block = True

    missing_gates = [gate for gate in required_gates if not gate_validity.get(gate, False)]
    if missing_gates:
        limitations.append("missing required verification gates: " + ", ".join(missing_gates))
        hard_block = True

    review = raw_manifest.get("review")
    if not isinstance(review, Mapping):
        limitations.append("independent review metadata is missing")
        hard_block = True
    else:
        builder = str(review.get("builder", "")).strip()
        reviewer = str(review.get("independent_reviewer", "")).strip()
        review_result = str(review.get("review_result", "")).strip().lower()
        if review_result != "approved":
            limitations.append("independent review is not approved")
            hard_block = True
        if not builder or not reviewer or builder == reviewer:
            limitations.append("independent reviewer must be present and distinct from builder")
            hard_block = True

    # De-duplicate while preserving the evidence-review order, especially the
    # source-hash limitation which callers use as the first diagnostic.
    limitations = list(dict.fromkeys(limitations))
    if hard_block:
        status: VerificationStatus = "blocked"
    elif failure_seen:
        status = "fail"
    else:
        status = "pass"
    return IssueVerificationResult(
        issue_id=issue_id,
        status=status,
        limitations=limitations,
        missing_gates=missing_gates,
        tracker_mutated=False,
        source_hash=expected_source_hash,
        environment_hash=expected_environment_hash,
        requirement_version=requirement_version,
        verification_runs=runs,
        manifest_path=manifest_path.as_posix(),
    )


def execute_command_plan(
    issue_id: str,
    *,
    evidence_root: Path,
    gates: Iterable[str],
    source_hash: str,
    environment_hash: str,
    commands: Sequence[VerificationCommand] | None = None,
    cwd: Path = ROOT,
) -> list[dict[str, object]]:
    """Optionally run fixed commands and capture only redacted local output.

    This helper writes command output beneath ``evidence_root`` and never
    writes an issue ledger, tracker record or remote state.  It does not create
    a verification manifest; a reviewer decides which captured runs are
    authoritative before assembling one.
    """

    root = Path(evidence_root)
    output_root = root / str(issue_id) / "commands"
    output_root.mkdir(parents=True, exist_ok=True)
    command_list = tuple(commands or fixed_command_plan(gates))
    runs: list[dict[str, object]] = []
    for index, command in enumerate(command_list):
        gate_name = command.gate or f"gate-{index}"
        prefix = f"{index:02d}-{re.sub(r'[^A-Za-z0-9_.-]+', '_', gate_name)}"
        started = datetime.now(timezone.utc)
        if not command.argv:
            stdout = ""
            stderr = "command plan has no fixed argv"
            exit_code = None
        else:
            completed = subprocess.run(
                list(command.argv),
                cwd=Path(cwd),
                env=os.environ.copy(),
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
            stdout = redact_text(completed.stdout or "")
            stderr = redact_text(completed.stderr or "")
            exit_code = completed.returncode
        stdout_path = output_root / f"{prefix}.stdout.txt"
        stderr_path = output_root / f"{prefix}.stderr.txt"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        relative_stdout = stdout_path.relative_to(root).as_posix()
        relative_stderr = stderr_path.relative_to(root).as_posix()
        result = "pass" if exit_code == 0 else ("blocked" if exit_code is None else "fail")
        runs.append(
            {
                "verification_run_id": f"command-{index:02d}-{gate_name}",
                "verification_type": gate_name,
                "command": " ".join(command.argv),
                "source_hash": source_hash,
                "environment_hash": environment_hash,
                "result": result,
                "exit_code": exit_code,
                "output_paths": [relative_stdout, relative_stderr],
                "output_checksums": [sha256_file(stdout_path), sha256_file(stderr_path)],
                "issue_ids": [issue_id],
                "gates": [gate_name],
                "skipped": False,
                "informational": False,
                "started_at": started.isoformat(),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return runs


def _parse_cli(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify local issue evidence without tracker mutation.")
    parser.add_argument("issue_id")
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "evidence")
    parser.add_argument("--matrix-path", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--source-hash")
    parser.add_argument("--environment-hash")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_cli(argv)
    result = verify_issue(
        args.issue_id,
        source_hash=args.source_hash,
        environment_hash=args.environment_hash,
        evidence_root=args.evidence_root,
        matrix_path=args.matrix_path,
    )
    print(result.model_dump_json(indent=2))
    return {"pass": 0, "fail": 1, "blocked": 2}[result.status]


if __name__ == "__main__":  # pragma: no cover - exercised by CLI smoke
    raise SystemExit(main())
