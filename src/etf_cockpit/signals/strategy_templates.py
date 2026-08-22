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
        "benchmark_id",
        "benchmark_period_days",
        "benchmark_return",
        "instrument_period_return",
        "cash_return",
        "excess_over_cash",
        "cash_comparison_status",
        "gross_expected_return",
        "q10_expected_return",
        "q50_expected_return",
        "q90_expected_return",
        "net_q10_expected_return",
        "net_expected_return",
        "net_q90_expected_return",
        "expected_return_horizon_days",
        "expected_return_order_value_eur",
        "expected_return_cost_bps",
        "expected_return_cost_eur",
        "expected_return_cost_ratio",
        "expected_return_distribution_version",
        "expected_return_source_id",
        "expected_return_source_dataset",
        "expected_return_source_digest",
        "expected_return_as_of",
        "expected_return_known_at",
        "expected_return_trust",
        "expected_return_source_bound",
        "sector_theme_warning",
        "crowding_top_ranked_concentration",
        "crowding_top_ranked_theme_concentration",
        "crowding_top_ranked_theme_warning",
        "evidence_maturity_state",
        "evidence_sample_days",
        "backtest_validity",
        "execution_allowed",
    ]
    for alternative in ("basket", "benchmark", "cash", "no_action"):
        columns.extend(
            [
                f"monthly_{alternative}_return",
                f"monthly_{alternative}_version",
                f"monthly_{alternative}_source_id",
                f"monthly_{alternative}_source_dataset",
                f"monthly_{alternative}_source_digest",
                f"monthly_{alternative}_as_of",
                f"monthly_{alternative}_known_at",
                f"monthly_{alternative}_horizon_days",
                f"monthly_{alternative}_reference_id",
                f"monthly_{alternative}_reference_version",
                f"monthly_{alternative}_reference_content_hash",
                f"monthly_{alternative}_trust",
                f"monthly_{alternative}_source_bound",
            ]
        )
    columns.extend(("monthly_no_action_constituent_id", "monthly_no_action_weight"))
    if scoreboard.empty:
        return pd.DataFrame(columns=columns)
    result = scoreboard[[column for column in columns if column in scoreboard.columns]].copy()
    if "execution_allowed" in result.columns:
        result["execution_allowed"] = False
    return result


def write_strategy_template_frame(scoreboard: pd.DataFrame, path) -> None:
    frame = strategy_template_frame(scoreboard)
    frame.to_csv(path, index=False)


def template_description(labels: list[str]) -> str:
    return " | ".join(STRATEGY_TEMPLATE_DESCRIPTIONS.get(label, label) for label in labels)


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and float(value) >= threshold
