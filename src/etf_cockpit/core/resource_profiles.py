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


RESOURCE_PROFILE_SCHEMA_VERSION = "resource-profiles.v1"


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
    ResourceProfile("minimum", 1_024, 2_048, 1, 8, 256, "baseline", "CPU-only baseline; optional foundation models remain disabled-safe."),
    ResourceProfile("recommended", 4_096, 10_240, 2, 32, 1_024, "small", "Balanced local profile for ordinary research and bounded jobs."),
    ResourceProfile("high", 8_192, 51_200, 4, 64, 2_048, "large", "Higher-throughput profile; GPU remains optional and never required."),
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
        profile_id = _profile_id(requested.get("profile", self.profile_id), allow_auto=True)
        selected = _PROFILE_BY_ID[self.profile_id if profile_id == "auto" else profile_id]
        reasons: list[str] = []
        warnings = list(self.profile_warnings)
        profile_decision = _profile_decision(self.snapshot, selected)
        reasons.extend(profile_decision.reasons)
        warnings.extend(profile_decision.warnings)
        memory_limit = self.snapshot.memory_available_mb if self.snapshot.memory_available_mb is not None else self.snapshot.memory_total_mb
        memory_requested = _positive_number(requested.get("memory_mb"))
        disk_requested = _positive_number(requested.get("disk_mb"))
        cpu_requested = _positive_number(requested.get("cpu"))
        if memory_requested is not None:
            if memory_limit is None:
                reasons.append("memory request cannot be checked because local capacity is unavailable")
            elif memory_requested > memory_limit:
                reasons.append(f"memory request {memory_requested:.0f} MB exceeds local limit {memory_limit:.0f} MB")
        if disk_requested is not None:
            if self.snapshot.disk_free_mb is None:
                reasons.append("disk request cannot be checked because local free space is unavailable")
            elif disk_requested > self.snapshot.disk_free_mb:
                reasons.append(f"disk request {disk_requested:.0f} MB exceeds free space {self.snapshot.disk_free_mb:.0f} MB")
        if cpu_requested is not None and cpu_requested > self.snapshot.cpu_cores:
            reasons.append(f"CPU request {cpu_requested:.0f} exceeds {self.snapshot.cpu_cores} local core(s)")
        gpu_requested = requested.get("gpu", False)
        if gpu_requested not in {False, None, "", 0} and not self.snapshot.gpu_available:
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

    return ResourcePolicy(root, requested_profile=requested_profile, snapshot=snapshot).report()


def estimate_workflow_resources(workflow_type: str, *, requested_profile: str = "auto", snapshot: HardwareSnapshot | None = None) -> dict[str, object]:
    """Estimate bounded job resources before a workflow is submitted."""

    policy = ResourcePolicy(requested_profile=requested_profile, snapshot=snapshot)
    kind = str(workflow_type).strip().casefold()
    multiplier = 2.0 if any(token in kind for token in ("train", "backtest", "optim")) else 1.0
    profile = policy.profile
    workload_memory = {"minimum": 512, "recommended": 1_024, "high": 2_048}[profile.profile_id]
    workload_disk = {"minimum": 512, "recommended": 2_048, "high": 8_192}[profile.profile_id]
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
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / (1024 * 1024), None
    except (AttributeError, OSError, ValueError):
        return None, None


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
    "RESOURCE_PROFILE_SCHEMA_VERSION",
    "ResourceDecision",
    "ResourcePolicy",
    "ResourceProfile",
    "detect_hardware",
    "estimate_workflow_resources",
    "resource_profile_report",
]
