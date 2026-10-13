from __future__ import annotations

import math

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import ComponentScores
from etf_cockpit.features.feature_pipeline import robust_zscore
from etf_cockpit.models.ensemble import effective_ensemble_weights
from etf_cockpit.portfolio.costs import estimated_cost_bps
from etf_cockpit.portfolio.rebalancing import rebalance_score


def _clean_score(value: float | int | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if number is None or not math.isfinite(number):
        return None
    return float(max(-1.0, min(1.0, number)))


def _cross_section_z(values: pd.Series) -> pd.Series:
    """Robust z-score of a score input; a present value with no cross-sectional dispersion is neutral (0).

    ``robust_zscore`` is unavailable for a constant series, but a present input among equal peers
    (or a single instrument) is simply average. A missing input stays NaN.
    """

    return robust_zscore(values).fillna(0.0).where(values.notna())


def component_scores(
    latest_features: pd.DataFrame,
    allocation: pd.DataFrame,
    config: AppConfig,
    *,
    toto_available: bool = False,
    timesfm_available: bool = False,
    forecast_scores: dict[str, dict[str, float]] | None = None,
    chatgpt_scores: dict[str, float] | None = None,
) -> pd.DataFrame:
    frame = latest_features.merge(
        allocation[["etf_id", "current_weight", "target_weight", "hard_band", "soft_band", "max_weight"]],
        on="etf_id",
        how="left",
    )
    frame["weighted_momentum"] = (
        0.15 * frame["momentum_20d"]
        + 0.35 * frame["momentum_60d"]
        + 0.35 * frame["momentum_120d"]
        + 0.15 * frame["momentum_180d"]
    )
    frame["score_momentum"] = (
        _cross_section_z(frame["weighted_momentum"]) / 3
    ).clip(-1, 1)
    slope_z = _cross_section_z(frame["trend_slope"]) / 3
    trend_inputs_available = frame[["trend_slope", "trend_100", "trend_200"]].notna().all(axis=1)
    binary_trend = (0.5 * frame["trend_100"] + 0.5 * frame["trend_200"]) * 2 - 1
    frame["score_trend"] = (0.70 * binary_trend + 0.30 * slope_z).where(trend_inputs_available).clip(-1, 1)
    annualised_volatility = frame["vol_60d_ann"].fillna(frame["ewma_vol_ann"])
    vol_z = _cross_section_z(annualised_volatility) / 3
    drawdown = frame["drawdown_60d_max"]
    dd_penalty = drawdown.clip(-0.40, 0) / 0.40
    frame["score_risk"] = (-0.65 * vol_z + 0.35 * (1 + dd_penalty)).where(
        annualised_volatility.notna() & drawdown.notna()
    ).clip(-1, 1)
    frame["score_rebalance"] = frame.apply(
        lambda row: rebalance_score(float(row.get("current_weight", 0) or 0), float(row.get("target_weight", 0) or 0), float(row.get("hard_band", 0.05) or 0.05)),
        axis=1,
    )
    frame["score_relative_strength"] = (
        _cross_section_z(frame["relative_strength_60d"]) / 3
    ).clip(-1, 1)
    forecast_scores = forecast_scores or {}
    frame["score_toto"] = frame["etf_id"].map(forecast_scores.get("toto", {})).map(_clean_score).astype(float)
    frame["score_timesfm"] = frame["etf_id"].map(forecast_scores.get("timesfm", {})).map(_clean_score).astype(float)
    baseline_forecast_score = frame["etf_id"].map(forecast_scores.get("baseline", {})).map(_clean_score).astype(float)
    deterministic_baseline_score = (0.55 * frame["score_momentum"] + 0.45 * frame["score_trend"]).clip(-1, 1)
    frame["score_baseline_ml"] = baseline_forecast_score.clip(-1, 1).where(
        baseline_forecast_score.notna(), deterministic_baseline_score
    )
    frame["score_chatgpt_thesis"] = frame["etf_id"].map(chatgpt_scores or {}).fillna(0.0).clip(-1, 1)
    frame["cost_penalty"] = frame["etf_id"].map(lambda etf_id: estimated_cost_bps(config, str(etf_id)) / 1000).clip(0, 0.08)
    frame["turnover_penalty"] = 0.0
    max_cap = frame["max_weight"].fillna(config.risks.portfolio_limits.max_single_etf_weight)
    frame["concentration_penalty"] = ((frame["current_weight"].fillna(0) / max_cap) - 0.85).clip(lower=0, upper=0.25)

    raw_weights = config.models.ensemble["weights"]
    # A live model that no promoted forecast row backs (shadow or unproven) contributes no score; its weight
    # is renormalised away instead of turning every composite score and confidence into NaN.
    weights = effective_ensemble_weights(
        raw_weights,
        toto_available=bool(toto_available and forecast_scores.get("toto")),
        timesfm_available=bool(timesfm_available and forecast_scores.get("timesfm")),
    )
    active_components = [
        (key, column, weight)
        for key, column in (
            ("momentum", "score_momentum"),
            ("trend", "score_trend"),
            ("risk", "score_risk"),
            ("rebalance", "score_rebalance"),
            ("relative_strength", "score_relative_strength"),
            ("toto", "score_toto"),
            ("timesfm", "score_timesfm"),
            ("baseline_ml", "score_baseline_ml"),
            ("chatgpt_thesis", "score_chatgpt_thesis"),
        )
        if (weight := weights.get(key, 0)) > 0
    ]
    finite_components = {
        key: frame[column].map(lambda value: pd.notna(value) and math.isfinite(float(value)))
        for key, column, _ in active_components
    }
    weighted_score = sum(
        weight * frame[column].where(finite_components[key], 0.0)
        for key, column, weight in active_components
    )
    retained_weight = sum(weight * finite_components[key] for key, _, weight in active_components)
    all_present = pd.Series(True, index=frame.index)
    for mask in finite_components.values():
        all_present &= mask
    # Preserve the original sum exactly for complete rows; renormalise only rows
    # with missing components. With no finite weighted evidence, remain unavailable.
    if active_components:
        weighted_score = weighted_score.where(all_present, weighted_score / retained_weight.where(retained_weight > 0))
    else:
        weighted_score = pd.Series(float("nan"), index=frame.index)
    frame["total_score"] = (weighted_score - frame["cost_penalty"] - frame["turnover_penalty"]).clip(-1, 1)
    agreement = 1 - frame[["score_momentum", "score_trend", "score_baseline_ml"]].std(axis=1).clip(0, 1)
    signal_strength = frame["total_score"].abs().clip(0, 1)
    cost_quality = (1 - frame["cost_penalty"].clip(0, 0.20) / 0.20).clip(0, 1)
    frame["confidence"] = (0.25 * 1.0 + 0.25 * agreement + 0.20 * 0.70 + 0.15 * signal_strength + 0.15 * cost_quality).clip(0, 0.95)
    unavailable_reasons = (
        ("score_trend", "trend_inputs_unavailable"),
        ("score_risk", "risk_inputs_unavailable"),
        ("score_relative_strength", "relative_strength_unavailable"),
        ("score_toto", "toto_forecast_unavailable"),
        ("score_timesfm", "timesfm_forecast_unavailable"),
    )
    frame["score_unavailable_reason_codes"] = frame.apply(
        lambda row: "|".join(
            [reason for column, reason in unavailable_reasons if _clean_score(row[column]) is None]
            + [f"model_missing:{key}" for key, column in (("toto", "score_toto"), ("timesfm", "score_timesfm"))
               if (toto_available if key == "toto" else timesfm_available) and _clean_score(row[column]) is None]
        ),
        axis=1,
    )
    return frame


def row_components(row: pd.Series) -> ComponentScores:
    return ComponentScores(
        momentum=_clean_score(row.get("score_momentum")),
        trend=_clean_score(row.get("score_trend")),
        risk=_clean_score(row.get("score_risk")),
        rebalance=_clean_score(row.get("score_rebalance")),
        relative_strength=_clean_score(row.get("score_relative_strength")),
        toto=_clean_score(row.get("score_toto")),
        timesfm=_clean_score(row.get("score_timesfm")),
        baseline_ml=_clean_score(row.get("score_baseline_ml")),
        chatgpt_thesis=_clean_score(row.get("score_chatgpt_thesis")),
        cost_penalty=max(0.0, float(row.get("cost_penalty") or 0.0)),
        turnover_penalty=max(0.0, float(row.get("turnover_penalty") or 0.0)),
        concentration_penalty=max(0.0, float(row.get("concentration_penalty") or 0.0)),
    )
