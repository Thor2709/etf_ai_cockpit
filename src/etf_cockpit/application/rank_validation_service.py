"""Read-only application service for point-in-time rank validation.

Open defaults: validate 1, 3, and 5 year windows from stored adjusted prices;
optional cost, cash, and fundamental evidence stays unavailable when absent.
Independent windows (including replay) use at most three worker threads;
results retain the requested window order and workers never persist evidence.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import (
    attach_fundamental_evidence,
    forward_comparator_frame,
    load_rank_validation_policy,
    price_knowledge_gap,
    price_momentum_risk_evidence,
    rank_validation_report_dict,
    research_policy,
    run_stored_rank_validation,
    window_coverage,
    window_decision_times,
)


_PRICE_RELATIVE = Path("data") / "validated" / "prices" / "prices_daily.parquet"
_DEFAULT_SCOPE = "listing:euronext_oslo:all"


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


def _load_membership(path: Path | None, root: Path, scope: str, as_known_at: datetime) -> pd.DataFrame:
    if path is not None:
        return _read_table(path)
    from etf_cockpit.data.universe_membership import membership_frame

    return membership_frame(scope, as_known_at, root=root)


def build_rank_validation_report(
    *,
    root: Path,
    years: Sequence[int] = (1, 3, 5),
    scope: str = _DEFAULT_SCOPE,
    benchmark_id: str | None = None,
    prices_path: Path | None = None,
    membership_path: Path | None = None,
    costs_path: Path | None = None,
    cash_path: Path | None = None,
    fundamentals_path: Path | None = None,
) -> dict[str, object]:
    """Build the research-only report without changing any rank authority."""

    resolved_root = Path(root).resolve()
    selected_years = tuple(int(value) for value in years)
    if not selected_years or any(value <= 0 for value in selected_years):
        raise ValueError("years must contain positive integers")
    prices_file = Path(prices_path) if prices_path is not None else resolved_root / _PRICE_RELATIVE
    prices = _read_table(prices_file)
    costs = _read_table(Path(costs_path) if costs_path is not None else None)
    cash = _read_table(Path(cash_path) if cash_path is not None else None)
    fundamentals = _read_table(Path(fundamentals_path) if fundamentals_path is not None else None)
    base_policy = load_rank_validation_policy()
    report: dict[str, object] = {
        "schema_version": 1,
        "kind": "rank_validation_report",
        "generated_for": "research_only",
        "policy_version": base_policy.version,
        "price_known_at_basis": "stored_known_at_column_required",
        "inputs": {
            "prices_rows": int(len(prices)), "costs_rows": int(len(costs)),
            "cash_rows": int(len(cash)), "fundamental_rows": int(len(fundamentals)),
            "benchmark_id": benchmark_id,
        },
        "windows": [], "promotion_applied": False, "rank_authority": False,
        "execution_allowed": False,
    }
    if prices.empty or not {"instrument_id", "date", "adjusted_close"}.issubset(prices.columns):
        report.update(status="unavailable", reason="stored adjusted-close history is unavailable")
        return report
    gap = price_knowledge_gap(prices)
    if gap is not None:
        report.update(status="unavailable", reason=gap)
        return report
    report["inputs"]["price_rows_without_verifiable_known_at"] = int(  # type: ignore[index]
        sum(
            int(count)  # one parse per distinct stamp: the stamps repeat for every instrument of a session
            for item, count in prices["known_at"].value_counts(dropna=False).items()
            if pd.isna(pd.to_datetime(item, errors="coerce", utc=True))
        )
    )
    parsed_dates = pd.to_datetime(prices["date"], errors="coerce")
    if parsed_dates.isna().all():
        report.update(status="unavailable", reason="stored adjusted-close dates are unavailable")
        return report
    last_session = max(item for item in parsed_dates.dt.date if item is not None)
    first_session = min(item for item in parsed_dates.dt.date if item is not None)
    as_known_at = datetime(last_session.year, last_session.month, last_session.day, 23, 59, 59, tzinfo=timezone.utc)
    memberships = _load_membership(Path(membership_path) if membership_path is not None else None, resolved_root, scope, as_known_at)
    report["inputs"]["membership_rows"] = int(len(memberships))  # type: ignore[index]

    def run_window(window_years: int) -> dict[str, object]:
        coverage = window_coverage(prices, window_years)
        if not coverage["sufficient"]:
            return {
                "requested_years": window_years, "status": "insufficient_evidence",
                "reason": coverage["reason"], "coverage": coverage,
                "decision_times": 0, "excluded_decision_times": 0, "sections": {},
            }
        times, excluded = window_decision_times(
            prices, window_years,
            step_sessions=base_policy.holding_period_sessions,
            holding_period_sessions=base_policy.holding_period_sessions,
        )
        evidence, skipped = price_momentum_risk_evidence(prices, times)
        benchmark = (
            forward_comparator_frame(prices, benchmark_id, times, base_policy.holding_period_sessions)
            if benchmark_id else pd.DataFrame()
        )
        window: dict[str, object] = {
            "requested_years": window_years, "status": "evaluated", "coverage": coverage,
            "first_price_date": first_session.isoformat(), "last_price_date": last_session.isoformat(),
            "decision_times": len(times), "excluded_decision_times": len(excluded),
            "instrument_skips": {key: len(value) for key, value in skipped.items()},
        }
        sections: dict[str, object] = {}
        runs = [("price_factors", research_policy(base_policy, fundamentals=False), evidence)]
        if fundamentals.empty:
            sections["fundamental_factors"] = {
                "status": "unavailable",
                "reason": "no point-in-time fundamentals evidence supplied; not filled",
            }
        else:
            runs.append((
                "fundamental_factors", research_policy(base_policy, fundamentals=True),
                attach_fundamental_evidence(evidence, fundamentals),
            ))
        for label, policy, run_evidence in runs:
            replay, validation = run_stored_rank_validation(
                run_evidence, memberships, prices, costs, benchmark, cash, times, policy=policy
            )
            sections[label] = rank_validation_report_dict(
                replay, validation, label=f"{label}_{window_years}y",
                requested_decision_times=times, excluded_decision_times=excluded,
            )
            conflicts = run_evidence.attrs.get("fundamental_conflicts")
            if conflicts:
                sections[label]["fundamental_conflicts"] = conflicts
        window["sections"] = sections
        return window

    max_workers = min(3, len(selected_years))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rank-window") as executor:
        report["windows"] = list(executor.map(run_window, selected_years))
    report["parallelism"] = {
        "unit": "requested_year_windows_including_replay", "executor": "thread_pool",
        "max_workers": max_workers, "output_order": "requested",
    }
    report["status"] = "reported"
    return report


__all__ = ["build_rank_validation_report"]
