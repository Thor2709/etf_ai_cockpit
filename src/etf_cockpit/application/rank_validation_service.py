"""Read-only application service for point-in-time rank validation.

Open defaults: validate 1, 3, and 5 year windows from stored adjusted prices;
optional cost, cash, and fundamental evidence stays unavailable when absent.
Independent windows (including replay) use at most three worker threads;
results retain the requested window order and workers never persist evidence.
A third, shadow run ranks quality and value challengers built from the stored
period store; it never shares a policy with the promotion rankers.
With benchmark VWCE, decision dates before 2019-07-29 use the VWRL.AS-spliced
comparator (OD-2 b) when the stored proxy file matches its manifest hash; all
other dates, and every date without a valid proxy, use the stored VWCE rows.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd
import pyarrow

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
from etf_cockpit.data.provenance import sha256_dataframe
from etf_cockpit.portfolio.benchmark_reference import (
    VWCE_PROXY_FILE,
    VWCE_PROXY_SYMBOL,
    VWCE_SPLICE_DATE,
    vwce_benchmark_series,
)


_PRICE_RELATIVE = Path("data") / "validated" / "prices" / "prices_daily.parquet"
_DEFAULT_SCOPE = "listing:euronext_oslo:all"
_VWCE_ID = "VWCE"  # the universe id (configs/universe.yaml)
_VWCE_PROXY_RELATIVE = Path("data") / "reference" / f"{VWCE_PROXY_FILE}.parquet"
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


def _vwce_comparator_prices(root: Path, prices: pd.DataFrame) -> tuple[pd.DataFrame | None, str | None]:
    """Prices whose VWCE rows are the VWRL.AS-spliced benchmark series, else ``(None, reason)``: stored rows only.

    Proxy rows on a day that is no stored session are dropped (not filled): the comparator keeps the replay sessions.
    """

    parquet = root / _VWCE_PROXY_RELATIVE
    try:
        proxy = pd.read_parquet(parquet)
        manifest = json.loads(parquet.with_suffix(".json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "proxy_file_missing"
    except (OSError, ValueError, pyarrow.ArrowException):
        return None, "proxy_file_unreadable"
    if not {"date", "adjusted_close", "known_at"} <= set(proxy.columns):
        return None, "proxy_file_unreadable"
    if not isinstance(manifest, dict) or manifest.get("source_hash") != sha256_dataframe(proxy):
        return None, "proxy_hash_mismatch"
    is_vwce = prices["instrument_id"].astype(str).eq(_VWCE_ID)
    series = vwce_benchmark_series(prices.loc[is_vwce], proxy)
    if series is None:
        return None, "splice_unavailable"
    sessions = set(pd.to_datetime(prices["date"].unique(), errors="coerce").normalize())
    is_proxy = series["benchmark_basis"].eq("proxy")
    series = series.loc[~is_proxy | pd.to_datetime(series["date"].where(is_proxy)).dt.normalize().isin(sessions)]
    return pd.concat([prices.loc[~is_vwce], series.assign(instrument_id=_VWCE_ID)], ignore_index=True), None


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
    traded = pd.DataFrame()
    if "close" in prices:
        dates = pd.to_datetime(prices["date"], errors="coerce")
        if getattr(dates.dt, "tz", None) is not None:
            dates = dates.dt.tz_localize(None)  # session dates are calendar days; market_inputs compares them tz-naive
        traded = prices.assign(date=dates.dt.normalize()).dropna(subset=["date"])
        # a bar is usable once known: its stored stamp, else the end of its session day (the rule market_inputs applies)
        traded["_known"] = (
            pd.to_datetime(traded["known_at"], errors="coerce", utc=True) if "known_at" in traded
            else (traded["date"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
        )
    rows: list[dict[str, object]] = []
    for instrument in sorted(frame["instrument_id"].astype(str).unique()):
        periods = store.periods_for(instrument, frame, chain)
        history = traded.loc[traded["instrument_id"].astype(str) == instrument].sort_values("date") if not traded.empty else traded
        for known in sorted({period.known_at for period in periods}):
            visible = sm.known_periods(periods, known)
            if not visible:
                continue
            bars = history.loc[history["_known"] <= known].drop(columns="_known") if not history.empty else history
            market = market_inputs(bars, store.latest_snapshot(instrument, snapshots, known), visible[-1].currency, known, fx, config)
            metrics = build_stock_evidence(instrument, periods, known, market, None, config).metrics
            row: dict[str, object] = {
                "instrument_id": instrument, "effective_at": visible[-1].period_end.isoformat(), "known_at": known.isoformat(),
            }
            for key, column, sign in _SHADOW_METRICS:
                metric = metrics.get(key)
                row[column] = sign * float(metric.value) if metric is not None and metric.available else float("nan")
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
    spliced = None
    if benchmark_id == _VWCE_ID:
        spliced, proxy_reason = _vwce_comparator_prices(resolved_root, prices)
        report["benchmark_proxy"] = {
            "status": "unavailable" if spliced is None else "used", "reason": proxy_reason,
            "proxy_source_id": VWCE_PROXY_SYMBOL,
        }

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
        if spliced is not None:  # only dates before the splice use the spliced series: their entry row is a proxy row
            splice = VWCE_SPLICE_DATE.isoformat()
            proxied = forward_comparator_frame(
                spliced, benchmark_id, [text for text in times if text[:10] < splice], base_policy.holding_period_sessions
            )
            parts = [frame for frame in (proxied, benchmark.loc[benchmark["decision_date"].ge(splice)]) if not frame.empty]
            benchmark = pd.concat(parts, ignore_index=True) if parts else proxied
            window["benchmark_proxy"] = {"proxy_source_id": VWCE_PROXY_SYMBOL, "proxy_decision_dates": len(proxied)}
        sections: dict[str, object] = {}

        def replay_section(label: str, policy, run_evidence: pd.DataFrame) -> dict[str, object]:
            replay, validation = run_stored_rank_validation(
                run_evidence, memberships, prices, costs, benchmark, cash, times, policy=policy
            )
            section = rank_validation_report_dict(
                replay, validation, label=label,
                requested_decision_times=times, excluded_decision_times=excluded,
            )
            conflicts = run_evidence.attrs.get("fundamental_conflicts")
            if conflicts:
                section["fundamental_conflicts"] = conflicts
            return section

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
            # one replay per challenger: a challenger available only late must not discard the cut-offs of the others
            per_challenger = {
                name: replay_section(
                    f"shadow_quality_value_{name}_{window_years}y",
                    replace(base_policy, rankers={name: RankerSpec(_SHADOW_VERSION, {}, name)}), shadow_evidence,
                )
                for name in (*shadow_components, "quality_v2")
            }
            first = next(iter(per_challenger.values()))
            sections["shadow_quality_value"] = {
                "label": f"shadow_quality_value_{window_years}y",
                "status": "evaluated",  # each challenger carries its own validation status under "challengers"
                "challengers": per_challenger,
                "development": {name: item["development"][name] for name, item in per_challenger.items() if name in item["development"]},
                "holdout": {name: item["holdout"][name] for name, item in per_challenger.items() if name in item["holdout"]},
                "holdout_decision_times": first["holdout_decision_times"],
                "unavailable_challengers": [name for name in _SHADOW_COMPONENTS if name not in shadow_components],
                "promotion_applied": False, "rank_authority": False, "execution_allowed": False,
            }
        for label, policy, run_evidence in runs:
            sections[label] = replay_section(f"{label}_{window_years}y", policy, run_evidence)
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
