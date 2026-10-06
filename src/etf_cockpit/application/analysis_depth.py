"""Versioned analysis-depth workload manifests and measured run evidence.

Stage wall time is exclusive of runner-reported acquisition and Training Centre
time; those durations are stored as separate timing records.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import json
import math
from pathlib import Path
import threading
import tempfile
import time
import tracemalloc
import uuid
from collections.abc import Callable, Mapping, Sequence

import yaml

from etf_cockpit.core.atomic_io import atomic_write_bytes, validate_parquet_file
from etf_cockpit.core.resource_profiles import estimate_workflow_resources


ANALYSIS_DEPTH_SCHEMA_VERSION = "analysis-depth.v1"
ANALYSIS_STAGE_SCHEMA_VERSION = "analysis-stage-manifest.v1"
ANALYSIS_RESOURCE_PLAN_SCHEMA_VERSION = "analysis-resource-plan.v1"
ANALYSIS_TIMING_SCHEMA_VERSION = "analysis-timing.v2"
ANALYSIS_UPGRADE_LINK_SCHEMA_VERSION = "analysis-upgrade-link.v1"
ANALYSIS_DEPTH_PROFILES_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "analysis_depth_profiles.yaml"
)
ANALYSIS_TIMINGS_RELATIVE_PATH = Path("data") / "analysis_timings.parquet"
REFERENCE_FIXTURE_ID = "reference_3000_supported_instruments"
REFERENCE_INSTRUMENT_COUNT = 3_000
MAX_PROFILE_DEPTH_WORKERS = 3
_TIMING_STORE_LOCK = threading.Lock()
_TRACE_LOCK = threading.Lock()
_TRACE_USERS = 0
_TRACE_OWNED = False


def _begin_resource_trace() -> None:
    global _TRACE_OWNED, _TRACE_USERS
    with _TRACE_LOCK:
        if _TRACE_USERS == 0:
            _TRACE_OWNED = not tracemalloc.is_tracing()
            if _TRACE_OWNED:
                tracemalloc.start()
        _TRACE_USERS += 1
        tracemalloc.reset_peak()


def _end_resource_trace() -> tuple[int, int]:
    global _TRACE_OWNED, _TRACE_USERS
    with _TRACE_LOCK:
        current, peak = tracemalloc.get_traced_memory()
        _TRACE_USERS -= 1
        if _TRACE_USERS == 0:
            if _TRACE_OWNED:
                tracemalloc.stop()
            _TRACE_OWNED = False
        return current, peak

MANDATORY_STAGE_IDS = (
    "identity_gate",
    "prices_gate",
    "data_gate",
    "hard_risk_gate",
    "liquidity_gate",
    "data_quality_gate",
    "formulas",
)
MANDATORY_GATE_IDS = frozenset(MANDATORY_STAGE_IDS) - {"formulas"}
PROFILE_IDS = ("quick", "medium", "high", "full")


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while loading the analysis-depth registry",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class AnalysisDepthError(ValueError):
    """Raised when a depth profile or its stage evidence is invalid."""

    def __init__(
        self,
        *args: object,
        timing_records: Sequence[AnalysisTimingRecord] = (),
    ) -> None:
        super().__init__(*args)
        self.timing_records = tuple(timing_records)


class MandatoryEvidenceError(AnalysisDepthError):
    """Raised when a required stage does not produce complete evidence."""

    def __init__(
        self,
        message: str,
        *,
        timing_records: Sequence[AnalysisTimingRecord] = (),
    ) -> None:
        super().__init__(message, timing_records=timing_records)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _string_tuple(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise AnalysisDepthError(f"{label} must be a list of strings")
    result = tuple(item.strip() for item in value if isinstance(item, str))
    if len(result) != len(value) or any(not item for item in result):
        raise AnalysisDepthError(f"{label} must contain non-blank strings")
    if len(set(result)) != len(result):
        raise AnalysisDepthError(f"{label} must not contain duplicates")
    if not result and not allow_empty:
        raise AnalysisDepthError(f"{label} must not be empty")
    return result


def _seed_tuple(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AnalysisDepthError(f"{label} must be a non-empty list of integer seeds")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise AnalysisDepthError(f"{label} must contain integer seeds")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise AnalysisDepthError(f"{label} must not contain duplicate seeds")
    return result


def _scalar_settings(value: object, label: str) -> tuple[tuple[str, object], ...]:
    if not isinstance(value, Mapping):
        raise AnalysisDepthError(f"{label} must be a mapping")
    result: list[tuple[str, object]] = []
    for key, item in sorted(value.items(), key=lambda entry: str(entry[0])):
        if not isinstance(key, str) or not key.strip():
            raise AnalysisDepthError(f"{label} keys must be non-blank strings")
        if isinstance(item, bool) or isinstance(item, (int, float, str)):
            if isinstance(item, float) and not math.isfinite(item):
                raise AnalysisDepthError(f"{label} values must be finite")
            result.append((key, item))
        else:
            raise AnalysisDepthError(f"{label} values must be scalar JSON values")
    return tuple(result)


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(str(item) for item in set(value) - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unsupported {', '.join(str(item) for item in unknown)}")
        raise AnalysisDepthError(f"{label} has invalid fields: {'; '.join(details)}")


@dataclass(frozen=True)
class AnalysisStageManifest:
    """Immutable versioned description of one analysis stage."""

    stage_id: str
    mandatory: bool
    stage_version: str
    model_families: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    horizons: tuple[str, ...] = ()
    seeds: tuple[int, ...] = ()
    robustness: tuple[tuple[str, object], ...] = ()
    schema_version: str = ANALYSIS_STAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stage_id": self.stage_id,
            "mandatory": self.mandatory,
            "stage_version": self.stage_version,
            "model_families": list(self.model_families),
            "sources": list(self.sources),
            "horizons": list(self.horizons),
            "seeds": list(self.seeds),
            "robustness": dict(self.robustness),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class AnalysisDepthProfile:
    """Frozen workload depth, separate from local hardware capacity."""

    profile_id: str
    profile_version: str
    stages: tuple[AnalysisStageManifest, ...]
    model_families: tuple[str, ...]
    sources: tuple[str, ...]
    horizons: tuple[str, ...]
    seeds: tuple[int, ...]
    robustness: tuple[tuple[str, object], ...]
    slo_seconds: int
    shard_size: int
    reference_fixture_id: str
    reference_fixture_digest: str | None
    reference_cpu_cores: int
    reference_memory_mb: int
    reference_gpu_label: str
    schema_version: str = ANALYSIS_DEPTH_SCHEMA_VERSION

    @property
    def mandatory_stages(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.stages if stage.mandatory)

    @property
    def optional_stages(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.stages if not stage.mandatory)

    @property
    def manifest_hash(self) -> str:
        return _content_hash(self.to_dict(include_hash=False))

    def stage(self, stage_id: str) -> AnalysisStageManifest:
        for stage in self.stages:
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(stage_id)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "stages": [stage.to_dict() for stage in self.stages],
            "model_families": list(self.model_families),
            "sources": list(self.sources),
            "horizons": list(self.horizons),
            "seeds": list(self.seeds),
            "robustness": dict(self.robustness),
            "slo_seconds": self.slo_seconds,
            "shard_size": self.shard_size,
            "reference_fixture_id": self.reference_fixture_id,
            "reference_fixture_digest": self.reference_fixture_digest,
            "reference_machine": {
                "cpu_cores": self.reference_cpu_cores,
                "memory_mb": self.reference_memory_mb,
                "gpu_label": self.reference_gpu_label,
            },
        }
        if include_hash:
            result["manifest_hash"] = self.manifest_hash
        return result

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class AnalysisResourcePlan:
    """Depth workload hints plus a separate hardware-profile estimate."""

    profile_id: str
    hardware_profile_id: str
    shard_size: int
    cpu_fallback: bool
    low_resource: bool
    estimated_cpu: float
    estimated_memory_mb: int
    estimated_disk_mb: int
    compatibility_status: str
    concurrency_limit: int = 1
    reasons: tuple[str, ...] = ()
    schema_version: str = ANALYSIS_RESOURCE_PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "hardware_profile_id": self.hardware_profile_id,
            "shard_size": self.shard_size,
            "cpu_fallback": self.cpu_fallback,
            "low_resource": self.low_resource,
            "estimated_cpu": self.estimated_cpu,
            "estimated_memory_mb": self.estimated_memory_mb,
            "estimated_disk_mb": self.estimated_disk_mb,
            "compatibility_status": self.compatibility_status,
            "concurrency_limit": self.concurrency_limit,
            "reasons": list(self.reasons),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class AnalysisTimingRecord:
    """Measured stage, acquisition, or Training Centre timing evidence."""

    run_id: str
    profile_id: str
    timing_kind: str
    stage_id: str
    wall_time_seconds: float
    cache_state: str
    provider_wait_seconds: float | None = None
    model_omissions: tuple[str, ...] = ()
    peak_resources: tuple[tuple[str, float], ...] = ()
    schema_version: str = ANALYSIS_TIMING_SCHEMA_VERSION
    outcome: str = "succeeded"

    def __post_init__(self) -> None:
        if self.outcome not in {"succeeded", "failed", "cancelled", "unknown"}:
            raise AnalysisDepthError("outcome must be succeeded, failed, cancelled or unknown")
        if self.timing_kind not in {"stage", "cold_acquisition", "training_centre"}:
            raise AnalysisDepthError("timing_kind must be stage, cold_acquisition or training_centre")
        if self.cache_state not in {"cold", "warm"}:
            raise AnalysisDepthError("cache_state must be cold or warm")
        _finite_nonnegative(self.wall_time_seconds, "wall_time_seconds")
        if self.provider_wait_seconds is not None:
            _finite_nonnegative(self.provider_wait_seconds, "provider_wait_seconds")
        if not self.run_id or not self.profile_id or not self.stage_id:
            raise AnalysisDepthError("timing records require run, profile and stage identifiers")
        if any(not isinstance(item, str) or not item.strip() for item in self.model_omissions):
            raise AnalysisDepthError("model_omissions must contain non-blank strings")
        if any(
            not isinstance(name, str) or not name.strip()
            for name, _value in self.peak_resources
        ):
            raise AnalysisDepthError("peak resource names must be non-blank strings")
        for name, value in self.peak_resources:
            _finite_nonnegative(value, f"peak_resources.{name}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "timing_kind": self.timing_kind,
            "stage_id": self.stage_id,
            "wall_time_seconds": self.wall_time_seconds,
            "cache_state": self.cache_state,
            "provider_wait_seconds": self.provider_wait_seconds,
            "model_omissions": list(self.model_omissions),
            "peak_resources": dict(self.peak_resources),
            "outcome": self.outcome,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class AnalysisUpgradeLink:
    """Lineage from an immutable earlier run to a deeper new run."""

    parent_run_id: str
    child_run_id: str
    from_profile: str
    to_profile: str
    reused_stage_hashes: tuple[str, ...] = ()
    schema_version: str = ANALYSIS_UPGRADE_LINK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "from_profile": self.from_profile,
            "to_profile": self.to_profile,
            "reused_stage_hashes": list(self.reused_stage_hashes),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisDepthError(f"{label} must be a finite non-negative number")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise AnalysisDepthError(f"{label} must be a finite non-negative number")
    return converted


def _profile_from_mapping(
    profile_id: str,
    raw: object,
    reference: object,
    reference_fixture_digest: object,
) -> AnalysisDepthProfile:
    if not isinstance(raw, Mapping) or not isinstance(reference, Mapping):
        raise AnalysisDepthError(f"profile {profile_id} must be a mapping")
    _require_keys(
        raw,
        {
            "profile_id", "profile_version", "mandatory_stages", "optional_stages",
            "model_families", "sources", "horizons", "seeds", "robustness",
            "slo_seconds", "shard_size",
        },
        f"profile {profile_id}",
    )
    _require_keys(reference, {"cpu_cores", "memory_mb", "gpu_label"}, "reference_machine")
    if raw.get("profile_id") != profile_id:
        raise AnalysisDepthError(f"profile key and profile_id differ for {profile_id}")
    profile_version = raw.get("profile_version")
    if not isinstance(profile_version, str) or not profile_version.strip():
        raise AnalysisDepthError(f"profile {profile_id} needs a version")
    mandatory = _string_tuple(raw.get("mandatory_stages"), f"{profile_id}.mandatory_stages")
    optional = _string_tuple(raw.get("optional_stages"), f"{profile_id}.optional_stages", allow_empty=True)
    if mandatory != MANDATORY_STAGE_IDS or set(mandatory) != set(MANDATORY_STAGE_IDS):
        missing = sorted(set(MANDATORY_STAGE_IDS) - set(mandatory))
        raise AnalysisDepthError(f"profile {profile_id} drops mandatory stage or gate: {', '.join(missing)}")
    if not MANDATORY_GATE_IDS.issubset(mandatory):
        raise AnalysisDepthError(f"profile {profile_id} drops a mandatory gate")
    if set(mandatory) & set(optional):
        raise AnalysisDepthError(f"profile {profile_id} repeats a stage as optional")
    models = _string_tuple(raw.get("model_families"), f"{profile_id}.model_families")
    sources = _string_tuple(raw.get("sources"), f"{profile_id}.sources")
    horizons = _string_tuple(raw.get("horizons"), f"{profile_id}.horizons")
    seeds = _seed_tuple(raw.get("seeds"), f"{profile_id}.seeds")
    robustness = _scalar_settings(raw.get("robustness"), f"{profile_id}.robustness")
    slo_seconds = raw.get("slo_seconds")
    shard_size = raw.get("shard_size")
    if isinstance(slo_seconds, bool) or not isinstance(slo_seconds, int) or slo_seconds <= 0:
        raise AnalysisDepthError(f"profile {profile_id}.slo_seconds must be a positive integer")
    if isinstance(shard_size, bool) or not isinstance(shard_size, int) or shard_size <= 0:
        raise AnalysisDepthError(f"profile {profile_id}.shard_size must be a positive integer")
    stages = tuple(
        AnalysisStageManifest(stage_id, True, "1") for stage_id in mandatory
    ) + tuple(
        AnalysisStageManifest(
            stage_id=stage_id,
            mandatory=False,
            stage_version="1",
            model_families=models,
            sources=sources,
            horizons=horizons,
            seeds=seeds,
            robustness=robustness,
        )
        for stage_id in optional
    )
    reference_cpu = reference.get("cpu_cores")
    reference_memory = reference.get("memory_mb")
    reference_gpu = reference.get("gpu_label")
    if (
        isinstance(reference_cpu, bool) or not isinstance(reference_cpu, int) or reference_cpu <= 0
        or isinstance(reference_memory, bool) or not isinstance(reference_memory, int) or reference_memory <= 0
        or not isinstance(reference_gpu, str) or not reference_gpu.strip()
    ):
        raise AnalysisDepthError("reference_machine needs positive cpu_cores/memory_mb and gpu_label")
    if reference_fixture_digest is None:
        normalized_reference_digest = None
    elif (
        not isinstance(reference_fixture_digest, str)
        or len(reference_fixture_digest) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in reference_fixture_digest)
    ):
        raise AnalysisDepthError("reference_fixture_digest must be a SHA-256 hex digest or null")
    else:
        normalized_reference_digest = reference_fixture_digest.casefold()
    return AnalysisDepthProfile(
        profile_id=profile_id,
        profile_version=profile_version,
        stages=stages,
        model_families=models,
        sources=sources,
        horizons=horizons,
        seeds=seeds,
        robustness=robustness,
        slo_seconds=slo_seconds,
        shard_size=shard_size,
        reference_fixture_id=REFERENCE_FIXTURE_ID,
        reference_fixture_digest=normalized_reference_digest,
        reference_cpu_cores=reference_cpu,
        reference_memory_mb=reference_memory,
        reference_gpu_label=reference_gpu,
    )


def load_analysis_depth_profiles(path: Path | None = None) -> dict[str, AnalysisDepthProfile]:
    """Load and validate the local registry, rejecting incomplete manifests."""

    registry_path = Path(path) if path is not None else ANALYSIS_DEPTH_PROFILES_PATH
    try:
        raw = yaml.load(registry_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise AnalysisDepthError(f"analysis-depth registry is unavailable or invalid: {exc}") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "analysis-depth-profiles.v1":
        raise AnalysisDepthError("analysis-depth registry schema_version is unsupported")
    _require_keys(
        raw,
        {
            "schema_version",
            "reference_fixture_id",
            "reference_fixture_digest",
            "reference_machine",
            "profiles",
        },
        "analysis-depth registry",
    )
    if raw.get("reference_fixture_id") != REFERENCE_FIXTURE_ID:
        raise AnalysisDepthError("analysis-depth registry reference fixture is unsupported")
    reference = raw.get("reference_machine")
    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, Mapping) or set(profiles_raw) != set(PROFILE_IDS):
        raise AnalysisDepthError("analysis-depth registry must declare Quick, Medium, High and Full")
    profiles = {
        profile_id: _profile_from_mapping(
            profile_id,
            profiles_raw[profile_id],
            reference,
            raw.get("reference_fixture_digest"),
        )
        for profile_id in PROFILE_IDS
    }
    mandatory_sets = {profile.mandatory_stages for profile in profiles.values()}
    if len(mandatory_sets) != 1 or next(iter(mandatory_sets)) != MANDATORY_STAGE_IDS:
        raise AnalysisDepthError("all profiles must preserve the identical mandatory stage set")
    return profiles


def profile_from_dict(payload: object) -> AnalysisDepthProfile:
    """Rebuild a profile frozen into a durable run and verify its content hash."""

    if not isinstance(payload, Mapping):
        raise AnalysisDepthError("frozen analysis-depth profile must be an object")
    profile_id = payload.get("profile_id")
    if profile_id not in PROFILE_IDS:
        raise AnalysisDepthError("frozen analysis-depth profile id is unsupported")
    raw_reference = payload.get("reference_machine")
    if not isinstance(payload.get("stages"), list) or not isinstance(raw_reference, Mapping):
        raise AnalysisDepthError("frozen analysis-depth profile manifest is malformed")
    stage_list = payload["stages"]
    mandatory = [item.get("stage_id") for item in stage_list if isinstance(item, Mapping) and item.get("mandatory") is True]
    optional = [item.get("stage_id") for item in stage_list if isinstance(item, Mapping) and item.get("mandatory") is False]
    if len(mandatory) + len(optional) != len(stage_list):
        raise AnalysisDepthError("frozen profile has malformed stages")
    raw = {
        "profile_id": profile_id,
        "profile_version": payload.get("profile_version"),
        "mandatory_stages": mandatory,
        "optional_stages": optional,
        "model_families": payload.get("model_families"),
        "sources": payload.get("sources"),
        "horizons": payload.get("horizons"),
        "seeds": payload.get("seeds"),
        "robustness": payload.get("robustness"),
        "slo_seconds": payload.get("slo_seconds"),
        "shard_size": payload.get("shard_size"),
    }
    profile = _profile_from_mapping(
        str(profile_id),
        raw,
        raw_reference,
        payload.get("reference_fixture_digest"),
    )
    expected_stages = payload.get("stages")
    if [stage.to_dict() for stage in profile.stages] != expected_stages:
        raise AnalysisDepthError("frozen profile stage details do not match the declared profile settings")
    expected_hash = payload.get("manifest_hash")
    if not isinstance(expected_hash, str) or expected_hash != profile.manifest_hash:
        raise AnalysisDepthError("frozen analysis-depth manifest hash is invalid")
    return profile


def create_resource_plan(
    profile: AnalysisDepthProfile,
    *,
    hardware_profile: str = "auto",
    low_resource: bool = False,
) -> AnalysisResourcePlan:
    """Estimate hardware compatibility while retaining depth semantics."""

    estimate = estimate_workflow_resources("bulk_analysis", requested_profile=hardware_profile)
    effective_profile = str(estimate["profile"])
    shard_size = 1 if low_resource else profile.shard_size
    reasons_raw = estimate.get("reasons", ())
    reasons = tuple(str(item) for item in reasons_raw) if isinstance(reasons_raw, (list, tuple)) else ()
    estimated_cpu = float(estimate["cpu"])
    estimated_memory_mb = int(estimate["memory_mb"])
    estimated_disk_mb = int(estimate["disk_mb"])
    concurrency_limit = (
        1
        if low_resource
        else max(
            1,
            min(MAX_PROFILE_DEPTH_WORKERS, int(estimated_cpu), estimated_memory_mb, estimated_disk_mb),
        )
    )
    return AnalysisResourcePlan(
        profile_id=profile.profile_id,
        hardware_profile_id=effective_profile,
        shard_size=shard_size,
        cpu_fallback=True,
        low_resource=bool(low_resource),
        estimated_cpu=estimated_cpu,
        estimated_memory_mb=estimated_memory_mb,
        estimated_disk_mb=estimated_disk_mb,
        compatibility_status=str(estimate["status"]),
        concurrency_limit=concurrency_limit,
        reasons=reasons,
    )


def resource_plan_from_dict(payload: object) -> AnalysisResourcePlan:
    """Rebuild a resource plan frozen into a durable run."""

    if not isinstance(payload, Mapping) or payload.get("schema_version") != ANALYSIS_RESOURCE_PLAN_SCHEMA_VERSION:
        raise AnalysisDepthError("stored analysis resource plan is malformed")
    if "concurrency_limit" not in payload:
        payload = {**payload, "concurrency_limit": 1}
    _require_keys(
        payload,
        {
            "schema_version", "profile_id", "hardware_profile_id", "shard_size",
            "cpu_fallback", "low_resource", "estimated_cpu", "estimated_memory_mb",
            "estimated_disk_mb", "compatibility_status", "concurrency_limit", "reasons",
        },
        "stored analysis resource plan",
    )
    reasons = payload.get("reasons", ())
    if not isinstance(reasons, (list, tuple)) or any(not isinstance(item, str) for item in reasons):
        raise AnalysisDepthError("stored resource plan reasons are malformed")
    if not isinstance(payload.get("cpu_fallback"), bool) or not isinstance(payload.get("low_resource"), bool):
        raise AnalysisDepthError("stored resource plan flags are malformed")
    if any(not isinstance(payload.get(field), str) or not payload.get(field) for field in ("profile_id", "hardware_profile_id", "compatibility_status")):
        raise AnalysisDepthError("stored resource plan identifiers are malformed")
    try:
        shard_size = payload["shard_size"]
        memory_mb = payload["estimated_memory_mb"]
        disk_mb = payload["estimated_disk_mb"]
        concurrency_limit = payload["concurrency_limit"]
        if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in (shard_size, memory_mb, disk_mb)):
            raise ValueError("integer resource fields must be positive")
        if (
            isinstance(concurrency_limit, bool)
            or not isinstance(concurrency_limit, int)
            or not 0 < concurrency_limit <= MAX_PROFILE_DEPTH_WORKERS
        ):
            raise ValueError("concurrency_limit must be a positive integer")
        cpu = _finite_nonnegative(payload["estimated_cpu"], "estimated_cpu")
        return AnalysisResourcePlan(
            profile_id=str(payload["profile_id"]),
            hardware_profile_id=str(payload["hardware_profile_id"]),
            shard_size=shard_size,
            cpu_fallback=payload["cpu_fallback"],
            low_resource=payload["low_resource"],
            estimated_cpu=cpu,
            estimated_memory_mb=memory_mb,
            estimated_disk_mb=disk_mb,
            compatibility_status=str(payload["compatibility_status"]),
            concurrency_limit=concurrency_limit,
            reasons=tuple(reasons),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisDepthError("stored analysis resource plan is malformed") from exc


def analysis_run_identity(
    inputs: Mapping[str, object],
    analyzer_id: str,
    profile: AnalysisDepthProfile,
    *,
    horizons: Sequence[str] | None = None,
    seeds: Sequence[int] | None = None,
) -> str:
    """Hash the exact inputs and frozen workload manifest used by a bulk run."""

    if not inputs:
        raise AnalysisDepthError("run identity requires at least one instrument")
    input_hashes = [
        (instrument_id, _content_hash(_json_safe(analysis_input)))
        for instrument_id, analysis_input in sorted(inputs.items())
    ]
    identity = {
        "analyzer_id": analyzer_id,
        "profile_id": profile.profile_id,
        "manifest_hash": profile.manifest_hash,
        "horizons": list(horizons if horizons is not None else profile.horizons),
        "seeds": list(seeds if seeds is not None else profile.seeds),
        "inputs": input_hashes,
    }
    return _content_hash(identity)


def stage_cache_key(
    instrument_id: str,
    analysis_input: object,
    analyzer_id: str,
    stage: AnalysisStageManifest,
    *,
    horizons: Sequence[str] | None = None,
    seeds: Sequence[int] | None = None,
) -> str:
    """Return a content-derived key that shares invariant stages across depths."""

    key: dict[str, object] = {
        "instrument_id": instrument_id,
        "input_hash": _content_hash(_json_safe(analysis_input)),
        "analyzer_id": analyzer_id,
        "stage": stage.to_dict(),
    }
    if not stage.mandatory:
        key["horizons"] = list(horizons if horizons is not None else stage.horizons)
        key["seeds"] = list(seeds if seeds is not None else stage.seeds)
    return _content_hash(key)


def stage_output_hash(value: object) -> str:
    """Hash a JSON-exportable stage result for content-addressed reuse."""

    return _content_hash(_json_safe(value))


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AnalysisDepthError("analysis inputs and stage outputs must use finite numbers")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise AnalysisDepthError("analysis inputs and stage outputs must use string keys")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise AnalysisDepthError(f"analysis input or stage output is not JSON-exportable: {type(value).__name__}")


def _mandatory_result_error(stage: AnalysisStageManifest, result: object) -> str | None:
    if not stage.mandatory:
        return None
    if result is None or result is False or result == "" or result == [] or result == {}:
        return f"mandatory evidence missing for stage {stage.stage_id}"
    if isinstance(result, Mapping):
        status = result.get("status")
        if isinstance(status, str) and status.casefold() in {"failed", "blocked", "missing", "unavailable", "incomplete", "omitted", "skipped"}:
            return f"mandatory evidence for stage {stage.stage_id} did not complete: {status}"
        if result.get("passed") is False:
            return f"mandatory gate {stage.stage_id} failed"
    return None


def _stage_return_parts(value: object) -> tuple[object, Mapping[str, object]]:
    if isinstance(value, Mapping) and "analysis_depth_result" in value and "analysis_depth_timing" in value:
        timing = value["analysis_depth_timing"]
        if not isinstance(timing, Mapping):
            raise AnalysisDepthError("analysis_depth_timing must be an object")
        return value["analysis_depth_result"], timing
    return value, {}


def _timing_metadata(
    raw: Mapping[str, object], profile: AnalysisDepthProfile
) -> tuple[float | None, tuple[str, ...], tuple[tuple[str, float], ...], tuple[tuple[str, float], ...]]:
    provider_wait_raw = raw.get("provider_wait_seconds")
    provider_wait = None if provider_wait_raw is None else _finite_nonnegative(provider_wait_raw, "provider_wait_seconds")
    omissions_raw = raw.get("model_omissions", ())
    omissions = _string_tuple(omissions_raw, "model_omissions", allow_empty=True)
    if not set(omissions).issubset(profile.model_families):
        raise AnalysisDepthError("model omission references a family outside the frozen profile")
    peaks_raw = raw.get("peak_resources", {})
    peaks: list[tuple[str, float]] = []
    if not isinstance(peaks_raw, Mapping):
        raise AnalysisDepthError("peak_resources must be an object")
    for key, value in sorted(peaks_raw.items(), key=lambda entry: str(entry[0])):
        if not isinstance(key, str) or not key.strip():
            raise AnalysisDepthError("peak resource names must be non-blank strings")
        peaks.append((key, _finite_nonnegative(value, f"peak_resources.{key}")))
    separate: list[tuple[str, float]] = []
    for field, kind in (("cold_acquisition_seconds", "cold_acquisition"), ("training_centre_seconds", "training_centre")):
        if field in raw:
            separate.append((kind, _finite_nonnegative(raw[field], field)))
    return provider_wait, omissions, tuple(peaks), tuple(separate)


StageRunner = Callable[[str, object, AnalysisStageManifest, AnalysisResourcePlan], object]


def execute_profiled_stages(
    profile: AnalysisDepthProfile,
    instrument_id: str,
    analysis_input: object,
    analyzer_id: str,
    stage_runner: StageRunner,
    cache: dict[str, dict[str, object]],
    *,
    run_id: str,
    cache_state: str = "cold",
    resource_plan: AnalysisResourcePlan | None = None,
    horizons: Sequence[str] | None = None,
    seeds: Sequence[int] | None = None,
    is_cancel_requested: Callable[[], bool] | None = None,
    cache_lock: threading.Lock | None = None,
    on_stage_progress: Callable[[str, int, int, str], None] | None = None,
) -> tuple[dict[str, object], tuple[AnalysisTimingRecord, ...]]:
    """Run each frozen stage or reuse a content-identical durable stage result."""

    if not callable(stage_runner):
        raise TypeError("stage_runner must be callable for a profile-depth run")
    if cache_state not in {"cold", "warm"}:
        raise AnalysisDepthError("cache_state must be cold or warm")
    stage_outputs: dict[str, object] = {}
    stage_hashes: dict[str, dict[str, object]] = {}
    timing_records: list[AnalysisTimingRecord] = []
    omissions: set[str] = set()
    omitted_stages: list[str] = []

    active_stage: AnalysisStageManifest | None = None
    active_stage_elapsed = 0.0
    active_stage_cache_state = cache_state
    try:
        for stage_index, stage in enumerate(profile.stages, start=1):
            active_stage = stage
            active_stage_elapsed = 0.0
            active_stage_cache_state = cache_state
            if is_cancel_requested is not None and is_cancel_requested():
                timing_records.append(AnalysisTimingRecord(
                    run_id=run_id,
                    profile_id=profile.profile_id,
                    timing_kind="stage",
                    stage_id=stage.stage_id,
                    wall_time_seconds=0.0,
                    cache_state=cache_state,
                    outcome="cancelled",
                ))
                break
            if on_stage_progress is not None:
                on_stage_progress(stage.stage_id, stage_index, len(profile.stages), "running")
            stage_horizons = tuple(horizons if horizons is not None else stage.horizons)
            stage_seeds = tuple(seeds if seeds is not None else stage.seeds)
            key = stage_cache_key(
                instrument_id,
                analysis_input,
                analyzer_id,
                stage,
                horizons=stage_horizons,
                seeds=stage_seeds,
            )
            lookup_started = time.perf_counter()
            with cache_lock if cache_lock is not None else nullcontext():
                cached = cache.get(key)
            cache_hit = (
                isinstance(cached, Mapping)
                and "result" in cached
                and cached.get("content_hash") == _content_hash(_json_safe(cached["result"]))
            )
            active_stage_cache_state = "warm" if cache_hit else "cold"
            provider_wait: float | None = None
            model_omissions: tuple[str, ...] = ()
            peak_resources: tuple[tuple[str, float], ...] = ()
            separate_timings: tuple[tuple[str, float], ...] = ()
            if cache_hit:
                _begin_resource_trace()
                stage_result = cached["result"]
                content_hash = str(cached["content_hash"])
                reused = True
                elapsed = time.perf_counter() - lookup_started
                active_stage_elapsed = elapsed
                stage_cache_state = "warm"
                _current_bytes, peak_bytes = _end_resource_trace()
                peak_resources = (("python_heap_peak_mb", peak_bytes / 1_048_576),)
            else:
                _begin_resource_trace()
                started = time.perf_counter()
                runner_called = False
                try:
                    if resource_plan is None:
                        raise AnalysisDepthError("profile-depth stages require a frozen resource plan")
                    runner_stage = (
                        replace(stage, horizons=stage_horizons, seeds=stage_seeds)
                        if not stage.mandatory
                        else stage
                    )
                    runner_called = True
                    raw_result = stage_runner(instrument_id, analysis_input, runner_stage, resource_plan)
                except Exception as exc:
                    elapsed = time.perf_counter() - started
                    active_stage_elapsed = elapsed
                    _current_bytes, peak_bytes = _end_resource_trace()
                    cancelled = is_cancel_requested is not None and is_cancel_requested()
                    if cancelled:
                        timing_records.append(AnalysisTimingRecord(
                            run_id=run_id,
                            profile_id=profile.profile_id,
                            timing_kind="stage",
                            stage_id=stage.stage_id,
                            wall_time_seconds=elapsed,
                            cache_state="cold",
                            peak_resources=(("python_heap_peak_mb", peak_bytes / 1_048_576),),
                            outcome="cancelled",
                        ))
                        break
                    if stage.mandatory and runner_called:
                        peak_resources = (("python_heap_peak_mb", peak_bytes / 1_048_576),)
                        timing_records.append(AnalysisTimingRecord(
                            run_id=run_id,
                            profile_id=profile.profile_id,
                            timing_kind="stage",
                            stage_id=stage.stage_id,
                            wall_time_seconds=elapsed,
                            cache_state="cold",
                            peak_resources=peak_resources,
                            outcome="failed",
                        ))
                        raise MandatoryEvidenceError(
                            f"mandatory stage {stage.stage_id} failed: {exc}",
                            timing_records=timing_records,
                        ) from exc
                    raise
                elapsed = time.perf_counter() - started
                active_stage_elapsed = elapsed
                _current_bytes, peak_bytes = _end_resource_trace()
                if is_cancel_requested is not None and is_cancel_requested():
                    timing_records.append(AnalysisTimingRecord(
                        run_id=run_id,
                        profile_id=profile.profile_id,
                        timing_kind="stage",
                        stage_id=stage.stage_id,
                        wall_time_seconds=elapsed,
                        cache_state="cold",
                        peak_resources=(("python_heap_peak_mb", peak_bytes / 1_048_576),),
                        outcome="cancelled",
                    ))
                    break
                stage_result, timing_raw = _stage_return_parts(raw_result)
                provider_wait, model_omissions, reported_peaks, separate_timings = _timing_metadata(timing_raw, profile)
                reported_separate_seconds = sum(seconds for _kind, seconds in separate_timings)
                if reported_separate_seconds > elapsed:
                    raise AnalysisDepthError(
                        "runner-reported acquisition and Training Centre time exceeds stage runner wall time"
                    )
                elapsed -= reported_separate_seconds
                active_stage_elapsed = elapsed
                peak_resources = tuple(sorted((*reported_peaks, ("python_heap_peak_mb", peak_bytes / 1_048_576))))
                stage_result = _json_safe(stage_result)
                reused = False
                stage_cache_state = "cold"
                content_hash = _content_hash(stage_result)
            error = _mandatory_result_error(stage, stage_result)
            if error is None and isinstance(stage_result, Mapping):
                declared_omissions = stage_result.get("model_omissions", ())
                if isinstance(declared_omissions, (list, tuple)):
                    model_omissions = tuple(str(item) for item in declared_omissions)
                    if not set(model_omissions).issubset(profile.model_families):
                        raise AnalysisDepthError("model omission references a family outside the frozen profile")
            if error is None:
                omissions.update(model_omissions)
                if stage_result is None and not stage.mandatory:
                    omitted_stages.append(stage.stage_id)
                stage_outputs[stage.stage_id] = stage_result
                stage_hashes[stage.stage_id] = {
                    "cache_key": key,
                    "content_hash": content_hash,
                    "reused": reused,
                }
            timing_records.append(AnalysisTimingRecord(
                run_id=run_id,
                profile_id=profile.profile_id,
                timing_kind="stage",
                stage_id=stage.stage_id,
                wall_time_seconds=elapsed,
                cache_state=stage_cache_state,
                provider_wait_seconds=provider_wait,
                model_omissions=model_omissions,
                peak_resources=peak_resources,
                outcome="failed" if error is not None else "succeeded",
            ))
            for timing_kind, seconds in separate_timings:
                timing_records.append(AnalysisTimingRecord(
                    run_id=run_id,
                    profile_id=profile.profile_id,
                    timing_kind=timing_kind,
                    stage_id=stage.stage_id,
                    wall_time_seconds=seconds,
                    cache_state=stage_cache_state,
                    provider_wait_seconds=provider_wait,
                    model_omissions=model_omissions,
                    peak_resources=peak_resources,
                    outcome="failed" if error is not None else "succeeded",
                ))
            if error is not None:
                raise MandatoryEvidenceError(error, timing_records=timing_records)
            if not reused:
                with cache_lock if cache_lock is not None else nullcontext():
                    existing = cache.get(key)
                    existing_hash = None
                    existing_valid = False
                    if isinstance(existing, Mapping) and "result" in existing:
                        try:
                            existing_hash = stage_output_hash(existing["result"])
                        except AnalysisDepthError:
                            pass
                        else:
                            existing_valid = existing_hash == existing.get("content_hash")
                    if existing_valid:
                        if existing_hash != content_hash:
                            raise AnalysisDepthError(
                                f"determinism violation for stage {stage.stage_id} and cache key {key}: "
                                f"existing hash {existing_hash} differs from recomputed hash {content_hash}"
                            )
                        stage_result = existing["result"]
                        stage_outputs[stage.stage_id] = stage_result
                    else:
                        cache[key] = {"content_hash": content_hash, "result": stage_result}
            if on_stage_progress is not None:
                on_stage_progress(stage.stage_id, stage_index, len(profile.stages), "completed")

    except AnalysisDepthError as exc:
        if active_stage is not None:
            has_stage_timing = any(
                record.run_id == run_id
                and record.stage_id == active_stage.stage_id
                and record.timing_kind == "stage"
                for record in timing_records
            )
            if has_stage_timing:
                timing_records[:] = [
                    replace(record, outcome="failed")
                    if record.run_id == run_id and record.stage_id == active_stage.stage_id
                    else record
                    for record in timing_records
                ]
            else:
                timing_records.append(AnalysisTimingRecord(
                    run_id=run_id,
                    profile_id=profile.profile_id,
                    timing_kind="stage",
                    stage_id=active_stage.stage_id,
                    wall_time_seconds=max(0.0, active_stage_elapsed),
                    cache_state=active_stage_cache_state,
                    outcome="failed",
                ))
        exc.timing_records = tuple(timing_records)
        raise

    deterministic_fields = {
        stage_id: stage_outputs[stage_id]
        for stage_id in profile.mandatory_stages
        if stage_id in stage_outputs
    }
    output = {
        "profile_id": profile.profile_id,
        "manifest_hash": profile.manifest_hash,
        "deterministic_fields": deterministic_fields,
        "stages": stage_outputs,
        "stage_hashes": stage_hashes,
        "omitted_optional_stages": omitted_stages,
        "model_omissions": sorted(omissions),
    }
    return output, tuple(timing_records)


def append_timing_records(root: Path, records: Sequence[AnalysisTimingRecord]) -> Path | None:
    """Append measured records to the project's Parquet timing store."""

    if not records:
        return None
    with _TIMING_STORE_LOCK:
        return _append_timing_records(root, records)


def _append_timing_records(root: Path, records: Sequence[AnalysisTimingRecord]) -> Path:
    import pandas as pd

    path = Path(root) / ANALYSIS_TIMINGS_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [record.to_dict() for record in records]
    for row in rows:
        row["peak_resources"] = _canonical_json(row["peak_resources"])
    frame = pd.DataFrame(rows)
    if path.is_file():
        previous = pd.read_parquet(path)
        expected = list(frame.columns)
        legacy = [column for column in expected if column != "outcome"]
        if list(previous.columns) == legacy:
            previous = previous.copy()
            previous["outcome"] = "unknown"
            previous = previous[expected]
        elif list(previous.columns) != expected:
            raise AnalysisDepthError("analysis_timings.parquet has an unsupported schema")
        frame = pd.concat((previous, frame), ignore_index=True)
    _write_parquet_atomically(frame, path)
    return path


def timing_percentiles(
    records: Sequence[AnalysisTimingRecord],
    *,
    profile_id: str | None = None,
    timing_kind: str = "stage",
) -> dict[str, float | int]:
    """Compute p50/p95 from stored measurements without deriving an ETA."""

    values = sorted(
        record.wall_time_seconds
        for record in records
        if record.timing_kind == timing_kind and (profile_id is None or record.profile_id == profile_id)
    )
    if not values:
        raise AnalysisDepthError("percentiles require measured timing records")

    def percentile(p: float) -> float:
        position = (len(values) - 1) * p
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return float(values[lower])
        fraction = position - lower
        return float(values[lower] + (values[upper] - values[lower]) * fraction)

    return {"sample_count": len(values), "p50_seconds": percentile(0.50), "p95_seconds": percentile(0.95)}


def certify_benchmark(
    profile: AnalysisDepthProfile,
    *,
    fixture_id: str,
    fixture_content_digest: str | None,
    instrument_count: int,
    cache_state: str,
    cache_hits: int,
    p95_seconds: float,
    machine: Mapping[str, object] | None,
) -> dict[str, object]:
    """Certify only matching reference content measured with observed cache hits."""

    reasons: list[str] = []
    if fixture_id != profile.reference_fixture_id:
        reasons.append("measurement did not use the declared reference fixture")
    if instrument_count != REFERENCE_INSTRUMENT_COUNT:
        reasons.append("measurement did not cover 3000 supported instruments")
    if isinstance(cache_hits, bool) or not isinstance(cache_hits, int) or cache_hits < 0:
        raise AnalysisDepthError("cache_hits must be a non-negative integer")
    measured_cache_state = "warm" if cache_hits > 0 else "cold"
    if cache_state != measured_cache_state:
        reasons.append("reported cache state does not match measured cache hits")
    if cache_hits == 0:
        reasons.append("measurement was not warm-cache")
    if profile.reference_fixture_digest is None:
        reasons.append("declared reference fixture content digest is unavailable")
    elif (
        not isinstance(fixture_content_digest, str)
        or len(fixture_content_digest) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in fixture_content_digest)
    ):
        reasons.append("fixture content digest is not a SHA-256 hex digest")
    elif fixture_content_digest.casefold() != profile.reference_fixture_digest:
        reasons.append("fixture content digest does not match the declared reference digest")
    machine = machine or {}
    try:
        cpu = int(machine.get("cpu_cores", 0))
        memory_mb = float(machine.get("memory_total_mb", machine.get("memory_mb", 0)))
        gpu_label = str(machine.get("gpu_label", ""))
    except (TypeError, ValueError):
        cpu, memory_mb, gpu_label = 0, 0.0, ""
    if cpu < profile.reference_cpu_cores or memory_mb < profile.reference_memory_mb:
        reasons.append("measurement machine does not meet the declared CPU and memory reference")
    if profile.reference_gpu_label.casefold() not in gpu_label.casefold():
        reasons.append("measurement machine does not match the declared GPU reference")
    measured = _finite_nonnegative(p95_seconds, "p95_seconds")
    if measured > profile.slo_seconds:
        reasons.append(f"p95 {measured:.6g}s exceeded the {profile.slo_seconds}s SLO")
    return {
        "status": "certified" if not reasons else "not_certified",
        "reason": None if not reasons else "; ".join(reasons),
        "p95_seconds": measured,
        "slo_seconds": profile.slo_seconds,
    }


ProgressCallback = Callable[["ProfileRunProgress"], None]
ANALYSIS_CERTIFICATIONS_RELATIVE_PATH = Path("data") / "analysis_certifications.parquet"
ANALYSIS_CERTIFICATION_SCHEMA_VERSION = "analysis-certification.v1"
_CERTIFICATION_STORE_LOCK = threading.Lock()
_CERTIFICATION_COLUMNS = (
    "schema_version",
    "profile_id",
    "manifest_hash",
    "run_id",
    "status",
    "reason",
    "p50_seconds",
    "p95_seconds",
    "slo_seconds",
    "sample_count",
    "created_at",
)
RESUME_NOTE = (
    "Resume re-runs the profile with the same in-memory stage cache so stages already completed for identical "
    "content are reused. It is not resumable across sessions: the timing store keeps no stage results."
)


@dataclass(frozen=True)
class ProfileRunProgress:
    """One per-stage progress event of a profile run (state is running or completed)."""

    run_id: str
    profile_id: str
    stage_id: str
    stage_index: int
    total_stages: int
    state: str
    instrument_id: str = ""
    instrument_index: int = 1
    instrument_count: int = 1


class ProfileRunUnavailable(Exception):
    """Raised by a binder when a profile run cannot start; the message is the visible reason."""


@dataclass(frozen=True)
class ProfileRunBinding:
    """Everything a profile run needs besides the profile: the instrument, its input and the stage runner."""

    instrument_id: str
    analysis_input: object
    analyzer_id: str
    stage_runner: StageRunner


@dataclass(frozen=True)
class ProfileRunResult:
    """Outcome of run_analysis_profile: completed, cancelled or failed (with a reason)."""

    run_id: str
    profile_id: str
    manifest_hash: str
    status: str
    reason: str | None
    completed_stages: tuple[str, ...]
    total_stages: int
    output: dict[str, object] | None
    timing_records: tuple[AnalysisTimingRecord, ...]
    resumable: bool
    resume_note: str = RESUME_NOTE


def run_analysis_profile(
    profile: AnalysisDepthProfile,
    binding: ProfileRunBinding,
    *,
    root: Path | None = None,
    cache: dict[str, dict[str, object]] | None = None,
    run_id: str | None = None,
    on_progress: ProgressCallback | None = None,
    is_cancel_requested: Callable[[], bool] | None = None,
    resource_plan: AnalysisResourcePlan | None = None,
) -> ProfileRunResult:
    """Run the selected profile's frozen stages through execute_profiled_stages.

    Reports per-stage progress, honours the cancel token between stages and fails
    closed: any stage error stops the run with status failed and the reason.
    Measured timings are appended to the timing store when a root is given; a
    store failure also fails the run because the evidence would be lost.
    """

    resolved_run_id = run_id or f"depth-run-{uuid.uuid4().hex[:12]}"
    stage_cache = cache if cache is not None else {}
    total = len(profile.stages)
    completed: list[str] = []

    def failed(reason: str, records: Sequence[AnalysisTimingRecord] = ()) -> ProfileRunResult:
        return ProfileRunResult(
            resolved_run_id, profile.profile_id, profile.manifest_hash, "failed", reason,
            tuple(completed), total, None, tuple(records), True,
        )

    def forward(stage_id: str, index: int, count: int, state: str) -> None:
        if state == "completed":
            completed.append(stage_id)
        if on_progress is not None:
            on_progress(ProfileRunProgress(resolved_run_id, profile.profile_id, stage_id, index, count, state))

    try:
        plan = resource_plan if resource_plan is not None else create_resource_plan(profile)
        output, records = execute_profiled_stages(
            profile,
            binding.instrument_id,
            binding.analysis_input,
            binding.analyzer_id,
            binding.stage_runner,
            stage_cache,
            run_id=resolved_run_id,
            cache_state="warm" if stage_cache else "cold",
            resource_plan=plan,
            is_cancel_requested=is_cancel_requested,
            on_stage_progress=forward,
        )
    except AnalysisDepthError as exc:
        records = tuple(getattr(exc, "timing_records", ()))
        persist_error = _persist_run_records(root, records)
        reason = str(exc) if persist_error is None else f"{exc}; {persist_error}"
        return failed(reason, records)
    except Exception as exc:  # fail closed: any stage, runner or callback error stops the run
        return failed(f"{type(exc).__name__}: {exc}")
    persist_error = _persist_run_records(root, records)
    if persist_error is not None:
        return failed(persist_error, records)
    cancelled = any(record.outcome == "cancelled" for record in records)
    return ProfileRunResult(
        resolved_run_id,
        profile.profile_id,
        profile.manifest_hash,
        "cancelled" if cancelled else "completed",
        "cancel requested; stopped between stages" if cancelled else None,
        tuple(completed),
        total,
        output,
        tuple(records),
        cancelled,
    )


def run_analysis_profile_set(
    profile: AnalysisDepthProfile,
    bindings: Sequence[ProfileRunBinding],
    *,
    root: Path | None = None,
    cache: dict[str, dict[str, object]] | None = None,
    run_id: str | None = None,
    on_progress: ProgressCallback | None = None,
    is_cancel_requested: Callable[[], bool] | None = None,
    resource_plan: AnalysisResourcePlan | None = None,
) -> ProfileRunResult:
    """Run the profile for every binding (one per instrument) through run_analysis_profile.

    Instruments run sequentially with one shared stage cache and run id. One
    instrument failing does not hide the others: the run ends failed, with the
    failing instruments and reasons, but every real timing is stored. Cancelling
    stops before the next stage and the remaining instruments never start.
    """

    resolved_run_id = run_id or f"depth-run-{uuid.uuid4().hex[:12]}"
    stage_cache = cache if cache is not None else {}
    items = tuple(bindings)
    count = len(items)
    per_instrument = len(profile.stages)
    total = per_instrument * count
    if count == 0:
        return ProfileRunResult(
            resolved_run_id, profile.profile_id, profile.manifest_hash, "failed",
            "no instruments to analyse", (), 0, None, (), False,
        )
    try:
        plan = resource_plan if resource_plan is not None else create_resource_plan(profile)
    except Exception as exc:
        return ProfileRunResult(
            resolved_run_id, profile.profile_id, profile.manifest_hash, "failed",
            f"{type(exc).__name__}: {exc}", (), total, None, (), False,
        )
    completed: list[str] = []
    records: list[AnalysisTimingRecord] = []
    outputs: dict[str, object] = {}
    failures: dict[str, str] = {}
    cancelled = False
    for position, binding in enumerate(items, start=1):
        if is_cancel_requested is not None and is_cancel_requested():
            cancelled = True
            break

        def relay(event: ProfileRunProgress, position: int = position, binding: ProfileRunBinding = binding) -> None:
            if on_progress is not None:
                on_progress(replace(
                    event, instrument_id=binding.instrument_id, instrument_index=position, instrument_count=count
                ))

        result = run_analysis_profile(
            profile,
            binding,
            root=root,
            cache=stage_cache,
            run_id=resolved_run_id,
            on_progress=relay,
            is_cancel_requested=is_cancel_requested,
            resource_plan=plan,
        )
        records.extend(result.timing_records)
        completed.extend(f"{binding.instrument_id}:{stage_id}" for stage_id in result.completed_stages)
        if result.status == "completed":
            outputs[binding.instrument_id] = result.output
        elif result.status == "cancelled":
            cancelled = True
            break
        else:
            failures[binding.instrument_id] = result.reason or "unknown failure"
    if cancelled:
        status, reason = "cancelled", "cancel requested; stopped between stages"
    elif failures:
        shown = "; ".join(f"{name}: {why}" for name, why in list(failures.items())[:3])
        more = f"; and {len(failures) - 3} more" if len(failures) > 3 else ""
        status, reason = "failed", f"{len(failures)} of {count} instruments failed ({shown}{more})"
    else:
        status, reason = "completed", None
    output = {"instruments": outputs, "failed_instruments": failures} if (outputs or failures) else None
    return ProfileRunResult(
        resolved_run_id, profile.profile_id, profile.manifest_hash, status, reason,
        tuple(completed), total, output, tuple(records), status != "completed",
    )


def _persist_run_records(root: Path | None, records: Sequence[AnalysisTimingRecord]) -> str | None:
    if root is None or not records:
        return None
    try:
        append_timing_records(root, records)
    except Exception as exc:
        return f"measured timings could not be stored ({type(exc).__name__}: {exc})"
    return None


def certify_and_record_benchmark(
    root: Path,
    profile: AnalysisDepthProfile,
    *,
    run_id: str,
    records: Sequence[AnalysisTimingRecord],
    fixture_id: str,
    fixture_content_digest: str | None,
    instrument_count: int,
    cache_state: str,
    cache_hits: int,
    machine: Mapping[str, object] | None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Run certify_benchmark on measured p95 and persist the verdict next to the timing store.

    Fails closed: without measured stage records for this run and profile nothing is
    certified or stored, and a run with failed or cancelled stages can never be certified.
    """

    measured = [
        record
        for record in records
        if record.run_id == run_id and record.profile_id == profile.profile_id and record.timing_kind == "stage"
    ]
    if not measured:
        raise AnalysisDepthError("certification requires measured timing records for this run and profile")
    stats = timing_percentiles(measured, profile_id=profile.profile_id)
    verdict = certify_benchmark(
        profile,
        fixture_id=fixture_id,
        fixture_content_digest=fixture_content_digest,
        instrument_count=instrument_count,
        cache_state=cache_state,
        cache_hits=cache_hits,
        p95_seconds=float(stats["p95_seconds"]),
        machine=machine,
    )
    status, reason = str(verdict["status"]), verdict["reason"]
    unsuccessful = sorted({record.outcome for record in measured if record.outcome in {"failed", "cancelled"}})
    if unsuccessful:
        status = "not_certified"
        reason = "; ".join(item for item in (reason, f"run contains {'/'.join(unsuccessful)} stages") if item)
    row: dict[str, object] = {
        "schema_version": ANALYSIS_CERTIFICATION_SCHEMA_VERSION,
        "profile_id": profile.profile_id,
        "manifest_hash": profile.manifest_hash,
        "run_id": run_id,
        "status": status,
        "reason": reason,
        "p50_seconds": float(stats["p50_seconds"]),
        "p95_seconds": float(stats["p95_seconds"]),
        "slo_seconds": float(profile.slo_seconds),
        "sample_count": int(stats["sample_count"]),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }
    import pandas as pd

    path = Path(root) / ANALYSIS_CERTIFICATIONS_RELATIVE_PATH
    with _CERTIFICATION_STORE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame([row], columns=list(_CERTIFICATION_COLUMNS))
        if path.is_file():
            previous = pd.read_parquet(path)
            if list(previous.columns) != list(_CERTIFICATION_COLUMNS):
                raise AnalysisDepthError("analysis_certifications.parquet has an unsupported schema")
            frame = pd.concat((previous, frame), ignore_index=True)
        _write_parquet_atomically(frame, path)
    return row


def _write_parquet_atomically(frame, path: Path) -> None:
    """Serialize beside the destination, then atomically replace it."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".parquet", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        frame.to_parquet(temporary_path, index=False)
        payload = temporary_path.read_bytes()
        atomic_write_bytes(path, payload, validate_parquet_file)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_certification(root: Path, profile_id: str, *, manifest_hash: str | None = None) -> dict[str, object] | None:
    """Latest stored certification for a profile (and manifest hash), or None when none exists.

    A stored certified row is only returned as certified when its own measured p95
    meets the stored SLO target; otherwise it reads as not_certified.
    """

    path = Path(root) / ANALYSIS_CERTIFICATIONS_RELATIVE_PATH
    if not path.is_file():
        return None
    import pandas as pd

    frame = pd.read_parquet(path)
    if list(frame.columns) != list(_CERTIFICATION_COLUMNS):
        raise AnalysisDepthError("analysis_certifications.parquet has an unsupported schema")
    frame = frame[frame["profile_id"] == profile_id]
    if manifest_hash is not None:
        frame = frame[frame["manifest_hash"] == manifest_hash]
    if frame.empty:
        return None
    latest = frame.sort_values("created_at", kind="stable").iloc[-1].to_dict()
    result = {
        key: (None if value is None or value != value else (value.item() if hasattr(value, "item") else value))
        for key, value in latest.items()
    }
    if result["status"] == "certified":
        p95, slo = result.get("p95_seconds"), result.get("slo_seconds")
        if (
            not isinstance(p95, (int, float))
            or not isinstance(slo, (int, float))
            or not math.isfinite(p95)
            or p95 > slo
            or not result.get("sample_count")
        ):
            result["status"] = "not_certified"
            result["reason"] = "stored certification is not backed by a measured run meeting the target"
    return result


__all__ = [
    "ANALYSIS_CERTIFICATIONS_RELATIVE_PATH",
    "ANALYSIS_DEPTH_PROFILES_PATH",
    "ANALYSIS_TIMINGS_RELATIVE_PATH",
    "AnalysisDepthError",
    "AnalysisDepthProfile",
    "AnalysisResourcePlan",
    "AnalysisStageManifest",
    "AnalysisTimingRecord",
    "AnalysisUpgradeLink",
    "MANDATORY_GATE_IDS",
    "MANDATORY_STAGE_IDS",
    "MandatoryEvidenceError",
    "PROFILE_IDS",
    "ProfileRunBinding",
    "ProfileRunProgress",
    "ProfileRunResult",
    "ProfileRunUnavailable",
    "REFERENCE_FIXTURE_ID",
    "REFERENCE_INSTRUMENT_COUNT",
    "StageRunner",
    "analysis_run_identity",
    "append_timing_records",
    "certify_and_record_benchmark",
    "certify_benchmark",
    "create_resource_plan",
    "execute_profiled_stages",
    "load_analysis_depth_profiles",
    "profile_from_dict",
    "read_certification",
    "resource_plan_from_dict",
    "run_analysis_profile",
    "run_analysis_profile_set",
    "stage_cache_key",
    "stage_output_hash",
    "timing_percentiles",
]
