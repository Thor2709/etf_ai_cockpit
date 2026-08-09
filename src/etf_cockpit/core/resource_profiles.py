"""Local hardware profiles and fail-closed pre-job resource policy.

The policy is deliberately descriptive and local-only. It does not collect
telemetry, select a broker or grant execution authority. Optional model
packages can use the selected batch/chunk/model-size hints, while the
deterministic baseline remains usable on the minimum profile.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
import math
import os
from pathlib import Path
import platform
import shutil
from typing import Callable

from etf_cockpit.core.performance import PerformanceBudgetError, build_performance_report
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope


RESOURCE_PROFILE_SCHEMA_VERSION = "resource-profiles.v1"
RESOURCE_CACHE_RELATIVE = Path("artifacts") / "resource-cache"
_MEMORY_RESERVE_MB = 256
_DISK_RESERVE_MB = 512


@dataclass(frozen=True)
class HardwareSnapshot:
    platform: str
    cpu_cores: int
    memory_total_mb: float | None
    memory_available_mb: float | None
    disk_free_mb: float | None
    gpu_available: bool
    gpu_label: str
    source: str = "local_host_probe"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceProfile:
    profile_id: str
    minimum_memory_mb: int
    minimum_disk_mb: int
    minimum_cpu_cores: int
    job_memory_limit_mb: int
    job_disk_limit_mb: int
    job_cpu_limit: int
    batch_size: int
    chunk_size: int
    model_size: str
    description: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceDecision:
    status: str
    profile_id: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "reasons": list(self.reasons), "warnings": list(self.warnings)}


PROFILES: tuple[ResourceProfile, ...] = (
    ResourceProfile("minimum", 1_024, 2_048, 1, 768, 1_536, 1, 8, 256, "baseline", "CPU-only baseline; optional foundation models remain disabled-safe."),
    ResourceProfile("recommended", 4_096, 10_240, 2, 3_072, 8_192, 2, 32, 1_024, "small", "Balanced local profile for ordinary research and bounded jobs."),
    ResourceProfile("high", 8_192, 51_200, 4, 6_144, 32_768, 4, 64, 2_048, "large", "Higher-throughput profile; GPU remains optional and never required."),
)
_PROFILE_BY_ID = {profile.profile_id: profile for profile in PROFILES}


class ResourcePolicy:
    """Evaluate durable jobs against one local, immutable host snapshot."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        requested_profile: str = "auto",
        snapshot: HardwareSnapshot | None = None,
    ) -> None:
        self.root = Path(root).resolve() if root is not None else None
        self.snapshot = snapshot or detect_hardware(self.root)
        self.requested_profile = _profile_id(requested_profile, allow_auto=True)
        self.profile_id, self.profile_status, self.profile_warnings = _select_profile(self.snapshot, self.requested_profile)

    @property
    def profile(self) -> ResourceProfile:
        return _PROFILE_BY_ID[self.profile_id]

    def evaluate(self, resources: dict[str, object] | None = None) -> ResourceDecision:
        requested = resources or {}
        try:
            profile_id = _profile_id(
                requested.get("profile", self.profile_id), allow_auto=True
            )
        except ValueError:
            return ResourceDecision(
                "blocked",
                "unknown",
                ("resource profile must be auto, minimum, recommended or high",),
            )
        selected = _PROFILE_BY_ID[self.profile_id if profile_id == "auto" else profile_id]
        reasons: list[str] = []
        warnings = list(self.profile_warnings)
        profile_decision = _profile_decision(self.snapshot, selected)
        reasons.extend(profile_decision.reasons)
        warnings.extend(profile_decision.warnings)
        memory_requested, memory_invalid = _declared_positive(requested, "memory_mb")
        disk_requested, disk_invalid = _declared_positive(requested, "disk_mb")
        cpu_requested, cpu_invalid = _declared_positive(requested, "cpu")
        if memory_invalid:
            reasons.append("memory request must be a finite positive number")
        if disk_invalid:
            reasons.append("disk request must be a finite positive number")
        if cpu_invalid:
            reasons.append("CPU request must be a finite positive number")
        if memory_requested is not None:
            if self.snapshot.memory_available_mb is None:
                reasons.append("memory request cannot be checked because local capacity is unavailable")
            else:
                memory_limit = min(float(selected.job_memory_limit_mb), max(0.0, self.snapshot.memory_available_mb - _MEMORY_RESERVE_MB))
                if memory_requested > memory_limit:
                    reasons.append(f"memory request {memory_requested:.0f} MB exceeds safe limit {memory_limit:.0f} MB")
                elif memory_limit > 0 and memory_requested >= 0.8 * memory_limit:
                    warnings.append(f"memory request uses at least 80% of the {memory_limit:.0f} MB safe limit")
        if disk_requested is not None:
            if self.snapshot.disk_free_mb is None:
                reasons.append("disk request cannot be checked because local free space is unavailable")
            else:
                disk_limit = min(float(selected.job_disk_limit_mb), max(0.0, self.snapshot.disk_free_mb - _DISK_RESERVE_MB))
                if disk_requested > disk_limit:
                    reasons.append(f"disk request {disk_requested:.0f} MB exceeds safe limit {disk_limit:.0f} MB")
                elif disk_limit > 0 and disk_requested >= 0.8 * disk_limit:
                    warnings.append(f"disk request uses at least 80% of the {disk_limit:.0f} MB safe limit")
        if cpu_requested is not None:
            cpu_limit = min(float(selected.job_cpu_limit), float(self.snapshot.cpu_cores))
            if cpu_requested > cpu_limit:
                reasons.append(f"CPU request {cpu_requested:.0f} exceeds safe limit {cpu_limit:.0f}")
        gpu_requested = requested.get("gpu", False)
        if not isinstance(gpu_requested, (bool, str, int)) or isinstance(
            gpu_requested, float
        ):
            reasons.append("GPU request must be a boolean or device label")
        elif bool(gpu_requested) and not self.snapshot.gpu_available:
            reasons.append("GPU was requested but no local GPU is available")
        if selected.profile_id != self.profile_id:
            warnings.append(f"job requested profile {selected.profile_id}; host-selected profile is {self.profile_id}")
        status = "blocked" if reasons else "warning" if warnings else "supported"
        return ResourceDecision(status, selected.profile_id, tuple(reasons), tuple(dict.fromkeys(warnings)))

    def report(self) -> dict[str, object]:
        profiles = []
        for profile in PROFILES:
            decision = _profile_decision(self.snapshot, profile)
            profiles.append({**profile.to_dict(), **decision.to_dict()})
        selected = self.profile
        return {
            "schema_version": RESOURCE_PROFILE_SCHEMA_VERSION,
            "snapshot": self.snapshot.to_dict(),
            "requested_profile": self.requested_profile,
            "selected_profile": selected.to_dict(),
            "selected_status": self.profile_status,
            "warnings": list(self.profile_warnings),
            "profiles": profiles,
            "limitations": _limitations(self.snapshot),
            "calculation_contract": {
                "profile_affects": ["batch_size", "chunk_size", "model_size", "resource_limits"],
                "profile_does_not_affect": ["deterministic_formulas", "risk_gates", "execution_authority"],
                "numerical_tolerance": 1e-12,
            },
            "execution_allowed": False,
            "network_calls": False,
        }


def detect_hardware(
    root: Path | None = None,
    *,
    cpu_counter: Callable[[], int | None] | None = None,
    memory_reader: Callable[[], tuple[float | None, float | None]] | None = None,
    disk_reader: Callable[[Path], float | None] | None = None,
    gpu_reader: Callable[[], tuple[bool, str]] | None = None,
) -> HardwareSnapshot:
    """Read local capacity once; injected readers make policy tests deterministic."""

    cpu = (cpu_counter or (lambda: os.cpu_count()))() or 1
    total, available = (memory_reader or _system_memory)()
    disk = (disk_reader or _free_disk)(Path(root or Path.cwd()))
    gpu, gpu_label = (gpu_reader or _no_gpu_probe)()
    return HardwareSnapshot(
        platform=platform.system() or "unknown",
        cpu_cores=max(1, int(cpu)),
        memory_total_mb=_finite_optional(total),
        memory_available_mb=_finite_optional(available),
        disk_free_mb=_finite_optional(disk),
        gpu_available=bool(gpu),
        gpu_label=str(gpu_label or "not_checked"),
    )


def resource_profile_report(root: Path | None = None, *, requested_profile: str = "auto", snapshot: HardwareSnapshot | None = None) -> dict[str, object]:
    """Return the user-facing local hardware/profile report."""

    policy = ResourcePolicy(root, requested_profile=requested_profile, snapshot=snapshot)
    report = policy.report()
    report["benchmarks"] = _benchmark_summary(policy.root)
    report["generated_cache"] = generated_cache_cleanup(policy.root, maximum_bytes=policy.profile.job_disk_limit_mb * 1024 * 1024)
    return report


def estimate_workflow_resources(workflow_type: str, *, requested_profile: str = "auto", snapshot: HardwareSnapshot | None = None) -> dict[str, object]:
    """Estimate bounded job resources before a workflow is submitted."""

    policy = ResourcePolicy(requested_profile=requested_profile, snapshot=snapshot)
    kind = str(workflow_type).strip().casefold()
    multiplier = 2.0 if any(token in kind for token in ("train", "backtest", "optim")) else 1.0
    profile = policy.profile
    workload_memory = {"minimum": 256, "recommended": 768, "high": 1_536}[profile.profile_id]
    workload_disk = {"minimum": 256, "recommended": 1_024, "high": 4_096}[profile.profile_id]
    estimate = {
        "workflow_type": kind,
        "profile": profile.profile_id,
        "cpu": min(float(profile.minimum_cpu_cores), float(policy.snapshot.cpu_cores)),
        "memory_mb": int(workload_memory * multiplier),
        "disk_mb": int(workload_disk * multiplier),
        "batch_size": max(1, int(profile.batch_size / multiplier)),
        "chunk_size": max(64, int(profile.chunk_size / multiplier)),
        "model_size": profile.model_size if multiplier == 1 else "baseline_or_small",
        "warnings": list(policy.profile_warnings),
        "execution_allowed": False,
    }
    decision = policy.evaluate({
        "profile": estimate["profile"],
        "memory_mb": estimate["memory_mb"],
        "disk_mb": estimate["disk_mb"],
        "cpu": estimate["cpu"],
    })
    estimate["status"] = decision.status
    estimate["warnings"] = list(dict.fromkeys((*estimate["warnings"], *decision.warnings)))
    estimate["reasons"] = list(decision.reasons)
    return estimate


def generated_cache_cleanup(
    root: Path | None,
    *,
    maximum_bytes: int,
    apply: bool = False,
    publish_guard: PublicationScopeFactory | None = None,
) -> dict[str, object]:
    """Plan or apply oldest-first cleanup in the dedicated generated cache only."""

    if maximum_bytes < 0:
        raise ValueError("maximum_bytes must be non-negative")
    if root is None:
        return {"status": "unavailable", "reason": "project root unavailable", "apply": apply, "removed": [], "execution_allowed": False}
    unresolved_cache_root = Path(root).resolve() / RESOURCE_CACHE_RELATIVE
    if unresolved_cache_root.is_symlink():
        return {
            "status": "unavailable",
            "reason": "generated cache path is a symbolic link",
            "cache_path": str(unresolved_cache_root),
            "apply": apply,
            "removed": [],
            "execution_allowed": False,
        }
    cache_root = unresolved_cache_root.resolve()
    candidates: list[tuple[float, str, Path, int]] = []
    if cache_root.is_dir():
        for path in cache_root.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    stat = path.stat()
                    candidates.append((stat.st_mtime, path.relative_to(cache_root).as_posix(), path, stat.st_size))
            except OSError:
                continue
    candidates.sort(key=lambda item: (item[0], item[1]))
    total_bytes = sum(item[3] for item in candidates)
    remaining = total_bytes
    selected: list[tuple[str, Path, int]] = []
    for _modified, relative, path, size in candidates:
        if remaining <= maximum_bytes:
            break
        selected.append((relative, path, size))
        remaining -= size
    removed: list[str] = []
    failures: list[str] = []
    if apply:
        for relative, path, _size in selected:
            try:
                with publication_scope(publish_guard):
                    path.unlink()
                removed.append(relative)
            except OSError as exc:
                failures.append(f"{relative}:{type(exc).__name__}")
    return {
        "status": "failed" if failures else "cleanup_required" if selected and not apply else "clean",
        "cache_path": str(cache_root),
        "maximum_bytes": int(maximum_bytes),
        "observed_bytes": int(total_bytes),
        "planned_removals": [relative for relative, _path, _size in selected],
        "removed": removed,
        "failures": failures,
        "apply": apply,
        "scope": "reproducible_generated_cache_only",
        "execution_allowed": False,
    }


def _select_profile(snapshot: HardwareSnapshot, requested: str) -> tuple[str, str, tuple[str, ...]]:
    available = [profile for profile in PROFILES if _profile_decision(snapshot, profile).status != "blocked"]
    if requested == "auto":
        if not available:
            return "minimum", "blocked", ("Host is below the minimum supported profile.",)
        selected = available[-1]
        decision = _profile_decision(snapshot, selected)
        return selected.profile_id, decision.status, decision.warnings
    profile = _PROFILE_BY_ID[requested]
    decision = _profile_decision(snapshot, profile)
    if decision.status != "blocked":
        return profile.profile_id, decision.status, decision.warnings
    fallback = next((item for item in reversed(PROFILES[: PROFILES.index(profile)]) if _profile_decision(snapshot, item).status != "blocked"), None)
    if fallback is None:
        return "minimum", "blocked", decision.reasons
    return fallback.profile_id, "degraded", (f"Requested profile {requested} is unavailable; using {fallback.profile_id}.", *decision.reasons)


def _profile_decision(snapshot: HardwareSnapshot, profile: ResourceProfile) -> ResourceDecision:
    reasons: list[str] = []
    warnings: list[str] = []
    if snapshot.memory_total_mb is not None and snapshot.memory_total_mb < profile.minimum_memory_mb:
        reasons.append(f"memory {snapshot.memory_total_mb:.0f} MB < {profile.minimum_memory_mb} MB")
    elif snapshot.memory_total_mb is None:
        warnings.append("total memory unavailable; memory capacity is not verified")
    if snapshot.disk_free_mb is not None and snapshot.disk_free_mb < profile.minimum_disk_mb:
        reasons.append(f"free disk {snapshot.disk_free_mb:.0f} MB < {profile.minimum_disk_mb} MB")
    elif snapshot.disk_free_mb is None:
        warnings.append("free disk unavailable; storage capacity is not verified")
    if snapshot.cpu_cores < profile.minimum_cpu_cores:
        reasons.append(f"CPU cores {snapshot.cpu_cores} < {profile.minimum_cpu_cores}")
    return ResourceDecision("blocked" if reasons else "warning" if warnings else "supported", profile.profile_id, tuple(reasons), tuple(warnings))


def _profile_id(value: object, *, allow_auto: bool) -> str:
    key = str(value or "auto").strip().casefold()
    if allow_auto and key == "auto":
        return key
    if key not in _PROFILE_BY_ID:
        raise ValueError(f"unknown resource profile: {value}")
    return key


def _positive_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _declared_positive(resources: dict[str, object], key: str) -> tuple[float | None, bool]:
    """Return a positive declaration and whether a supplied value was invalid."""

    if key not in resources:
        return None, False
    value = resources[key]
    if value is None or isinstance(value, bool):
        return None, True
    number = _positive_number(value)
    return number, number is None


def _benchmark_summary(root: Path | None) -> dict[str, object]:
    """Summarise the existing versioned local performance evidence."""

    if root is None:
        return {
            "status": "unavailable",
            "reason": "project root unavailable",
            "timing_record_count": 0,
            "measurements": [],
            "network_calls": False,
        }
    try:
        report = build_performance_report(root)
    except (PerformanceBudgetError, OSError, TypeError, ValueError) as exc:
        return {
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "timing_record_count": 0,
            "measurements": [],
            "network_calls": False,
        }
    relevant_ids = {
        "startup_cold",
        "algorithm_scores",
        "screen_100",
        "screen_1000",
        "screen_10000",
        "backtest",
        "training",
        "app_peak_memory",
        "local_storage",
    }
    measurements = [
        item
        for item in report.get("measurements", [])
        if isinstance(item, dict) and item.get("metric_id") in relevant_ids
    ]
    return {
        "status": report.get("status", "unavailable"),
        "timing_record_count": int(report.get("timing_record_count", 0)),
        "measurements": measurements,
        "failures": list(report.get("failures", [])),
        "network_calls": False,
    }


def _finite_optional(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _free_disk(root: Path) -> float | None:
    try:
        return shutil.disk_usage(root).free / (1024 * 1024)
    except OSError:
        return None


def _system_memory() -> tuple[float | None, float | None]:
    if os.name == "nt":
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_uint32), ("memory_load", ctypes.c_uint32), ("total", ctypes.c_uint64), ("available", ctypes.c_uint64), ("total_page", ctypes.c_uint64), ("available_page", ctypes.c_uint64), ("total_virtual", ctypes.c_uint64), ("available_virtual", ctypes.c_uint64), ("available_extended", ctypes.c_uint64)]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.total / (1024 * 1024), status.available / (1024 * 1024)
        except (AttributeError, OSError, TypeError):
            pass
    linux_memory = _linux_memory()
    if linux_memory != (None, None):
        return linux_memory
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / (1024 * 1024), None
    except (AttributeError, OSError, ValueError):
        return None, None


def _linux_memory(path: Path = Path("/proc/meminfo")) -> tuple[float | None, float | None]:
    """Read Linux total and available memory without an optional dependency."""

    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    values: dict[str, float] = {}
    for row in rows:
        name, separator, raw_value = row.partition(":")
        if not separator or name not in {"MemTotal", "MemAvailable"}:
            continue
        parts = raw_value.split()
        if not parts:
            continue
        try:
            amount = float(parts[0])
        except ValueError:
            continue
        multiplier = 1024 if len(parts) > 1 and parts[1].casefold() == "kb" else 1
        values[name] = amount * multiplier / (1024 * 1024)
    return values.get("MemTotal"), values.get("MemAvailable")


def _no_gpu_probe() -> tuple[bool, str]:
    return False, "not_checked"


def _limitations(snapshot: HardwareSnapshot) -> list[str]:
    limitations = ["No external telemetry or cloud compute is used.", "Optional foundation models remain unavailable when packages or weights are missing."]
    if not snapshot.gpu_available:
        limitations.append("GPU acceleration is unavailable or not checked; CPU-only baselines remain the supported path.")
    if snapshot.memory_available_mb is None:
        limitations.append("Available-memory headroom is not measured; job memory requests remain conservative declarations.")
    return limitations


__all__ = [
    "HardwareSnapshot",
    "PROFILES",
    "RESOURCE_CACHE_RELATIVE",
    "RESOURCE_PROFILE_SCHEMA_VERSION",
    "ResourceDecision",
    "ResourcePolicy",
    "ResourceProfile",
    "detect_hardware",
    "estimate_workflow_resources",
    "generated_cache_cleanup",
    "resource_profile_report",
]
