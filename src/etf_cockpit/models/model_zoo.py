"""Local model-zoo contracts and deterministic research baselines.

The zoo is deliberately separate from signal generation.  It provides a
typed catalogue and bounded research runners for Forecast Lab; it never
selects, promotes or executes a model.  Optional model packages and weights
are represented as unavailable evidence rather than silently replaced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Literal

import numpy as np
import pandas as pd


MODEL_ZOO_SCHEMA_VERSION = "model-zoo.v1"
ModelTask = Literal["return", "risk", "quantile", "fundamentals"]
ModelState = Literal["available", "unavailable"]


@dataclass(frozen=True)
class ModelCard:
    """Auditable metadata for one model family in the local research zoo."""

    model_id: str
    display_name: str
    family: str
    tasks: tuple[ModelTask, ...]
    horizons: tuple[int, ...]
    data_needs: tuple[str, ...]
    licence: str
    version: str
    optional: bool
    state: ModelState
    state_reason: str
    latency_class: str
    resource_class: str
    checksum: str = "not_applicable"
    promotion_state: str = "shadow_only"
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.execution_allowed:
            raise ValueError("model-zoo entries cannot grant execution authority")
        if not self.tasks or not self.horizons or not self.data_needs:
            raise ValueError("model-zoo cards require task, horizon and data metadata")
        if self.state == "unavailable" and not self.state_reason.strip():
            raise ValueError("unavailable model-zoo entries require a reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MODEL_ZOO_SCHEMA_VERSION,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "family": self.family,
            "tasks": list(self.tasks),
            "horizons": list(self.horizons),
            "data_needs": list(self.data_needs),
            "licence": self.licence,
            "version": self.version,
            "optional": self.optional,
            "state": self.state,
            "state_reason": self.state_reason,
            "latency_class": self.latency_class,
            "resource_class": self.resource_class,
            "checksum": self.checksum,
            "promotion_state": self.promotion_state,
            "execution_allowed": False,
        }


_DEFAULT_HORIZONS = (5, 20, 60, 120, 180)


def model_zoo_catalogue(
    *,
    optional_status: Mapping[str, bool] | None = None,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
) -> tuple[ModelCard, ...]:
    """Return deterministic baseline/challenger cards.

    ``optional_status`` is supplied by the local weight inventory or by a
    forecast artefact report.  Missing entries remain explicitly unavailable.
    No network or package discovery is performed here.
    """

    clean_horizons = tuple(sorted({int(value) for value in horizons if int(value) > 0})) or _DEFAULT_HORIZONS
    optional_status = optional_status or {}
    cards = (
        _card("naive_drift", "Naive drift", "naive", ("return", "quantile"), clean_horizons, ("adjusted_close",), "MIT", "1", False, "available", "Deterministic local baseline.", "low", "low"),
        _card("historical_median", "Historical median", "naive", ("return", "risk", "quantile"), clean_horizons, ("adjusted_close",), "MIT", "1", False, "available", "Deterministic local baseline.", "low", "low"),
        _card("linear_ridge", "Linear ridge", "linear", ("return", "quantile"), clean_horizons, ("adjusted_close",), "BSD-3-Clause", "1", False, "available", "Regularised linear baseline.", "low", "low"),
        _card("elastic_net", "Elastic net", "linear", ("return", "quantile"), clean_horizons, ("adjusted_close", "local_features"), "BSD-3-Clause", "1", False, "available", "Regularised linear challenger; walk-forward validation required.", "low", "low"),
        _card("robust_regression", "Robust regression", "robust", ("return", "risk"), clean_horizons, ("adjusted_close", "local_features"), "BSD-3-Clause", "1", False, "available", "Outlier-resistant local challenger.", "low", "low"),
        _card("state_space", "State-space EWMA", "state-space", ("return", "risk", "quantile"), clean_horizons, ("adjusted_close",), "MIT", "1", False, "available", "Bounded local state estimate; not a fitted production model.", "low", "low"),
        _card("econometric_ar", "Econometric AR(1)", "econometric", ("return", "risk", "quantile"), clean_horizons, ("adjusted_close",), "MIT", "1", False, "available", "Deterministic autoregressive challenger.", "low", "low"),
        _card("tree_boosting", "Tree boosting", "tree-boosting", ("return", "risk", "fundamentals"), clean_horizons, ("adjusted_close", "local_features", "fundamentals"), "Model-specific terms", "optional", True, "unavailable" if not optional_status.get("tree_boosting", False) else "available", "Optional dependency/validated feature set is not registered locally.", "medium", "medium"),
        _card("timesfm", "TimesFM", "foundation", ("return", "quantile"), clean_horizons, ("adjusted_close",), "Model-specific terms", "optional", True, "available" if optional_status.get("timesfm", False) else "unavailable", "Optional local weights and runtime are not available." if not optional_status.get("timesfm", False) else "Optional local challenger; validation and licence review remain required.", "high", "high"),
        _card("toto", "Toto", "foundation", ("return", "quantile"), clean_horizons, ("adjusted_close",), "Model-specific terms", "optional", True, "available" if optional_status.get("toto", False) else "unavailable", "Optional local weights and runtime are not available." if not optional_status.get("toto", False) else "Optional local challenger; validation and licence review remain required.", "high", "high"),
    )
    return cards


def model_zoo_frame(
    *,
    optional_status: Mapping[str, bool] | None = None,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Serialise cards into a stable UI/report table."""

    columns = [
        "model_id", "display_name", "family", "tasks", "horizons", "data_needs",
        "licence", "version", "optional", "state", "state_reason", "latency_class",
        "resource_class", "checksum", "promotion_state", "execution_allowed",
    ]
    rows = [card.to_dict() for card in model_zoo_catalogue(optional_status=optional_status, horizons=horizons)]
    return pd.DataFrame(rows, columns=columns)


def run_model_zoo(
    adjusted_close: pd.Series,
    horizons: Sequence[int],
    *,
    etf_id: str = "UNKNOWN",
    forecast_date: date | None = None,
    task: ModelTask = "return",
    model_ids: Sequence[str] | None = None,
    fundamentals: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Run bounded deterministic local research baselines.

    The input is intentionally named ``adjusted_close`` and is rejected when
    it is not a positive finite series.  Results are descriptive, marked
    ``not_selected`` and require walk-forward evidence before any later
    promotion workflow may consider them.
    """

    if task not in {"return", "risk", "quantile", "fundamentals"}:
        raise ValueError(f"Unsupported model-zoo task: {task}")
    values = pd.to_numeric(adjusted_close, errors="coerce")
    if values.empty or values.isna().any() or not np.isfinite(values.to_numpy()).all() or (values <= 0).any():
        raise ValueError("adjusted_close must contain only positive finite values")
    clean_horizons = tuple(sorted({int(value) for value in horizons if int(value) > 0}))
    if not clean_horizons:
        raise ValueError("at least one positive forecast horizon is required")
    log_prices = np.log(values.astype(float))
    returns = log_prices.diff().dropna()
    selected = set(model_ids) if model_ids is not None else None
    rows: list[dict[str, object]] = []
    cards = {card.model_id: card for card in model_zoo_catalogue(horizons=clean_horizons)}
    candidates = [card for card in cards.values() if task in card.tasks]
    for card in candidates:
        if selected is not None and card.model_id not in selected:
            continue
        for horizon in clean_horizons:
            if card.optional:
                unavailable_reason = (
                    "No local point-in-time fundamentals target was supplied."
                    if task == "fundamentals" and fundamentals is None
                    else card.state_reason
                )
                rows.append(
                    {
                        "model_id": card.model_id,
                        "model_name": card.display_name,
                        "model_version": card.version,
                        "licence": card.licence,
                        "latency_class": card.latency_class,
                        "resource_class": card.resource_class,
                        "checksum": card.checksum,
                        "task": task,
                        "etf_id": etf_id,
                        "forecast_date": forecast_date.isoformat() if forecast_date else None,
                        "horizon_days": horizon,
                        "expected_return": None,
                        "forecast_vol": None,
                        "q10_return": None,
                        "q50_return": None,
                        "q90_return": None,
                        "status": "unavailable",
                        "reason": unavailable_reason,
                        "selection_state": "not_selected",
                        "validation_scope": "walk_forward_required",
                        "execution_allowed": False,
                    }
                )
                continue
            if task == "fundamentals":
                expected, volatility = 0.0, 0.0
            else:
                expected, volatility = _estimate(card.model_id, log_prices, returns, horizon)
            status = "ok"
            reason = "Deterministic local research output."
            if task == "fundamentals":
                if fundamentals is None or "expected_return" not in fundamentals:
                    expected = 0.0
                    volatility = 0.0
                    status = "unavailable"
                    reason = "No local point-in-time fundamentals target was supplied."
                else:
                    expected = float(fundamentals["expected_return"])
                    volatility = 0.0
            if task == "risk":
                expected_value: float | None = None
            else:
                expected_value = expected
            interval = volatility * sqrt(horizon / 252.0)
            rows.append(
                {
                    "model_id": card.model_id,
                    "model_name": card.display_name,
                    "model_version": card.version,
                    "licence": card.licence,
                    "latency_class": card.latency_class,
                    "resource_class": card.resource_class,
                    "checksum": card.checksum,
                    "task": task,
                    "etf_id": etf_id,
                    "forecast_date": forecast_date.isoformat() if forecast_date else None,
                    "horizon_days": horizon,
                    "expected_return": expected_value,
                    "forecast_vol": interval,
                    "q10_return": None if task == "risk" else expected - 1.28 * interval,
                    "q50_return": expected_value,
                    "q90_return": None if task == "risk" else expected + 1.28 * interval,
                    "status": status,
                    "reason": reason,
                    "selection_state": "not_selected",
                    "validation_scope": "walk_forward_required",
                    "execution_allowed": False,
                }
            )
    return pd.DataFrame(rows, columns=[
        "model_id", "model_name", "model_version", "licence", "latency_class", "resource_class", "checksum",
        "task", "etf_id", "forecast_date", "horizon_days",
        "expected_return", "forecast_vol", "q10_return", "q50_return", "q90_return",
        "status", "reason", "selection_state", "validation_scope", "execution_allowed",
    ])


def _card(
    model_id: str,
    display_name: str,
    family: str,
    tasks: tuple[ModelTask, ...],
    horizons: tuple[int, ...],
    data_needs: tuple[str, ...],
    licence: str,
    version: str,
    optional: bool,
    state: ModelState,
    state_reason: str,
    latency_class: str,
    resource_class: str,
) -> ModelCard:
    return ModelCard(
        model_id=model_id,
        display_name=display_name,
        family=family,
        tasks=tasks,
        horizons=horizons,
        data_needs=data_needs,
        licence=licence,
        version=version,
        optional=optional,
        state=state,
        state_reason=state_reason,
        latency_class=latency_class,
        resource_class=resource_class,
    )


def _estimate(model_id: str, log_prices: pd.Series, returns: pd.Series, horizon: int) -> tuple[float, float]:
    if returns.empty:
        return 0.0, 0.0
    recent = returns.tail(180)
    if model_id == "naive_drift":
        drift = float(recent.iloc[-1])
    elif model_id == "historical_median":
        drift = float(returns.median())
    elif model_id == "linear_ridge":
        drift = _linear_slope(log_prices, penalty=1e-3)
    elif model_id == "elastic_net":
        drift = _linear_slope(log_prices, penalty=0.05)
    elif model_id == "robust_regression":
        drift = float(returns.median())
    elif model_id == "state_space":
        drift = float(recent.ewm(alpha=0.2, adjust=False).mean().iloc[-1])
    elif model_id == "econometric_ar":
        drift = _ar1_drift(returns)
    else:
        raise ValueError(f"Unsupported runnable model: {model_id}")
    volatility = float(recent.std(ddof=1) * sqrt(252)) if len(recent) > 1 else 0.0
    return drift * horizon, volatility


def _linear_slope(log_prices: pd.Series, *, penalty: float) -> float:
    if len(log_prices) < 2:
        return 0.0
    x = np.arange(len(log_prices), dtype=float)
    x -= x.mean()
    y = log_prices.to_numpy(dtype=float)
    y -= y.mean()
    denominator = float(np.dot(x, x) + penalty)
    return float(np.dot(x, y) / denominator)


def _ar1_drift(returns: pd.Series) -> float:
    if len(returns) < 3:
        return float(returns.mean())
    previous = returns.iloc[:-1].to_numpy(dtype=float)
    current = returns.iloc[1:].to_numpy(dtype=float)
    denominator = float(np.dot(previous, previous) + 1e-6)
    coefficient = float(np.dot(previous, current) / denominator)
    return float(returns.iloc[-1]) * coefficient


__all__ = ["MODEL_ZOO_SCHEMA_VERSION", "ModelCard", "model_zoo_catalogue", "model_zoo_frame", "run_model_zoo"]
