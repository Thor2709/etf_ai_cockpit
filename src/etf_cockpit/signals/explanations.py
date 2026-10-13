from __future__ import annotations

import pandas as pd
from math import isfinite


def explain_signal(row: pd.Series, action: str, blocked_by: list[str]) -> tuple[str, str]:
    def display(key: str, format_spec: str = ".2f") -> str:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            return "unavailable"
        return format(value, format_spec) if isfinite(value) else "unavailable"
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
        f"Total score {display('total_score')} with confidence {display('confidence')}. "
        f"Momentum {display('score_momentum')}, trend {display('score_trend')}, risk {display('score_risk')}, baseline {display('score_baseline_ml')}, "
        f"Toto {display('score_toto')}, TimesFM {display('score_timesfm')}, portfolio drift {display('drift', '+.1%')}. "
        "Primary horizon is 1-3 months, with 3-6 months used as confirmation. "
        "This is an advisory analysis score; models do not execute trades or invent missing data."
    )
    if blocked_by:
        long += f" Blocked by: {', '.join(blocked_by)}."
    return short, long
