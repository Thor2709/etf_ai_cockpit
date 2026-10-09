"""Pure bank-economics calculations for the native Sparebank EC suite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from . import book_calcs
from .models import BankEconomics, UNAVAILABLE

from etf_cockpit.core.values import finite_float_or_none as _number

# Plain-language reasons shown next to a missing scorecard input (SB2). Keys are scorecard input ids.
MISSING_REASONS: dict[str, str] = {
    "cet1_headroom_pp": "Needs the bank's CET1 requirement (legal minimum plus buffers and Pillar 2) from its Pillar 3 or annual report; confirm it in the Pillar 3 queue.",
    "cost_of_risk_bps": "Needs impairment losses and loans in two consecutive annual statements.",
    "stage_3_ratio_pct": "The Stage 3 share is only printed in the notes or Pillar 3 report; confirm it in the Pillar 3 queue.",
    "lcr_pct": "LCR is printed in the Pillar 3 or annual report only; confirm it in the Pillar 3 queue.",
    "nsfr_pct": "NSFR is printed in the Pillar 3 or annual report only; confirm it in the Pillar 3 queue.",
    "deposit_to_loan_ratio_pct": "Deposit coverage is printed in the annual report or Pillar 3; it is not tagged in the filing.",
    "normalised_roe_minus_cost_of_equity_pp": "Needs the EC-attributable result and the owner capital pools from the filing.",
}


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
    reported: float | None
    adjustments: tuple[NormalisationAdjustment, ...]
    normalised: float | None
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
        return NormalisationBridge(None, parsed, None, equity_denominator=_number(equity_denominator), status="unavailable")
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
    stage3_flow_fields = ("new_stage3", "cured_stage3", "repaid_stage3", "written_off_stage3")
    allowance_flow_fields = ("allowance_expense", "allowance_releases", "allowance_used_writeoffs")
    warnings: list[str] = []
    stage3_flows_complete = all(values[key] is not None for key in stage3_flow_fields)
    inferred_close = (
        opening + values["new_stage3"] - values["cured_stage3"]
        - values["repaid_stage3"] - values["written_off_stage3"]
        if opening is not None and stage3_flows_complete
        else None
    )
    if opening is not None and values["closing_stage3"] is None and not stage3_flows_complete:
        warnings.append("stage3_flow_inputs_incomplete")
    close = values["closing_stage3"] if values["closing_stage3"] is not None else inferred_close
    allowance_close = values["closing_allowance"]
    allowance_flows_complete = all(values[key] is not None for key in allowance_flow_fields)
    inferred_allowance = (
        values["opening_allowance"] + values["allowance_expense"] - values["allowance_releases"] - values["allowance_used_writeoffs"]
        if values["opening_allowance"] is not None and allowance_flows_complete
        else None
    )
    if values["opening_allowance"] is not None and values["closing_allowance"] is None and not allowance_flows_complete:
        warnings.append("allowance_flow_inputs_incomplete")
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
        writeoff_net_exposure=net_writeoff, new_expense_from_writeoff=values["allowance_expense"],
        ratio_open=ratio_open, ratio_close=ratio_close, ratio_numerator_effect=numerator_effect, ratio_denominator_effect=denominator_effect,
        warning=";".join(warnings) or None,
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
    # PPP and credit loss are additive capital inputs, not optional terms. A
    # missing component must not be interpreted as zero.
    closing = c + p - loss if None not in (c, p, loss) else None
    ratio = closing / r if closing is not None and r not in (None, 0) else None
    headroom = closing - target * r if None not in (closing, target, r) else None
    capacity = c + p - target * r if None not in (c, p, target, r) else None
    shortfall = headroom if headroom is not None and headroom < 0 else 0.0 if headroom is not None else None
    numerator_effect = ((c - _number(prior_cet1)) / _number(prior_rwa)) if None not in (c, _number(prior_cet1), prior_rwa) and prior_rwa else None
    rwa_effect = (c / r - c / _number(prior_rwa)) if None not in (c, r, _number(prior_rwa)) and r and _number(prior_rwa) else None
    rwa_capacity = closing / target if None not in (closing, target) and target else None
    rwa_headroom_capacity = headroom / target if None not in (headroom, target) and target else None
    status = "resolved" if None not in (c, p, loss, r, target) else "unavailable"
    return CapitalResilience(c, p, loss, r, target, closing, ratio, headroom, shortfall, capacity, rwa_capacity, rwa_headroom_capacity, numerator_effect, rwa_effect, status)


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


def _statement_value(statements: Mapping[str, object] | None, side: str, name: str) -> float | None:
    block = statements.get(side) if isinstance(statements, Mapping) else None
    return _number(block.get(name)) if isinstance(block, Mapping) else None


def lending_economics(metrics: Mapping[str, object], statements: Mapping[str, object] | None) -> dict[str, object]:
    """Lending axis inputs: risk-adjusted margin (eq. 1.14), growth divergences (p. 96), cost-to-assets (p. 54)."""

    nim, cor = _number(metrics.get("net_interest_margin")), _number(metrics.get("cost_of_risk"))
    loan_growth, deposit_growth = _number(metrics.get("loan_growth")), _number(metrics.get("deposit_growth"))
    nii_now = _statement_value(statements, "current", "net_interest_income")
    nii_before = _statement_value(statements, "prior", "net_interest_income")
    nii_growth = book_calcs.growth_rate(nii_before, nii_now)
    assets_now = _statement_value(statements, "current", "total_assets")
    assets_before = _statement_value(statements, "prior", "total_assets")
    average_assets = (assets_now + assets_before) / 2 if assets_now is not None and assets_before is not None else None
    opex = _statement_value(statements, "current", "operating_expenses")
    equity_growth = book_calcs.growth_rate(_statement_value(statements, "prior", "equity"), _statement_value(statements, "current", "equity"))
    asset_growth = book_calcs.growth_rate(assets_before, assets_now)
    return {
        "net_interest_margin": nim,
        "cost_of_risk": cor,
        "risk_adjusted_margin": book_calcs.risk_adjusted_lending_spread(nim, cor),
        "loan_growth": loan_growth,
        "deposit_growth": deposit_growth,
        "loan_minus_deposit_growth": book_calcs.growth_gap(loan_growth, deposit_growth),
        "nii_growth": nii_growth,
        "nii_minus_loan_growth": book_calcs.growth_gap(nii_growth, loan_growth),
        "cost_to_average_assets": book_calcs.cost_to_assets(opex, average_assets),
        "equity_growth": equity_growth,
        "asset_growth": asset_growth,
        "capital_self_funding_gap": book_calcs.growth_gap(equity_growth, asset_growth),
        "period": statements.get("period_end") if isinstance(statements, Mapping) else None,
        "prior_period": statements.get("prior_period_end") if isinstance(statements, Mapping) else None,
    }


_STATUTORY_TAX_RATE = 0.25  # Norwegian financial-sector rate (22 % + 3 % financial-activities surcharge); fallback only.


def owner_normalisation(
    bank: BankEconomics,
    claim: object,
    *,
    sustainable_roe_assumption: object | None = None,
    assumption_source: str | None = None,
) -> BankEconomics:
    """Sustainable ROE bridge on the EC owner claim (book eq. 3.5 / 5.10, p. 47 and p. 104).

    Starts from the EC-attributable result and the owner capital pools of the filing and applies
    only adjustments the filed statements evidence: credit losses are never normalised below the
    average of the filed years (benign years are haircut, high years are not added back without
    evidence of a one-off; book 5.2.3-5.2.4, p. 103). Every adjustment keeps its audit trail.
    Sustainable ROE is withheld when loss-cycle, owner-share, securities/alliance, or rate-cycle
    bridge inputs are missing. An explicit owner sustainable-ROE assumption is labelled separately.
    """

    from dataclasses import replace

    statements = bank.reported.get("statements") if isinstance(bank.reported, Mapping) else None
    earnings = _number(getattr(claim, "owner_attributable_earnings", None))
    book = _number(getattr(claim, "owner_attributable_book", None))
    book_basis = "owner_attributable_book"
    if book is None:
        book = _number(getattr(claim, "owner_pool_total", None))
        book_basis = "owner_pool_total"
    share = _number(getattr(claim, "reconstructed_eierbrok", None))
    if share is None:
        share = _number(getattr(claim, "reported_eierbrok", None))
    reasons = dict(bank.reasons)
    key = "normalised_roe_minus_cost_of_equity_pp"
    reported_roe = earnings / book if earnings is not None and book is not None and book > 0 else None
    assumption = _number(sustainable_roe_assumption)
    if assumption is not None:
        normalised = {
            "reported_roe": reported_roe,
            "normalised_roe": assumption,
            "status": "resolved",
            "owner_assumption": True,
            "assumption_source": assumption_source or "explicit owner sustainable-ROE assumption",
            "owner_book_basis": "owner_attributable_book" if _number(getattr(claim, "owner_attributable_book", None)) is not None else "owner_pool_total",
            "adjustments": (),
            "missing_components": (),
        }
        reasons.pop(key, None)
        return replace(bank, normalised=normalised, reasons=reasons)

    if earnings is None or book is None or book <= 0:
        missing = "the EC-attributable result" if earnings is None else "the owner capital pools"
        reasons[key] = f"Needs {missing} from the filing (the owner claim is not fully reconstructed)."
        return replace(bank, normalised={}, reasons=reasons)

    current_loss = _statement_value(statements, "current", "impairment_losses")
    prior_loss = _statement_value(statements, "prior", "impairment_losses")
    missing_components = []
    if earnings is None:
        missing_components.append("EC-attributable result")
    if book is None or book <= 0:
        missing_components.append("positive owner-capital denominator")
    if current_loss is None:
        missing_components.append("current-period impairment losses")
    if prior_loss is None:
        missing_components.append("prior-period impairment losses")
    if share is None:
        missing_components.append("reported or reconstructed eierbrøk")
    missing_components.extend(("securities/alliance and one-off gain history", "rate-cycle deposit-cost history"))
    pre_tax = _statement_value(statements, "current", "income_before_tax")
    tax = _statement_value(statements, "current", "income_tax")
    tax_rate = tax / pre_tax if pre_tax and tax is not None and pre_tax > 0 and 0.0 <= tax / pre_tax <= 0.5 else None
    tax_source = "effective rate of the filing (income tax / profit before tax)"
    if tax_rate is None:
        tax_rate, tax_source = _STATUTORY_TAX_RATE, "statutory fallback 25 % (filing does not give a usable effective rate)"
    adjustments: list[NormalisationAdjustment] = []
    if current_loss is not None and prior_loss is not None and share is not None:
        through_cycle = max(current_loss, (current_loss + prior_loss) / 2.0)
        extra_loss = through_cycle - current_loss
        amount = -book_calcs.tax_effected(extra_loss, tax_rate) * share if extra_loss > 0 else 0.0
        adjustments.append(
            NormalisationAdjustment(
                amount=amount,
                mechanism="credit losses normalised to the average of the two filed years when the current year is below it (never below)",
                evidence_locator="statement facts: impairment losses, current and prior year of the same filing",
                persistence_assumption="permanent: low losses are not capitalised indefinitely (book 5.2.3, p. 103)",
                tax_treatment=f"tax-effected at {tax_rate:.1%} ({tax_source}); allocated to the EC owner claim by eierbrok",
                label="Through-cycle credit loss",
            )
        )
    bridge = normalisation_bridge(earnings, adjustments, equity_denominator=book)
    normalised = dict(bridge.__dict__)
    normalised.update(
        reported_roe=reported_roe,
        owner_book_basis=book_basis,
        denominator_basis="closing owner capital (conservative versus the average the book prefers, eq. 1.22)",
        tax_rate=tax_rate,
        tax_rate_source=tax_source,
        not_adjusted=(
            "securities, alliance and one-off gains: the filing carries no multi-year history to separate them (book p. 60)",
            "rate-cycle spread windfall (deposit beta needs the deposit cost history, book p. 5)",
        ),
        status="resolved",
        missing_components=(),
    )
    if missing_components:
        normalised.update(
            normalised_roe=None,
            status="unavailable",
            missing_components=tuple(missing_components),
            reason_code="SUSTAINABLE_ROE_BRIDGE_INPUTS_MISSING",
        )
        reasons[key] = "Sustainable ROE unavailable; missing bridge inputs: " + ", ".join(missing_components) + "."
        return replace(bank, normalised=normalised, reasons=reasons)
    reasons.pop(key, None)
    return replace(bank, normalised=normalised, reasons=reasons, calculation_ids=tuple(dict.fromkeys((*bank.calculation_ids, "normalisation_bridge"))))


def build_bank_economics(evidence: Mapping[str, object] | None = None, *, bank_metrics: Iterable[object] = ()) -> BankEconomics:
    """Build the interpretation layer from EC facts and #705 metric objects."""

    values = dict(evidence or {})
    metrics: dict[str, object] = {}
    metric_sources: dict[str, str] = {}
    metric_evidence_ids: list[str] = []
    for item in bank_metrics:
        if isinstance(item, Mapping):
            name, value = item.get("metric"), item.get("value")
            metric_evidence_ids.extend(str(item[key]) for key in ("evidence_id", "source_id", "source_url") if item.get(key))
            source = item.get("source") or item.get("source_locator") or item.get("source_url") or item.get("source_id")
        else:
            name, value = getattr(item, "metric", None), getattr(item, "value", None)
            metric_evidence_ids.extend(str(getattr(item, key)) for key in ("evidence_id", "source_id", "source_url") if getattr(item, key, None))
            source = getattr(item, "source", None) or getattr(item, "source_locator", None) or getattr(item, "source_id", None)
        if name:
            metrics[str(name)] = value
            if source:
                metric_sources[str(name)] = str(source)
    merged = {**metrics, **values}
    reported_input = merged.get("reported_earnings", merged.get("earnings"))
    bridge = normalisation_bridge(reported_input, merged.get("normalisation_adjustments", ()), equity_denominator=merged.get("average_common_equity", merged.get("equity")), reported_pre_tax=merged.get("reported_pre_tax"), pre_tax_adjustments=merged.get("pre_tax_adjustments", ()), ec_share=merged.get("ec_share"), ec_count=merged.get("ec_count")) if reported_input is not None else None
    capital = capital_resilience(merged.get("cet1"), merged.get("ppp"), merged.get("credit_loss"), merged.get("rwa"), merged.get("target_ratio")) if any(key in merged for key in ("cet1", "ppp", "credit_loss", "rwa", "target_ratio")) else None
    resilience = dict(capital.__dict__) if capital else {}
    cet1_ratio = _number(merged.get("cet1_ratio"))
    if cet1_ratio is not None:
        resilience["cet1_ratio"] = cet1_ratio
        cet1_provenance = merged.get("cet1_ratio_provenance")
        if cet1_provenance is not None:
            resilience["provenance"] = {"cet1_ratio": cet1_provenance}
    credit_input = dict(merged.get("credit")) if isinstance(merged.get("credit"), Mapping) else None
    if credit_input is None:
        credit_aliases = ("opening_stage3", "new_stage3", "cured_stage3", "repaid_stage3", "written_off_stage3", "closing_stage3", "opening_allowance", "allowance_expense", "allowance_releases", "allowance_used_writeoffs", "closing_allowance", "loans_open", "loans_close", "stage2_open", "stage2_close")
        derived_credit = {key: merged[key] for key in credit_aliases if key in merged}
        credit_input = derived_credit or None
    if credit_input:
        credit_fields = {name for name in credit_reconciliation.__kwdefaults__ or ()}
        credit = credit_reconciliation(**{key: value for key, value in credit_input.items() if key in credit_fields}).__dict__
    else:
        credit = {}
    stage3_ratio = _number((credit_input or {}).get("stage_3_ratio_pct", merged.get("stage_3_ratio_pct")))
    if stage3_ratio is not None:
        credit["stage_3_ratio_pct"] = stage3_ratio
        if (credit_input or {}).get("provenance") is not None:
            credit["provenance"] = (credit_input or {})["provenance"]
    stage2_ratio = _number((credit_input or {}).get("stage_2_ratio_pct", merged.get("stage_2_ratio_pct")))
    if stage2_ratio is not None:
        credit["stage_2_ratio_pct"] = stage2_ratio
    stage3_coverage = book_calcs.stage3_coverage(
        _number((credit_input or {}).get("stage_3_allowance")), _number((credit_input or {}).get("stage_3_exposure"))
    )
    if stage3_coverage is not None:
        credit["stage_3_coverage"] = stage3_coverage
    # Capital headroom is measured against the full requirement (book eq. 1.17, p. 10), never the headline ratio alone.
    requirement = _number(merged.get("cet1_requirement_ratio"))
    headroom = book_calcs.cet1_headroom(cet1_ratio, requirement)
    if headroom is not None:
        resilience["cet1_requirement_ratio"] = requirement
        resilience["headroom_pp"] = headroom * 100.0
        surplus = book_calcs.surplus_cet1(headroom, _number(merged.get("rwa_nok")))
        if surplus is not None:
            resilience["surplus_cet1_nok"] = surplus
            resilience["rwa"] = _number(merged.get("rwa_nok"))
    leverage_ratio = _number(merged.get("leverage_ratio"))
    if leverage_ratio is not None:
        resilience["leverage_ratio"] = leverage_ratio
    funding_input = merged.get("funding") if isinstance(merged.get("funding"), Mapping) else {}
    funding = {
        "deposit_beta": funding_input.get("deposit_beta", metrics.get("deposit_beta", UNAVAILABLE)),
        "deposit_to_loan_ratio": funding_input.get("deposit_to_loan_ratio", UNAVAILABLE),
        "lcr": funding_input.get("lcr", metrics.get("liquidity_coverage_ratio", UNAVAILABLE)),
        "nsfr": funding_input.get("nsfr", metrics.get("net_stable_funding_ratio", UNAVAILABLE)),
        "reference_rate": funding_input.get("reference_rate", UNAVAILABLE),
        "window": funding_input.get("window", UNAVAILABLE),
        "population": funding_input.get("population", UNAVAILABLE),
        "provenance": funding_input.get("provenance", {}),
    }
    concentration = dict(merged.get("concentration")) if isinstance(merged.get("concentration"), Mapping) else {}
    if not concentration:
        for key in ("top_exposure_share", "large_exposure_ratio", "sector_concentration", "geographic_concentration"):
            if key in merged:
                concentration[key] = merged[key]
    if concentration:
        concentration = {**concentration, "interpretation": concentration.get("interpretation", "operator_supplied")}
    statements = merged.get("statements") if isinstance(merged.get("statements"), Mapping) else None
    lending = lending_economics(metrics, statements) if statements is not None or metrics else {}
    allocation = {
        "capital_self_funding_gap": lending.get("capital_self_funding_gap"),
        "equity_growth": lending.get("equity_growth"),
        "asset_growth": lending.get("asset_growth"),
        "cet1_surplus_nok": resilience.get("surplus_cet1_nok"),
        "leverage_ratio": resilience.get("leverage_ratio"),
        "payout_symmetry_gap": book_calcs.payout_symmetry_gap(_number(merged.get("owner_payout_rate")), _number(merged.get("ownerless_payout_rate"))),
        "owner_payout_rate": _number(merged.get("owner_payout_rate")),
        "ownerless_payout_rate": _number(merged.get("ownerless_payout_rate")),
    }
    for fund_key in ("deposit_beta", "wholesale_maturing_12m"):
        if funding_input.get(fund_key) is not None:
            funding[fund_key] = funding_input[fund_key]
    funding.setdefault("wholesale_maturing_12m", UNAVAILABLE)
    unavailable = tuple(name for name, value in (("lcr", funding.get("lcr")), ("nsfr", funding.get("nsfr"))) if value in (None, UNAVAILABLE))
    evidence_values = metric_evidence_ids + [str(merged[key]) for key in ("evidence_id", "source_id", "source_url", "filing_version") if merged.get(key)]
    if bridge:
        evidence_values.extend(item.evidence_locator for item in bridge.adjustments if item.evidence_locator)
    if isinstance(funding_input, Mapping):
        evidence_values.extend(str(funding_input[key]) for key in ("evidence_id", "source_id") if funding_input.get(key))
        funding_provenance = funding_input.get("provenance")
        if isinstance(funding_provenance, Mapping):
            for item in funding_provenance.values():
                if isinstance(item, Mapping):
                    evidence_values.extend(str(item[key]) for key in ("source_locator", "source_url") if item.get(key))
                    citations = item.get("source_citations")
                    if isinstance(citations, (tuple, list)):
                        for citation in citations:
                            if isinstance(citation, Mapping):
                                evidence_values.extend(str(citation[key]) for key in ("source_locator", "source_url") if citation.get(key))
    credit_provenance = (credit_input or {}).get("provenance")
    if isinstance(credit_provenance, Mapping):
        for item in credit_provenance.values():
            if isinstance(item, Mapping):
                evidence_values.extend(str(item[key]) for key in ("source_locator", "source_url") if item.get(key))
    cet1_provenance = merged.get("cet1_ratio_provenance")
    if isinstance(cet1_provenance, Mapping):
        evidence_values.extend(str(cet1_provenance[key]) for key in ("source_locator", "source_url") if cet1_provenance.get(key))
    if isinstance(concentration, Mapping):
        evidence_values.extend(str(concentration[key]) for key in ("evidence_id", "source_id") if concentration.get(key))
    evidence_ids = tuple(dict.fromkeys(evidence_values))
    calculation_ids = tuple(name for name in ("normalisation_bridge" if bridge and bridge.status == "resolved" else None, "capital_resilience" if capital and capital.status == "resolved" else None, "credit_reconciliation" if credit else None, "funding_evidence" if any(funding.get(key) not in (None, UNAVAILABLE) for key in ("deposit_beta", "deposit_to_loan_ratio", "lcr", "nsfr")) else None, "concentration_interpretation" if concentration else None) if name)
    complete = bool(evidence_ids and calculation_ids and (not capital or capital.status == "resolved"))
    status = "resolved" if complete else "partial"
    reasons = {
        "cet1_headroom_pp": MISSING_REASONS["cet1_headroom_pp"] if "headroom_pp" not in resilience else "",
        "stage_3_ratio_pct": MISSING_REASONS["stage_3_ratio_pct"] if "stage_3_ratio_pct" not in credit else "",
        "lcr_pct": MISSING_REASONS["lcr_pct"] if funding.get("lcr") in (None, UNAVAILABLE) else "",
        "nsfr_pct": MISSING_REASONS["nsfr_pct"] if funding.get("nsfr") in (None, UNAVAILABLE) else "",
        "deposit_to_loan_ratio_pct": MISSING_REASONS["deposit_to_loan_ratio_pct"] if funding.get("deposit_to_loan_ratio") in (None, UNAVAILABLE) else "",
        "cost_of_risk_bps": MISSING_REASONS["cost_of_risk_bps"] if _number(metrics.get("cost_of_risk")) is None else "",
    }
    reasons = {key: text for key, text in reasons.items() if text}
    if lending:
        calculation_ids = (*calculation_ids, "lending_economics")
    statement_sources = statements.get("sources", {}) if isinstance(statements, Mapping) else {}
    provenance = {**metric_sources}
    if isinstance(statement_sources, Mapping):
        provenance.update({f"statement.{name}": str(source) for name, source in statement_sources.items() if source})
    return BankEconomics(status=status, reported={"metrics": metrics, "statements": statements or {}, "provenance": provenance}, normalised=bridge.__dict__ if bridge else {}, resilience=resilience, credit=credit, funding=funding, concentration=concentration, evidence_ids=evidence_ids, unavailable_fields=unavailable, coverage=(1.0 if complete else 0.5 if bridge or capital or credit else 0.0), calculation_ids=calculation_ids, lending=lending, allocation=allocation, reasons=reasons)


analyse_bank_economics = build_bank_economics
calculate_capital = capital_resilience
stage_ratio_effect = credit_reconciliation


__all__ = [
    "BankEconomics", "CapitalResilience", "CreditReconciliation", "FundingEvidence", "NormalisationAdjustment", "NormalisationBridge",
    "analyse_bank_economics", "build_bank_economics", "lending_economics", "owner_normalisation", "calculate_capital", "capital_headroom", "capital_resilience", "credit_reconciliation", "deposit_beta", "efficiency_effects", "normalisation_bridge", "normalise_earnings", "roe_decomposition", "stage_ratio_effect", "stage_stock_flow",
]
