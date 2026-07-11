from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.portfolio.risk import projected_weight_allowed


def evaluate_risk_gates(
    config: AppConfig,
    row: pd.Series,
    data_report: DataQualityReport,
    *,
    candidate_action: str,
    projected_weight: float | None,
    cash_weight: float,
    model_disagreement: float = 0.0,
) -> tuple[list[str], list[str]]:
    etf_id = str(row["etf_id"])
    blocked: list[str] = []
    warnings: list[str] = []

    if not data_report.trading_allowed:
        blocked.append("portfolio_validation_block")

    for issue in data_report.issues:
        if issue.etf_id in {etf_id, "ALL"}:
            if issue.severity == "block":
                blocked.append(issue.code)
            elif issue.severity == "warning":
                warnings.append(issue.code)

    if candidate_action in {"buy", "add"} and float(row.get("trend_200") or 0.0) <= 0:
        blocked.append("below_sma_200")

    if candidate_action in {"buy", "add"} and float(row.get("drawdown_60d_max") or 0.0) < -config.risks.portfolio_limits.max_expected_drawdown_60d:
        blocked.append("expected_drawdown_gate")

    if candidate_action in {"buy", "add", "trim", "sell"}:
        edge = abs(float(row.get("expected_edge_60d") or 0.0))
        estimated_cost = float(row.get("cost_bps") or 0.0) / 10_000
        required_edge = config.risks.portfolio_limits.min_edge_to_cost_ratio * estimated_cost
        if edge < required_edge:
            blocked.append("edge_below_cost_threshold")

    if candidate_action in {"buy", "add"} and projected_weight is not None:
        ok, reason = projected_weight_allowed(config, etf_id, projected_weight)
        if not ok and reason:
            blocked.append(reason)
        projected_cash = cash_weight - max(0.0, projected_weight - float(row.get("current_weight") or 0.0))
        if projected_cash < config.risks.portfolio_limits.cash_min_weight:
            blocked.append("cash_minimum_breached")

    if model_disagreement > 0.80:
        blocked.append("model_disagreement")

    return sorted(set(blocked)), sorted(set(warnings))
