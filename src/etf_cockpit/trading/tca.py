"""Paper fill transaction-cost attribution and completed-fill calibration."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

TCA_SCHEMA_VERSION = "tca_attribution.v1"


@dataclass(frozen=True)
class TCAAttributionRecord:
    """Derived, read-only attribution for one recorded fill."""

    attribution_id: str
    schema_version: str
    account_id: str
    fill_id: str
    order_id: str | None
    proposal_id: str | None
    run_id: str | None
    instrument_id: str | None
    side: str | None
    order_status: str
    association_status: str
    quantity: float | None
    price: float | None
    currency: str | None
    fill_as_of: str | None
    fee: float | None
    ledger_fee_reconciliation: str
    reference_price: float | None
    reference_source: str | None
    benchmark_decision_time: str | None
    benchmark_arrival_time: str | None
    benchmark_source_authority: str | None
    benchmark_source_checksum: str | None
    estimated_total_cost: float | None
    realised_price_slippage: float | None
    realised_fee: float | None
    realised_total_cost: float | None
    estimated_to_realised_variance: float | None
    delay_cost: float | None
    spread_cost: float | None
    impact_cost: float | None
    component_total_slippage: float | None
    reconciliation_status: str
    realised_cost_bps: float | None
    completed_order: bool
    calibration_eligible: bool
    cost_forecast: Mapping[str, object] | None
    benchmark_limitations: tuple[str, ...]
    source_authority: str = "local_paper_ledger"
    execution_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        """Return a detached JSON-compatible projection."""

        result = asdict(self)
        result["cost_forecast"] = copy.deepcopy(self.cost_forecast)
        result["benchmark_limitations"] = list(self.benchmark_limitations)
        return result


class TCACalculator:
    """Calculate signed fill slippage, known fees and benchmark decomposition."""

    def calculate(
        self,
        fill: Mapping[str, object],
        order: Mapping[str, object] | None = None,
        *,
        cost_forecast: Mapping[str, object] | None = None,
        benchmark: Mapping[str, object] | None = None,
        account_id: str = "local-paper",
    ) -> TCAAttributionRecord:
        fill_id = _text(fill.get("fill_id") or fill.get("paper_trade_id"))
        order_id = _text(fill.get("order_id"))
        matched_order = order is not None and order_id is not None and _text(order.get("order_id")) == order_id
        linked_order = order if matched_order else None
        proposal_id = _text(linked_order.get("proposal_id")) if linked_order is not None else None
        order_status = str((linked_order or {}).get("status") or fill.get("status") or "unknown")
        association_status = "order_linked" if matched_order else "unexpected"
        side = str((linked_order or {}).get("side") or fill.get("side") or "").strip().lower() or None
        direction = 1.0 if side == "buy" else -1.0 if side == "sell" else None
        raw_quantity = _number(fill.get("quantity"))
        raw_price = _number(fill.get("price"))
        raw_fee = _number(fill.get("fee"))
        quantity = raw_quantity if raw_quantity is not None and raw_quantity > 0 else None
        price = raw_price if raw_price is not None and raw_price > 0 else None
        fee = raw_fee if raw_fee is not None and raw_fee >= 0 else None
        currency = _text(fill.get("currency") or (linked_order or {}).get("currency"))
        instrument_id = _text(fill.get("instrument_id") or (linked_order or {}).get("instrument_id"))
        run_id = _text((linked_order or {}).get("run_id"))
        if run_id is None and linked_order is not None:
            snapshot = linked_order.get("proposal_snapshot")
            if isinstance(snapshot, Mapping):
                run_id = _text(snapshot.get("run_id"))

        frozen_forecast = copy.deepcopy(cost_forecast) if cost_forecast is not None else _forecast_from_order(linked_order)
        forecast_currency, forecast_total = _forecast_total(frozen_forecast)
        order_quantity = _number((linked_order or {}).get("quantity"))
        if forecast_total is not None and order_quantity is not None and quantity is not None and order_quantity > 0:
            estimated_total = forecast_total * quantity / order_quantity
        else:
            estimated_total = None
        if forecast_total is not None and (
            forecast_currency is None or currency is None or forecast_currency.upper() != currency.upper()
        ):
            estimated_total = None

        decision_price = _number((benchmark or {}).get("decision_price"))
        if decision_price is not None and decision_price <= 0:
            decision_price = None
        reference = decision_price
        reference_source = _text((benchmark or {}).get("reference_source"))
        if reference is None:
            reference = _number((benchmark or {}).get("reference_price"))
        if reference is None and linked_order is not None:
            reference = _number(linked_order.get("execution_price"))
            if reference is not None:
                reference_source = "paper_order_execution_quote"
        if reference is not None and reference <= 0:
            reference = None
        realised_slippage = (
            direction * quantity * (price - reference)
            if direction is not None and quantity is not None and price is not None and reference is not None
            else None
        )

        delay_cost: float | None = None
        spread_cost: float | None = None
        impact_cost: float | None = None
        component_total: float | None = None
        limitations: list[str] = []
        arrival_mid = _number((benchmark or {}).get("arrival_mid_price"))
        if arrival_mid is not None and arrival_mid <= 0:
            arrival_mid = None
        arrival_spread_bps = _number((benchmark or {}).get("arrival_spread_bps"))
        if decision_price is None or arrival_mid is None:
            limitations.append("decision_or_arrival_midpoint_unavailable")
        elif direction is not None and quantity is not None:
            delay_cost = direction * quantity * (arrival_mid - decision_price)
        if arrival_spread_bps is None:
            limitations.append("arrival_spread_unavailable")
        elif arrival_spread_bps < 0:
            limitations.append("arrival_spread_invalid")
        elif arrival_mid is not None and quantity is not None:
            spread_cost = quantity * arrival_mid * arrival_spread_bps / 20_000.0
        if realised_slippage is not None and delay_cost is not None and spread_cost is not None:
            impact_cost = realised_slippage - delay_cost - spread_cost
            component_total = delay_cost + spread_cost + impact_cost
            reconciliation_status = "reconciled" if math.isclose(component_total, realised_slippage, rel_tol=1e-10, abs_tol=1e-8) else "mismatch"
        else:
            reconciliation_status = "incomplete"
        if reference is None:
            limitations.append("pre_fill_reference_price_unavailable")
        if quantity is None:
            limitations.append("fill_quantity_unavailable")
        if price is None:
            limitations.append("fill_price_unavailable")
        if fee is None:
            limitations.append("fill_fee_unavailable")
        if association_status == "unexpected":
            limitations.append("order_association_unavailable")
        elif proposal_id is None:
            limitations.append("proposal_association_unavailable")
        if frozen_forecast is None:
            limitations.append("cost_forecast_unavailable")
        elif estimated_total is None:
            limitations.append("forecast_currency_or_order_quantity_unavailable")
        if currency is None:
            limitations.append("fill_currency_unavailable")
        realised_total = (
            realised_slippage + fee
            if realised_slippage is not None and fee is not None and currency is not None
            else None
        )
        variance = realised_total - estimated_total if realised_total is not None and estimated_total is not None else None
        filled_value = quantity * price if quantity is not None and price is not None else None
        realised_cost_bps = realised_total / filled_value * 10_000.0 if realised_total is not None and filled_value and filled_value > 0 else None
        filled_quantity = _number((linked_order or {}).get("filled_quantity"))
        completed_order = (
            linked_order is not None
            and order_status == "filled"
            and order_quantity is not None
            and order_quantity > 0
            and filled_quantity is not None
            and filled_quantity + 1e-8 >= order_quantity
        )
        calibration_eligible = completed_order and realised_cost_bps is not None
        stable_fill_id = fill_id or "unknown-fill"
        attribution_id = hashlib.sha256(f"{account_id}\0{stable_fill_id}".encode("utf-8")).hexdigest()
        return TCAAttributionRecord(
            attribution_id=attribution_id,
            schema_version=TCA_SCHEMA_VERSION,
            account_id=str(account_id),
            fill_id=stable_fill_id,
            order_id=order_id,
            proposal_id=proposal_id,
            run_id=run_id,
            instrument_id=instrument_id,
            side=side,
            order_status=order_status,
            association_status=association_status,
            quantity=quantity,
            price=price,
            currency=currency,
            fill_as_of=_text(fill.get("as_of")),
            fee=fee,
            ledger_fee_reconciliation="matched" if fee is not None else "unavailable",
            reference_price=reference,
            reference_source=reference_source,
            benchmark_decision_time=_text((benchmark or {}).get("decision_time")),
            benchmark_arrival_time=_text((benchmark or {}).get("arrival_time")),
            benchmark_source_authority=_text((benchmark or {}).get("source_authority")),
            benchmark_source_checksum=_text((benchmark or {}).get("source_checksum")),
            estimated_total_cost=estimated_total,
            realised_price_slippage=realised_slippage,
            realised_fee=fee,
            realised_total_cost=realised_total,
            estimated_to_realised_variance=variance,
            delay_cost=delay_cost,
            spread_cost=spread_cost,
            impact_cost=impact_cost,
            component_total_slippage=component_total,
            reconciliation_status=reconciliation_status,
            realised_cost_bps=realised_cost_bps,
            completed_order=completed_order,
            calibration_eligible=calibration_eligible,
            cost_forecast=frozen_forecast,
            benchmark_limitations=tuple(dict.fromkeys(limitations)),
        )


def calibrate_completed_fills(records: Sequence[TCAAttributionRecord | Mapping[str, object]]) -> dict[str, object]:
    """Summarise observed cost only from fully completed, attributable orders."""

    samples: list[float] = []
    for record in records:
        row = record.as_dict() if isinstance(record, TCAAttributionRecord) else record
        if row.get("calibration_eligible") is not True or row.get("completed_order") is not True:
            continue
        value = _number(row.get("realised_cost_bps"))
        if value is not None:
            samples.append(value)
    return {
        "sample_count": len(samples),
        "mean_realised_cost_bps": sum(samples) / len(samples) if samples else None,
        "reason": None if samples else "no_completed_fills_with_known_cost",
        "source_authority": "completed_paper_fills",
        "execution_allowed": False,
    }


class TCAAttributionStore:
    """Persist one idempotent JSON record per paper fill."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def persist(self, records: Sequence[TCAAttributionRecord]) -> int:
        persisted = 0
        for record in records:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{record.attribution_id}.json"
            encoded = json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
            if path.exists() and path.read_text(encoding="utf-8") == encoded:
                continue
            handle_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=self.directory, delete=False) as handle:
                    handle_name = handle.name
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(handle_name, path)
            finally:
                if handle_name is not None and os.path.exists(handle_name):
                    os.unlink(handle_name)
            persisted += 1
        return persisted

    def load(self) -> tuple[dict[str, object], ...]:
        if not self.directory.exists():
            return ()
        rows: list[dict[str, object]] = []
        for path in sorted(self.directory.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema_version") != TCA_SCHEMA_VERSION:
                raise ValueError(f"TCA attribution record is invalid: {path.name}")
            rows.append(value)
        return tuple(rows)


def _forecast_from_order(order: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if order is None:
        return None
    direct = order.get("cost_forecast")
    snapshot = order.get("proposal_snapshot")
    if not isinstance(direct, Mapping) and isinstance(snapshot, Mapping):
        direct = snapshot.get("cost_forecast") or snapshot.get("cost_estimate")
    return copy.deepcopy(direct) if isinstance(direct, Mapping) else None


def _forecast_total(forecast: Mapping[str, object] | None) -> tuple[str | None, float | None]:
    if forecast is None:
        return None, None
    currency = _text(forecast.get("currency"))
    total = _number(forecast.get("total_cost_eur"))
    if total is not None:
        return currency or "EUR", total
    total = _number(forecast.get("total_cost"))
    if total is not None:
        return currency, total
    cost_bps = _number(forecast.get("total_cost_bps"))
    order_value = _number(forecast.get("order_value_eur"))
    if cost_bps is not None and order_value is not None:
        return currency or "EUR", order_value * cost_bps / 10_000.0
    return currency, None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "TCAAttributionRecord",
    "TCAAttributionStore",
    "TCACalculator",
    "calibrate_completed_fills",
]
