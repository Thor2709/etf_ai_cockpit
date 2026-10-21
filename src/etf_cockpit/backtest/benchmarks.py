from __future__ import annotations

from collections.abc import Mapping
import math

import pandas as pd

from etf_cockpit.core.config import AppConfig


def target_weights(config: AppConfig, columns: list[str]) -> pd.Series:
    raw = pd.Series({etf_id: position.target_weight for etf_id, position in config.targets.positions.items()})
    weights = raw.reindex(columns).fillna(0.0)
    total = weights.sum()
    return weights / total if total > 0 else pd.Series(1 / len(columns), index=columns)


def equal_weights(columns: list[str]) -> pd.Series:
    return pd.Series(1 / len(columns), index=columns)


def momentum_weights(price_history: pd.DataFrame, columns: list[str]) -> pd.Series:
    if len(price_history) < 181:
        return equal_weights(columns)
    mom = 0.4 * (price_history.iloc[-1] / price_history.iloc[-60] - 1)
    mom += 0.4 * (price_history.iloc[-1] / price_history.iloc[-120] - 1)
    mom += 0.2 * (price_history.iloc[-1] / price_history.iloc[-180] - 1)
    # The top half by blended momentum, equal weight, long only.
    return long_only_top_n_weights(mom.reindex(columns), max(1, len(columns) // 2))


def trend_weights(config: AppConfig, price_history: pd.DataFrame, columns: list[str]) -> pd.Series:
    base = target_weights(config, columns)
    if len(price_history) < 200:
        return base
    sma = price_history.tail(200).mean()
    active = price_history.iloc[-1] > sma
    weights = base.where(active, 0.0)
    total = weights.sum()
    return weights / total if total > 0 else pd.Series(0.0, index=columns)


def long_only_top_n_weights(scores: pd.Series, top_n: int) -> pd.Series:
    """Equal-weight the ``top_n`` highest finite scores; every other weight is zero.

    The result is long-only (no negative weight, sum 1, or all-zero when no
    finite score exists); ties break on the instrument id for determinism.
    """

    numeric = pd.to_numeric(scores, errors="coerce")
    valid = numeric[numeric.map(lambda value: math.isfinite(value) if pd.notna(value) else False)]
    weights = pd.Series(0.0, index=scores.index, dtype=float)
    count = min(max(int(top_n), 0), len(valid))
    if count <= 0:
        return weights
    ordered = sorted(valid.items(), key=lambda item: (-float(item[1]), str(item[0])))
    for instrument_id, _ in ordered[:count]:
        weights.loc[instrument_id] = 1.0 / count
    return weights


def assert_long_only(weights: pd.Series) -> pd.Series:
    """Return ``weights`` unchanged, or raise when any weight is short or non-finite."""

    values = pd.to_numeric(weights, errors="coerce")
    if values.isna().any() or (values < -1e-12).any() or not values.map(math.isfinite).all():
        raise ValueError("investable portfolios must be long-only with finite weights")
    return weights


def investable_comparison(
    long_leg_return: float,
    *,
    short_leg_return: float | None = None,
    benchmark_return: float | None = None,
    cash_return: float | None = None,
) -> dict[str, object]:
    """Compare a long-only top-N result with VWCE and cash; the short leg is research only.

    The investable result is the long leg alone.  A long-short spread (which
    assumes free shorting) is reported under ``research_only`` and never feeds
    ``investable_return``.
    """

    long_value = float(long_leg_return)
    if not math.isfinite(long_value):
        return {"status": "unavailable", "reason": "long-leg return is not finite", "short_leg_included": False}

    def excess(reference: float | None) -> float | None:
        if reference is None or not math.isfinite(float(reference)):
            return None
        return long_value - float(reference)

    short_value = None if short_leg_return is None else float(short_leg_return)
    spread = None if short_value is None or not math.isfinite(short_value) else long_value - short_value
    return {
        "status": "available",
        "investable_return": long_value,
        "excess_vs_benchmark": excess(benchmark_return),
        "excess_vs_cash": excess(cash_return),
        "short_leg_included": False,
        "research_only": {"long_short_spread": spread, "label": "research_only_not_investable"},
    }


# Fixed baselines compared in every report: QV and QVM are the quality(-momentum)
# strategies, v3 is the live signal pipeline, top-N is the long-only momentum book.
# The v3 label is only attached to the signal strategy when its signals carry the
# repository's score-engine-v3 formula identifier (``v3_formula_identity``).
V3_BASELINE_LABEL = "v3"
FIXED_BASELINE_STRATEGIES = {
    "QV": "quality_only",
    "QVM": "quality_momentum",
    "v3": "signal_strategy",
    "top_n_long_only": "momentum_only",
}


def investable_comparator_summary(
    strategy_results: Mapping[str, Mapping[str, float]],
    *,
    initial_value_eur: float,
    vwce: Mapping[str, object] | None,
    universe: list[str],
    start: object,
    end: object,
    cost_regime: str,
    cost_model_id: str,
    unavailable_strategies: Mapping[str, str] | None = None,
    v3_formula_identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Long-only strategies vs VWCE and cash on one universe, date range and cost path.

    Every entry in ``strategy_results`` and the VWCE row come from the same cost
    machinery (``cost_eur``); the fixed baselines are named by identity.  A
    baseline in ``unavailable_strategies`` (strategy name -> reason: no evidence,
    never held a position) is reported as ``status: unavailable``, never as a
    number from an all-cash book.  The ``v3`` baseline is mapped from the repository
    formula identifier: ``v3_formula_identity`` carries the expected ``formula_version``
    and the versions ``observed`` on the strategy's signals; without a match the
    baseline is unavailable, never assumed.
    """

    blocked = dict(unavailable_strategies or {})
    baselines: dict[str, dict[str, object]] = {}
    for label, name in FIXED_BASELINE_STRATEGIES.items():
        if name not in strategy_results:
            continue
        if label == V3_BASELINE_LABEL:
            mismatch = _v3_identity_mismatch(v3_formula_identity)
            if mismatch is not None:
                baselines[label] = {"strategy": name, "status": "unavailable", "reason": mismatch}
                continue
        if name in blocked:
            baselines[label] = {"strategy": name, "status": "unavailable", "reason": blocked[name]}
        else:
            extra = (
                {"formula_version": str(v3_formula_identity["expected"])}  # type: ignore[index]
                if label == V3_BASELINE_LABEL
                else {}
            )
            baselines[label] = {"strategy": name, "status": "available", **extra, **strategy_results[name]}
    return {
        "long_only": True,
        "short_legs_excluded": True,
        "universe": list(universe),
        "start_date": str(start),
        "end_date": str(end),
        "cost_regime": cost_regime,
        "cost_model_id": cost_model_id,
        "strategies": {name: dict(values) for name, values in strategy_results.items()},
        "baselines": baselines,
        "vwce": dict(vwce) if vwce is not None else {"status": "unavailable", "reason": "no canonical benchmark"},
        "cash": float(initial_value_eur),
    }


def _v3_identity_mismatch(identity: Mapping[str, object] | None) -> str | None:
    """Reason the signal strategy cannot be labelled ``v3``, or None when its signals carry the repo identifier."""

    if not identity:
        return "v3_formula_identity_not_supplied"
    expected = str(identity.get("expected") or "").strip()
    observed = {str(item).strip() for item in (identity.get("observed") or ()) if str(item).strip()}  # type: ignore[attr-defined]
    if not expected:
        return "v3_formula_identifier_unavailable_in_repository"
    if not observed:
        return "signal_formula_version_unobserved"
    if observed != {expected}:
        return f"signal_formula_version_mismatch: expected {expected}, observed {', '.join(sorted(observed))}"
    return None
