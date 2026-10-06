"""ETF economics read model for Instrument Detail (application; ADR-0002)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from etf_cockpit.data.etf_economics import calculate_etf_economics

if TYPE_CHECKING:
    from etf_cockpit.application.snapshot_builder import CockpitSnapshot


def build_etf_economics_panel(
    snapshot: CockpitSnapshot,
    instrument_id: str,
    *,
    records: object = None,
    fund_total_return: object = None,
    benchmark_total_return: object = None,
    as_of: object = None,
    horizon_days: int = 252,
    benchmark_id: str | None = None,
    currency: str | None = None,
    closure_policy: object = None,
) -> dict[str, Any]:
    """Return the local ETF economics read model without provider access."""

    supplied_records = records
    if supplied_records is None:
        for name in ("etf_economics", "etf_economics_records", "economics_records"):
            candidate = getattr(snapshot, name, None)
            if candidate is not None:
                supplied_records = candidate
                break
    supplied_fund = fund_total_return
    if supplied_fund is None:
        for name in ("etf_fund_total_return", "fund_total_return"):
            candidate = getattr(snapshot, name, None)
            if candidate is not None:
                supplied_fund = candidate
                break
    supplied_benchmark = benchmark_total_return
    if supplied_benchmark is None:
        for name in ("etf_benchmark_total_return", "benchmark_total_return"):
            candidate = getattr(snapshot, name, None)
            if candidate is not None:
                supplied_benchmark = candidate
                break
    supplied_policy = closure_policy
    if supplied_policy is None:
        supplied_policy = getattr(snapshot, "etf_closure_policy", None)
    decision_time = as_of if as_of is not None else getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    report = calculate_etf_economics(
        instrument_id,
        supplied_records if supplied_records is not None else (),
        fund_total_return=supplied_fund,
        benchmark_total_return=supplied_benchmark,
        as_of=decision_time,
        horizon_days=horizon_days,
        benchmark_id=benchmark_id,
        currency=currency,
        closure_policy=supplied_policy,
    )
    return report.as_dict()


__all__ = ["build_etf_economics_panel"]
