"""Portfolio maturity and fixed-income cash-flow views over saved calendar data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
_BOND_ASSET_TYPES = frozenset(
    {"bond", "fixed_income", "fixed income", "government_bond", "corporate_bond"}
)
_FLOW_TYPES = frozenset({"income", "maturity_proceeds"})


def build_portfolio_maturity_ladder(
    calendar_projection: Mapping[str, object] | None,
    *,
    holdings: Sequence[Mapping[str, object]] = (),
    terms_projections: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Aggregate canonical, point-in-time calendar flows by their exact payment date.

    Exact dates preserve the certified schedule and avoid arbitrary month/year
    boundaries. Amounts and FX are consumed from the portfolio calendar without
    recalculating them here. Missing amounts stay unavailable in every total.
    """

    projection = calendar_projection if isinstance(calendar_projection, Mapping) else {}
    terms_by_id = dict(terms_projections or {})
    bond_positions: dict[str, dict[str, object]] = {}
    for row in holdings:
        instrument_id = str(row.get("instrument_id", row.get("etf_id", "")) or "").strip()
        asset_type = str(row.get("asset_type", "") or "").strip().casefold()
        if instrument_id and asset_type in _BOND_ASSET_TYPES:
            bond_positions[instrument_id] = dict(row)

    decision_time = projection.get("decision_time")
    currency = str(projection.get("currency") or "") or None
    calendar_coverage = projection.get("coverage")
    calendar_coverage = dict(calendar_coverage) if isinstance(calendar_coverage, Mapping) else {}
    term_coverage = calendar_coverage.get("fixed_income_terms")
    term_coverage = dict(term_coverage) if isinstance(term_coverage, Mapping) else {
        "status": "unavailable",
        "reason": "fixed_income_terms_coverage_unavailable",
    }

    source_as_of_dates: dict[str, dict[str, str]] = {}
    for instrument_id, term_projection in terms_by_id.items():
        term_value = term_projection.get("terms")
        term = term_value if isinstance(term_value, Mapping) else {}
        dates = {
            key: str(term[key])
            for key in ("known_at", "retrieved_at")
            if term.get(key) not in (None, "")
        }
        if dates:
            source_as_of_dates[str(instrument_id)] = dates

    grouped: dict[tuple[str | None, str, str], dict[str, object]] = {}
    instrument_flows: dict[tuple[str, str, str], list[Mapping[str, object]]] = {}
    raw_flows = projection.get("cash_flows")
    flows = raw_flows if isinstance(raw_flows, Sequence) and not isinstance(raw_flows, (str, bytes)) else ()
    for raw in flows:
        if not isinstance(raw, Mapping):
            continue
        instrument_id = str(raw.get("instrument_id") or "").strip()
        flow_type = str(raw.get("flow_type") or "")
        if instrument_id not in bond_positions or flow_type not in _FLOW_TYPES:
            continue
        payment_date_value = raw.get("payment_date")
        payment_date = str(payment_date_value)[:10] if payment_date_value else None
        flow_currency = str(raw.get("currency") or currency or "").upper() or "unavailable"
        key = (payment_date, flow_type, flow_currency)
        group = grouped.setdefault(
            key,
            {
                "payment_date": payment_date,
                "flow_type": flow_type,
                "currency": flow_currency,
                "_amounts": [],
                "_complete": True,
                "flow_count": 0,
                "known_flow_count": 0,
                "source_confidences": set(),
                "source_ids": set(),
                "source_version_ids": set(),
                "instrument_ids": set(),
                "reason_codes": set(),
            },
        )
        amount = _decimal(raw.get("amount"))
        group["flow_count"] = int(group["flow_count"]) + 1
        group["instrument_ids"].add(instrument_id)  # type: ignore[union-attr]
        if amount is None:
            group["_complete"] = False
            reason = str(raw.get("reason") or "projected_cash_flow_amount_unavailable")
            group["reason_codes"].add(reason)  # type: ignore[union-attr]
        else:
            group["_amounts"].append(amount)  # type: ignore[union-attr]
            group["known_flow_count"] = int(group["known_flow_count"]) + 1
        term_value = terms_by_id.get(instrument_id, {}).get("terms")
        term = term_value if isinstance(term_value, Mapping) else {}
        confidence = str(term.get("confidence") or "unavailable")
        group["source_confidences"].add(confidence)  # type: ignore[union-attr]
        for field, target in (("source_id", "source_ids"), ("source_version_id", "source_version_ids")):
            source = raw.get(field)
            if source:
                group[target].add(str(source))  # type: ignore[union-attr]
        instrument_flows.setdefault((instrument_id, flow_type, flow_currency), []).append(raw)

    ladder_rows: list[dict[str, object]] = []
    for key, group in sorted(
        grouped.items(), key=lambda item: (item[0][0] or "9999-12-31", item[0][1], item[0][2])
    ):
        complete = bool(group["_complete"])
        amounts = group["_amounts"]
        amount = sum(amounts, Decimal("0")) if complete and amounts else None
        confidences = sorted(group["source_confidences"])
        ladder_rows.append(
            {
                "payment_date": key[0],
                "flow_type": key[1],
                "currency": key[2],
                "amount": amount,
                "status": "available" if complete and amounts else "unavailable",
                "flow_count": group["flow_count"],
                "known_flow_count": group["known_flow_count"],
                "source_confidence": confidences[0] if len(confidences) == 1 else "mixed" if confidences else "unavailable",
                "source_ids": sorted(group["source_ids"]),
                "source_version_ids": sorted(group["source_version_ids"]),
                "instrument_ids": sorted(group["instrument_ids"]),
                "reason_codes": sorted(group["reason_codes"]),
            }
        )

    totals_by_key: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for row in ladder_rows:
        totals_by_key.setdefault((str(row["flow_type"]), str(row["currency"])), []).append(row)
    totals: list[dict[str, object]] = []
    for (flow_type, flow_currency), rows in sorted(totals_by_key.items()):
        amounts = [_decimal(row.get("amount")) for row in rows]
        complete = all(amount is not None for amount in amounts)
        totals.append(
            {
                "flow_type": flow_type,
                "currency": flow_currency,
                "amount": sum((amount for amount in amounts if amount is not None), Decimal("0")) if complete else None,
                "status": "available" if complete else "partial",
                "flow_count": sum(int(row.get("flow_count") or 0) for row in rows),
                "reason_codes": sorted(
                    {str(reason) for row in rows for reason in row.get("reason_codes", ())}
                ),
            }
        )

    position_rows: list[dict[str, object]] = []
    for instrument_id, holding in sorted(bond_positions.items()):
        term_projection = terms_by_id.get(instrument_id, {})
        term_value = term_projection.get("terms")
        term = term_value if isinstance(term_value, Mapping) else {}
        reasons = [str(code) for code in term_projection.get("reason_codes", ())] if isinstance(term_projection.get("reason_codes", ()), Sequence) else []
        if str(term_projection.get("status") or "unavailable") != "available":
            reasons.extend(["fixed_income_terms_unavailable"] if not reasons else [])
        matching_flows = [item for item in flows if isinstance(item, Mapping) and str(item.get("instrument_id") or "") == instrument_id and str(item.get("flow_type") or "") in _FLOW_TYPES]
        if not matching_flows:
            reasons.append("contractual_cash_flows_unavailable")
        position_rows.append(
            {
                "instrument_id": instrument_id,
                "quantity": _decimal(holding.get("quantity", holding.get("units"))),
                "market_value_eur": _decimal(holding.get("market_value_eur", holding.get("value_eur"))),
                "terms_status": str(term_projection.get("status") or "unavailable"),
                "maturity_date": term.get("maturity_date"),
                "issuer_id": term.get("issuer_id"),
                "country": term.get("country"),
                "currency": term.get("currency"),
                "source_id": term.get("source_id"),
                "source_confidence": term.get("confidence") or "unavailable",
                "source_as_of_dates": source_as_of_dates.get(instrument_id, {}),
                "reason_codes": sorted(set(reasons)),
            }
        )

    exposure = {
        category: _categorical_exposure(position_rows, category)
        for category in ("issuer_id", "country", "currency")
    }
    exposure.update(
        {
            "duration": {"status": "unavailable", "reason": "saved_fixed_income_portfolio_duration_exposure_unavailable"},
            "rating": {"status": "unavailable", "reason": "fixed_income_terms_do_not_include_credit_rating"},
            "sector": {"status": "unavailable", "reason": "fixed_income_terms_do_not_include_sector_classification"},
        }
    )
    coverage = {
        "fixed_income_terms": term_coverage,
        "held_bond_count": len(bond_positions),
        "flow_count": sum(int(row.get("flow_count") or 0) for row in ladder_rows),
        "known_flow_count": sum(int(row.get("known_flow_count") or 0) for row in ladder_rows),
        "unavailable_flow_count": sum(
            int(row.get("flow_count") or 0) - int(row.get("known_flow_count") or 0)
            for row in ladder_rows
        ),
    }
    warnings = [str(item) for item in projection.get("warnings", ())] if isinstance(projection.get("warnings", ()), Sequence) else []
    unavailable_terms = [row["instrument_id"] for row in position_rows if row["terms_status"] != "available"]
    if unavailable_terms:
        warnings.append("fixed_income_terms_unavailable:" + ",".join(map(str, unavailable_terms)))
    if coverage["unavailable_flow_count"]:
        warnings.append("fixed_income_cash_flow_amounts_incomplete")
    partial = bool(unavailable_terms or coverage["unavailable_flow_count"])
    partial = partial or str(term_coverage.get("status") or "unavailable") in {"partial", "unavailable"}
    status = "unavailable" if not bond_positions or not ladder_rows else "partial" if partial else "available"
    reason = None
    if not bond_positions:
        reason = "no_fixed_income_holdings_in_snapshot"
    elif not ladder_rows:
        reason = "no_saved_fixed_income_cash_flows_available"
    return {
        "schema_version": "portfolio_maturity_ladder.v1",
        "status": status,
        "reason": reason,
        "decision_time": decision_time,
        "currency": currency,
        "cash_flows": ladder_rows,
        "totals": totals,
        "positions": position_rows,
        "exposures": exposure,
        "coverage": coverage,
        "source_as_of_dates": source_as_of_dates,
        "warnings": list(dict.fromkeys(warnings)),
        "execution_allowed": False,
    }


def _categorical_exposure(
    positions: Sequence[Mapping[str, object]], category: str
) -> dict[str, object]:
    grouped: dict[str, Decimal] = {}
    missing = 0
    for position in positions:
        label = str(position.get(category) or "").strip()
        market_value = _decimal(position.get("market_value_eur"))
        if not label or market_value is None:
            missing += 1
            continue
        grouped[label] = grouped.get(label, Decimal("0")) + market_value
    rows = [
        {"label": label, "market_value_eur": amount, "currency": "EUR"}
        for label, amount in sorted(grouped.items())
    ]
    status = "unavailable" if not positions or (not rows and missing) else "partial" if missing else "available"
    reason = None
    if status != "available":
        reason = "bond_terms_or_position_market_value_unavailable"
    return {"status": status, "rows": rows, "uncovered_positions": missing, "reason": reason}


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None
