from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json

import numpy as np

from etf_cockpit.validation.optimisation import run_walk_forward_tuning
from etf_cockpit.validation.tuning_registry import DEFAULT_REGISTRY_PATH, load_tuning_registry

RUNS = 40
LEVEL, TRIAL_NOISE = 0.5, 0.5  # every setting earns LEVEL (so absolute-Sharpe tests do not decide) plus noise


def _dates(count: int) -> list[date]:
    days, day = [], date(2018, 1, 1)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _objective(seed: int, n: int, registry, target: dict[str, float] | None = None, *, level: float = LEVEL, scale: float = 1.0):
    """Per-date score = ``level`` + common noise (sd 1) + noise of that parameter set (sd TRIAL_NOISE).

    No knob changes the expected score unless ``target`` plants one optimum: the expected gain is then
    ``scale`` * (squared span-normalised distance of the current settings - that of the trial) from ``target``.
    """
    common = np.random.default_rng(seed).standard_normal(n)
    current = registry.current_values()
    spans = {item.key: item.upper - item.lower for item in registry.parameters}

    def loss(parameters) -> float:
        return scale * sum(((float(parameters[key]) - value) / spans[key]) ** 2 for key, value in (target or {}).items())

    def per_date(parameters) -> np.ndarray:
        key = json.dumps({name: round(float(value), 9) for name, value in sorted(parameters.items())})
        noise = np.random.default_rng(int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:15], 16)).standard_normal(n)
        return level + common + TRIAL_NOISE * noise + loss(current) - loss(parameters)

    def evaluate(parameters, indices, context) -> float:
        return float(per_date(parameters)[list(indices)].mean())

    evaluate.identity = f"gate-fixture:{seed}:{json.dumps(target, sort_keys=True)}"
    evaluate.edge_units = "net_return_vs_vwce"  # per-date values stand for net forward returns vs VWCE
    evaluate.per_session = per_date
    return evaluate


def _decisions(tmp_path, target=None, runs=RUNS, **shape):
    registry = load_tuning_registry(DEFAULT_REGISTRY_PATH)
    dates = _dates(480)
    return [
        run_walk_forward_tuning(
            tmp_path / f"s{seed}", f"gate-{seed}", registry, _objective(seed, len(dates), registry, target, **shape), dates,
            data_provenance="synthetic",
        ).decision
        for seed in range(runs)
    ]


def test_tuner_proposes_at_most_5_percent_of_the_time_when_no_knob_has_an_edge(tmp_path) -> None:
    decisions = _decisions(tmp_path)
    assert "unavailable" not in decisions
    assert decisions.count("propose_change") <= 0.05 * RUNS, decisions


def test_tuner_still_proposes_a_planted_optimum(tmp_path) -> None:
    current = load_tuning_registry(DEFAULT_REGISTRY_PATH).current_values()
    target = dict(current) | {"score.etf.headline.risk": 0.4583, "score.etf.headline.liquidity_cost": 0.2417}  # group total kept
    # A strong base (level 6) keeps the absolute DSR test passable against the spread of 60 trials over 10 knobs.
    assert _decisions(tmp_path, target, runs=3, level=6.0, scale=4.0) == ["propose_change"] * 3
