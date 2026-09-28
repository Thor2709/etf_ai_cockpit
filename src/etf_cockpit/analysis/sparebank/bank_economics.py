"""Pure bank-economics calculations for the native Sparebank EC suite."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from .models import BankEconomics, UNAVAILABLE


@dataclass(frozen=True)
class NormalisationAdjustment:
    amount: float
    mechanism: str
    evidence_locator: str = ""
    persistence_assumption: str = ""
    tax_treatment: str = ""
    label: str = ""


@dataclass(frozen=True)
class NormalisationBridge:
    reported: float
    adjustments: tuple[NormalisationAdjustment, ...]
    normalised: float
    reported_pre_tax: float | None = None
    pre_tax_adjustments: tuple[float, ...] = ()
    normalised_pre_tax: float | None = None
    equity_denominator: float | None = None
    reported_roe: float | None = None
    normalised_roe: float | None = None
    ec_share: float | None = None
    ec_eps: float | None = None
    status: str = "resolved"


@dataclass(frozen=True)
class CreditReconciliation:
    opening_stage3: float | None = None
    new_stage3: float | None = None
    cured_stage3: float | None = None
    repaid_stage3: float | None = None
    written_off_stage3: float | None = None
    closing_stage3: float | None = None
    opening_allowance: float | None = None
    allowance_expense: float | None = None
    allowance_releases: float | None = None
    allowance_used_writeoffs: float | None = None
    closing_allowance: float | None = None
    writeoff_net_exposure: float | None = None
    new_expense_from_writeoff: float | None = None
    ratio_open: float | None = None
    ratio_close: float | None = None
    ratio_numerator_effect: float | None = None
    ratio_denominator_effect: float | None = None
    warning: str | None = None


@dataclass(frozen=True)
class CapitalResilience:
    cet1: float | None
    ppp: float | None
    credit_loss: float | None
    rwa: float | None
    target_ratio: float | None
    closing_cet1: float | None
    closing_ratio: float | None
    headroom_nok: float | None
    shortfall_nok: float | None
    loss_capacity_to_target: float | None
    rwa_capacity: float | None = None
    rwa_headroom_capacity: float | None = None
    ratio_change_numerator_effect: float | None = None
    ratio_change_rwa_effect: float | None = None
    status: str = "resolved"


@dataclass(frozen=True)
class FundingEvidence:
    status: str
    deposit_beta: float | None = None
    reference_rate: str | None = None
    window: str | None = None
    population: str | None = None
    marginal_cost: float | None = None
    average_cost: float | None = None
    lcr: float | None = None
    nsfr: float | None = None
    unavailable_fields: tuple[str, ...] = ()


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _adjustment(value: object) -> NormalisationAdjustment | None:
    if isinstance(value, NormalisationAdjustment):
        return value
    if not isinstance(value, Mapping):
        return None
    amount = _number(value.get("amount", value.get("value")))
    if amount is None:
        return None
    return NormalisationAdjustment(
        amount=amount,
        mechanism=str(value.get("mechanism", value.get("label", ""))),
        evidence_locator=str(value.get("evidence_locator", value.get("source", ""))),
        persistence_assumption=str(value.get("persistence_assumption", "")),
        tax_treatment=str(value.get("tax_treatment", "")),
        label=str(value.get("label", "")),
    )


def normalisation_bridge(
    reported: float | None,
    adjustments: Iterable[NormalisationAdjustment | Mapping[str, object]] = (),
    *,
    equity_denominator: float | None = None,
    reported_pre_tax: float | None = None,
    pre_tax_adjustments: Iterable[float] = (),
    ec_share: float | None = None,
    ec_count: float | None = None,
) -> NormalisationBridge:
    """Reconcile reported earnings to normalised earnings exactly."""

    base = _number(reported)
    parsed = tuple(item for value in adjustments if (item := _adjustment(value)) is not None)
    if base is None:
        return NormalisationBridge(0.0, parsed, 0.0, status="unavailable")
    normalised = base + sum(item.amount for item in parsed)
    pretax = _number(reported_pre_tax)
    pretax_values = tuple(
        number
        for value in pre_tax_adjustments
        if (number := _number(value if not isinstance(value, Mapping) else value.get("amount", value.get("value")))) is not None
    )
    normalised_pretax = pretax + sum(pretax_values) if pretax is not None else None
    equity = _number(equity_denominator)
    reported_roe = base / equity if equity not in (None, 0) else None
    normalised_roe = normalised / equity if equity not in (None, 0) else None
    share = _number(ec_share)
    count = _number(ec_count)
    eps = normalised * share / count if None not in (share, count) and count else None
    return NormalisationBridge(
        reported=base,
        adjustments=parsed,
        normalised=normalised,
        reported_pre_tax=pretax,
        pre_tax_adjustments=pretax_values,
        normalised_pre_tax=normalised_pretax,
        equity_denominator=equity,
        reported_roe=reported_roe,
        normalised_roe=normalised_roe,
        ec_share=share,
        ec_eps=eps,
    )


normalise_earnings = normalisation_bridge


def roe_decomposition(
    net_income: float | None,
    average_assets: float | None,
    average_common_equity: float | None,
) -> Mapping[str, float | None]:
    """Return ROA, leverage and ROE using consistent average denominators."""

    income, assets, equity = map(_number, (net_income, average_assets, average_common_equity))
    roa = income / assets if income is not None and assets not in (None, 0) else None
    leverage = assets / equity if assets is not None and equity not in (None, 0) else None
    roe = roa * leverage if roa is not None and leverage is not None else None
    return {"roa": roa, "leverage": leverage, "roe": roe}


def efficiency_effects(
    income_before: float | None,
    income_after: float | None,
    costs_before: float | None,
    costs_after: float | None,
    average_assets: float | None = None,
) -> Mapping[str, float | None]:
    """Split cost/income movement into income and cost effects."""

    ib, ia, cb, ca, assets = map(_number, (income_before, income_after, costs_before, costs_after, average_assets))
    ratio_before = cb / ib if ib not in (None, 0) and cb is not None else None
    ratio_after = ca / ia if ia not in (None, 0) and ca is not None else None
    return {
        "ratio_before": ratio_before,
        "ratio_after": ratio_after,
        "change": ratio_after - ratio_before if ratio_before is not None and ratio_after is not None else None,
        "income_effect": ca / ib - ca / ia if None not in (ca, ib, ia) and ib and ia else None,
        "cost_effect": ca / ia - cb / ia if None not in (ca, cb, ia) and ia else None,
        "cost_to_average_assets_before": cb / assets if None not in (cb, assets) and assets else None,
        "cost_to_average_assets_after": ca / assets if None not in (ca, assets) and assets else None,
    }


def credit_reconciliation(
    *,
    opening_stage3: float | None = None,
    new_stage3: float | None = None,
    cured_stage3: float | None = None,
    repaid_stage3: float | None = None,
    written_off_stage3: float | None = None,
    closing_stage3: float | None = None,
    opening_allowance: float | None = None,
    allowance_expense: float | None = None,
    allowance_releases: float | None = None,
    allowance_used_writeoffs: float | None = None,
    closing_allowance: float | None = None,
    loans_open: float | None = None,
    loans_close: float | None = None,
    stage2_open: float | None = None,
    stage2_close: float | None = None,
) -> CreditReconciliation:
    values = {name: _number(value) for name, value in locals().items() if name not in {"loans_open", "loans_close", "stage2_open", "stage2_close"}}
    opening = values["opening_stage3"]
    inferred_close = (
        opening + (values["new_stage3"] or 0.0) - (values["cured_stage3"] or 0.0)
        - (values["repaid_stage3"] or 0.0) - (values["written_off_stage3"] or 0.0)
        if opening is not None and any(values[key] is not None for key in ("new_stage3", "cured_stage3", "repaid_stage3", "written_off_stage3"))
        else None
    )
    close = values["closing_stage3"] if values["closing_stage3"] is not None else inferred_close
    allowance_close = values["closing_allowance"]
    inferred_allowance = (
        values["opening_allowance"] + (values["allowance_expense"] or 0.0) - (values["allowance_releases"] or 0.0) - (values["allowance_used_writeoffs"] or 0.0)
        if values["opening_allowance"] is not None and any(values[key] is not None for key in ("allowance_expense", "allowance_releases", "allowance_used_writeoffs"))
        else None
    )
    if allowance_close is None:
        allowance_close = inferred_allowance
    gross_open, gross_close = _number(stage2_open), _number(stage2_close)
    lo, lc = _number(loans_open), _number(loans_close)
    ratio_open = gross_open / lo if gross_open is not None and lo not in (None, 0) else None
    ratio_close = gross_close / lc if gross_close is not None and lc not in (None, 0) else None
    numerator_effect = (gross_close - gross_open) / lo if None not in (gross_open, gross_close, lo) and lo else None
    denominator_effect = gross_close / lc - gross_close / lo if None not in (gross_close, lo, lc) and lo and lc else None
    net_writeoff = (close - (allowance_close or 0.0)) if close is not None and allowance_close is not None else None
    used = values["allowance_used_writeoffs"]
    return CreditReconciliation(
        opening_stage3=opening, new_stage3=values["new_stage3"], cured_stage3=values["cured_stage3"], repaid_stage3=values["repaid_stage3"],
        written_off_stage3=values["written_off_stage3"], closing_stage3=close,
        opening_allowance=values["opening_allowance"], allowance_expense=values["allowance_expense"], allowance_releases=values["allowance_releases"], allowance_used_writeoffs=used, closing_allowance=allowance_close,
        writeoff_net_exposure=net_writeoff, new_expense_from_writeoff=0.0 if used is not None and values["allowance_expense"] in (None, 0.0) else values["allowance_expense"],
        ratio_open=ratio_open, ratio_close=ratio_close, ratio_numerator_effect=numerator_effect, ratio_denominator_effect=denominator_effect,
    )


stage_stock_flow = credit_reconciliation


def capital_resilience(
    cet1: float | None,
    ppp: float | None,
    credit_loss: float | None,
    rwa: float | None,
    target_ratio: float | None,
    *,
    prior_cet1_ratio: float | None = None,
    prior_cet1: float | None = None,
    prior_rwa: float | None = None,
) -> CapitalResilience:
    c, p, loss, r, target = map(_number, (cet1, ppp, credit_loss, rwa, target_ratio))
    closing = c + (p or 0.0) - (loss or 0.0) if c is not None else None
    ratio = closing / r if closing is not None and r not in (None, 0) else None
    headroom = closing - target * r if None not in (closing, target, r) else None
    capacity = c + (p or 0.0) - target * r if None not in (c, target, r) else None
    shortfall = headroom if headroom is not None and headroom < 0 else 0.0 if headroom is not None else None
    numerator_effect = ((c - _number(prior_cet1)) / _number(prior_rwa)) if None not in (c, _number(prior_cet1), prior_rwa) and prior_rwa else None
    rwa_effect = (c / r - c / _number(prior_rwa)) if None not in (c, r, _number(prior_rwa)) and r and _number(prior_rwa) else None
    rwa_capacity = closing / target if None not in (closing, target) and target else None
    rwa_headroom_capacity = headroom / target if None not in (headroom, target) and target else None
    return CapitalResilience(c, p, loss, r, target, closing, ratio, headroom, shortfall, capacity, rwa_capacity, rwa_headroom_capacity, numerator_effect, rwa_effect, "resolved" if None not in (c, r) else "unavailable")


capital_headroom = capital_resilience


def deposit_beta(
    deposit_rate_change: float | None,
    reference_rate_change: float | None,
    *,
    reference_rate: str | None = None,
    window: str | None = None,
    population: str | None = None,
) -> FundingEvidence:
    if not reference_rate or not window or not population or _number(reference_rate_change) in (None, 0) or _number(deposit_rate_change) is None:
        return FundingEvidence("unavailable", reference_rate=reference_rate, window=window, population=population, unavailable_fields=("deposit_beta",))
    return FundingEvidence("resolved", deposit_beta=_number(deposit_rate_change) / _number(reference_rate_change), reference_rate=reference_rate, window=window, population=population)


def build_bank_economics(evidence: Mapping[str, object] | None = None, *, bank_metrics: Iterable[object] = ()) -> BankEconomics:
    """Build the interpretation layer from EC facts and #705 metric objects."""

    values = dict(evidence or {})
    metrics: dict[str, object] = {}
    for item in bank_metrics:
        if isinstance(item, Mapping):
            name, value = item.get("metric"), item.get("value")
        else:
            name, value = getattr(item, "metric", None), getattr(item, "value", None)
        if name:
            metrics[str(name)] = value
    merged = {**metrics, **values}
    bridge = normalisation_bridge(merged.get("reported_earnings", merged.get("earnings")), merged.get("normalisation_adjustments", ()), equity_denominator=merged.get("average_common_equity", merged.get("equity")), reported_pre_tax=merged.get("reported_pre_tax"), pre_tax_adjustments=merged.get("pre_tax_adjustments", ()), ec_share=merged.get("ec_share"), ec_count=merged.get("ec_count")) if merged.get("reported_earnings", merged.get("earnings")) is not None else None
    capital = capital_resilience(merged.get("cet1"), merged.get("ppp"), merged.get("credit_loss"), merged.get("rwa"), merged.get("target_ratio")) if any(key in merged for key in ("cet1", "ppp", "credit_loss", "rwa", "target_ratio")) else None
    unavailable = tuple(name for name, value in (("lcr", metrics.get("liquidity_coverage_ratio")), ("nsfr", metrics.get("net_stable_funding_ratio"))) if value is None)
    return BankEconomics(status="resolved" if bridge or capital else "partial", reported={"metrics": metrics}, normalised=bridge.__dict__ if bridge else {}, resilience=capital.__dict__ if capital else {}, credit={}, funding={"lcr": metrics.get("liquidity_coverage_ratio", UNAVAILABLE), "nsfr": metrics.get("net_stable_funding_ratio", UNAVAILABLE)}, unavailable_fields=unavailable, coverage=(1.0 if bridge and capital else 0.5 if bridge or capital else 0.0), calculation_ids=tuple(name for name in ("normalisation_bridge" if bridge else None, "capital_resilience" if capital else None) if name))


analyse_bank_economics = build_bank_economics
calculate_capital = capital_resilience
stage_ratio_effect = credit_reconciliation


__all__ = [
    "BankEconomics", "CapitalResilience", "CreditReconciliation", "FundingEvidence", "NormalisationAdjustment", "NormalisationBridge",
    "analyse_bank_economics", "build_bank_economics", "calculate_capital", "capital_headroom", "capital_resilience", "credit_reconciliation", "deposit_beta", "efficiency_effects", "normalisation_bridge", "normalise_earnings", "roe_decomposition", "stage_ratio_effect", "stage_stock_flow",
]
