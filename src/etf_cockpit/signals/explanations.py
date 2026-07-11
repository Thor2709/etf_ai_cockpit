from __future__ import annotations

import pandas as pd


def explain_signal(row: pd.Series, action: str, blocked_by: list[str]) -> tuple[str, str]:
    momentum = float(row.get("score_momentum") or 0)
    trend = float(row.get("score_trend") or 0)
    risk = float(row.get("score_risk") or 0)
    drift = float(row.get("drift") or 0)
    total = float(row.get("total_score") or 0)
    confidence = float(row.get("confidence") or 0)
    baseline = float(row.get("score_baseline_ml") or 0)
    toto = float(row.get("score_toto") or 0)
    timesfm = float(row.get("score_timesfm") or 0)
    if blocked_by:
        short = f"{action.replace('_', ' ').title()} after evidence scoring; execution guardrails flag {', '.join(blocked_by[:3])}."
    elif action in {"buy", "add", "add_candidate"}:
        short = "Add candidate because the combined algorithm and model evidence is positive."
    elif action in {"trim", "trim_candidate"}:
        short = "Trim candidate because the combined evidence is weak or risk-adjusted trend is poor."
    elif action == "sell":
        short = "Rare sell candidate due to weak score, weak trend and existing exposure."
    elif action == "manual_review":
        short = "Evidence is incomplete or conflicted enough to require manual review."
    elif action == "hold":
        short = "Hold because evidence is not strong enough for a new candidate rating."
    else:
        short = "No trade because the score is neutral or the edge is small after costs."

    long = (
        f"Total score {total:.2f} with confidence {confidence:.2f}. "
        f"Momentum {momentum:.2f}, trend {trend:.2f}, risk {risk:.2f}, baseline {baseline:.2f}, "
        f"Toto {toto:.2f}, TimesFM {timesfm:.2f}, portfolio drift {drift:+.1%}. "
        "Primary horizon is 1-3 months, with 3-6 months used as confirmation. "
        "This is an advisory analysis score; models do not execute trades or invent missing data."
    )
    if blocked_by:
        long += f" Blocked by: {', '.join(blocked_by)}."
    return short, long
