"""Optional, non-advisory ETF tax and currency context scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Mapping

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
