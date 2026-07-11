from __future__ import annotations

import pandas as pd


STRATEGY_TEMPLATE_DESCRIPTIONS = {
    "dual_momentum_etf": "ETF template: medium-term momentum, positive trend and acceptable risk.",
    "quality_momentum_stock": "Stock template: stock quality plus price momentum.",
    "value_momentum_stock": "Stock template: attractive valuation with at least acceptable quality and momentum.",
    "defensive_watch": "Defensive template: useful evidence exists, but risk/friction or market regime calls for caution.",
    "no_template": "No template matched. Treat the row as a general evidence review.",
}


def strategy_template_labels(
    *,
    asset_type: str,
    evidence_score: float | None,
    risk_friction_score: float | None,
    component_scores: dict[str, float | None],
    regime_label: str,
) -> list[str]:
    labels: list[str] = []
    momentum = component_scores.get("momentum")
    trend = component_scores.get("trend")
    risk = component_scores.get("risk")
    relative = component_scores.get("relative_strength")
    value = component_scores.get("stock_value")
    quality = component_scores.get("stock_quality")
    regime_defensive = "defensive" in regime_label.lower()

    if asset_type == "ETF":
        if _at_least(momentum, 6.5) and _at_least(trend, 6.0) and _at_least(relative, 5.5) and _at_least(risk, 5.0):
            labels.append("dual_momentum_etf")
    else:
        if _at_least(quality, 6.5) and _at_least(momentum, 6.0) and _at_least(trend, 5.5):
            labels.append("quality_momentum_stock")
        if _at_least(value, 6.5) and _at_least(quality, 5.0) and _at_least(momentum, 5.5):
            labels.append("value_momentum_stock")

    if (evidence_score is not None and evidence_score >= 5.0) and (
        regime_defensive or (risk_friction_score is not None and risk_friction_score < 5.0)
    ):
        labels.append("defensive_watch")
    return labels or ["no_template"]


def strategy_template_frame(scoreboard: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "instrument_id",
        "symbol",
        "asset_type",
        "evidence_score_10",
        "risk_friction_10",
        "strategy_template_label",
        "strategy_template_descriptions",
        "market_regime_label",
    ]
    return scoreboard[[column for column in columns if column in scoreboard.columns]].copy() if not scoreboard.empty else pd.DataFrame(columns=columns)


def write_strategy_template_frame(scoreboard: pd.DataFrame, path) -> None:
    frame = strategy_template_frame(scoreboard)
    frame.to_csv(path, index=False)


def template_description(labels: list[str]) -> str:
    return " | ".join(STRATEGY_TEMPLATE_DESCRIPTIONS.get(label, label) for label in labels)


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and float(value) >= threshold
