"""Point-in-time portfolio events and cash flows from saved local evidence.

Calendar authority is ranked regulator, exchange, issuer, then other when the
stored source authority has one of those exact labels. Calendar rows without an
explicit expected/confirmed field stay estimated. Certified contractual bond
schedules are confirmed; corporate-action revisions keep their stored history.
High and critical event-risk levels are advisory blackout candidates only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from etf_cockpit.data.event_calendar import events_available_as_of, load_calendar_events, normalise_event_decision_time
from etf_cockpit.data.fx_data import FxRateSnapshot, build_fx_rate_snapshot, fx_cross_rate
from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    CorporateActionType,
    reconcile_provider_observations,
)
from etf_cockpit.portfolio.ledger_projection import PositionBalance


EventStatus = Literal["confirmed", "estimated", "revised", "cancelled"]
_AUTHORITY_RANK = ("regulator", "exchange", "issuer", "other")
_INCOME_ACTIONS = frozenset(
    {
        CorporateActionType.DIVIDEND.value,
        CorporateActionType.CASH_DIVIDEND.value,
        CorporateActionType.CAPITAL_GAIN.value,
        CorporateActionType.DISTRIBUTION.value,
        CorporateActionType.COUPON.value,
        CorporateActionType.INTEREST.value,
        CorporateActionType.ACCRUED_SETTLEMENT.value,
        CorporateActionType.RECOVERY.value,
    }
)
_PRINCIPAL_ACTIONS = frozenset(
    {
        CorporateActionType.PRINCIPAL_REDEMPTION.value,
        CorporateActionType.REDEMPTION.value,
        CorporateActionType.CALL.value,
        CorporateActionType.PUT.value,
        CorporateActionType.AMORTISATION.value,
        CorporateActionType.TENDER.value,
    }
)


@dataclass(frozen=True)
class PortfolioEvent:
    event_id: str
    instrument_id: str
    event_type: str
    title: str
    description: str | None
    event_date: str | None
    payment_date: str | None
    timezone_name: str | None
    status: EventStatus
    source_authority: str | None
    source_id: str | None
    source_url: str | None
    source_rank: str
    confidence: str | None
    affected_exposure: Mapping[str, object]
    risk_level: str
    blackout_candidate: bool
    blackout_reason: str
    version: int = 1
    supersedes_event_id: str | None = None
    source_version_id: str | None = None


@dataclass(frozen=True)
class ProjectedCashFlow:
    event_id: str
    instrument_id: str
    flow_type: str
    payment_date: str | None
    status: EventStatus
    quantity: Decimal | None
    local_amount: Decimal | None
    local_currency: str | None
    amount: Decimal | None
    currency: str
    source_id: str | None
    source_version_id: str | None
    reason: str | None = None


def build_portfolio_calendar(
    holdings: pd.DataFrame | Sequence[PositionBalance] | None,
    *,
    decision_time: object,
    output_currency: str = "EUR",
    event_rows: pd.DataFrame | None = None,
    corporate_actions: Sequence[CorporateAction] = (),
    fixed_income_terms: Mapping[str, Mapping[str, object]] | None = None,
    fx_rates: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Build a read-only calendar using only facts known by decision_time."""

    cutoff = normalise_event_decision_time(decision_time)
    currency = str(output_currency or "").strip().upper()
    unavailable = {
        "schema_version": "portfolio_calendar.v1",
        "status": "unavailable",
        "reason": None,
        "decision_time": cutoff.isoformat() if cutoff is not None else None,
        "currency": currency or None,
        "available_output_currencies": ["EUR"],
        "events": [],
        "event_versions": [],
        "cash_flows": [],
        "cash_flow_summaries": [],
        "coverage": {},
        "warnings": [],
        "execution_allowed": False,
        "proposal_allowed": False,
    }
    if cutoff is None:
        unavailable["reason"] = "portfolio_decision_time_unavailable"
        unavailable["warnings"] = ["A timezone-aware portfolio snapshot time is required."]
        return unavailable
    if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
        unavailable["reason"] = "output_currency_invalid"
        unavailable["warnings"] = ["Output currency must be a three-letter uppercase code."]
        return unavailable

    holding_rows = _holding_records(holdings)
    holding_index = _holding_index(holding_rows)
    terms_by_instrument = dict(fixed_income_terms or {})
    warnings: list[str] = []
    coverage: dict[str, dict[str, object]] = {}

    source_events = load_calendar_events() if event_rows is None else event_rows.copy()
    visible_events = events_available_as_of(source_events, cutoff.to_pydatetime())
    events: list[PortfolioEvent] = []
    for row in visible_events.to_dict("records"):
        item = _calendar_event(row, holding_index)
        if item is not None and _event_not_before_cutoff(item.event_date, item.timezone_name, cutoff):
            events.append(item)
            if item.confidence is None:
                warnings.append("calendar_event_confidence_unavailable")
    coverage["event_calendar"] = {
        "status": "available" if events else "unavailable",
        "reason": None if events else "No valid calendar events were saved and available at the portfolio snapshot time.",
    }
    if not events:
        warnings.append("event_calendar_unavailable")

    visible_actions = tuple(item for item in corporate_actions if _known_by(item.known_at, cutoff))
    action_versions, current_actions, action_warnings = _corporate_action_events(
        visible_actions, holding_index
    )
    warnings.extend(action_warnings)
    events.extend(
        item
        for item in current_actions
        if _event_not_before_cutoff(item.payment_date or item.event_date, item.timezone_name, cutoff)
    )
    if any(item.source_authority is None for item in current_actions):
        warnings.append("corporate_action_source_authority_unavailable")
    if any(item.confidence is None for item in current_actions):
        warnings.append("corporate_action_confidence_unavailable")
    coverage["corporate_actions"] = {
        "status": "available" if visible_actions else "unavailable",
        "reason": None if visible_actions else "No corporate-action observations were saved and known at the portfolio snapshot time.",
    }
    event_versions = [asdict(item) for item in action_versions]

    fx_frame = fx_rates if isinstance(fx_rates, pd.DataFrame) else pd.DataFrame()
    fx_snapshot = build_fx_rate_snapshot(fx_frame, decision_time=cutoff.to_pydatetime())
    coverage["fx"] = {
        "status": "available" if fx_snapshot.available else "unavailable",
        "reason": fx_snapshot.reason,
        "source_snapshot": fx_snapshot.source_snapshot,
        "as_of_date": fx_snapshot.as_of_date.isoformat() if fx_snapshot.as_of_date else None,
    }

    bond_ids = {key for key, holding in holding_index.items() if _is_bond(holding.get("asset_type"))}
    terms_missing = sorted(
        instrument_id
        for instrument_id in bond_ids
        if str(terms_by_instrument.get(instrument_id, {}).get("status", "unavailable")) != "available"
    )
    coverage["fixed_income_terms"] = {
        "status": "partial" if terms_missing else "available" if bond_ids else "unavailable",
        "unavailable_instruments": terms_missing,
        "reason": "Certified terms and contractual schedules are unavailable for one or more held bonds." if terms_missing else None,
    }
    warnings.extend(f"fixed_income_terms_unavailable:{instrument_id}" for instrument_id in terms_missing)

    cash_flows: list[ProjectedCashFlow] = []
    for action_id, candidates in _active_action_groups(visible_actions).items():
        if not candidates:
            continue
        instrument_id = candidates[0].instrument_id
        holding = holding_index.get(instrument_id)
        if holding is None:
            continue
        selected = _select_action(candidates)
        if selected is None:
            warnings.append(f"corporate_action_conflict:{action_id}")
            continue
        if _is_bond(holding.get("asset_type")):
            terms = terms_by_instrument.get(instrument_id, {})
            terms_available = str(terms.get("status")) == "available"
            is_future = _payment_not_before(selected.payable_at, cutoff)
            if not terms_available and is_future and selected.action_type in _INCOME_ACTIONS | _PRINCIPAL_ACTIONS:
                cash_flows.append(
                    _action_cash_flow(
                        selected,
                        holding,
                        currency,
                        fx_snapshot,
                        bond_terms_available=False,
                    )
                )
            if selected.action_type in {CorporateActionType.CALL.value, CorporateActionType.PUT.value, CorporateActionType.TENDER.value}:
                if is_future and terms_available:
                    cash_flows.append(
                        _action_cash_flow(
                            selected,
                            holding,
                            currency,
                            fx_snapshot,
                            bond_terms_available=True,
                        )
                    )
            continue
        if selected.action_type in _INCOME_ACTIONS | _PRINCIPAL_ACTIONS and _payment_not_before(selected.payable_at, cutoff):
            cash_flows.append(_action_cash_flow(selected, holding, currency, fx_snapshot))

    for instrument_id in sorted(bond_ids):
        terms = terms_by_instrument.get(instrument_id, {})
        if str(terms.get("status", "unavailable")) != "available":
            continue
        holding = holding_index[instrument_id]
        cash_flows.extend(_terms_cash_flows(instrument_id, holding, terms, currency, fx_snapshot, cutoff))
        events.extend(_terms_events(instrument_id, holding, terms, cutoff))

    events.sort(key=_event_sort_key)
    cash_flows.sort(key=lambda item: (item.payment_date or "9999-12-31", item.instrument_id, item.flow_type, item.source_version_id or ""))
    for flow in cash_flows:
        if flow.reason and flow.reason not in warnings:
            warnings.append(flow.reason)

    summaries = _cash_flow_summaries(cash_flows)
    available_currencies = {currency, "EUR"}
    available_currencies.update(
        item.currency.upper()
        for item in visible_actions
        if item.currency and len(item.currency) == 3 and item.currency.isalpha()
    )
    for projection in terms_by_instrument.values():
        terms_value = projection.get("terms")
        terms = terms_value if isinstance(terms_value, Mapping) else {}
        term_currency = _text(terms.get("currency"))
        if term_currency and len(term_currency) == 3 and term_currency.isalpha():
            available_currencies.add(term_currency.upper())
    any_data = bool(events or cash_flows)
    result_status = "unavailable" if not any_data else "partial" if warnings else "available"
    return {
        **unavailable,
        "status": result_status,
        "reason": None if any_data else "No saved point-in-time events or contractual cash flows are available for these holdings.",
        "events": [asdict(item) for item in events],
        "event_versions": event_versions,
        "cash_flows": [asdict(item) for item in cash_flows],
        "cash_flow_summaries": summaries,
        "coverage": coverage,
        "warnings": list(dict.fromkeys(warnings)),
        "available_output_currencies": sorted(available_currencies),
    }


def _holding_records(holdings: pd.DataFrame | Sequence[PositionBalance] | None) -> list[dict[str, object]]:
    if isinstance(holdings, pd.DataFrame):
        return [dict(row) for row in holdings.to_dict("records")]
    if holdings is None:
        return []
    rows: list[dict[str, object]] = []
    for item in holdings:
        if isinstance(item, PositionBalance):
            rows.append({"instrument_id": item.instrument_id, "quantity": item.quantity})
        elif isinstance(item, Mapping):
            rows.append(dict(item))
    return rows


def _holding_index(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        instrument_id = _text(row.get("instrument_id", row.get("etf_id")))
        if instrument_id:
            grouped[instrument_id].append(row)
    result: dict[str, dict[str, object]] = {}
    for instrument_id, items in grouped.items():
        quantities = [_decimal(item.get("quantity", item.get("units"))) for item in items]
        quantity = sum((value for value in quantities if value is not None), Decimal("0")) if all(value is not None for value in quantities) else None
        types = {_text(item.get("asset_type")) for item in items if _text(item.get("asset_type"))}
        values = [_decimal(item.get("market_value_eur", item.get("value_eur"))) for item in items]
        market_value = sum((value for value in values if value is not None), Decimal("0")) if values and all(value is not None for value in values) else None
        result[instrument_id] = {
            "instrument_id": instrument_id,
            "quantity": quantity,
            "asset_type": next(iter(types)) if len(types) == 1 else None,
            "market_value_eur": market_value,
        }
    return result


def _calendar_event(row: Mapping[str, object], holdings: Mapping[str, Mapping[str, object]]) -> PortfolioEvent | None:
    event_id = _text(row.get("event_id"))
    instrument_id = _text(row.get("instrument_id"))
    if not event_id or not instrument_id:
        return None
    risk = str(row.get("risk_level") or "unknown").strip().casefold()
    authority = _text(row.get("source_authority"))
    return PortfolioEvent(
        event_id=event_id,
        instrument_id=instrument_id,
        event_type=str(row.get("event_type") or "unknown"),
        title=str(row.get("title") or row.get("event_type") or "Event"),
        description=_text(row.get("description")),
        event_date=_text(row.get("event_time")) or _text(row.get("event_date")),
        payment_date=None,
        timezone_name=_text(row.get("timezone_name")),
        status="estimated",
        source_authority=authority,
        source_id=_text(row.get("source_id")),
        source_url=_text(row.get("source_url")),
        source_rank=_rank_label(authority),
        confidence=None,
        affected_exposure=_affected_exposure(instrument_id, holdings.get(instrument_id, {})),
        risk_level=risk,
        blackout_candidate=risk in {"high", "critical"},
        blackout_reason="explicit_event_policy_required" if risk in {"high", "critical"} else "saved_risk_level_does_not_trigger_blackout",
        source_version_id=_text(row.get("event_checksum")),
    )


def _corporate_action_events(
    actions: Sequence[CorporateAction],
    holdings: Mapping[str, Mapping[str, object]],
) -> tuple[list[PortfolioEvent], list[PortfolioEvent], list[str]]:
    by_lineage: dict[tuple[str, str, str], list[CorporateAction]] = defaultdict(list)
    for item in actions:
        by_lineage[(item.action_id, item.source_id, item.instrument_id)].append(item)
    history: list[PortfolioEvent] = []
    latest_by_action: dict[str, list[CorporateAction]] = defaultdict(list)
    for (action_id, _source_id, _instrument_id), versions in sorted(by_lineage.items()):
        ordered = sorted(versions, key=lambda item: (item.revision, item.known_at, item.source_checksum))
        latest = ordered[-1]
        for item in ordered:
            if item is not latest or item.status == "superseded":
                status: EventStatus = "revised"
            elif item.status == "retracted":
                status = "cancelled"
            else:
                status = "estimated"
            history.append(
                _action_event(
                    item,
                    holdings,
                    status=status,
                    version=item.revision,
                    supersedes_event_id=action_id if item.revision > 1 else None,
                )
            )
        latest_by_action[action_id].append(latest)

    warnings: list[str] = []
    current: list[PortfolioEvent] = []
    for action_id, candidates in sorted(latest_by_action.items()):
        latest_statuses = {item.status for item in candidates}
        if len(latest_statuses) != 1:
            warnings.append(f"corporate_action_status_conflict:{action_id}")
            continue
        latest_status = next(iter(latest_statuses))
        if latest_status == "retracted":
            current.extend(
                _action_event(item, holdings, status="cancelled", version=item.revision, supersedes_event_id=action_id if item.revision > 1 else None)
                for item in candidates
            )
            continue
        if latest_status == "superseded":
            continue
        selected = _select_action(candidates)
        if selected is None:
            warnings.append(f"corporate_action_conflict:{action_id}")
            continue
        has_prior = any(
            item.action_id == selected.action_id
            and item.source_id == selected.source_id
            and item.revision < selected.revision
            for item in actions
        )
        current.append(
            _action_event(
                selected,
                holdings,
                status="revised" if has_prior else "estimated",
                version=selected.revision,
                supersedes_event_id=action_id if selected.revision > 1 else None,
            )
        )
    return history, current, warnings


def _action_event(
    item: CorporateAction,
    holdings: Mapping[str, Mapping[str, object]],
    *,
    status: EventStatus,
    version: int,
    supersedes_event_id: str | None,
) -> PortfolioEvent:
    confidence = _text(item.terms.get("confidence"))
    authority = _text(item.terms.get("source_authority"))
    return PortfolioEvent(
        event_id=item.action_id,
        instrument_id=item.instrument_id,
        event_type=item.action_type,
        title=item.action_type.replace("_", " ").title(),
        description=None,
        event_date=item.event_at,
        payment_date=item.payable_at,
        timezone_name="UTC",
        status=status,
        source_authority=authority,
        source_id=item.source_id,
        source_url=None,
        source_rank=_rank_label(authority),
        confidence=confidence,
        affected_exposure=_affected_exposure(item.instrument_id, holdings.get(item.instrument_id, {})),
        risk_level="unknown",
        blackout_candidate=False,
        blackout_reason="saved_corporate_action_has_no_event_risk_policy",
        version=version,
        supersedes_event_id=supersedes_event_id,
        source_version_id=item.source_checksum,
    )


def _active_action_groups(actions: Sequence[CorporateAction]) -> dict[str, list[CorporateAction]]:
    by_lineage: dict[tuple[str, str, str], list[CorporateAction]] = defaultdict(list)
    for item in actions:
        by_lineage[(item.action_id, item.source_id, item.instrument_id)].append(item)
    active: dict[str, list[CorporateAction]] = defaultdict(list)
    for (action_id, _source_id, _instrument_id), versions in by_lineage.items():
        latest = max(versions, key=lambda item: (item.revision, item.known_at, item.source_checksum))
        if latest.status == "active":
            active[action_id].append(latest)
    return active


def _select_action(candidates: Sequence[CorporateAction]) -> CorporateAction | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    report = reconcile_provider_observations(*(tuple([item]) for item in candidates))
    if not report.available or report.selected_source_id is None:
        return None
    return next((item for item in candidates if item.source_id == report.selected_source_id), None)


def _action_cash_flow(
    action: CorporateAction,
    holding: Mapping[str, object],
    output_currency: str,
    fx_snapshot: FxRateSnapshot,
    *,
    bond_terms_available: bool = True,
) -> ProjectedCashFlow:
    quantity = _decimal(holding.get("quantity"))
    local_currency = action.currency
    payment_date = _text(action.payable_at)
    local_amount: Decimal | None = None
    reason: str | None = None
    if _is_bond(holding.get("asset_type")) and not bond_terms_available:
        reason = "fixed_income_terms_unavailable"
    elif quantity is None:
        reason = "holding_quantity_unavailable"
    elif action.amount is None or local_currency is None:
        reason = "corporate_action_amount_or_currency_unavailable"
    else:
        local_amount = Decimal(str(action.amount)) * quantity
    if payment_date is None:
        reason = reason or "cash_flow_payment_date_unavailable"
    amount, fx_reason = _convert_amount(local_amount, local_currency, output_currency, fx_snapshot)
    reason = reason or fx_reason
    if reason is not None:
        amount = None
    flow_type = "income" if action.action_type in _INCOME_ACTIONS else "maturity_proceeds"
    return ProjectedCashFlow(
        event_id=action.action_id,
        instrument_id=action.instrument_id,
        flow_type=flow_type,
        payment_date=payment_date,
        status="estimated" if action.revision == 1 else "revised",
        quantity=quantity,
        local_amount=local_amount,
        local_currency=local_currency,
        amount=amount,
        currency=output_currency,
        source_id=action.source_id,
        source_version_id=action.source_checksum,
        reason=reason,
    )


def _terms_cash_flows(
    instrument_id: str,
    holding: Mapping[str, object],
    projection: Mapping[str, object],
    output_currency: str,
    fx_snapshot: FxRateSnapshot,
    cutoff: pd.Timestamp,
) -> list[ProjectedCashFlow]:
    terms_value = projection.get("terms")
    terms = terms_value if isinstance(terms_value, Mapping) else {}
    quantity = _decimal(holding.get("quantity"))
    flows: list[ProjectedCashFlow] = []
    version_id = _text(terms.get("version_id"))
    for flow_type, key in (("income", "coupon_schedule"), ("maturity_proceeds", "redemption_schedule")):
        raw_flows = projection.get(key, ())
        if not isinstance(raw_flows, Sequence) or isinstance(raw_flows, (str, bytes)):
            continue
        for raw in raw_flows:
            if not isinstance(raw, Mapping):
                continue
            payment_date = _iso_date(raw.get("payment_date"))
            if payment_date is not None and pd.Timestamp(payment_date).date() < cutoff.date():
                continue
            amount_per_unit = _decimal(raw.get("amount"))
            local_currency = _text(raw.get("currency")) or _text(terms.get("currency"))
            local_amount: Decimal | None = None
            reason: str | None = None
            if payment_date is None:
                reason = "contractual_payment_date_unavailable"
            elif quantity is None:
                reason = "holding_quantity_unavailable"
            elif amount_per_unit is None or local_currency is None:
                reason = "contractual_terms_amount_or_currency_unavailable"
            else:
                local_amount = amount_per_unit * quantity
            amount, fx_reason = _convert_amount(local_amount, local_currency, output_currency, fx_snapshot)
            reason = reason or fx_reason
            if reason is not None:
                amount = None
            source_id = _text(raw.get("source_id")) or _text(terms.get("source_id"))
            source_version = _text(raw.get("source_version_id")) or version_id
            flows.append(
                ProjectedCashFlow(
                    event_id=version_id or source_version or instrument_id,
                    instrument_id=instrument_id,
                    flow_type=flow_type,
                    payment_date=payment_date,
                    status="confirmed",
                    quantity=quantity,
                    local_amount=local_amount,
                    local_currency=local_currency,
                    amount=amount,
                    currency=output_currency,
                    source_id=source_id,
                    source_version_id=source_version,
                    reason=reason,
                )
            )
    return flows


def _terms_events(
    instrument_id: str,
    holding: Mapping[str, object],
    projection: Mapping[str, object],
    cutoff: pd.Timestamp,
) -> list[PortfolioEvent]:
    terms_value = projection.get("terms")
    terms = terms_value if isinstance(terms_value, Mapping) else {}
    result: list[PortfolioEvent] = []
    version_id = _text(terms.get("version_id"))
    maturity = _iso_date(terms.get("maturity_date"))
    for flow_type, key in (("coupon", "coupon_schedule"), ("maturity", "redemption_schedule")):
        raw_flows = projection.get(key, ())
        if not isinstance(raw_flows, Sequence) or isinstance(raw_flows, (str, bytes)):
            continue
        for raw in raw_flows:
            if not isinstance(raw, Mapping):
                continue
            event_date = _iso_date(raw.get("payment_date"))
            if event_date is None or pd.Timestamp(event_date).date() < cutoff.date():
                continue
            source_id = _text(raw.get("source_id")) or _text(terms.get("source_id"))
            is_maturity = flow_type == "maturity" and event_date == maturity
            result.append(
                PortfolioEvent(
                    event_id=version_id or _text(raw.get("source_version_id")) or source_id or instrument_id,
                    instrument_id=instrument_id,
                    event_type="maturity" if is_maturity else flow_type,
                    title="Bond maturity" if is_maturity else "Bond coupon" if flow_type == "coupon" else "Bond redemption",
                    description=None,
                    event_date=event_date,
                    payment_date=event_date,
                    timezone_name="UTC",
                    status="confirmed",
                    source_authority="contractual_terms",
                    source_id=source_id,
                    source_url=_text(terms.get("source_document")),
                    source_rank="other",
                    confidence=_text(terms.get("confidence")),
                    affected_exposure=_affected_exposure(instrument_id, holding),
                    risk_level="unknown",
                    blackout_candidate=False,
                    blackout_reason="contractual_cash_flow_has_no_blackout_policy",
                    version=int(terms.get("revision", 1) or 1),
                    source_version_id=_text(raw.get("source_version_id")) or version_id,
                )
            )
    return result


def _cash_flow_summaries(flows: Sequence[ProjectedCashFlow]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[ProjectedCashFlow]] = defaultdict(list)
    for flow in flows:
        if flow.payment_date is None:
            continue
        date_value = pd.Timestamp(flow.payment_date)
        month = date_value.strftime("%Y-%m")
        quarter = f"{date_value.year}-Q{((date_value.month - 1) // 3) + 1}"
        groups[("month", month, flow.flow_type)].append(flow)
        groups[("quarter", quarter, flow.flow_type)].append(flow)
    result: list[dict[str, object]] = []
    for (period_type, period, flow_type), items in sorted(groups.items()):
        amounts = [item.amount for item in items]
        amount = sum((value for value in amounts if value is not None), Decimal("0")) if all(value is not None for value in amounts) else None
        local_currencies = {item.local_currency for item in items}
        local_amounts = [item.local_amount for item in items]
        local_amount = sum((value for value in local_amounts if value is not None), Decimal("0")) if len(local_currencies) == 1 and all(value is not None for value in local_amounts) else None
        result.append(
            {
                "period_type": period_type,
                "period": period,
                "flow_type": flow_type,
                "amount": amount,
                "currency": items[0].currency,
                "local_amount": local_amount,
                "local_currency": next(iter(local_currencies)) if len(local_currencies) == 1 else None,
                "flow_count": len(items),
                "status": "confirmed" if all(item.status == "confirmed" and item.amount is not None for item in items) else "estimated",
                "reason": None if amount is not None else "one_or_more_cash_flows_unavailable",
                "execution_allowed": False,
            }
        )
    return result


def _convert_amount(
    amount: Decimal | None,
    local_currency: str | None,
    output_currency: str,
    snapshot: FxRateSnapshot,
) -> tuple[Decimal | None, str | None]:
    if amount is None:
        return None, None
    source = _text(local_currency)
    if source is None:
        return None, "cash_flow_currency_unavailable"
    source = source.upper()
    if source == output_currency:
        return amount, None
    if not snapshot.available:
        return None, "fx_coverage_unavailable"
    cross = fx_cross_rate(snapshot, source, output_currency)
    if cross is None:
        return None, "fx_conversion_unavailable"
    converted = amount * Decimal(str(cross.rate))
    if not converted.is_finite():
        return None, "fx_conversion_nonfinite"
    return converted, None


def _affected_exposure(instrument_id: str, holding: Mapping[str, object]) -> dict[str, object]:
    quantity = _decimal(holding.get("quantity"))
    market_value = _decimal(holding.get("market_value_eur"))
    return {
        "instrument_id": instrument_id,
        "quantity": quantity,
        "market_value": market_value,
        "currency": "EUR" if market_value is not None else None,
        "unavailable_reason": None if quantity is not None or market_value is not None else "holding_exposure_unavailable",
    }


def _event_not_before_cutoff(event_date: str | None, timezone_name: str | None, cutoff: pd.Timestamp) -> bool:
    if not event_date:
        return False
    try:
        parsed = pd.Timestamp(event_date)
        if parsed.tzinfo is None:
            if len(event_date) == 10:
                if timezone_name:
                    local_date = cutoff.tz_convert(ZoneInfo(timezone_name)).date()
                else:
                    local_date = cutoff.date()
                return parsed.date() >= local_date
            return False
        return parsed.tz_convert("UTC") >= cutoff
    except (TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        return False


def _payment_not_before(payment_date: str | None, cutoff: pd.Timestamp) -> bool:
    if payment_date is None:
        return True
    try:
        parsed = pd.Timestamp(payment_date)
        return parsed.date() >= cutoff.date()
    except (TypeError, ValueError, OverflowError):
        return False


def _known_by(value: object, cutoff: pd.Timestamp) -> bool:
    try:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            return False
        return parsed.tz_convert("UTC") <= cutoff
    except (TypeError, ValueError, OverflowError):
        return False


def _rank_label(authority: str | None) -> str:
    key = str(authority or "").strip().casefold()
    return key if key in _AUTHORITY_RANK[:-1] else "other"


def _event_sort_key(event: PortfolioEvent) -> tuple[object, ...]:
    event_date = event.payment_date or event.event_date or "9999-12-31"
    rank = _AUTHORITY_RANK.index(event.source_rank) if event.source_rank in _AUTHORITY_RANK else len(_AUTHORITY_RANK)
    return event_date, rank, event.event_id, event.source_id or ""


def _is_bond(value: object) -> bool:
    return str(value or "").strip().casefold() in {"bond", "fixed_income", "fixed income", "government_bond", "corporate_bond"}


def _iso_date(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in {"", "none", "nan", "nat", "<na>"} else text


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


__all__ = ["PortfolioEvent", "ProjectedCashFlow", "build_portfolio_calendar"]
