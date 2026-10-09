"""ETF economics read model for Instrument Detail (application; ADR-0002)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from etf_cockpit.data.etf_economics import calculate_etf_economics, load_etf_e1_fields, load_etf_reference_context
from etf_cockpit.data.fund_holdings import holdings_splits, select_holdings_as_of

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
    payload = report.as_dict()
    metadata = getattr(snapshot, "etf_metadata", None)
    if not isinstance(metadata, pd.DataFrame):
        metadata = load_etf_reference_context("etf_metadata")
    else:
        from etf_cockpit.data.etf_e1_fetch import decode_e1_reference_context

        metadata = decode_e1_reference_context(metadata)
    rows = metadata.to_dict("records")
    issuer_rows = [row for row in rows if row.get("source_authority") == "issuer_document"]
    public_rows = [row for row in rows if row.get("source_authority") == "public_page"]
    vendor_rows = [row for row in rows if "yfinance" in str(row.get("source", row.get("provider", ""))).casefold()]
    canonical = supplied_records.records if hasattr(supplied_records, "records") else supplied_records
    if isinstance(canonical, pd.DataFrame):
        canonical = canonical.to_dict("records")
    fields = load_etf_e1_fields(
        instrument_id, decision_time=decision_time,
        issuer_records=[*(canonical or ()), *issuer_rows], public_records=public_rows, vendor_records=vendor_rows,
    )
    if metadata.attrs.get("unavailable_reason"):
        for field in fields.values():
            if field["value"] is None:
                field["reason"] = metadata.attrs["unavailable_reason"]
    fields["tracking_difference"] = {
        "value": report.tracking_difference,
        "reason": ", ".join(report.missing_evidence) if report.tracking_difference is None else None,
        "source": f"{report.fund_source_id} / {report.benchmark_source_id}" if report.tracking_difference is not None else None,
        "as_of": report.matched_end,
        "known_at": max(filter(None, (report.fund_total_return_selected_known_at, report.benchmark_total_return_selected_known_at)), default=None),
        "window": f"{report.matched_start} to {report.matched_end}" if report.matched_start else None,
    }
    from etf_cockpit.application.overlap import load_direct_holdings

    evidence = getattr(snapshot, "etf_holdings", None)
    if not isinstance(evidence, pd.DataFrame):
        evidence = load_direct_holdings()
        identity_column = "instrument_id" if "instrument_id" in evidence else "etf_id" if "etf_id" in evidence else None
        instrument_rows = evidence.loc[evidence[identity_column].astype(str).eq(instrument_id)] if identity_column else pd.DataFrame()
        if instrument_rows.empty or instrument_rows.get("authority", pd.Series(dtype=str)).eq("manual_unverified").all():
            evidence = load_etf_reference_context("etf_holdings")
    selected = select_holdings_as_of(evidence, instrument_id, decision_time)
    splits = holdings_splits(selected)
    if evidence.attrs.get("unavailable_reason"):
        splits["reason"] = evidence.attrs["unavailable_reason"]
    for dimension in ("country", "sector"):
        name = f"{dimension}_split"
        labels = selected.get(dimension, pd.Series(dtype=str)).fillna("").astype(str).str.strip().str.casefold()
        classified = (~labels.isin({"", "unknown", "unknown/unmapped", "unclassified", "nan", "none"})).any()
        if splits[dimension] and (classified or fields[name]["value"] is None):
            fields[name] = {"value": splits[dimension], "as_of": splits["as_of"], "known_at": splits["known_at"], "source": ", ".join(sorted(set(selected.get("source_id", selected.get("source", pd.Series(dtype=str))).dropna().astype(str)))), "reason": None}
        elif fields[name]["value"] is not None:
            values = fields[name]["value"]
            weights = pd.to_numeric(pd.Series(values), errors="coerce")
            total = weights.sum()
            if weights.isna().any() or weights.lt(0).any() or not 0 < total <= 1.01:
                fields[name].update(value=None, reason=f"{dimension}_split_weights_not_usable")
            else:
                values = dict(values)
                if total < 1:
                    values["Other/unclassified"] = values.get("Other/unclassified", 0) + 1 - total
                fields[name]["value"] = values
    holding_rows = []
    if splits["reason"] is None:
        for row in selected.sort_values("weight", ascending=False).head(25).to_dict("records"):
            holding_rows.append({"name": row.get("security", row.get("holding_name")), "weight": float(row["weight"]), "country": row.get("country"), "sector": row.get("sector")})
    payload.update(e1=fields, holdings=holding_rows, holdings_count=splits["count"], holdings_reason=splits["reason"], holdings_as_of=splits["as_of"], disclosed_weight=splits.get("disclosed_weight"))
    ter = fields["ter"]["value"]
    policy = fields["distribution_policy"]["value"]
    payload["summary"] = (
        (f"The disclosed TER is {ter:.2%}. " if ter is not None else f"TER is unavailable ({fields['ter']['reason']}). ")
        + (f"The share class is {policy}. " if policy else f"Distribution policy is unavailable ({fields['distribution_policy']['reason']}). ")
        + (f"{len(selected)} disclosed holdings cover {splits.get('disclosed_weight', 0):.1%} of fund weight; the remainder is Other/unclassified." if holding_rows else f"Holdings are unavailable ({splits['reason']}).")
    )
    return payload


__all__ = ["build_etf_economics_panel"]
