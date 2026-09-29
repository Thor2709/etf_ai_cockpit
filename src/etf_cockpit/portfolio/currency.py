from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Literal, Mapping

import pandas as pd

from etf_cockpit.data.fx_data import FxCrossRate, FxRateSnapshot, build_fx_rate_snapshot, fx_cross_rate
from etf_cockpit.portfolio.sandbox import PortfolioAnalysis


@dataclass(frozen=True)
class CurrencyProjection:
    projection_id: str
    schema_version: str
    version: int
    analysis_source_snapshot: str | None
    source_currency: str
    currency: str
    decision_time: str | None
    source_snapshot: tuple[tuple[str, str], ...]
    fx_snapshot_date: date | None
    fx_snapshot_checksum: str | None
    reference_rate: float | None
    reference_rate_label: str
    reference_rate_legs: tuple[object, ...]
    monetary_fields: Mapping[str, Mapping[str, object]]
    available: bool
    reason: str | None
    execution_allowed: Literal[False] = False


def project_portfolio_currency(
    analysis: PortfolioAnalysis,
    target_currency: str,
    fx_rates: pd.DataFrame,
) -> CurrencyProjection:
    """Create an immutable, informational projection of the EUR analysis snapshot."""

    target = str(target_currency or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", target):
        raise ValueError("Target currency must be a three-letter currency code.")

    source_currency = "EUR"
    decision_time = _analysis_decision_time(analysis)
    decision_label = _decision_label(decision_time)
    analysis_snapshot = _analysis_source_snapshot(analysis)
    snapshot: FxRateSnapshot | None = None
    cross_rate: FxCrossRate | None = None
    reason: str | None = None
    available = analysis_snapshot is not None

    if analysis_snapshot is None:
        reason = "Analysis source snapshot is unavailable."
        available = False
        reference_rate = None
        rate_label = "Reference FX rate unavailable; no executable conversion is provided."
        rate_legs: tuple[object, ...] = ()
    elif target == source_currency:
        reference_rate = 1.0
        rate_label = "Identity currency projection; no FX rate required. Informational and non-executable."
        rate_legs: tuple[object, ...] = ()
    else:
        snapshot = build_fx_rate_snapshot(fx_rates, decision_time=decision_time)
        cross_rate = fx_cross_rate(snapshot, source_currency, target)
        if cross_rate is None:
            reason = snapshot.reason or f"No consistent point-in-time FX reference path is available from {source_currency} to {target}."
            available = False
            reference_rate = None
            rate_label = "Reference FX rate unavailable; no executable conversion is provided."
            rate_legs = ()
        else:
            reference_rate = cross_rate.rate
            rate_label = cross_rate.label
            rate_legs = cross_rate.legs

    snapshot_parts = [("analysis", analysis_snapshot)] if analysis_snapshot is not None else []
    fx_checksum = snapshot.source_snapshot if snapshot is not None else None
    if fx_checksum is not None:
        snapshot_parts.append(("fx", fx_checksum))
    source_snapshot = tuple(snapshot_parts)
    projected_fields: dict[str, Mapping[str, object]] = {}
    for name, raw_value in _monetary_values(analysis):
        amount, amount_reason = _canonical_monetary_value(raw_value)
        converted: float | None
        if amount_reason is not None:
            converted = None
        elif not available or reference_rate is None:
            converted = None
            amount_reason = reason or "Currency projection is unavailable."
        else:
            assert amount is not None
            converted = amount * reference_rate
            if not math.isfinite(converted):
                converted = None
                amount_reason = "Projected monetary amount is not finite."
        projected_fields[name] = MappingProxyType(
            {
                "value": converted,
                "currency": target,
                "source_currency": source_currency,
                "source_snapshot": source_snapshot,
                "unavailable_reason": amount_reason,
            }
        )

    projection_material = {
        "analysis_source_snapshot": analysis_snapshot,
        "currency": target,
        "decision_time": decision_label,
        "fx_snapshot_checksum": fx_checksum,
        "reference_rate": reference_rate,
    }
    projection_id = hashlib.sha256(json.dumps(projection_material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return CurrencyProjection(
        projection_id=projection_id,
        schema_version="currency_projection.v1",
        version=1,
        analysis_source_snapshot=analysis_snapshot,
        source_currency=source_currency,
        currency=target,
        decision_time=decision_label,
        source_snapshot=source_snapshot,
        fx_snapshot_date=snapshot.as_of_date if snapshot is not None else None,
        fx_snapshot_checksum=fx_checksum,
        reference_rate=reference_rate,
        reference_rate_label=rate_label,
        reference_rate_legs=rate_legs,
        monetary_fields=MappingProxyType(projected_fields),
        available=available,
        reason=reason,
    )


def _analysis_decision_time(analysis: PortfolioAnalysis) -> date | datetime | str | None:
    binding = analysis.snapshot_binding
    if binding is not None and binding.as_of:
        return binding.as_of
    return analysis.candidate.source_as_of


def _decision_label(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    cleaned = str(value).strip()
    return cleaned or None


def _analysis_source_snapshot(analysis: PortfolioAnalysis) -> str | None:
    candidate = analysis.candidate
    binding = analysis.snapshot_binding
    checksum = str(binding.source_checksum if binding and binding.source_checksum else candidate.source_checksum or "").strip()
    revision = str(binding.source_revision if binding and binding.source_revision else candidate.source_revision or "").strip()
    if not checksum or checksum.casefold() == "unknown":
        return None
    material = {
        "candidate_id": candidate.candidate_id,
        "candidate_checksum": candidate.source_checksum,
        "candidate_revision": candidate.source_revision,
        "binding_snapshot_id": binding.snapshot_id if binding else None,
        "binding_source_checksum": binding.source_checksum if binding else None,
        "binding_source_revision": binding.source_revision if binding else None,
        "binding_price_checksum": binding.price_source_checksum if binding else None,
        "binding_price_revision": binding.price_source_revision if binding else None,
        "monetary_fields": [
            (name, {"value": amount, "unavailable_reason": reason})
            for name, value in _monetary_values(analysis)
            for amount, reason in (_canonical_monetary_value(value),)
        ],
    }
    if not revision:
        return None
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _canonical_monetary_value(value: object) -> tuple[float | None, str | None]:
    if value is None:
        return None, "Source monetary amount is unavailable."
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, "Source monetary amount is invalid."
    if not math.isfinite(amount):
        return None, "Source monetary amount is not finite."
    return amount, None


def _monetary_values(analysis: PortfolioAnalysis) -> tuple[tuple[str, object], ...]:
    values: list[tuple[str, object]] = [("current_value_eur", analysis.current_value_eur)]
    values.append(("candidate.analysis_notional_eur", analysis.candidate.analysis_notional_eur))
    for index, row in enumerate(analysis.allocations):
        values.append((f"allocations[{index}].signed_notional_eur", row.signed_notional_eur))
        values.append((f"allocations[{index}].market_value_eur", row.market_value_eur))
    for index, row in enumerate(analysis.holdings):
        values.append((f"holdings[{index}].market_value_eur", row.market_value_eur))

    cost = analysis.cost
    if cost is not None:
        values.extend(
            (
                ("cost.total_order_value_eur", cost.total_order_value_eur),
                ("cost.total_cost_eur", cost.total_cost_eur),
                ("cost.capacity_eur", cost.capacity_eur),
            )
        )
        for index, estimate in enumerate(cost.estimates):
            values.extend(
                (
                    (f"cost.estimates[{index}].order_value_eur", estimate.order_value_eur),
                    (f"cost.estimates[{index}].commission_eur", estimate.commission_eur),
                    (f"cost.estimates[{index}].total_cost_eur", estimate.total_cost_eur),
                    (f"cost.estimates[{index}].capacity_eur", estimate.capacity_eur),
                )
            )
    return tuple(values)
