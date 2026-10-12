"""Optional, non-advisory ETF tax and currency context scenarios."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Any, Mapping

import yaml

_DISCLAIMER = "Informational only; not tax, legal, or investment advice."


@dataclass(frozen=True)
class ETFContextAssumptions:
    """Versioned assumptions supplied explicitly for an informational scenario."""

    version: int = 1
    tax_enabled: bool = False
    tax_residence_country: str | None = None
    source_withholding_rate: float | None = None
    source_withholding_label: str | None = None
    known_at: datetime | None = None
    hedge_enabled: bool = False
    hedge_ratio: float | None = None
    hedge_target_currency: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version != 1:
            raise ValueError(f"Unsupported ETF tax-context version: {self.version}")
        _validate_rate("source_withholding_rate", self.source_withholding_rate)
        _validate_rate("hedge_ratio", self.hedge_ratio)
        if not isinstance(self.tax_enabled, bool) or not isinstance(self.hedge_enabled, bool):
            raise ValueError("tax_enabled and hedge_enabled must be booleans")
        if self.known_at is not None and not isinstance(self.known_at, datetime):
            raise ValueError("known_at must be an ISO-8601 timestamp")


@dataclass(frozen=True)
class CurrencyContext:
    trading_currency: str | None
    economic_currency_weights: tuple[tuple[str, float], ...] | None
    primary_economic_currency: str | None
    trading_currency_differs_from_economic: bool | None
    economic_currency_reason: str | None
    hedge_enabled: bool
    hedge_ratio: float | None
    hedge_target_currency: str | None
    hedge_reason: str | None
    execution_allowed: bool = False
    disclaimer: str = _DISCLAIMER


@dataclass(frozen=True)
class TaxEffect:
    label: str
    rate: float
    dividend_return_rate: float
    return_drag_rate: float


@dataclass(frozen=True)
class ExcludedTaxEffect:
    label: str
    reason: str


@dataclass(frozen=True)
class NetReturnScenario:
    gross_return_rate: float | None
    dividend_return_rate: float | None
    net_return_rate: float | None
    tax_drag_rate: float | None
    included_tax_effects: tuple[TaxEffect, ...]
    excluded_tax_effects: tuple[ExcludedTaxEffect, ...]
    assumption_version: int | None
    unavailable_reason: str | None
    execution_allowed: bool = False
    disclaimer: str = _DISCLAIMER


def _validate_rate(name: str, value: float | None) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{name} must be between 0 and 1")


def load_tax_hedge_assumptions(
    config_path: str | Path | None = None,
) -> ETFContextAssumptions:
    """Load an explicit YAML assumption file; omission returns disabled defaults."""
    if config_path is None:
        return ETFContextAssumptions()
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("ETF tax-context configuration must be a mapping")
    known_at = raw.get("known_at")
    if isinstance(known_at, str):
        try:
            known_at = datetime.fromisoformat(known_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("known_at must be an ISO-8601 timestamp") from exc
    raw["known_at"] = known_at
    try:
        return ETFContextAssumptions(**raw)
    except TypeError as exc:
        raise ValueError("ETF tax-context configuration has unknown or missing fields") from exc


def build_currency_context(
    trading_currency: str | None,
    economic_currency_weights: Mapping[str, float] | None,
    assumptions: ETFContextAssumptions | None = None,
) -> CurrencyContext:
    """Keep a listing currency separate from explicitly supplied asset exposure."""
    trading = trading_currency.upper() if trading_currency else None
    weights: tuple[tuple[str, float], ...] | None = None
    primary: str | None = None
    differs: bool | None = None
    reason: str | None = None
    if not economic_currency_weights:
        reason = "Economic currency exposure was not supplied."
    else:
        combined: dict[str, float] = {}
        for currency, raw_weight in economic_currency_weights.items():
            if not isinstance(currency, str) or not currency.strip() or isinstance(raw_weight, bool):
                raise ValueError("economic currency weights must be finite fractions")
            weight = float(raw_weight)
            if not math.isfinite(weight) or not 0 <= weight <= 1:
                raise ValueError("economic currency weights must be finite fractions")
            code = currency.strip().upper()
            combined[code] = combined.get(code, 0.0) + weight
        normalised = tuple(sorted(combined.items()))
        if math.fsum(weight for _, weight in normalised) > 1 + 1e-9:
            raise ValueError("economic currency weights cannot total more than 1")
        weights = normalised
        total = math.fsum(weight for _, weight in normalised)
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            reason = "Economic currency weights are partial; the primary currency is unavailable."
        else:
            largest = max(weight for _, weight in normalised)
            leaders = [currency for currency, weight in normalised if math.isclose(weight, largest)]
            if len(leaders) != 1:
                reason = "Economic currency exposure has no unique primary currency."
            else:
                primary = leaders[0]
                if trading is None:
                    reason = "Trading currency was not supplied."
                else:
                    differs = trading != primary

    assumptions = assumptions or ETFContextAssumptions()
    hedge_ratio = assumptions.hedge_ratio if assumptions.hedge_enabled else None
    hedge_target = (
        assumptions.hedge_target_currency.upper()
        if assumptions.hedge_enabled and assumptions.hedge_target_currency
        else None
    )
    if not assumptions.hedge_enabled:
        hedge_reason = "No active currency-hedge assumption was supplied."
    elif hedge_ratio is None or hedge_target is None:
        hedge_reason = "Hedge ratio or target currency is unavailable."
    else:
        hedge_reason = None
    return CurrencyContext(
        trading,
        weights,
        primary,
        differs,
        reason,
        assumptions.hedge_enabled,
        hedge_ratio,
        hedge_target,
        hedge_reason,
    )


def calculate_core_quality_tax_bias(
    assumptions: ETFContextAssumptions | None = None,
) -> float:
    """Tax context never changes residence-neutral core ETF quality."""
    del assumptions
    return 0.0


def calculate_net_return_scenario(
    gross_return_rate: float | None,
    dividend_return_rate: float | None,
    assumptions: ETFContextAssumptions | None = None,
    decision_time: datetime | None = None,
) -> NetReturnScenario:
    """Apply only explicitly enabled source withholding; report all exclusions."""
    for name, value in (
        ("gross_return_rate", gross_return_rate),
        ("dividend_return_rate", dividend_return_rate),
    ):
        if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError(f"{name} must be finite")
    if dividend_return_rate is not None and dividend_return_rate < 0:
        raise ValueError("dividend_return_rate cannot be negative")

    included: tuple[TaxEffect, ...] = ()
    excluded: list[ExcludedTaxEffect] = []
    assumptions_usable = assumptions is not None
    unavailable_reason: str | None = None
    if assumptions is None:
        excluded.append(ExcludedTaxEffect("Source withholding", "Tax assumptions were not supplied."))
        unavailable_reason = "Tax assumptions were not supplied; only gross return is available."
    elif decision_time is not None and assumptions.known_at is None:
        assumptions_usable = False
        unavailable_reason = "Assumption known_at was not supplied for this decision time."
        excluded.append(ExcludedTaxEffect("Source withholding", unavailable_reason))
    elif decision_time is not None and assumptions.known_at is not None:
        try:
            is_future = assumptions.known_at > decision_time
        except TypeError as exc:
            raise ValueError("known_at and decision_time must use compatible time zones") from exc
        if is_future:
            assumptions_usable = False
            unavailable_reason = "Assumption was not known at the decision time."
            excluded.append(ExcludedTaxEffect("Source withholding", unavailable_reason))

    if assumptions is not None and assumptions_usable:
        if not assumptions.tax_enabled:
            excluded.append(ExcludedTaxEffect("Source withholding", "Tax assumptions are disabled."))
            unavailable_reason = "Tax assumptions are disabled; only gross return is available."
        elif assumptions.source_withholding_rate is None:
            excluded.append(
                ExcludedTaxEffect("Source withholding", "Withholding rate was not supplied.")
            )
            unavailable_reason = "Withholding rate was not supplied."
        elif dividend_return_rate is None:
            excluded.append(
                ExcludedTaxEffect("Source withholding", "Dividend return input was not supplied.")
            )
            unavailable_reason = "Dividend return input was not supplied."
        else:
            label = assumptions.source_withholding_label or "Source dividend withholding"
            drag = dividend_return_rate * assumptions.source_withholding_rate
            included = (
                TaxEffect(label, assumptions.source_withholding_rate, dividend_return_rate, drag),
            )

    residence_reason = (
        "Tax residence was not supplied; no residence-based rate was inferred."
        if assumptions is None or not assumptions.tax_residence_country
        else "Residence-specific rates were not supplied."
    )
    excluded.append(ExcludedTaxEffect("Residence-based tax", residence_reason))

    tax_drag = math.fsum(effect.return_drag_rate for effect in included) if included else None
    net_return = (
        gross_return_rate - tax_drag
        if gross_return_rate is not None and tax_drag is not None
        else None
    )
    if gross_return_rate is None and unavailable_reason is None:
        unavailable_reason = "Gross return input was not supplied."
    elif net_return is None and unavailable_reason is None:
        unavailable_reason = "No complete included tax effect was available."
    return NetReturnScenario(
        gross_return_rate,
        dividend_return_rate,
        net_return,
        tax_drag,
        included,
        tuple(excluded),
        assumptions.version if assumptions is not None else None,
        unavailable_reason,
    )


def build_etf_tax_context_panel(
    structure: Mapping[str, object] | None,
    economics: Mapping[str, object] | None,
    *,
    trading_currency: str | None,
    share_class_id: str | None = None,
    economic_currency_weights: Mapping[str, float] | None = None,
    assumptions: ETFContextAssumptions | None = None,
    decision_time: datetime | None = None,
) -> dict[str, Any]:
    """Join existing dated ETF structure/economics evidence without inference."""

    usable_assumptions = assumptions
    assumptions_reason: str | None = None
    if assumptions is not None and assumptions.known_at is not None:
        if decision_time is None:
            usable_assumptions = None
            assumptions_reason = "Decision time is unavailable for dated tax and hedge assumptions."
        else:
            try:
                is_future = assumptions.known_at > decision_time
            except TypeError:
                is_future = True
                assumptions_reason = "Assumption and decision timestamps use incompatible time zones."
            if is_future:
                usable_assumptions = None
                assumptions_reason = assumptions_reason or "Assumptions were not known at the decision time."

    structure_fields = structure.get("fields") if isinstance(structure, Mapping) else None
    domicile_claim = structure_fields.get("domicile") if isinstance(structure_fields, Mapping) else None
    domicile = _structure_evidence(domicile_claim)

    economics = economics if isinstance(economics, Mapping) else {}
    e1 = economics.get("e1")
    e1 = e1 if isinstance(e1, Mapping) else {}
    distribution_policy = _economics_evidence(e1.get("distribution_policy"))
    fund_metrics = economics.get("fund_metrics")
    fund_metrics = fund_metrics if isinstance(fund_metrics, Mapping) else {}
    share_classes = economics.get("share_class_metrics")
    share_classes = share_classes if isinstance(share_classes, Mapping) else {}
    class_metrics = share_classes.get(share_class_id) if share_class_id else None
    class_metrics = class_metrics if isinstance(class_metrics, Mapping) else None
    if share_class_id is not None:
        distribution_metrics = class_metrics or {}
    else:
        distribution_metrics = fund_metrics
    frequency = _fund_metric_evidence(distribution_metrics, "distribution_frequency")
    distribution_amount = _fund_metric_evidence(
        distribution_metrics,
        "distribution_amount",
        require_currency=True,
    )
    distribution_available = any(
        field["status"] == "available"
        for field in (distribution_policy, frequency, distribution_amount)
    )
    distribution = {
        "status": "available" if distribution_available else "unavailable",
        "policy": distribution_policy,
        "frequency": frequency,
        "amount": distribution_amount,
        "share_class_id": share_class_id if class_metrics is not None else None,
        "scope": "share_class" if class_metrics is not None else "fund" if share_class_id is None else "unavailable",
        "execution_allowed": False,
    }
    if not distribution_available:
        distribution["reason"] = "No dated distribution-policy or share-class distribution evidence was supplied."

    currency = build_currency_context(
        trading_currency,
        economic_currency_weights,
        usable_assumptions,
    )
    try:
        tax_scenario = calculate_net_return_scenario(
            None,
            None,
            usable_assumptions,
            decision_time,
        )
        tax = asdict(tax_scenario)
        tax["status"] = "available" if tax_scenario.net_return_rate is not None else "unavailable"
        tax["reason"] = tax_scenario.unavailable_reason
    except ValueError as exc:
        tax = {
            "status": "unavailable",
            "net_return_rate": None,
            "tax_drag_rate": None,
            "included_tax_effects": (),
            "excluded_tax_effects": (),
            "assumption_version": usable_assumptions.version if usable_assumptions is not None else None,
            "reason": str(exc),
            "execution_allowed": False,
            "disclaimer": _DISCLAIMER,
        }
    excluded_effects = tax.get("excluded_tax_effects") or ()
    residence_reason = next(
        (
            item.get("reason")
            for item in excluded_effects
            if isinstance(item, Mapping) and item.get("label") == "Residence-based tax"
        ),
        "Residence-specific rates and accepted source evidence were not supplied.",
    )
    hedge_assumption_status = (
        "available"
        if currency.hedge_enabled
        and currency.hedge_ratio is not None
        and currency.hedge_target_currency is not None
        else "unavailable"
    )
    hedge_assumption = {
        "status": hedge_assumption_status,
        "enabled": currency.hedge_enabled,
        "ratio": currency.hedge_ratio,
        "target_currency": currency.hedge_target_currency,
        "reason": currency.hedge_reason,
        "execution_allowed": False,
    }
    has_context = (
        domicile["status"] == "available"
        or distribution_available
        or currency.trading_currency is not None
    )
    return {
        "status": "partial" if has_context else "unavailable",
        "assumptions": {
            "status": "available" if usable_assumptions is not None else "unavailable",
            "version": usable_assumptions.version if usable_assumptions is not None else None,
            "reason": assumptions_reason,
            "execution_allowed": False,
        },
        "domicile": domicile,
        "distribution": distribution,
        "currency": asdict(currency),
        "source_withholding": tax,
        "residence_tax": {
            "status": "unavailable",
            "value": None,
            "reason": residence_reason,
            "execution_allowed": False,
        },
        "hedge_assumption": hedge_assumption,
        "hedge_economics": {
            "status": "unavailable",
            "value": None,
            "reason": "Hedge cost and benefit evidence and an owner-approved methodology were not supplied.",
            "execution_allowed": False,
        },
        "execution_allowed": False,
        "disclaimer": _DISCLAIMER,
    }


def _structure_evidence(value: object) -> dict[str, object]:
    if isinstance(value, Mapping) and value.get("status") == "resolved":
        text = value.get("value")
        source = value.get("source_id")
        as_of = value.get("document_date")
        known_at = value.get("known_at")
        checksum = value.get("checksum")
        if (
            isinstance(text, str)
            and text.strip()
            and isinstance(source, str)
            and source.strip()
            and as_of not in (None, "", "unavailable")
            and known_at not in (None, "", "unavailable")
            and checksum not in (None, "", "unavailable")
        ):
            return {
                "status": "available",
                "value": text.strip(),
                "source": source,
                "as_of": as_of,
                "known_at": known_at,
                "document_id": value.get("document_id"),
                "page": value.get("page"),
                "checksum": value.get("checksum"),
                "reason": None,
                "execution_allowed": False,
            }
    status = value.get("status") if isinstance(value, Mapping) else "unavailable"
    return {
        "status": "unavailable",
        "value": None,
        "source": None,
        "as_of": None,
        "known_at": None,
        "reason": f"Domicile evidence is not resolved ({status}).",
        "execution_allowed": False,
    }


def _economics_evidence(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        item = value.get("value")
        source = value.get("source")
        as_of = value.get("as_of")
        known_at = value.get("known_at")
        if (
            isinstance(item, str)
            and item in {"accumulating", "distributing"}
            and isinstance(source, str)
            and source.strip()
            and as_of not in (None, "", "unavailable")
            and known_at not in (None, "", "unavailable")
        ):
            return {
                "status": "available",
                "value": item,
                "source": source,
                "as_of": as_of,
                "known_at": known_at,
                "reason": None,
                "execution_allowed": False,
            }
        reason = value.get("reason") or "Distribution policy lacks a valid value or dated source binding."
    else:
        reason = "Distribution policy evidence is unavailable."
    return {
        "status": "unavailable",
        "value": None,
        "source": None,
        "as_of": None,
        "known_at": None,
        "reason": str(reason),
        "execution_allowed": False,
    }


def _fund_metric_evidence(
    metrics: Mapping[str, object],
    name: str,
    *,
    require_currency: bool = False,
) -> dict[str, object]:
    value = metrics.get(name)
    source = metrics.get("source_id")
    as_of = metrics.get("evidence_as_of") or metrics.get("as_of")
    known_at = metrics.get("evidence_known_at") or metrics.get("known_at")
    currency = metrics.get("distribution_currency")
    valid = (
        value is not None
        and isinstance(source, str)
        and bool(source.strip())
        and as_of not in (None, "", "unavailable")
        and known_at not in (None, "", "unavailable")
    )
    if require_currency:
        valid = valid and isinstance(currency, str) and bool(currency.strip())
    if valid and name == "distribution_frequency":
        valid = isinstance(value, str) and bool(value.strip())
    if valid and name == "distribution_amount":
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
    if valid:
        return {
            "status": "available",
            "value": value,
            "currency": currency if require_currency else None,
            "source": source,
            "as_of": as_of,
            "known_at": known_at,
            "reason": None,
            "execution_allowed": False,
        }
    reason = (
        "Distribution amount currency is unavailable."
        if value is not None and require_currency and not currency
        else f"{name.replace('_', ' ').capitalize()} lacks a valid dated source binding."
    )
    return {
        "status": "unavailable",
        "value": None,
        "currency": None,
        "source": None,
        "as_of": None,
        "known_at": None,
        "reason": reason,
        "execution_allowed": False,
    }
