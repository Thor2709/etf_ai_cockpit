"""Deterministic synthetic and adversarial fixtures for model robustness.

Synthetic outputs are deliberately separate from real market data.  Every
returned frame carries a synthetic marker and the metadata refuses promotion
authority, so generated performance cannot silently enter forward evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd


class SyntheticScenarioError(ValueError):
    """Raised when a synthetic scenario is unsafe or malformed."""


@dataclass(frozen=True)
class SyntheticScenarioSpec:
    """Bounded parameters for one reproducible synthetic fixture."""

    scenario_id: str = "baseline-robustness"
    assets: tuple[str, ...] = ("SYNTH_A", "SYNTH_B", "SYNTH_C")
    periods: int = 252
    seed: int = 42
    start_date: str = "2020-01-01"
    start_price: float = 100.0
    annual_volatility: float = 0.20
    regime_count: int = 3
    jump_probability: float = 0.015
    missing_rate: float = 0.02
    restatement_rate: float = 0.01
    action_rate: float = 0.01
    conflict_rate: float = 0.01
    execution_failures: int = 3

    def __post_init__(self) -> None:
        if not self.scenario_id.strip() or len(self.scenario_id) > 80:
            raise SyntheticScenarioError("scenario_id must be a bounded non-empty value")
        if not self.assets or len(self.assets) > 50 or len(set(self.assets)) != len(self.assets):
            raise SyntheticScenarioError("assets must be unique and contain between one and fifty names")
        if any(not asset.strip() or len(asset) > 40 for asset in self.assets):
            raise SyntheticScenarioError("asset names must be bounded and non-empty")
        if not 2 <= self.periods <= 10_000:
            raise SyntheticScenarioError("periods must be between 2 and 10000")
        if self.start_price <= 0 or self.annual_volatility <= 0:
            raise SyntheticScenarioError("start_price and annual_volatility must be positive")
        if not 1 <= self.regime_count <= 8:
            raise SyntheticScenarioError("regime_count must be between one and eight")
        for label, value in (
            ("jump_probability", self.jump_probability),
            ("missing_rate", self.missing_rate),
            ("restatement_rate", self.restatement_rate),
            ("action_rate", self.action_rate),
            ("conflict_rate", self.conflict_rate),
        ):
            if not 0 <= value <= 1:
                raise SyntheticScenarioError(f"{label} must be between zero and one")
        if not 0 <= self.execution_failures <= 100:
            raise SyntheticScenarioError("execution_failures must be between zero and one hundred")


@dataclass(frozen=True)
class SyntheticDataset:
    """Synthetic fixture frames and immutable provenance metadata."""

    prices: pd.DataFrame
    data_quality: pd.DataFrame
    corporate_actions: pd.DataFrame
    provider_conflicts: pd.DataFrame
    execution_events: pd.DataFrame
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.metadata.get("synthetic") is not True:
            raise SyntheticScenarioError("synthetic datasets must carry synthetic=true")
        if self.metadata.get("promotion_eligible") is not False:
            raise SyntheticScenarioError("synthetic datasets cannot be promotion eligible")


class SyntheticScenarioGenerator:
    """Create deterministic, labelled market and failure fixtures."""

    version = "synthetic-fixtures.v1"

    def generate(self, spec: SyntheticScenarioSpec = SyntheticScenarioSpec()) -> SyntheticDataset:
        rng = np.random.default_rng(spec.seed)
        dates = pd.date_range(spec.start_date, periods=spec.periods, freq="D")
        assets = list(spec.assets)
        regimes = self._regimes(rng, spec.periods, spec.regime_count)
        common = rng.normal(0.0002, spec.annual_volatility / np.sqrt(252), spec.periods)
        frames: list[pd.DataFrame] = []
        quality_rows: list[dict[str, Any]] = []
        for index, asset in enumerate(assets):
            idiosyncratic = rng.normal(0, spec.annual_volatility / np.sqrt(252), spec.periods)
            regime_scale = np.take(np.linspace(0.65, 1.8, spec.regime_count), regimes)
            returns = common * 0.45 + idiosyncratic * regime_scale
            jump_mask = rng.random(spec.periods) < spec.jump_probability
            jumps = rng.normal(0, spec.annual_volatility * 0.75, spec.periods) * jump_mask
            returns = returns + jumps
            prices = spec.start_price * np.exp(np.cumsum(returns + index * 0.00001))
            observed = prices.copy()
            missing_mask = rng.random(spec.periods) < spec.missing_rate
            observed[missing_mask] = np.nan
            for position in np.flatnonzero(missing_mask):
                quality_rows.append(
                    self._quality_row(asset, dates[position], "missing_observation", "high", "price", spec)
                )
            for position in np.flatnonzero(jump_mask):
                quality_rows.append(self._quality_row(asset, dates[position], "jump", "medium", "price", spec))
            frames.append(
                pd.DataFrame(
                    {
                        "asset": asset,
                        "date": dates,
                        "close": observed,
                        "adjusted_close": observed,
                        "is_adjusted": True,
                        "synthetic": True,
                        "regime": regimes,
                        "jump": jump_mask,
                    }
                )
            )
        prices_frame = pd.concat(frames, ignore_index=True)
        actions = self._actions(rng, assets, dates, spec)
        restatements = self._restatements(rng, prices_frame, spec)
        quality = pd.DataFrame(quality_rows + restatements)
        if quality.empty:
            quality = pd.DataFrame(columns=["asset", "date", "issue", "severity", "field", "synthetic"])
        conflicts = self._conflicts(rng, assets, dates, spec)
        execution = self._execution_events(rng, spec)
        metadata = self._metadata(spec, prices_frame, actions, quality, conflicts, execution)
        return SyntheticDataset(prices_frame, quality, actions, conflicts, execution, metadata)

    @staticmethod
    def validate(dataset: SyntheticDataset) -> dict[str, Any]:
        """Return invariant evidence without treating synthetic data as alpha."""

        frames = {
            "prices": dataset.prices,
            "data_quality": dataset.data_quality,
            "corporate_actions": dataset.corporate_actions,
            "provider_conflicts": dataset.provider_conflicts,
            "execution_events": dataset.execution_events,
        }
        synthetic_columns = {
            name: bool(frame.empty or frame.get("synthetic", pd.Series(dtype=bool)).fillna(False).all())
            for name, frame in frames.items()
        }
        return {
            "status": "pass" if all(synthetic_columns.values()) else "fail",
            "synthetic_labels": synthetic_columns,
            "promotion_eligible": False,
            "seed": dataset.metadata.get("seed"),
            "dataset_hash": dataset.metadata.get("dataset_hash"),
            "rows": {name: int(len(frame)) for name, frame in frames.items()},
        }

    @staticmethod
    def promotion_guard(evidence: Mapping[str, Any]) -> dict[str, Any]:
        """Make synthetic-only performance ineligible for model promotion."""

        return {
            "promotion_eligible": False,
            "synthetic_evidence_excluded": True,
            "reason": "Synthetic fixtures are for invariants, rare failures and robustness only.",
            "observed_evidence_count": int(evidence.get("observed_evidence_count", 0)),
        }

    @staticmethod
    def _regimes(rng: np.random.Generator, periods: int, count: int) -> np.ndarray:
        regimes = np.zeros(periods, dtype=int)
        for position in range(1, periods):
            regimes[position] = regimes[position - 1] if rng.random() < 0.96 else int(rng.integers(count))
        return regimes

    @staticmethod
    def _quality_row(asset: str, timestamp: pd.Timestamp, issue: str, severity: str, field: str, spec: SyntheticScenarioSpec) -> dict[str, Any]:
        return {"asset": asset, "date": timestamp.date().isoformat(), "issue": issue, "severity": severity, "field": field, "synthetic": True, "seed": spec.seed}

    def _actions(self, rng: np.random.Generator, assets: list[str], dates: pd.DatetimeIndex, spec: SyntheticScenarioSpec) -> pd.DataFrame:
        rows = []
        for asset in assets:
            for position in np.flatnonzero(rng.random(spec.periods) < spec.action_rate):
                rows.append({"asset": asset, "date": dates[position].date().isoformat(), "action": "split" if position % 2 else "dividend", "ratio": 2.0 if position % 2 else 0.01, "synthetic": True, "seed": spec.seed})
        return pd.DataFrame(rows, columns=["asset", "date", "action", "ratio", "synthetic", "seed"])

    def _restatements(self, rng: np.random.Generator, prices: pd.DataFrame, spec: SyntheticScenarioSpec) -> list[dict[str, Any]]:
        rows = []
        for asset in spec.assets:
            candidates = prices[prices["asset"] == asset].dropna(subset=["adjusted_close"])
            for position in np.flatnonzero(rng.random(len(candidates)) < spec.restatement_rate):
                row = candidates.iloc[position]
                value = float(row["adjusted_close"])
                rows.append({"asset": asset, "date": row["date"].date().isoformat(), "issue": "restatement", "severity": "high", "field": "adjusted_close", "old_value": value, "new_value": value * 1.01, "synthetic": True, "seed": spec.seed})
        return rows

    def _conflicts(self, rng: np.random.Generator, assets: list[str], dates: pd.DatetimeIndex, spec: SyntheticScenarioSpec) -> pd.DataFrame:
        rows = []
        for asset in assets:
            for position in np.flatnonzero(rng.random(spec.periods) < spec.conflict_rate):
                rows.append({"asset": asset, "date": dates[position].date().isoformat(), "provider_a": "synthetic-official", "provider_b": "synthetic-secondary", "value_a": 100.0, "value_b": 101.0, "resolution": "quarantine", "synthetic": True, "seed": spec.seed})
        return pd.DataFrame(rows, columns=["asset", "date", "provider_a", "provider_b", "value_a", "value_b", "resolution", "synthetic", "seed"])

    @staticmethod
    def _execution_events(rng: np.random.Generator, spec: SyntheticScenarioSpec) -> pd.DataFrame:
        statuses = ["partial_fill", "latency", "rejected", "reconciliation_mismatch"]
        rows = [{"event_id": f"synthetic-order-{index:03d}", "status": statuses[index % len(statuses)], "latency_ms": int(rng.integers(10, 2500)), "synthetic": True, "seed": spec.seed} for index in range(spec.execution_failures)]
        return pd.DataFrame(rows, columns=["event_id", "status", "latency_ms", "synthetic", "seed"])

    def _metadata(self, spec: SyntheticScenarioSpec, *frames: pd.DataFrame) -> dict[str, Any]:
        payload = {"generator_version": self.version, "spec": asdict(spec), "frame_rows": [len(frame) for frame in frames]}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return {"synthetic": True, "promotion_eligible": False, "generator_version": self.version, "scenario_id": spec.scenario_id, "seed": spec.seed, "spec": asdict(spec), "dataset_hash": hashlib.sha256(encoded).hexdigest()}


__all__ = ["SyntheticDataset", "SyntheticScenarioError", "SyntheticScenarioGenerator", "SyntheticScenarioSpec"]
