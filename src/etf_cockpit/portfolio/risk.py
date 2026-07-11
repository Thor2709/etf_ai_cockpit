from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import DataQualityIssue


def concentration_warnings(config: AppConfig, allocation: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    limits = config.risks.portfolio_limits
    for _, row in allocation.iterrows():
        if row["current_weight"] > min(row.get("max_weight", 1.0), limits.max_single_etf_weight):
            warnings.append(f"{row['etf_id']} exceeds single ETF cap.")
    for column, limit, label in [
        ("sector", limits.max_sector_weight, "sector"),
        ("region", limits.max_region_weight, "region"),
        ("theme", limits.max_theme_weight, "theme"),
    ]:
        if column in allocation:
            grouped = allocation.groupby(column, dropna=False)["current_weight"].sum()
            for key, weight in grouped.items():
                if pd.notna(key) and weight > limit:
                    warnings.append(f"{label} cap exceeded: {key} at {weight:.1%}.")
    return warnings


def target_policy_issues(config: AppConfig) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    universe = config.universe.by_id()
    limit = config.risks.portfolio_limits.max_single_etf_weight
    for etf_id, target in config.targets.positions.items():
        etf = universe.get(etf_id)
        effective_limit = min(limit, etf.max_weight if etf else 1.0)
        if target.target_weight > effective_limit:
            issues.append(
                DataQualityIssue(
                    etf_id=etf_id,
                    severity="warning",
                    code="target_policy_violation",
                    message=(
                        f"{etf_id} target_weight {target.target_weight:.0%} exceeds "
                        f"max_single_etf_weight {effective_limit:.0%}. Shown as portfolio context; it no longer blocks instrument analysis."
                    ),
                )
            )
    target_total = sum(position.target_weight for position in config.targets.positions.values()) + config.targets.cash_target_weight
    if abs(target_total - 1.0) > 0.005:
        issues.append(
            DataQualityIssue(
                etf_id="ALL",
                severity="block",
                code="target_total_invalid",
                message=f"Target weights plus cash equal {target_total:.2%}; expected approximately 100%.",
            )
        )
    return issues


def projected_weight_allowed(config: AppConfig, etf_id: str, projected_weight: float) -> tuple[bool, str | None]:
    etf = config.universe.by_id().get(etf_id)
    limit = min(config.risks.portfolio_limits.max_single_etf_weight, etf.max_weight if etf else 1.0)
    if projected_weight > limit:
        return False, f"projected_weight_above_cap:{limit:.1%}"
    return True, None
