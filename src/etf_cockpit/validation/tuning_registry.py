"""Registry of tunable score/forecast/ensemble knobs for bounded optimisation.

The registry is configuration-driven (``configs/tuning_v1.yaml``).  Bounds come
from the registry; the CURRENT value of every knob is read from its source
settings file.  Nothing here writes to a settings file, and a missing or
out-of-bounds source value fails closed with ``TuningRegistryError``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import yaml

from etf_cockpit.core.paths import CONFIG_DIR


TUNING_REGISTRY_VERSION = "tuning-registry.v1"
DEFAULT_REGISTRY_PATH = CONFIG_DIR / "tuning_v1.yaml"
_TOLERANCE = 1e-9


class TuningRegistryError(ValueError):
    """Raised when the registry or a knob's current value cannot be verified."""


@dataclass(frozen=True)
class SearchDefaults:
    max_trials: int = 60
    max_seconds: float = 60.0
    max_memory_mb: int = 256
    seed: int = 42
    refine_after: int | None = 8
    patience: int | None = 25
    prune_warmup_trials: int = 5


@dataclass(frozen=True)
class GuardDefaults:
    min_tune_samples: int = 250
    min_eval_samples: int = 60
    eval_blocks: int = 4
    min_block_win_fraction: float = 0.75
    change_penalty: float = 0.02
    min_improvement: float = 0.0


@dataclass(frozen=True)
class SplitDefaults:
    eval_size: int = 120
    horizon: int = 20
    embargo: int = 0
    final_test_size: int = 60


@dataclass(frozen=True)
class TuningDefaults:
    search: SearchDefaults = SearchDefaults()
    guards: GuardDefaults = GuardDefaults()
    split: SplitDefaults = SplitDefaults()


@dataclass(frozen=True)
class TunableParameter:
    key: str
    file: str
    path: tuple[str, ...]
    lower: float
    upper: float
    step: float
    current: float
    group: str | None = None
    model: str | None = None

    def grid(self) -> tuple[float, ...]:
        """Bounded grid with the current value first (it is the search baseline)."""

        count = int(math.floor((self.upper - self.lower) / self.step + _TOLERANCE))
        points = [round(self.lower + index * self.step, 10) for index in range(count + 1)]
        points = [value for value in points if abs(value - self.current) > _TOLERANCE]
        return (self.current, *points)


@dataclass(frozen=True)
class TuningRegistry:
    version: str
    parameters: tuple[TunableParameter, ...]
    defaults: TuningDefaults
    source_checksums: Mapping[str, str]
    registry_checksum: str

    def current_values(self) -> dict[str, float]:
        return {item.key: item.current for item in self.parameters}

    def search_space(self) -> dict[str, tuple[float, ...]]:
        return {item.key: item.grid() for item in self.parameters}

    def models_in_scope(self) -> tuple[str, ...]:
        return tuple(sorted({item.model for item in self.parameters if item.model}))

    def distance_from_current(self, values: Mapping[str, float]) -> float:
        """Mean absolute move as a fraction of each knob's bound range (0 = unchanged)."""

        moves = [abs(float(values[item.key]) - item.current) / (item.upper - item.lower) for item in self.parameters]
        return sum(moves) / len(moves)

    def materialise(self, values: Mapping[str, object]) -> dict[str, float]:
        """Clip to bounds and rescale each group to its current total (sum-preserving)."""

        result: dict[str, float] = {}
        for item in self.parameters:
            if item.key not in values:
                raise TuningRegistryError(f"missing value for knob {item.key}")
            number = float(values[item.key])  # type: ignore[arg-type]
            if not math.isfinite(number):
                raise TuningRegistryError(f"non-finite value for knob {item.key}")
            result[item.key] = min(item.upper, max(item.lower, number))
        for group in sorted({item.group for item in self.parameters if item.group}):
            members = [item for item in self.parameters if item.group == group]
            _rescale_group(members, result, sum(item.current for item in members))
        return {key: round(value, 10) for key, value in result.items()}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": TUNING_REGISTRY_VERSION,
            "version": self.version,
            "registry_checksum": self.registry_checksum,
            "source_checksums": dict(self.source_checksums),
            "parameters": [
                {
                    "key": item.key,
                    "file": item.file,
                    "path": list(item.path),
                    "lower": item.lower,
                    "upper": item.upper,
                    "step": item.step,
                    "current": item.current,
                    "group": item.group,
                    "model": item.model,
                }
                for item in self.parameters
            ],
        }


def _rescale_group(members: list[TunableParameter], values: dict[str, float], total: float) -> None:
    """Water-filling: scale free members to ``total``, pinning any that hit a bound."""

    if sum(item.lower for item in members) > total + _TOLERANCE or sum(item.upper for item in members) < total - _TOLERANCE:
        raise TuningRegistryError(f"group total {total:.6f} is unreachable inside the bounds of {members[0].group}")
    pinned: set[str] = set()
    for _ in range(len(members) + 1):
        free = [item for item in members if item.key not in pinned]
        remaining = total - sum(values[key] for key in pinned)
        free_sum = sum(values[item.key] for item in free)
        if not free or free_sum <= 0:
            break
        scale = remaining / free_sum
        proposed = {item.key: values[item.key] * scale for item in free}
        violated = [item for item in free if not item.lower - _TOLERANCE <= proposed[item.key] <= item.upper + _TOLERANCE]
        if not violated:
            values.update(proposed)
            return
        for item in violated:
            values[item.key] = min(item.upper, max(item.lower, proposed[item.key]))
            pinned.add(item.key)
    if abs(sum(values[item.key] for item in members) - total) > 1e-6:
        raise TuningRegistryError(f"group {members[0].group} could not be rescaled to its current total")


def load_tuning_registry(path: Path | None = None, *, config_dir: Path | None = None) -> TuningRegistry:
    """Load the registry and read every knob's current value from its source file."""

    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    source_root = Path(config_dir) if config_dir is not None else registry_path.parent
    try:
        raw = registry_path.read_bytes()
        document = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TuningRegistryError(f"tuning registry unreadable: {type(exc).__name__}") from exc
    if not isinstance(document, Mapping) or int(document.get("schema_version", 0)) != 1 or not document.get("parameters"):
        raise TuningRegistryError("tuning registry has no schema_version 1 parameter list")
    sources: dict[str, object] = {}
    checksums: dict[str, str] = {}
    parameters: list[TunableParameter] = []
    seen: set[str] = set()
    for entry in document["parameters"]:
        key = str(entry.get("key", "")).strip()
        if not key or key in seen:
            raise TuningRegistryError(f"knob key missing or duplicated: {key!r}")
        seen.add(key)
        file = str(entry.get("file", ""))
        if file not in sources:
            try:
                content = (source_root / file).read_bytes()
                sources[file] = yaml.safe_load(content.decode("utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                raise TuningRegistryError(f"source file for {key} unreadable: {file}") from exc
            checksums[file] = hashlib.sha256(content).hexdigest()
        node: object = sources[file]
        path_parts = tuple(str(part) for part in entry.get("path", ()))
        for part in path_parts:
            if not isinstance(node, Mapping) or part not in node:
                raise TuningRegistryError(f"knob {key}: path {'/'.join(path_parts)} not found in {file}")
            node = node[part]
        if isinstance(node, bool) or not isinstance(node, (int, float)) or not math.isfinite(float(node)):
            raise TuningRegistryError(f"knob {key}: current value is not a finite number")
        lower, upper, step, current = (float(entry.get("lower", math.nan)), float(entry.get("upper", math.nan)), float(entry.get("step", math.nan)), float(node))
        if not (math.isfinite(lower) and math.isfinite(upper) and math.isfinite(step)) or not lower < upper or step <= 0:
            raise TuningRegistryError(f"knob {key}: bounds/step must be finite with lower < upper and step > 0")
        if not lower - _TOLERANCE <= current <= upper + _TOLERANCE:
            raise TuningRegistryError(f"knob {key}: current value {current} lies outside [{lower}, {upper}]")
        parameters.append(
            TunableParameter(key, file, path_parts, lower, upper, step, current, entry.get("group") or None, entry.get("model") or None)
        )
    defaults = _defaults(document.get("defaults") or {})
    registry = TuningRegistry(str(document.get("version", "")), tuple(parameters), defaults, dict(sorted(checksums.items())), hashlib.sha256(raw).hexdigest())
    registry.materialise(registry.current_values())  # group totals must be reachable
    return registry


def _defaults(block: Mapping[str, object]) -> TuningDefaults:
    try:
        return TuningDefaults(
            SearchDefaults(**dict(block.get("search") or {})),  # type: ignore[arg-type]
            GuardDefaults(**dict(block.get("guards") or {})),  # type: ignore[arg-type]
            SplitDefaults(**dict(block.get("split") or {})),  # type: ignore[arg-type]
        )
    except TypeError as exc:
        raise TuningRegistryError(f"unknown tuning default: {exc}") from exc


def registry_fingerprint(registry: TuningRegistry) -> str:
    payload = json.dumps(registry.to_dict(), sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "GuardDefaults",
    "SearchDefaults",
    "SplitDefaults",
    "TUNING_REGISTRY_VERSION",
    "TunableParameter",
    "TuningDefaults",
    "TuningRegistry",
    "TuningRegistryError",
    "load_tuning_registry",
    "registry_fingerprint",
]
