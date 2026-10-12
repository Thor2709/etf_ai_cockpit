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
import re

import yaml

from etf_cockpit.core.paths import CONFIG_DIR


TUNING_REGISTRY_VERSION = "tuning-registry.v1"
DEFAULT_REGISTRY_PATH = CONFIG_DIR / "tuning_v1.yaml"
_TOLERANCE = 1e-9
_MAX_GRID_POINTS = 10_000


class TuningRegistryError(ValueError):
    """Raised when the registry or a knob's current value cannot be verified."""


def _integer(name: str, value: object, minimum: int | None = None, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int) or (minimum is not None and value < minimum):
        raise TuningRegistryError(f"invalid tuning default {name}: {value!r}")


def _number(name: str, value: object, *, minimum: float = 0.0, maximum: float | None = None, exclusive: bool = False) -> None:
    ok = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))
    if ok:
        number = float(value)  # type: ignore[arg-type]
        ok = (number > minimum if exclusive else number >= minimum) and (maximum is None or number <= maximum)
    if not ok:
        raise TuningRegistryError(f"invalid tuning default {name}: {value!r}")


@dataclass(frozen=True)
class SearchDefaults:
    max_trials: int = 60
    max_seconds: float = 60.0
    max_memory_mb: int = 256
    seed: int = 42
    refine_after: int | None = 8
    patience: int | None = 25
    prune_warmup_trials: int = 5

    def __post_init__(self) -> None:
        _integer("max_trials", self.max_trials, 1)
        _number("max_seconds", self.max_seconds, exclusive=True)
        _integer("max_memory_mb", self.max_memory_mb, 1)
        _integer("seed", self.seed)
        _integer("refine_after", self.refine_after, 1, optional=True)
        _integer("patience", self.patience, 1, optional=True)
        _integer("prune_warmup_trials", self.prune_warmup_trials, 1)


@dataclass(frozen=True)
class GuardDefaults:
    min_tune_samples: int = 250
    min_eval_samples: int = 60
    eval_blocks: int = 4
    min_block_win_fraction: float = 0.75
    change_penalty: float = 0.02
    min_improvement: float = 0.0

    def __post_init__(self) -> None:
        _integer("min_tune_samples", self.min_tune_samples, 1)
        _integer("min_eval_samples", self.min_eval_samples, 1)
        _integer("eval_blocks", self.eval_blocks, 1)
        _number("min_block_win_fraction", self.min_block_win_fraction, maximum=1.0, exclusive=True)
        _number("change_penalty", self.change_penalty)
        _number("min_improvement", self.min_improvement)


@dataclass(frozen=True)
class SplitDefaults:
    eval_size: int = 120
    horizon: int = 20
    embargo: int = 0
    final_test_size: int = 60

    def __post_init__(self) -> None:
        _integer("eval_size", self.eval_size, 1)
        _integer("horizon", self.horizon, 1)
        _integer("embargo", self.embargo, 0)
        _integer("final_test_size", self.final_test_size, 0)


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


def _metadata_identifier(value: object, label: str, *, optional: bool = False) -> str | None:
    """Knob identifiers/group/model must be bounded identifier strings (same alphabet the search accepts)."""

    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value.strip()):
        raise TuningRegistryError(f"{label} must be a bounded identifier string")
    return value.strip()


def load_tuning_registry(path: Path | None = None, *, config_dir: Path | None = None) -> TuningRegistry:
    """Load the registry and read every knob's current value from its source file."""

    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    source_root = Path(config_dir) if config_dir is not None else registry_path.parent
    try:
        raw = registry_path.read_bytes()
        document = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TuningRegistryError(f"tuning registry unreadable: {type(exc).__name__}") from exc
    version = document.get("schema_version") if isinstance(document, Mapping) else None
    if not isinstance(document, Mapping) or isinstance(version, bool) or version != 1:
        raise TuningRegistryError("tuning registry has no schema_version 1 parameter list")
    entries = document.get("parameters")
    if not isinstance(entries, list) or not entries:
        raise TuningRegistryError("tuning registry has no schema_version 1 parameter list")
    sources: dict[str, object] = {}
    checksums: dict[str, str] = {}
    parameters: list[TunableParameter] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TuningRegistryError("tuning registry parameter entry must be a mapping")
        key = _metadata_identifier(entry.get("key"), "knob key")
        if key in seen:
            raise TuningRegistryError(f"knob key missing or duplicated: {key!r}")
        seen.add(key)
        group = _metadata_identifier(entry.get("group"), f"knob {key}: group", optional=True)
        model = _metadata_identifier(entry.get("model"), f"knob {key}: model", optional=True)
        file = entry.get("file")
        raw_path = entry.get("path")
        if not isinstance(file, str) or not file.strip() or not isinstance(raw_path, list) or not raw_path:
            raise TuningRegistryError(f"knob {key}: file and path must be a string and a non-empty list")
        if file not in sources:
            try:
                content = (source_root / file).read_bytes()
                sources[file] = yaml.safe_load(content.decode("utf-8"))
            except (OSError, ValueError, yaml.YAMLError) as exc:
                raise TuningRegistryError(f"source file for {key} unreadable: {file}") from exc
            checksums[file] = hashlib.sha256(content).hexdigest()
        node: object = sources[file]
        path_parts = tuple(str(part) for part in raw_path)
        for part in path_parts:
            if not isinstance(node, Mapping) or part not in node:
                raise TuningRegistryError(f"knob {key}: path {'/'.join(path_parts)} not found in {file}")
            node = node[part]
        if isinstance(node, bool) or not isinstance(node, (int, float)) or not math.isfinite(float(node)):
            raise TuningRegistryError(f"knob {key}: current value is not a finite number")
        try:
            lower, upper, step, current = (float(entry["lower"]), float(entry["upper"]), float(entry["step"]), float(node))
        except (KeyError, TypeError, ValueError) as exc:
            raise TuningRegistryError(f"knob {key}: lower/upper/step must be numbers") from exc
        if not (math.isfinite(lower) and math.isfinite(upper) and math.isfinite(step)) or not lower < upper or step <= 0:
            raise TuningRegistryError(f"knob {key}: bounds/step must be finite with lower < upper and step > 0")
        if (upper - lower) / step > _MAX_GRID_POINTS:
            raise TuningRegistryError(f"knob {key}: step is too small for a bounded grid")
        if not lower - _TOLERANCE <= current <= upper + _TOLERANCE:
            raise TuningRegistryError(f"knob {key}: current value {current} lies outside [{lower}, {upper}]")
        parameters.append(
            TunableParameter(key, file, path_parts, lower, upper, step, current, group, model)
        )
    defaults = _defaults(document.get("defaults"))
    registry = TuningRegistry(str(document.get("version", "")), tuple(parameters), defaults, dict(sorted(checksums.items())), hashlib.sha256(raw).hexdigest())
    registry.materialise(registry.current_values())  # group totals must be reachable
    return registry


def _defaults(block: object) -> TuningDefaults:
    if block is None:
        block = {}
    if not isinstance(block, Mapping) or not set(block) <= {"search", "guards", "split"}:
        raise TuningRegistryError("tuning defaults must be a mapping of search/guards/split")
    sections = []
    for name, factory in (("search", SearchDefaults), ("guards", GuardDefaults), ("split", SplitDefaults)):
        section = block.get(name)
        if section is None:
            section = {}
        if not isinstance(section, Mapping):
            raise TuningRegistryError(f"tuning defaults {name} must be a mapping")
        try:
            sections.append(factory(**dict(section)))
        except TypeError as exc:
            raise TuningRegistryError(f"unknown tuning default in {name}: {exc}") from exc
    return TuningDefaults(*sections)


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
