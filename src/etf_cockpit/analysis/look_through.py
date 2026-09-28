"""Pure, point-in-time ETF holdings look-through calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from numbers import Real
from typing import Mapping

import pandas as pd

from etf_cockpit.data.event_calendar import normalise_event_decision_time
from etf_cockpit.data.fund_holdings import normalise_holdings
from etf_cockpit.features.overlap import (
    _choose_source_group,
    _normalise_snapshot,
    _source_groups,
    _typed_identity,
)


_DEFAULT_MAX_HOLDINGS_AGE_DAYS = 90
_RECONCILIATION_TOLERANCE = 1e-9


@dataclass(frozen=True)
class LookThroughSummary:
    instrument_id: str
    status: str
    holdings_date: str | None
    analysis_date: str
    decision_time: str | None
    source: str | None
    source_id: str | None
    source_ids: tuple[str, ...]
    revision_lineage: tuple[str, ...]
    completeness: str
    freshness: str
    provider_coverage: float
    provider_coverage_weight: float
    reported_total_weight: float
    mapped_weight: float
    cash_weight: float
    derivative_weight: float
    unresolved_weight: float
    fund_weight: float
    reconciliation_delta: float
    total_weight_status: str
    concentration: Mapping[str, object]
    exposures: Mapping[str, object]
    fundamental_data_coverage: Mapping[str, Mapping[str, float]]
    calculated_metrics: Mapping[str, Mapping[str, object]]
    provider_reported_metrics: Mapping[str, Mapping[str, object]]
    lineage: Mapping[str, object]
    aggregation_conventions: tuple[str, ...]
    limitations: tuple[str, ...]
    execution_allowed: bool = False


def calculate_look_through(
    holdings: pd.DataFrame,
    *,
    instrument_id: str,
    decision_time: str | datetime,
    analysis_date: str | date | datetime | None = None,
    holdings_date: str | date | datetime | None = None,
    source: str | None = None,
    constituent_fundamentals: pd.DataFrame | None = None,
    identity_map: Mapping[str, str] | None = None,
    provider_metrics: Mapping[str, object] | None = None,
    max_holdings_age_days: int = _DEFAULT_MAX_HOLDINGS_AGE_DAYS,
) -> LookThroughSummary:
    """Calculate direct holdings exposure and covered constituent metrics.

    Holdings are normalised through the canonical holdings normaliser, then
    resolved with the same typed identifier mapper used by ETF overlap. The
    optional ``identity_map`` maps those typed identifiers to canonical issuer
    or instrument keys when the caller has an identity-master resolution.
    """
    cutoff = normalise_event_decision_time(decision_time)
    analysis = _as_date(analysis_date) if analysis_date is not None else (cutoff.date() if cutoff else None)
    provider = _provider_metrics(provider_metrics)
    conventions = _AGGREGATION_CONVENTIONS
    if cutoff is None or analysis is None or analysis > cutoff.date():
        return _empty_summary(
            instrument_id,
            analysis.isoformat() if analysis else "unavailable",
            cutoff.isoformat() if cutoff else None,
            "unavailable",
            ("A timezone-aware decision time and an analysis date no later than it are required.",),
            conventions,
            provider,
        )
    if isinstance(max_holdings_age_days, bool) or not isinstance(max_holdings_age_days, int) or max_holdings_age_days < 0:
        return _empty_summary(
            instrument_id,
            analysis.isoformat(),
            cutoff.isoformat(),
            "unavailable",
            ("Maximum holdings age must be a non-negative integer.",),
            conventions,
            provider,
        )
    if not isinstance(holdings, pd.DataFrame) or not holdings.columns.is_unique or holdings.empty:
        return _empty_summary(
            instrument_id,
            analysis.isoformat(),
            cutoff.isoformat(),
            "unavailable",
            ("A local holdings snapshot is unavailable or malformed.",),
            conventions,
            provider,
        )

    selected, selected_date, selected_source, selection_warning, selected_known_at = _select_holdings(
        holdings, instrument_id, cutoff, analysis, holdings_date, source
    )
    if selected.empty or selected_date is None:
        return _empty_summary(
            instrument_id,
            analysis.isoformat(),
            cutoff.isoformat(),
            "unavailable",
            (selection_warning or "No holdings snapshot was available by the decision time.",),
            conventions,
            provider,
        )

    normaliser_input = selected.copy()
    if "instrument_type" not in normaliser_input.columns and "exposure_type" in normaliser_input.columns:
        normaliser_input["instrument_type"] = normaliser_input["exposure_type"]
    typed_identity_counts: dict[str, int] = {}
    for _, row in normaliser_input.iterrows():
        identity = _typed_identity(row)
        if identity is not None:
            typed_identity_counts[identity] = typed_identity_counts.get(identity, 0) + 1
    has_duplicate_typed_identities = any(count > 1 for count in typed_identity_counts.values())
    normalized = normalise_holdings(
        normaliser_input,
        instrument_id,
        selected_date,
        selected_source or "unknown",
        today=cutoff.date(),
        stale_after_days=max_holdings_age_days,
    )
    lineage_source_ids = _unique_text(selected.get("source_id"))
    revisions = _unique_text(selected.get("revision"))
    limitations: list[str] = []
    if has_duplicate_typed_identities:
        limitations.append("Repeated typed holding identities were reported; duplicate rows are merged into one economic exposure after exact duplicate rows are removed.")
    if selection_warning:
        limitations.append(selection_warning)
    if selected_known_at is None:
        limitations.append("Holdings known-at time is unavailable; stored source lineage is retained without a stronger PIT claim.")
    if normalized.warnings:
        limitations.extend(normalized.warnings)
    if normalized.completeness == "invalid":
        reported = _safe_reported_total(selected)
        return _summary_from_unusable(
            instrument_id=instrument_id,
            status="invalid",
            holdings_date=selected_date.isoformat(),
            analysis_date=analysis.isoformat(),
            decision_time=cutoff.isoformat(),
            source=selected_source,
            source_id=normalized.source_id or None,
            source_ids=lineage_source_ids,
            revisions=revisions,
            completeness=normalized.completeness,
            freshness=normalized.freshness,
            reported_total=reported,
            limitations=limitations,
            conventions=conventions,
            provider=provider,
            lineage={"known_at": selected_known_at, "normaliser_source_id": normalized.source_id},
        )

    reported_total = math.fsum(float(value) for value in normalized.frame["weight"])
    overlap_frame = normalized.frame.copy()
    if "exposure_type" not in overlap_frame.columns:
        overlap_frame["exposure_type"] = overlap_frame.get("instrument_type", pd.Series("security", index=overlap_frame.index))
    coverage = _normalise_snapshot(
        instrument_id,
        selected_date.isoformat(),
        normalized.source_id,
        overlap_frame,
        selection_warning,
        cutoff.date(),
        known_at=selected_known_at,
    )
    if coverage.status == "missing" and coverage.warnings:
        limitations.extend(coverage.warnings)

    # The overlap mapper has already merged exact duplicate identifiers. Use
    # its typed identities and direct holdings as the source for all buckets.
    cash_weight = math.fsum(item.weight for item in coverage.holdings if item.exposure_type == "cash")
    derivative_weight = math.fsum(item.weight for item in coverage.holdings if item.exposure_type == "derivative")
    fund_weight = math.fsum(item.weight for item in coverage.holdings if item.exposure_type == "fund")
    mapped_items = [item for item in coverage.holdings if item.exposure_type == "security"]
    mapped_weight = math.fsum(item.weight for item in mapped_items)
    unresolved_rows = overlap_frame.loc[overlap_frame.apply(lambda row: _typed_identity(row) is None, axis=1)]
    unresolved_weight = math.fsum(float(value) for value in unresolved_rows["weight"])
    unresolved_weight += fund_weight
    unresolved_weight += math.fsum(item.weight for item in coverage.holdings if item.exposure_type == "unknown")

    # Identity-master results, when supplied, take precedence. Explicit issuer
    # claims still provide the existing economic grouping for listing variants.
    economic: dict[str, dict[str, object]] = {}
    for item in mapped_items:
        canonical = _canonical_key(item.identity, item.issuer, item.company, identity_map)
        bucket = economic.setdefault(
            canonical,
            {"weight": 0.0, "identities": [], "display_names": [], "sectors": [], "countries": [], "currencies": []},
        )
        bucket["weight"] = float(bucket["weight"]) + item.weight
        bucket["identities"].append(item.identity)
        bucket["display_names"].append(item.display_name)
        for dimension in ("sectors", "countries", "currencies"):
            field = {"sectors": "sector", "countries": "country", "currencies": "currency"}[dimension]
            if getattr(item, field):
                bucket[dimension].append(getattr(item, field))
        if not item.issuer and not item.company and not _mapped_identity(identity_map, item.identity):
            limitations.append(f"Issuer-level grouping is unavailable for {item.identity}; other listings may remain separate.")

    economic_rows = []
    for key, values in sorted(economic.items()):
        economic_rows.append(
            {
                "identity": key,
                "display_name": min(values["display_names"]),
                "weight": round(float(values["weight"]), 12),
                "listing_identities": tuple(sorted(set(values["identities"]))),
                "sector": _single_value(values["sectors"]),
                "country": _single_value(values["countries"]),
                "currency": _single_value(values["currencies"]),
            }
        )
    economic_rows.sort(key=lambda row: (-row["weight"], row["identity"]))
    concentration = _concentration(economic_rows, mapped_weight)
    exposures = _exposures(economic_rows, coverage.holdings)

    metrics, metric_coverage, metric_limitations = _aggregate_fundamentals(
        economic_rows,
        mapped_items,
        constituent_fundamentals,
        identity_map or {},
        cutoff,
        analysis,
    )
    limitations.extend(metric_limitations)

    delta = math.fsum((mapped_weight, cash_weight, derivative_weight, unresolved_weight)) - reported_total
    if abs(delta) > 1e-9:
        # Preserve conservation without manufacturing a resolved exposure.
        unresolved_weight += reported_total - math.fsum((mapped_weight, cash_weight, derivative_weight, unresolved_weight))
        delta = math.fsum((mapped_weight, cash_weight, derivative_weight, unresolved_weight)) - reported_total
        limitations.append("Unclassified residual weight is retained in unresolved exposure to conserve the provider total.")
    total_weight_status = _weight_total_status(reported_total)
    if total_weight_status == "under_100":
        limitations.append("Reported holdings total is below 100%; disclosed holdings coverage is partial.")
    elif total_weight_status == "over_100":
        limitations.append("Reported holdings total is above 100%; weights are shown as reported and are not rescaled.")
    if normalized.freshness == "stale":
        limitations.append(f"Holdings are older than the configured maximum age of {max_holdings_age_days} days at decision time.")
    if fund_weight > 0:
        limitations.append("Fund-of-funds exposure is shown in unresolved weight; recursive fund look-through is unavailable.")
    if any(item.exposure_type == "derivative" for item in coverage.holdings):
        limitations.append("Derivative weights are kept separate; underlying exposure is not inferred without explicit evidence.")

    fundamentals_partial = mapped_weight > 0 and any(
        metric_coverage[name]["covered_weight"] < mapped_weight - 1e-9 for name in ("pe_ratio", "roic")
    )
    status = (
        "stale"
        if normalized.freshness == "stale"
        else "partial"
        if normalized.completeness != "full" or unresolved_weight > _RECONCILIATION_TOLERANCE
        or fundamentals_partial
        or total_weight_status == "under_100"
        or "Holdings rows not known" in (selection_warning or "")
        else "available"
    )
    if total_weight_status == "over_100":
        status = "overreported"
    return LookThroughSummary(
        instrument_id=str(instrument_id),
        status=status,
        holdings_date=selected_date.isoformat(),
        analysis_date=analysis.isoformat(),
        decision_time=cutoff.isoformat(),
        source=selected_source,
        source_id=normalized.source_id,
        source_ids=lineage_source_ids,
        revision_lineage=revisions,
        completeness=normalized.completeness,
        freshness=normalized.freshness,
        provider_coverage=min(1.0, max(0.0, reported_total)),
        provider_coverage_weight=round(reported_total, 12),
        reported_total_weight=round(reported_total, 12),
        mapped_weight=round(mapped_weight, 12),
        cash_weight=round(cash_weight, 12),
        derivative_weight=round(derivative_weight, 12),
        unresolved_weight=round(unresolved_weight, 12),
        fund_weight=round(fund_weight, 12),
        reconciliation_delta=round(delta, 12),
        total_weight_status=total_weight_status,
        concentration=concentration,
        exposures=exposures,
        fundamental_data_coverage=metric_coverage,
        calculated_metrics=metrics,
        provider_reported_metrics=provider,
        lineage={
            "known_at": selected_known_at,
            "normaliser_source_id": normalized.source_id,
            "source_ids": lineage_source_ids,
            "revisions": revisions,
            "authority": normalized.authority,
            "confidence": normalized.confidence,
        },
        aggregation_conventions=conventions,
        limitations=tuple(dict.fromkeys(limitations)),
    )


_AGGREGATION_CONVENTIONS = (
    "Holdings are normalised with data.fund_holdings.normalise_holdings; exact duplicate rows are removed by that contract.",
    "Typed ISIN, namespace-qualified identifier, and explicit cash identities reuse features.overlap identity mapping.",
    "Economic concentration merges typed listings sharing an explicit issuer/company key or a supplied identity-map key.",
    "Mapped, cash, derivative, and unresolved weights use reported portfolio weights; reconciliation tolerance is 1e-9 and no category is renormalised.",
    "Any total differing from 100% by more than 1e-9 is explicitly flagged, even inside the holdings normaliser's acceptance band.",
    "Any total differing from 100% by more than 1e-9 is explicitly flagged, even inside the holdings normaliser's acceptance band.",
    "Funds are included in unresolved weight and separately disclosed as fund weight; recursive look-through is not calculated.",
    "Top holding shares are gross portfolio weights; HHI normalises mapped operating-company economic weights to mapped weight, and effective holdings = 1 / HHI.",
    "Look-through P/E is covered weight divided by weighted earnings yield, where each constituent yield is 1 / P/E; negative P/E contributes negative earnings yield, zero P/E is excluded, and nonpositive aggregate yield has no P/E result.",
    "ROIC is an arithmetic weight-average over mapped constituents with finite, point-in-time ROIC evidence only.",
    "Fundamental coverage is reported per metric as absolute covered weight and covered weight / mapped operating-company weight.",
    "Facts with an available-at/known-at after decision time or an as-of date after analysis date are excluded.",
    "Provider headline metrics remain provider-reported and are never used as calculated constituent results.",
)


def _select_holdings(
    holdings: pd.DataFrame,
    instrument_id: str,
    cutoff: datetime,
    analysis: date,
    holdings_date: str | date | datetime | None,
    source: str | None,
) -> tuple[pd.DataFrame, date | None, str | None, str | None, str | None]:
    frame = holdings.copy()
    if "instrument_id" in frame.columns:
        frame = frame.loc[frame["instrument_id"].map(lambda value: isinstance(value, str) and value == instrument_id)].copy()
    if frame.empty:
        return frame, None, source, None, None
    date_column = next((name for name in ("as_of", "as_of_date") if name in frame.columns), None)
    requested_date = _as_date(holdings_date) if holdings_date is not None else None
    if requested_date is not None:
        chosen_date = requested_date
        if date_column is not None:
            frame = frame.loc[frame[date_column].map(_as_date).eq(chosen_date)].copy()
    elif date_column is not None:
        parsed_dates = frame[date_column].map(_as_date)
        eligible = parsed_dates.map(lambda value: value is not None and value <= analysis)
        frame = frame.loc[eligible].copy()
        if frame.empty:
            return frame, None, source, "No holdings snapshot dated on or before the analysis date exists.", None
        chosen_date = max(value for value in frame[date_column].map(_as_date) if value is not None)
        frame = frame.loc[frame[date_column].map(_as_date).eq(chosen_date)].copy()
    else:
        return frame.iloc[0:0], None, source, "The holdings snapshot has no as-of date.", None
    if chosen_date is None or chosen_date > analysis:
        return frame.iloc[0:0], chosen_date, source, "The holdings date is after the analysis date.", None

    known_column = next((name for name in ("known_at", "available_at") if name in frame.columns), None)
    known_at = None
    warning = None
    if known_column is not None:
        parsed_known = frame[known_column].map(normalise_event_decision_time)
        visible = parsed_known.map(lambda value: value is not None and value <= cutoff)
        if not visible.all():
            frame = frame.loc[visible].copy()
            parsed_known = parsed_known.loc[visible]
            warning = "Holdings rows not known by the decision time were excluded."
        if frame.empty:
            return frame, chosen_date, source, "No holdings rows were known by the decision time.", None
        known_values = [value for value in parsed_known if value is not None]
        known_at = max(known_values).isoformat() if known_values else None

    source_warning = None
    if source is not None and "source" in frame.columns:
        frame = frame.loc[frame["source"].map(_clean_text).eq(source)].copy()
        if frame.empty:
            return frame, chosen_date, source, "No holdings rows match the requested source.", known_at
    if source is None:
        if "source_id" in frame.columns:
            chosen, source_warning = _choose_source_group(_source_groups(frame))
            if chosen is None:
                return frame.iloc[0:0], chosen_date, None, source_warning, known_at
            source_id, frame = chosen
            del source_id
        source_values = sorted({_clean_text(value) for value in frame.get("source", pd.Series(dtype=object)) if _clean_text(value)})
        selected_source = source_values[0] if len(source_values) == 1 else None
    else:
        selected_source = source
    warning = "; ".join(value for value in (warning, source_warning) if value) or None
    return frame, chosen_date, selected_source, warning, known_at


def _aggregate_fundamentals(
    economic_rows: list[dict[str, object]],
    mapped_items: list[object],
    fundamentals: pd.DataFrame | None,
    identity_map: Mapping[str, str],
    cutoff: datetime,
    analysis: date,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, float]], list[str]]:
    mapped_weight = math.fsum(float(row["weight"]) for row in economic_rows)
    empty_coverage = {
        name: {"covered_weight": 0.0, "mapped_weight": round(mapped_weight, 12), "coverage_fraction": 0.0}
        for name in ("pe_ratio", "roic")
    }
    metrics: dict[str, dict[str, object]] = {
        "pe_ratio": {"status": "unavailable", "value": None, "method": "covered_weight / weighted_earnings_yield"},
        "roic": {"status": "unavailable", "value": None, "method": "covered-constituent arithmetic weight average"},
    }
    limitations: list[str] = []
    if fundamentals is None or not isinstance(fundamentals, pd.DataFrame) or fundamentals.empty or not fundamentals.columns.is_unique:
        limitations.append("Constituent fundamental evidence is unavailable; provider headline metrics remain separate.")
        return metrics, empty_coverage, limitations

    rows: list[dict[str, object]] = []
    for row in fundamentals.to_dict("records"):
        known = normalise_event_decision_time(row.get("available_at", row.get("known_at")))
        effective = _as_date(row.get("as_of_date", row.get("as_of")))
        if known is None or known > cutoff or effective is None or effective > analysis:
            continue
        if not _clean_text(row.get("source_id")):
            limitations.append("Constituent fundamental rows without source lineage were excluded.")
            continue
        rows.append(row)

    holdings_by_key: dict[str, list[object]] = {}
    for holding in mapped_items:
        key = _canonical_key(holding.identity, holding.issuer, holding.company, identity_map)
        holdings_by_key.setdefault(key, []).append(holding)
    selected_metrics: dict[str, list[tuple[float, float, object, Mapping[str, object]]]] = {
        "pe_ratio": [], "roic": []
    }
    pe_covered = roic_covered = 0.0
    weighted_yield = 0.0
    weighted_roic = 0.0
    for economic in economic_rows:
        key = str(economic["identity"])
        holdings_for_key = holdings_by_key.get(key, [])
        holding_keys = {key}
        for holding in holdings_for_key:
            holding_keys.add(holding.identity)
            if holding.issuer:
                holding_keys.add(holding.issuer)
            if holding.company:
                holding_keys.add(holding.company)
        holding_keys = {value.casefold() for value in holding_keys}
        matches = [row for row in rows if holding_keys.intersection(_fundamental_keys(row))]
        if not matches:
            continue
        matches.sort(key=lambda row: (_as_date(row.get("as_of_date", row.get("as_of"))) or date.min,
                                      normalise_event_decision_time(row.get("available_at", row.get("known_at"))) or datetime.min.replace(tzinfo=cutoff.tzinfo),
                                      _clean_text(row.get("source_id"))))
        latest_key = (
            _as_date(matches[-1].get("as_of_date", matches[-1].get("as_of"))),
            normalise_event_decision_time(matches[-1].get("available_at", matches[-1].get("known_at"))),
        )
        latest = [row for row in matches if (
            _as_date(row.get("as_of_date", row.get("as_of"))),
            normalise_event_decision_time(row.get("available_at", row.get("known_at"))),
        ) == latest_key]
        if len({_metric_signature(row) for row in latest}) > 1:
            limitations.append(f"Conflicting same-vintage constituent evidence was excluded for {key}.")
            continue
        evidence = latest[-1]
        weight = float(economic["weight"])
        currencies = {holding.currency.upper() for holding in holdings_for_key if holding.currency}
        fact_currency = _clean_text(evidence.get("currency")).upper()
        if fact_currency and currencies and currencies != {fact_currency}:
            limitations.append(f"Fundamental currency does not match reported holding currency for {key}; metrics were excluded.")
            continue
        pe = _finite_number(evidence.get("pe_ratio"))
        if pe is not None:
            if pe == 0:
                limitations.append(f"Zero P/E evidence was excluded to avoid division by zero for {key}.")
            else:
                yld = 1.0 / pe
                if math.isfinite(yld):
                    pe_covered += weight
                    weighted_yield += weight * yld
                    selected_metrics["pe_ratio"].append((weight, pe, key, evidence))
                else:
                    limitations.append(f"Nonfinite earnings yield was excluded for {key}.")
        roic = _finite_number(evidence.get("roic"))
        if roic is not None:
            roic_covered += weight
            weighted_roic += weight * roic
            selected_metrics["roic"].append((weight, roic, key, evidence))

    empty_coverage["pe_ratio"] = {
        "covered_weight": round(pe_covered, 12),
        "mapped_weight": round(mapped_weight, 12),
        "coverage_fraction": round(pe_covered / mapped_weight, 12) if mapped_weight > 0 else 0.0,
    }
    empty_coverage["roic"] = {
        "covered_weight": round(roic_covered, 12),
        "mapped_weight": round(mapped_weight, 12),
        "coverage_fraction": round(roic_covered / mapped_weight, 12) if mapped_weight > 0 else 0.0,
    }
    if pe_covered > 0 and math.isfinite(weighted_yield) and weighted_yield > 0:
        pe_value = pe_covered / weighted_yield
        if math.isfinite(pe_value):
            metrics["pe_ratio"] = {
                "status": "available",
                "value": pe_value,
                "covered_weight": round(pe_covered, 12),
                "weighted_earnings_yield": weighted_yield / pe_covered,
                "method": "covered_weight / weighted_earnings_yield",
                "negative_earnings_convention": "Negative P/E contributes its negative earnings yield; nonpositive aggregate yield has no reported P/E.",
                "contributors": tuple(
                    {
                        "identity": key,
                        "weight": round(weight, 12),
                        "pe_ratio": value,
                        "source_id": _clean_text(row.get("source_id")),
                        "as_of_date": _as_date(row.get("as_of_date", row.get("as_of"))).isoformat(),
                        "available_at": normalise_event_decision_time(row.get("available_at", row.get("known_at"))).isoformat(),
                    }
                    for weight, value, key, row in selected_metrics["pe_ratio"]
                ),
            }
    elif pe_covered > 0:
        metrics["pe_ratio"] = {
            "status": "unavailable",
            "value": None,
            "covered_weight": round(pe_covered, 12),
            "weighted_earnings_yield": weighted_yield / pe_covered if math.isfinite(weighted_yield) else None,
            "method": "covered_weight / weighted_earnings_yield",
            "negative_earnings_convention": "Negative P/E contributes its negative earnings yield; nonpositive aggregate yield has no reported P/E.",
        }
        if math.isfinite(weighted_yield):
            limitations.append("Aggregate earnings yield is zero or negative; calculated look-through P/E is unavailable.")
        else:
            limitations.append("Aggregate earnings yield is nonfinite; calculated look-through P/E is unavailable.")
    if roic_covered > 0 and math.isfinite(weighted_roic):
        metrics["roic"] = {
            "status": "available",
            "value": weighted_roic / roic_covered,
            "covered_weight": round(roic_covered, 12),
            "method": "covered-constituent arithmetic weight average",
            "contributors": tuple(
                {
                    "identity": key,
                    "weight": round(weight, 12),
                    "roic": value,
                    "source_id": _clean_text(row.get("source_id")),
                    "as_of_date": _as_date(row.get("as_of_date", row.get("as_of"))).isoformat(),
                    "available_at": normalise_event_decision_time(row.get("available_at", row.get("known_at"))).isoformat(),
                }
                for weight, value, key, row in selected_metrics["roic"]
            ),
        }
    elif roic_covered > 0:
        limitations.append("Weighted ROIC arithmetic was nonfinite; the aggregate is unavailable.")
    if pe_covered < mapped_weight or roic_covered < mapped_weight:
        limitations.append("Missing or unusable constituent metrics lower fundamental-data coverage; missing values were not treated as zero.")
    return metrics, empty_coverage, limitations


def _concentration(rows: list[dict[str, object]], mapped_weight: float) -> dict[str, object]:
    square_sum = math.fsum(float(row["weight"]) ** 2 for row in rows)
    hhi = square_sum / (mapped_weight**2) if mapped_weight > 0 else 0.0
    top_5 = math.fsum(float(row["weight"]) for row in rows[:5])
    top_10 = math.fsum(float(row["weight"]) for row in rows[:10])
    return {
        "top_holdings": tuple(rows[:10]),
        "top_5_share": round(top_5, 12),
        "top_10_share": round(top_10, 12),
        "top_5_share_covered": round(top_5 / mapped_weight, 12) if mapped_weight > 0 else 0.0,
        "top_10_share_covered": round(top_10 / mapped_weight, 12) if mapped_weight > 0 else 0.0,
        "hhi": round(hhi, 12),
        "hhi_gross_weight_squared": round(square_sum, 12),
        "effective_number_of_holdings": round(1.0 / hhi, 12) if hhi > 0 else None,
        "denominator_weight": round(mapped_weight, 12),
        "denominator": "mapped operating-company weight",
    }


def _exposures(economic_rows: list[dict[str, object]], direct_holdings: tuple[object, ...]) -> dict[str, object]:
    result: dict[str, dict[str, float]] = {name: {} for name in ("issuer", "sector", "country", "currency", "listing")}
    for row in economic_rows:
        result["issuer"][str(row["identity"])] = round(float(row["weight"]), 12)
        for dimension in ("sector", "country", "currency"):
            bucket = row[dimension]
            if bucket:
                result[dimension][str(bucket)] = round(result[dimension].get(str(bucket), 0.0) + float(row["weight"]), 12)
    for item in direct_holdings:
        if item.exposure_type == "security":
            result["listing"][item.identity] = round(result["listing"].get(item.identity, 0.0) + item.weight, 12)
    return {name: dict(sorted(values.items())) for name, values in result.items()}


def _canonical_key(identity: str, issuer: str | None, company: str | None, identity_map: Mapping[str, str] | None) -> str:
    if identity_map:
        mapped = _mapped_identity(identity_map, identity)
        if mapped and str(mapped).strip():
            return str(mapped).strip().casefold()
    issuer_key = (issuer or company or "").strip()
    return issuer_key.casefold() if issuer_key else identity


def _mapped_identity(identity_map: Mapping[str, str] | None, identity: str) -> str | None:
    if not identity_map:
        return None
    return next(
        (str(value) for key, value in identity_map.items() if str(key).casefold() == identity.casefold() and str(value).strip()),
        None,
    )


def _fundamental_keys(row: Mapping[str, object]) -> set[str]:
    result = set()
    for column in ("identity", "instrument_id", "issuer", "company"):
        value = _clean_text(row.get(column))
        if value:
            result.add(value.casefold())
    typed = _typed_identity(pd.Series(row))
    if typed:
        result.add(typed.casefold())
    return result


def _metric_signature(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(_finite_number(row.get(field)) for field in ("pe_ratio", "roic")) + (_clean_text(row.get("currency")).upper(),)


def _provider_metrics(values: Mapping[str, object] | None) -> dict[str, dict[str, object]]:
    if not isinstance(values, Mapping):
        return {}
    return {
        str(name): {"label": "provider_reported", "value": value}
        for name, value in values.items()
        if pd.api.types.is_scalar(value) and not (not isinstance(value, (str, bytes)) and pd.isna(value))
    }


def _summary_from_unusable(
    *,
    instrument_id: str,
    status: str,
    holdings_date: str,
    analysis_date: str,
    decision_time: str,
    source: str | None,
    source_id: str | None,
    source_ids: tuple[str, ...],
    revisions: tuple[str, ...],
    completeness: str,
    freshness: str,
    reported_total: float,
    limitations: list[str],
    conventions: tuple[str, ...],
    provider: Mapping[str, Mapping[str, object]],
    lineage: Mapping[str, object],
) -> LookThroughSummary:
    total_status = _weight_total_status(reported_total) if reported_total > 0 else "unavailable"
    if status == "invalid":
        limitations = [*limitations, "Holdings failed the shared normalisation contract; reported weight is retained as unresolved."]
    if reported_total > 0 and total_status != "within_tolerance":
        limitations.append(f"Reported holdings total is {total_status.replace('_', ' ')}.")
    return LookThroughSummary(
        instrument_id, status, holdings_date, analysis_date, decision_time, source, source_id, source_ids, revisions,
        completeness, freshness, min(1.0, max(0.0, reported_total)), reported_total, round(reported_total, 12),
        0.0, 0.0, 0.0, round(reported_total, 12), 0.0, 0.0, total_status,
        {"top_holdings": (), "top_5_share": 0.0, "top_10_share": 0.0, "top_5_share_covered": 0.0,
         "top_10_share_covered": 0.0, "hhi": 0.0, "hhi_gross_weight_squared": 0.0,
         "effective_number_of_holdings": None, "denominator_weight": 0.0, "denominator": "mapped operating-company weight"},
        {name: {} for name in ("issuer", "sector", "country", "currency", "listing")},
        {name: {"covered_weight": 0.0, "mapped_weight": 0.0, "coverage_fraction": 0.0} for name in ("pe_ratio", "roic")},
        {"pe_ratio": {"status": "unavailable", "value": None}, "roic": {"status": "unavailable", "value": None}},
        provider, lineage, conventions, tuple(dict.fromkeys(limitations)), False,
    )


def _empty_summary(
    instrument_id: str,
    analysis_date: str,
    decision_time: str | None,
    status: str,
    limitations: tuple[str, ...],
    conventions: tuple[str, ...],
    provider: Mapping[str, Mapping[str, object]],
) -> LookThroughSummary:
    return _summary_from_unusable(
        instrument_id=instrument_id,
        status=status,
        holdings_date="",
        analysis_date=analysis_date,
        decision_time=decision_time or "",
        source=None,
        source_id=None,
        source_ids=(),
        revisions=(),
        completeness="unavailable",
        freshness="unknown",
        reported_total=0.0,
        limitations=list(limitations),
        conventions=conventions,
        provider=provider,
        lineage={},
    )


def _safe_reported_total(frame: pd.DataFrame) -> float:
    column = next((name for name in ("weight", "weight_decimal", "weight_percent", "weight_pct") if name in frame), None)
    if column is None:
        return 0.0
    values = []
    for value in frame[column]:
        number = _finite_number(value)
        if number is None or number < 0:
            return 0.0
        values.append(number)
    total = math.fsum(values)
    if column in {"weight_percent", "weight_pct"}:
        total /= 100.0
    return total


def _weight_total_status(total: float) -> str:
    if total > 1.0 + _RECONCILIATION_TOLERANCE:
        return "over_100"
    if total < 1.0 - _RECONCILIATION_TOLERANCE:
        return "under_100"
    return "within_tolerance"


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _single_value(values: list[object]) -> str | None:
    unique = sorted({_clean_text(value) for value in values if _clean_text(value)})
    return unique[0] if len(unique) == 1 else None


def _unique_text(values: object) -> tuple[str, ...]:
    if not isinstance(values, pd.Series):
        return ()
    return tuple(sorted({_clean_text(value) for value in values if _clean_text(value)}))


def _clean_text(value: object) -> str:
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return ""
    return str(value).strip()
