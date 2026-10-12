"""ETF economics read model for Instrument Detail (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import pandas as pd

from etf_cockpit.data.etf_economics import calculate_etf_economics, load_etf_e1_fields, load_etf_reference_context
from etf_cockpit.data.fund_holdings import holdings_splits, select_holdings_as_of
from etf_cockpit.data.etf_cutoff import etf_decision_cutoff, snapshot_etf_cutoff

if TYPE_CHECKING:
    from etf_cockpit.application.snapshot_builder import CockpitSnapshot


def load_etf_holdings_evidence(snapshot: object, instrument_ids: list[str], decision_time: object) -> pd.DataFrame:
    """Reuse dated reference holdings when a fund has no usable direct evidence."""
    from etf_cockpit.application.overlap import load_direct_holdings

    supplied = getattr(snapshot, "etf_holdings", None)
    direct = supplied if isinstance(supplied, pd.DataFrame) else load_direct_holdings()
    reference = None
    selections = []
    for instrument_id in instrument_ids:
        selected = select_holdings_as_of(direct, instrument_id, decision_time)
        if not isinstance(supplied, pd.DataFrame) and (selected.empty or selected.get("authority", pd.Series("", index=selected.index)).eq("manual_unverified").all()):
            if reference is None:
                reference = load_etf_reference_context("etf_holdings")
            selected = select_holdings_as_of(reference, instrument_id, decision_time)
        selections.append(selected)
    if len(selections) == 1:
        return selections[0]
    # Per-fund alternatives remain in their source store; the cube consumes
    # only one acquisition per fund, with no cross-fund frame attributes.
    frames = []
    for selected in selections:
        frame = selected.copy()
        frame.attrs = {}
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fund_split_weights(snapshot: object, instrument_id: str, dimension: str) -> dict[str, float] | None:
    """The stored country/sector split of one fund ({label: fraction}), exactly what its Fund view shows.

    ``None`` when no dated split is stored: the caller must leave that weight unknown, never guess it.
    """

    try:
        panel = build_etf_economics_panel(snapshot, instrument_id)  # type: ignore[arg-type]
    except (KeyError, OSError, TypeError, ValueError, ArithmeticError):
        return None
    field = (panel.get("e1") or {}).get(f"{dimension}_split") or {}
    value = field.get("value") if isinstance(field, Mapping) else None
    if not isinstance(value, Mapping) or not value:
        return None
    try:
        return {str(label): float(weight) for label, weight in value.items()}
    except (TypeError, ValueError):
        return None


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
    decision_time = etf_decision_cutoff(as_of) if as_of is not None else snapshot_etf_cutoff(snapshot)
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
        include_traceability=True,
    )
    if metadata.attrs.get("unavailable_reason"):
        for field in fields.values():
            if field["value"] is None:
                field["reason"] = metadata.attrs["unavailable_reason"]
    tracking_source = (
        f"{report.fund_source_id} / {report.benchmark_source_id}"
        if report.tracking_difference is not None or report.tracking_error is not None
        else None
    )
    tracking_known_at = max(
        filter(None, (report.fund_total_return_selected_known_at, report.benchmark_total_return_selected_known_at)),
        default=None,
    )
    tracking_window = f"{report.matched_start} to {report.matched_end}" if report.matched_start else None
    tracking_method = "compounded matched canonical total-return growth"
    tracking_error_method = (
        "sample standard deviation of matched active daily returns, annualised by sqrt(252)"
    )
    tracking_freshness_status = (
        "not_assessed" if report.tracking_status == "available" else "unavailable"
    )
    tracking_freshness_reason = (
        "no tracking freshness limit is configured"
        if report.tracking_status == "available"
        else ", ".join(report.missing_evidence) or "matched_total_return"
    )
    fields["tracking_difference"] = {
        "value": report.tracking_difference,
        "status": "available" if report.tracking_difference is not None else "unavailable",
        "reason": ", ".join(report.missing_evidence) if report.tracking_difference is None else None,
        "source": tracking_source if report.tracking_difference is not None else None,
        "source_provenance": {
            "fund": report.fund_source_provenance,
            "benchmark": report.benchmark_source_provenance,
        },
        "as_of": report.matched_end,
        "effective_at": report.matched_end,
        "known_at": tracking_known_at,
        "window": tracking_window,
        "window_start": report.matched_start,
        "window_end": report.matched_end,
        "benchmark_id": report.benchmark_id,
        "benchmark_currency": report.benchmark_currency,
        "currency": report.currency,
        "frequency": report.sampling_frequency,
        "horizon_days": report.horizon_days,
        "sample_count": report.matched_rows,
        "coverage": report.coverage,
        "coverage_ratio": report.coverage_ratio,
        "calculation_method": tracking_method,
        "evidence_label": report.tracking_evidence_label,
        "freshness_status": tracking_freshness_status,
        "freshness_reason": tracking_freshness_reason,
    }
    tracking_error_reason = None
    if report.tracking_error is None:
        tracking_error_reason = (
            "fewer than two matched active daily returns"
            if report.tracking_status == "available"
            else ", ".join(report.missing_evidence) or "matched_total_return"
        )
    fields["tracking_error"] = {
        "value": report.tracking_error,
        "status": "available" if report.tracking_error is not None else "unavailable",
        "reason": tracking_error_reason,
        "source": tracking_source if report.tracking_error is not None else None,
        "source_provenance": {
            "fund": report.fund_source_provenance,
            "benchmark": report.benchmark_source_provenance,
        },
        "as_of": report.matched_end,
        "effective_at": report.matched_end,
        "known_at": tracking_known_at,
        "window": tracking_window,
        "window_start": report.matched_start,
        "window_end": report.matched_end,
        "benchmark_id": report.benchmark_id,
        "benchmark_currency": report.benchmark_currency,
        "currency": report.currency,
        "frequency": report.sampling_frequency,
        "horizon_days": report.horizon_days,
        "sample_count": report.matched_rows,
        "coverage": report.coverage,
        "coverage_ratio": report.coverage_ratio,
        "calculation_method": tracking_error_method,
        "unit": report.tracking_unit,
        "evidence_label": report.tracking_evidence_label,
        "freshness_status": tracking_freshness_status,
        "freshness_reason": tracking_freshness_reason,
    }
    selected = load_etf_holdings_evidence(snapshot, [instrument_id], decision_time)
    splits = holdings_splits(selected)
    if selected.attrs.get("unavailable_reason"):
        splits["reason"] = selected.attrs["unavailable_reason"]
    for dimension in ("country", "sector"):
        name = f"{dimension}_split"
        labels = selected.get(dimension, pd.Series(dtype=str)).fillna("").astype(str).str.strip().str.casefold()
        classified = (~labels.isin({"", "unknown", "unknown/unmapped", "unclassified", "nan", "none"})).any()
        if splits[dimension] and (classified or fields[name]["value"] is None):
            fields[name] = {"value": splits[dimension], "as_of": splits["as_of"], "known_at": splits["known_at"], "source": ", ".join(sorted(set(selected.get("source_id", selected.get("source", pd.Series(dtype=str))).dropna().astype(str)))), "reason": None}
    holding_rows = []
    if splits["reason"] is None:
        for row in selected.sort_values("weight", ascending=False).head(25).to_dict("records"):
            holding_rows.append({"name": row.get("security", row.get("holding_name")), "weight": float(row["weight"]), "country": row.get("country"), "sector": row.get("sector")})
    payload.update(e1=fields, holdings=holding_rows, holdings_count=splits["count"], holdings_reason=splits["reason"], holdings_as_of=splits["as_of"], disclosed_weight=splits.get("disclosed_weight"))
    class_metrics = report.share_class_metrics.get(instrument_id, {})
    fund_metrics = report.fund_metrics
    class_identity_matches = bool(
        class_metrics
        and class_metrics.get("scope") == "share_class"
        and class_metrics.get("share_class_id") == instrument_id
        and class_metrics.get("instrument_id") == instrument_id
        and class_metrics.get("currency") is not None
        and class_metrics.get("currency") == fund_metrics.get("currency")
        and class_metrics.get("benchmark_id") is not None
        and class_metrics.get("benchmark_id") == fund_metrics.get("benchmark_id")
        and class_metrics.get("benchmark_currency") is not None
        and class_metrics.get("benchmark_currency") == fund_metrics.get("benchmark_currency")
    )
    identity_reasons = []
    if not class_metrics:
        identity_reasons.append("exact_share_class_evidence_unavailable")
    elif not class_identity_matches:
        identity_reasons.append("share_class_currency_or_benchmark_mapping_unavailable")
    identity_audit = {
        "status": "available" if class_identity_matches else "unavailable",
        "instrument_id": instrument_id,
        "fund_scope_instrument_id": fund_metrics.get("instrument_id"),
        "share_class_id": class_metrics.get("share_class_id"),
        "fund_currency": fund_metrics.get("currency"),
        "share_class_currency": class_metrics.get("currency"),
        "fund_benchmark_id": fund_metrics.get("benchmark_id"),
        "share_class_benchmark_id": class_metrics.get("benchmark_id"),
        "fund_benchmark_currency": fund_metrics.get("benchmark_currency"),
        "share_class_benchmark_currency": class_metrics.get("benchmark_currency"),
        "listing_identity_status": "unavailable",
        "listing_identity_reason": "the economics evidence has no separate listing identifier or mapping",
        "reason": ", ".join(identity_reasons) if identity_reasons else None,
    }
    payload["identity_audit"] = identity_audit
    ter = fields["ter"]["value"]
    policy = fields["distribution_policy"]["value"]
    ter_field = fields["ter"]
    tracking_field = fields["tracking_difference"]
    tracking_error_field = fields["tracking_error"]
    coverage = tracking_field["coverage_ratio"]
    coverage_text = f"{coverage:.0%}" if coverage is not None else "unavailable"
    tracking_summary = (
        f"Tracking evidence: {tracking_field['evidence_label'] or 'unavailable'}; "
        f"source/provider {tracking_field['source'] or 'unavailable'}; "
        f"provenance fund {tracking_field['source_provenance']['fund'] or 'unavailable'}; "
        f"benchmark {tracking_field['source_provenance']['benchmark'] or 'unavailable'}; "
        f"benchmark {tracking_field['benchmark_id'] or 'unavailable'} "
        f"({tracking_field['benchmark_currency'] or 'currency unavailable'}); "
        f"currency {tracking_field['currency'] or 'unavailable'}; "
        f"period {tracking_field['window'] or 'unavailable'}; "
        f"frequency {tracking_field['frequency'] or 'unavailable'}; "
        f"sample count {tracking_field['sample_count']}; coverage {coverage_text}; "
        f"method {tracking_field['calculation_method']}; "
        f"effective_at {tracking_field['effective_at'] or 'unavailable'}; "
        f"known_at {tracking_field['known_at'] or 'unavailable'}; "
        f"freshness {tracking_field['freshness_status']} ({tracking_field['freshness_reason']})."
    )
    tracking_error_summary = (
        f"Tracking error {tracking_error_field['value']:.2%} "
        if tracking_error_field["value"] is not None
        else "Tracking error unavailable "
    )
    tracking_error_summary += (
        f"{tracking_error_field['unit']}; method {tracking_error_field['calculation_method']}; "
        f"status {tracking_error_field['status']} "
        f"({tracking_error_field['reason'] or 'available'})."
    )
    ter_summary = (
        f"TER evidence: {ter_field.get('value_origin') or 'unavailable'}; "
        f"source/provider {ter_field.get('source') or 'unavailable'}; "
        f"provenance {ter_field.get('source_provenance') or 'unavailable'}; "
        f"scope {ter_field.get('scope') or 'instrument scope unverified'}; "
        f"share_class_id {ter_field.get('share_class_id') or 'unavailable'}; "
        f"effective_at {ter_field.get('effective_at') or 'unavailable'}; "
        f"known_at {ter_field.get('known_at') or 'unavailable'}; "
        f"freshness {ter_field.get('freshness_status', 'unavailable')} "
        f"({ter_field.get('freshness_reason') or 'unavailable'})."
    )
    exact_class_record = bool(
        class_metrics
        and class_metrics.get("scope") == "share_class"
        and class_metrics.get("share_class_id") == instrument_id
        and class_metrics.get("instrument_id") == instrument_id
    )
    ocf_value = class_metrics.get("ocf") if exact_class_record else None
    ocf_display = f"{ocf_value:.2%}" if ocf_value is not None else "unavailable"
    ocf_summary = (
        f"OCF {ocf_display} (share class {instrument_id}; "
        f"unit {class_metrics.get('fee_unit') or 'unavailable'}; "
        f"source/provider {class_metrics.get('source_id') or 'unavailable'}; "
        f"provenance {class_metrics.get('source_provenance') or 'unavailable'}; "
        f"effective_at {class_metrics.get('effective_at') or 'unavailable'}; "
        f"known_at {class_metrics.get('known_at') or 'unavailable'})."
        if ocf_value is not None
        else f"OCF unavailable ({class_metrics.get('share_class_id') or 'exact share-class evidence unavailable'})."
    )
    aum_value = fund_metrics.get("aum")
    flow_value = fund_metrics.get("flows")
    aum_flow_summary = (
        f"Fund-scope AUM {aum_value if aum_value is not None else 'unavailable'} "
        f"{fund_metrics.get('aum_unit') or ''}; source/provider {fund_metrics.get('source_id') or 'unavailable'}; "
        f"provenance {fund_metrics.get('source_provenance') or 'unavailable'}; "
        f"effective_at {fund_metrics.get('aum_as_of') or 'unavailable'}; "
        f"known_at {fund_metrics.get('evidence_known_at') or 'unavailable'}; "
        f"freshness {fund_metrics.get('aum_status') or 'unavailable'} "
        f"({fund_metrics.get('aum_warning') or 'no AUM freshness warning'}). "
        f"Fund-scope flows {flow_value if flow_value is not None else 'unavailable'} "
        f"{fund_metrics.get('flows_unit') or ''} over "
        f"{fund_metrics.get('flow_period_days') or 'unavailable'} days; "
        f"effective_at {fund_metrics.get('flows_as_of') or 'unavailable'}; "
        f"known_at {fund_metrics.get('evidence_known_at') or 'unavailable'}; "
        "flow freshness not assessed (no flow freshness limit is configured)."
    )
    closure = report.closure_risk_proxy
    factor_coverage = closure.get("factor_coverage", {})
    closure_factors = closure.get("factors", {})
    policy_provenance = closure.get("policy_provenance", {})
    policy_interval = closure.get("policy_interval", {})
    factor_values = ", ".join(
        f"{name}={value}" for name, value in closure_factors.items()
    ) or "unavailable"
    closure_summary = (
        f"Economic-quality/closure proxy: status {closure.get('status', 'unavailable')}; "
        f"label {closure.get('label', 'unavailable')}; method {closure.get('method', 'unavailable')}; "
        f"factors {factor_values}; policy source/provider {policy_provenance.get('source_id', 'unavailable')}; "
        f"policy provenance {policy_provenance.get('source_provenance', 'unavailable')}; "
        f"policy effective_from {policy_interval.get('effective_from', 'unavailable')}; "
        f"policy effective_until {policy_interval.get('effective_until', 'unavailable')}; "
        f"policy known_at {policy_provenance.get('known_at', 'unavailable')}; "
        f"score {closure.get('score') if closure.get('score') is not None else 'unavailable'}; "
        f"factor coverage {factor_coverage.get('available', 0)}/{factor_coverage.get('total', 0)}; "
        f"missing factors {', '.join(closure.get('missing_factors', ())) or 'none reported'}; "
        f"reason {closure.get('reason', 'unavailable')}."
    )
    identity_summary = (
        f"Identity audit: {identity_audit['status']}; instrument_id {instrument_id}; "
        f"share_class_id {identity_audit['share_class_id'] or 'unavailable'}; "
        f"fund benchmark/currency {identity_audit['fund_benchmark_id'] or 'unavailable'}/"
        f"{identity_audit['fund_currency'] or 'unavailable'}; "
        f"class benchmark/currency {identity_audit['share_class_benchmark_id'] or 'unavailable'}/"
        f"{identity_audit['share_class_currency'] or 'unavailable'}; "
        f"listing identity {identity_audit['listing_identity_status']} "
        f"({identity_audit['listing_identity_reason']})."
    )
    payload["summary"] = (
        (f"The disclosed TER is {ter:.2%}. " if ter is not None else f"TER is unavailable ({fields['ter']['reason']}). ")
        + (f"The share class is {policy}. " if policy else f"Distribution policy is unavailable ({fields['distribution_policy']['reason']}). ")
        + (f"{len(selected)} disclosed holdings cover {splits.get('disclosed_weight', 0):.1%} of fund weight; the remainder is Other/unclassified." if holding_rows else f"Holdings are unavailable ({splits['reason']}).")
        + " " + ter_summary + " " + ocf_summary + " " + tracking_summary
        + " " + tracking_error_summary
        + " " + aum_flow_summary + " " + closure_summary
        + " " + identity_summary
    )
    return payload


__all__ = ["build_etf_economics_panel"]
