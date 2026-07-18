"""Leakage-safe feature and target contracts for local model research.

The store is intentionally small and local-first.  Feature definitions are
durable policy records; materialisation selects only rows available by the
decision timestamp and never copies target columns into an inference matrix.
No model fitting or execution authority is provided here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Literal

import pandas as pd

from etf_cockpit.data.local_storage import TransactionalStore


class FeatureStoreError(ValueError):
    """Raised when a feature or target contract cannot be used safely."""


MissingPolicy = Literal["null", "zero", "reject"]
TargetKind = Literal["forward_return", "excess_return", "drawdown", "tail", "event"]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_ENTITY_COLUMNS = ("etf_id", "instrument_id", "entity_id")
_ENTITY_TYPE = "feature.definition"
_TARGET_TYPE = "feature.target"


def _identifier(value: str, label: str) -> str:
    value = str(value).strip()
    if not _IDENTIFIER.fullmatch(value):
        raise FeatureStoreError(f"{label} must be a bounded identifier")
    return value


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    source_column: str
    version: str = "1.0"
    lookback_days: int = 0
    availability_delay_days: int = 0
    dependencies: tuple[str, ...] = ()
    units: str = "unknown"
    missing_policy: MissingPolicy = "null"
    source_dataset: str = "features"

    def __post_init__(self) -> None:
        _identifier(self.feature_id, "feature_id")
        if not str(self.source_column).strip() or str(self.source_column).startswith(("target_", "label_")):
            raise FeatureStoreError("feature source columns must be named data fields, not target or label fields")
        if self.lookback_days < 0 or self.availability_delay_days < 0:
            raise FeatureStoreError("feature lookback and availability delay must be non-negative")
        if self.missing_policy not in {"null", "zero", "reject"}:
            raise FeatureStoreError(f"unsupported missing policy: {self.missing_policy}")


@dataclass(frozen=True)
class TargetDefinition:
    target_id: str
    horizon_days: int
    kind: TargetKind = "forward_return"
    version: str = "1.0"
    units: str = "return"
    embargo_days: int = 0
    event_threshold: float | None = None

    def __post_init__(self) -> None:
        _identifier(self.target_id, "target_id")
        if self.target_id.startswith(("feature_", "input_")):
            raise FeatureStoreError("target identifiers cannot masquerade as feature inputs")
        if self.horizon_days < 1 or self.embargo_days < 0:
            raise FeatureStoreError("target horizon must be positive and embargo non-negative")
        if self.kind not in {"forward_return", "excess_return", "drawdown", "tail", "event"}:
            raise FeatureStoreError(f"unsupported target kind: {self.kind}")
        if self.kind == "event" and self.event_threshold is None:
            raise FeatureStoreError("event targets require an event threshold")


@dataclass(frozen=True)
class LeakageCheck:
    safe: bool
    overlapping_rows: int
    embargo_days: int
    message: str


BUILTIN_FEATURES: tuple[FeatureDefinition, ...] = (
    FeatureDefinition("return_1d_log", "return_1d_log", units="log_return"),
    FeatureDefinition("return_20d_log", "return_20d_log", lookback_days=20, units="log_return"),
    FeatureDefinition("momentum_60d", "momentum_60d", lookback_days=60, units="log_return"),
    FeatureDefinition("vol_20d_ann", "vol_20d_ann", lookback_days=20, units="annualised_volatility"),
    FeatureDefinition("drawdown_current", "drawdown_current", units="decimal"),
    FeatureDefinition("liquidity_score", "liquidity_score", units="score"),
)


class LocalFeatureStore:
    """Durable feature/target catalogue and point-in-time materialiser."""

    execution_allowed = False

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def register_feature(self, definition: FeatureDefinition) -> FeatureDefinition:
        payload = _definition_payload(definition)
        existing = self.get(_ENTITY_TYPE, definition.feature_id)
        if existing is not None and existing != payload:
            raise FeatureStoreError(f"feature definition already exists with different content: {definition.feature_id}")
        self._put(_ENTITY_TYPE, definition.feature_id, payload)
        return definition

    def register_target(self, definition: TargetDefinition) -> TargetDefinition:
        payload = _definition_payload(definition)
        existing = self.get(_TARGET_TYPE, definition.target_id)
        if existing is not None and existing != payload:
            raise FeatureStoreError(f"target definition already exists with different content: {definition.target_id}")
        self._put(_TARGET_TYPE, definition.target_id, payload)
        return definition

    def feature_catalogue(self, *, include_builtins: bool = True) -> tuple[FeatureDefinition, ...]:
        stored = tuple(_feature_definition(row) for row in self._list(_ENTITY_TYPE))
        by_id = {item.feature_id: item for item in (BUILTIN_FEATURES if include_builtins else ())}
        by_id.update({item.feature_id: item for item in stored})
        return tuple(by_id[key] for key in sorted(by_id))

    def target_catalogue(self) -> tuple[TargetDefinition, ...]:
        return tuple(_target_definition(row) for row in self._list(_TARGET_TYPE))

    def definition_hash(self, definitions: Sequence[FeatureDefinition] | None = None) -> str:
        values = definitions if definitions is not None else self.feature_catalogue()
        return _hash_payload([_definition_payload(item) for item in sorted(values, key=lambda value: value.feature_id)])

    def materialise(
        self,
        features: pd.DataFrame,
        decision_times: Iterable[str | date | datetime],
        *,
        feature_ids: Sequence[str] | None = None,
        entity_column: str | None = None,
        date_column: str = "date",
        mode: Literal["offline", "paper", "live"] = "offline",
    ) -> pd.DataFrame:
        """Build a point-in-time matrix using only available feature rows."""

        if mode not in {"offline", "paper", "live"}:
            raise FeatureStoreError(f"unsupported inference mode: {mode}")
        if not isinstance(features, pd.DataFrame):
            raise TypeError("features must be a pandas DataFrame")
        entity_column = entity_column or _first_column(features, _ENTITY_COLUMNS)
        if features.empty:
            result = pd.DataFrame(columns=[entity_column or "etf_id", "decision_time", "inference_mode"])
            result.attrs.update({"execution_allowed": False, "definition_hash": self.definition_hash(())})
            return result
        if entity_column is None or date_column not in features.columns:
            raise FeatureStoreError(f"feature data requires an entity column and {date_column!r}")
        definitions = self._selected_definitions(feature_ids)
        if feature_ids is None:
            definitions = tuple(item for item in definitions if item.source_column in features.columns)
        missing_columns = [item.source_column for item in definitions if item.source_column not in features.columns]
        if missing_columns:
            raise FeatureStoreError(f"registered feature columns are unavailable: {', '.join(sorted(missing_columns))}")
        decisions = _decision_dates(decision_times)
        if not decisions:
            return pd.DataFrame(columns=[entity_column, "decision_time", "inference_mode"])
        source = features.copy()
        source["__feature_time"] = _timestamps(source[date_column])
        if "available_at" in source.columns:
            source["__available_at"] = _timestamps(source["available_at"])
        else:
            source["__available_at"] = source["__feature_time"]
        entities = sorted(source[entity_column].dropna().astype(str).unique())
        rows: list[dict[str, object]] = []
        definition_hash = self.definition_hash(definitions)
        for entity in entities:
            entity_rows = source[source[entity_column].astype(str) == entity].sort_values(["__feature_time", "__available_at"])
            for decision in decisions:
                output: dict[str, object] = {entity_column: entity, "decision_time": decision.date().isoformat(), "inference_mode": mode}
                selected_times: list[pd.Timestamp] = []
                for definition in definitions:
                    cutoff = decision - pd.Timedelta(days=definition.availability_delay_days)
                    candidates = entity_rows[(entity_rows["__feature_time"] <= cutoff) & (entity_rows["__available_at"] <= decision)]
                    if candidates.empty:
                        if definition.missing_policy == "reject":
                            raise FeatureStoreError(f"feature {definition.feature_id} is unavailable for {entity} at {decision.date()}")
                        value: object = 0.0 if definition.missing_policy == "zero" else None
                        output[definition.feature_id] = value
                        output[f"missing_{definition.feature_id}"] = True
                        continue
                    selected = candidates.iloc[-1]
                    output[definition.feature_id] = _safe_scalar(selected[definition.source_column])
                    output[f"missing_{definition.feature_id}"] = pd.isna(selected[definition.source_column])
                    selected_times.extend([selected["__feature_time"], selected["__available_at"]])
                output["feature_time"] = max(selected_times).date().isoformat() if selected_times else None
                output["feature_definition_hash"] = definition_hash
                output["source_vintage_hash"] = _hash_payload({key: output[key] for key in sorted(output) if key not in {"inference_mode"}})
                rows.append(output)
        result = pd.DataFrame(rows)
        result.attrs.update({"execution_allowed": False, "definition_hash": definition_hash, "mode": mode})
        return result

    def build_targets(
        self,
        prices: pd.DataFrame,
        decision_times: Iterable[str | date | datetime],
        *,
        target_ids: Sequence[str] | None = None,
        entity_column: str | None = None,
        date_column: str = "date",
        price_column: str = "adjusted_close",
        benchmark_prices: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Materialise future outcomes separately from model inputs."""

        if not isinstance(prices, pd.DataFrame) or prices.empty:
            return pd.DataFrame()
        entity_column = entity_column or _first_column(prices, _ENTITY_COLUMNS)
        if entity_column is None or date_column not in prices.columns or price_column not in prices.columns:
            raise FeatureStoreError(f"prices require an entity, {date_column!r} and adjusted prices")
        if "is_adjusted" in prices.columns and not prices["is_adjusted"].fillna(False).all():
            raise FeatureStoreError("unadjusted prices cannot be used for targets")
        definitions = self._selected_targets(target_ids)
        if not definitions:
            raise FeatureStoreError("register at least one target definition before materialising targets")
        decisions = _decision_dates(decision_times)
        source = prices.copy()
        source["__date"] = _timestamps(source[date_column])
        source["__price"] = pd.to_numeric(source[price_column], errors="coerce")
        benchmark = _prepare_benchmark(benchmark_prices, date_column, price_column) if benchmark_prices is not None else None
        rows: list[dict[str, object]] = []
        for entity, group in source.groupby(entity_column, sort=True):
            group = group.sort_values("__date").dropna(subset=["__price"])
            for decision in decisions:
                current = group[group["__date"] <= decision].tail(1)
                if current.empty:
                    continue
                current_row = current.iloc[0]
                current_position = int(group.index.get_loc(current.index[-1]))
                current_price = float(current_row["__price"])
                output: dict[str, object] = {entity_column: str(entity), "decision_time": decision.date().isoformat()}
                for definition in definitions:
                    target_position = current_position + definition.horizon_days
                    future = group.iloc[target_position : target_position + 1]
                    end_cutoff = future.iloc[0]["__date"] if not future.empty else decision + pd.Timedelta(days=definition.horizon_days)
                    if future.empty or current_price == 0:
                        output[definition.target_id] = None
                        output[f"{definition.target_id}__end_time"] = None
                        continue
                    end_row = future.iloc[0]
                    end_price = float(end_row["__price"])
                    value = end_price / current_price - 1.0
                    if definition.kind == "excess_return":
                        if benchmark is None:
                            raise FeatureStoreError("excess-return targets require benchmark prices")
                        benchmark_value = _forward_benchmark_return(benchmark, decision, end_cutoff)
                        value = None if benchmark_value is None else value - benchmark_value
                    elif definition.kind in {"drawdown", "tail"}:
                        future_values = group.iloc[current_position + 1 : target_position + 1]["__price"]
                        if future_values.empty:
                            value = None
                        else:
                            value = float(future_values.min()) / current_price - 1.0
                    elif definition.kind == "event":
                        value = bool(value >= float(definition.event_threshold or 0.0))
                    output[definition.target_id] = value
                    output[f"{definition.target_id}__end_time"] = end_row["__date"].date().isoformat()
                    output[f"{definition.target_id}__embargo_until"] = (end_row["__date"] + pd.Timedelta(days=definition.embargo_days)).date().isoformat()
                rows.append(output)
        result = pd.DataFrame(rows)
        result.attrs.update({"execution_allowed": False, "target_definition_hash": _hash_payload([_definition_payload(item) for item in definitions])})
        return result

    def leakage_check(self, targets: pd.DataFrame, target_id: str, *, validation_start: str | date | datetime) -> LeakageCheck:
        """Check that training outcomes do not overlap a validation decision."""

        if target_id not in targets.columns or "decision_time" not in targets.columns:
            raise FeatureStoreError("target frame requires decision_time and the selected target")
        definition = next((item for item in self.target_catalogue() if item.target_id == target_id), None)
        if definition is None:
            raise FeatureStoreError(f"unknown target definition: {target_id}")
        cutoff = _parse_timestamp(validation_start)
        end_column = f"{target_id}__embargo_until"
        if end_column not in targets.columns:
            raise FeatureStoreError(f"target frame is missing {end_column}")
        ends = _timestamps(targets[end_column])
        decisions = _timestamps(targets["decision_time"])
        overlaps = int(((decisions < cutoff) & (ends >= cutoff)).sum())
        safe = overlaps == 0
        return LeakageCheck(safe, overlaps, definition.embargo_days, "safe" if safe else "training targets overlap the validation embargo window")

    @staticmethod
    def coverage(matrix: pd.DataFrame) -> dict[str, object]:
        if matrix.empty:
            return {"rows": 0, "features": 0, "coverage": {}, "missing_rows": 0}
        feature_columns = [column for column in matrix.columns if not column.startswith(("missing_", "__")) and column not in {"decision_time", "feature_time", "feature_definition_hash", "source_vintage_hash", "inference_mode"} and column not in _ENTITY_COLUMNS]
        coverage = {column: round(float(1.0 - matrix[column].isna().mean()), 6) for column in feature_columns}
        missing_rows = int(matrix[[f"missing_{column}" for column in feature_columns if f"missing_{column}" in matrix]].any(axis=1).sum())
        return {"rows": int(len(matrix)), "features": len(feature_columns), "coverage": coverage, "missing_rows": missing_rows}

    @staticmethod
    def drift(reference: pd.DataFrame, current: pd.DataFrame, feature_ids: Sequence[str] | None = None) -> dict[str, object]:
        ids = list(feature_ids or sorted(set(reference.columns) & set(current.columns)))
        result: dict[str, object] = {}
        for feature_id in ids:
            left = pd.to_numeric(reference[feature_id], errors="coerce")
            right = pd.to_numeric(current[feature_id], errors="coerce")
            left_mean, right_mean = float(left.mean()), float(right.mean())
            left_std, right_std = float(left.std(ddof=0)), float(right.std(ddof=0))
            scale = max(abs(left_std), abs(left_mean), 1e-9)
            result[feature_id] = {"reference_mean": left_mean, "current_mean": right_mean, "mean_delta": right_mean - left_mean, "std_delta": right_std - left_std, "missing_rate_delta": float(right.isna().mean() - left.isna().mean()), "drifted": abs(right_mean - left_mean) / scale > 0.25}
        return {"features": result, "feature_count": len(result)}

    def get(self, entity_type: str, entity_id: str) -> dict[str, object] | None:
        with TransactionalStore(self.root) as store:
            record = store.get(entity_type, entity_id)
        return None if record is None else record.payload

    def _list(self, entity_type: str) -> tuple[dict[str, object], ...]:
        with TransactionalStore(self.root) as store:
            return tuple(record.payload for record in store.list(entity_type))

    def _put(self, entity_type: str, entity_id: str, payload: Mapping[str, object]) -> None:
        with TransactionalStore(self.root) as store:
            store.put(entity_type, entity_id, payload)

    def _selected_definitions(self, feature_ids: Sequence[str] | None) -> tuple[FeatureDefinition, ...]:
        definitions = self.feature_catalogue(include_builtins=feature_ids is None)
        if feature_ids is None:
            return definitions
        wanted = set(feature_ids)
        selected = tuple(item for item in definitions if item.feature_id in wanted)
        if len(selected) != len(wanted):
            raise FeatureStoreError("unknown feature definition requested")
        return selected

    def _selected_targets(self, target_ids: Sequence[str] | None) -> tuple[TargetDefinition, ...]:
        definitions = self.target_catalogue()
        if target_ids is None:
            return definitions
        wanted = set(target_ids)
        selected = tuple(item for item in definitions if item.target_id in wanted)
        if len(selected) != len(wanted):
            raise FeatureStoreError("unknown target definition requested")
        return selected


def _definition_payload(value: FeatureDefinition | TargetDefinition) -> dict[str, object]:
    payload = asdict(value)
    for key, item in list(payload.items()):
        if isinstance(item, tuple):
            payload[key] = list(item)
    return payload


def _feature_definition(payload: Mapping[str, object]) -> FeatureDefinition:
    values = {key: value for key, value in payload.items() if key in FeatureDefinition.__dataclass_fields__}
    values["dependencies"] = tuple(values.get("dependencies", ()))
    return FeatureDefinition(**values)


def _target_definition(payload: Mapping[str, object]) -> TargetDefinition:
    return TargetDefinition(**{key: value for key, value in payload.items() if key in TargetDefinition.__dataclass_fields__})


def _first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _parse_timestamp(value: str | date | datetime | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.normalize()


def _timestamps(values: Iterable[object]) -> pd.Series:
    series = values if isinstance(values, pd.Series) else pd.Series(list(values))
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    return parsed.dt.tz_localize(None).dt.normalize()


def _decision_dates(values: Iterable[str | date | datetime]) -> list[pd.Timestamp]:
    return sorted({_parse_timestamp(value) for value in values})


def _safe_scalar(value: object) -> object:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prepare_benchmark(frame: pd.DataFrame, date_column: str, price_column: str) -> pd.DataFrame:
    if date_column not in frame.columns or price_column not in frame.columns:
        raise FeatureStoreError("benchmark prices require date and adjusted_close columns")
    result = frame[[date_column, price_column]].copy()
    result["__date"] = _timestamps(result[date_column])
    result["__price"] = pd.to_numeric(result[price_column], errors="coerce")
    return result.dropna(subset=["__date", "__price"]).sort_values("__date")


def _forward_benchmark_return(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    left = frame[frame["__date"] <= start].tail(1)
    right = frame[frame["__date"] >= end].head(1)
    if left.empty or right.empty or float(left.iloc[0]["__price"]) == 0:
        return None
    return float(right.iloc[0]["__price"]) / float(left.iloc[0]["__price"]) - 1.0


__all__ = [
    "BUILTIN_FEATURES",
    "FeatureDefinition",
    "FeatureStoreError",
    "LeakageCheck",
    "LocalFeatureStore",
    "TargetDefinition",
]
