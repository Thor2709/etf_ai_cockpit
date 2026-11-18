"""Read-only application service for point-in-time rank validation.

Open defaults: validate 1, 3, and 5 year windows from stored adjusted prices;
optional cost, cash, and fundamental evidence stays unavailable when absent.
Independent windows (including replay) use at most three worker threads;
results retain the requested window order and workers never persist evidence.
A third, shadow run ranks quality and value challengers built from the stored
period store; it never shares a policy with the promotion rankers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import (
    RankerSpec,
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
_SHADOW_VERSION = "shadow-quality-value-v1"
# stock-evidence metric -> (challenger column, sign); a "_neg" column carries the negated metric (high is bad)
_SHADOW_METRICS = (
    ("gross_profitability", "gross_profitability", 1.0),
    ("accruals", "sloan_accruals_neg", -1.0),
    ("dilution", "net_share_issuance_neg", -1.0),
    ("piotroski_f", "piotroski_f", 1.0),
    ("shareholder_yield", "shareholder_yield", 1.0),
)
_SHADOW_COMPONENTS = tuple(column for _, column, _ in _SHADOW_METRICS) + ("asset_growth_neg",)
_SHADOW_COLUMNS = ["instrument_id", "effective_at", "known_at", *_SHADOW_COMPONENTS]


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


def _load_membership(path: Path | None, root: Path, scope: str, as_known_at: datetime) -> pd.DataFrame:
    if path is not None:
        return _read_table(path)
    from etf_cockpit.data.universe_membership import membership_frame

    return membership_frame(scope, as_known_at, root=root)


def _shadow_rows(root: Path, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per instrument and ``known_at`` version of the period store: the challenger columns as known then.

    The stock-evidence build runs at each version's ``known_at``, so a row holds only facts learned by then.
    A metric that is unavailable stays NaN; nothing is filled.
    """

    from etf_cockpit.analysis import stock_metrics as sm
    from etf_cockpit.analysis.stock_evidence import build_stock_evidence
    from etf_cockpit.analysis.stock_universe import market_inputs
    from etf_cockpit.data import stock_fundamentals as store

    frame = store.read_periods(root)
    if frame.empty:
        return pd.DataFrame(columns=_SHADOW_COLUMNS)
    config = store.load_stock_config(root)
    chain = list((config.get("sources", {}) or {}).get("chain", ["sec_edgar", "esef", "yfinance"]))
    snapshots, fx = store.read_snapshots(root), store.read_fx(root)
    traded = prices.assign(date=pd.to_datetime(prices["date"], errors="coerce")).dropna(subset=["date"]) if "close" in prices else pd.DataFrame()
    rows: list[dict[str, object]] = []
    for instrument in sorted(frame["instrument_id"].astype(str).unique()):
        periods = store.periods_for(instrument, frame, chain)
        history = traded.loc[traded["instrument_id"].astype(str) == instrument].sort_values("date") if not traded.empty else traded
        for known in sorted({period.known_at for period in periods}):
            visible = sm.known_periods(periods, known)
            if not visible:
                continue
            market = market_inputs(history, store.latest_snapshot(instrument, snapshots, known), visible[-1].currency, known, fx, config)
            metrics = build_stock_evidence(instrument, periods, known, market, None, config).metrics
            row: dict[str, object] = {
                "instrument_id": instrument, "effective_at": visible[-1].period_end.isoformat(), "known_at": known.isoformat(),
            }
            for key, column, sign in _SHADOW_METRICS:
                row[column] = sign * float(metrics[key].value) if metrics[key].available else float("nan")
            latest = sm.latest_balance(visible, ["total_assets"])
            prior = sm.opening_balance(visible, latest.period_end, ["total_assets"]) if latest is not None else None
            row["asset_growth_neg"] = (
                -(latest.values["total_assets"] / prior.values["total_assets"] - 1.0)
                if prior is not None and prior.currency == latest.currency and prior.values["total_assets"] > 0
                else float("nan")
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=_SHADOW_COLUMNS)


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
    shadow_rows = _shadow_rows(resolved_root, prices)
    shadow_components = [name for name in _SHADOW_COMPONENTS if shadow_rows[name].notna().any()]

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
        if not shadow_components:
            sections["shadow_quality_value"] = {
                "status": "unavailable",
                "reason": "no quality or value challenger has an available value in the period store; not filled",
            }
        else:
            shadow_evidence = attach_fundamental_evidence(evidence, shadow_rows, shadow_components)
            for name in shadow_components:
                if name not in shadow_evidence:
                    shadow_evidence[name] = float("nan")
            # quality_v2: mean of the cross-sectional percentile ranks of the components available for that row
            shadow_evidence["quality_v2"] = shadow_evidence.groupby("known_at")[shadow_components].rank(pct=True).mean(axis=1)
            challengers = {name: RankerSpec(_SHADOW_VERSION, {}, name) for name in (*shadow_components, "quality_v2")}
            runs.append(("shadow_quality_value", replace(base_policy, rankers=challengers), shadow_evidence))
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
            if label == "shadow_quality_value":
                sections[label]["unavailable_challengers"] = [name for name in _SHADOW_COMPONENTS if name not in shadow_components]
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
