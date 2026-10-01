from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import math
from pathlib import Path


@dataclass(frozen=True)
class MutationThresholds:
    version: int
    scope: str
    required_kill_rate: float
    critical_mutants: tuple[str, ...]


@dataclass(frozen=True)
class MutationProbe:
    mutation: Callable[[], AbstractContextManager[object]]
    invariant: Callable[[], None]


def load_mutation_thresholds(path: Path) -> MutationThresholds:
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    version: int | None = None
    scope: str | None = None
    required_kill_rate: float | None = None
    mutants: list[str] = []
    in_mutants = False

    for line in lines:
        if line.startswith("version: "):
            if version is not None:
                raise ValueError("duplicate mutation-threshold version")
            version = int(line.removeprefix("version: "))
        elif line.startswith("scope: "):
            if scope is not None:
                raise ValueError("duplicate mutation-threshold scope")
            scope = line.removeprefix("scope: ")
        elif line.startswith("required_kill_rate: "):
            if required_kill_rate is not None:
                raise ValueError("duplicate mutation kill-rate threshold")
            required_kill_rate = float(line.removeprefix("required_kill_rate: "))
        elif line == "critical_mutants:":
            if in_mutants:
                raise ValueError("duplicate critical-mutants section")
            in_mutants = True
        elif line.startswith("  - id: ") and in_mutants:
            mutants.append(line.removeprefix("  - id: ").strip())
        else:
            raise ValueError(f"unsupported mutation-threshold syntax: {line!r}")

    if version != 1 or scope != "safety-critical-packages" or not mutants:
        raise ValueError("mutation thresholds are incomplete or unsupported")
    if required_kill_rate is None or not math.isfinite(required_kill_rate) or not 0 < required_kill_rate <= 1:
        raise ValueError("required mutation kill rate must be in (0, 1]")
    if any(not mutant for mutant in mutants) or len(set(mutants)) != len(mutants):
        raise ValueError("critical mutant IDs must be non-empty and unique")
    return MutationThresholds(version, scope, required_kill_rate, tuple(mutants))


def run_critical_mutants(
    path: Path,
    probes: Mapping[str, MutationProbe],
) -> tuple[dict[str, str], float]:
    thresholds = load_mutation_thresholds(path)
    if set(probes) != set(thresholds.critical_mutants):
        raise ValueError("mutation probes must exactly match configured critical mutants")

    for mutant_id in thresholds.critical_mutants:
        probes[mutant_id].invariant()

    results: dict[str, str] = {}
    for mutant_id in thresholds.critical_mutants:
        probe = probes[mutant_id]
        with probe.mutation():
            try:
                probe.invariant()
            except AssertionError:
                results[mutant_id] = "mutant killed"
            else:
                results[mutant_id] = "mutant survived"

    kill_rate = sum(result == "mutant killed" for result in results.values()) / len(results)
    if kill_rate < thresholds.required_kill_rate:
        survivors = tuple(mutant for mutant, result in results.items() if result != "mutant killed")
        raise AssertionError(f"critical mutants survived: {survivors}; kill rate={kill_rate:.3f}")
    return results, kill_rate
