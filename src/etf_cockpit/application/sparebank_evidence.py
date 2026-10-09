"""Assemble the bank-economics evidence for one Sparebank EC (application layer, SB2).

Two sources are merged into the evidence mapping consumed by ``analysis.sparebank``:

* ``statements``: the current and prior-year values of the primary statements, taken from the same
  filing (the prior-year comparative is published with the filing, so it is point-in-time safe);
* confirmed Pillar 3 figures from the owner's queue (``data/pending/pillar3``); a figure that is still
  pending or was rejected is never used.

The calculations themselves live in ``analysis.sparebank``; nothing is computed here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from pathlib import Path

import pandas as pd

from etf_cockpit.data.pillar3_queue import confirmed_figures, load_queue

# name -> (field holding the selector, selector). Selectors are canonical statement metrics or IFRS concept names.
_STATEMENT_SELECTORS: dict[str, tuple[str, str]] = {
    "net_interest_income": ("canonical_metric", "net_interest_income"),
    "operating_expenses": ("canonical_metric", "operating_expenses"),
    "impairment_losses": ("canonical_metric", "impairment_losses"),
    "net_profit": ("canonical_metric", "net_profit"),
    "profit_attributable_to_owners": ("canonical_metric", "net_income_attributable_to_owners"),
    "loans_to_customers": ("canonical_metric", "loans_to_customers"),
    "deposits_from_customers": ("canonical_metric", "deposits_from_customers"),
    "total_assets": ("canonical_metric", "total_assets"),
    "equity": ("canonical_metric", "equity"),
    "income_before_tax": ("concept", "ProfitLossBeforeTax"),
    "income_tax": ("concept", "IncomeTaxExpenseContinuingOperations"),
    # Profit share the issuer tags for the ownerless primary capital (extension concept, reviewed mapping).
    "ownerless_result": ("canonical_metric", "ownerless_result"),
    "basic_eps": ("concept", "BasicEarningsLossPerShare"),
}
_PER_SHARE = {"basic_eps"}
_NOMINAL_RANGE = (1.0, 60.0)


def _is_undimensioned(row: Mapping[str, object]) -> bool:
    dimensions = row.get("dimensions")
    if dimensions is None:
        return True
    if isinstance(dimensions, float) and math.isnan(dimensions):
        return True
    return str(dimensions).strip() in {"", "{}"}


def _period(row: Mapping[str, object]) -> pd.Timestamp | None:
    value = row.get("effective_at") or row.get("end") or row.get("instant")
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def statement_series(rows: Iterable[Mapping[str, object]], *, target_period: str | None = None) -> dict[str, object]:
    """Current and prior-year primary-statement values from one filing's rows (annual periods)."""

    eligible = [row for row in rows if _is_undimensioned(row) and _period(row) is not None]
    anchors = [_period(row) for row in eligible if row.get("canonical_metric") == "net_interest_income"]
    if target_period:
        anchor = pd.Timestamp(target_period, tz="UTC")
        anchor = anchor if anchor in anchors else None
    else:
        anchor = max(anchors) if anchors else None
    if anchor is None:
        return {}
    prior_anchor = anchor - pd.DateOffset(years=1)
    result: dict[str, object] = {
        "period_end": anchor.date().isoformat(),
        "prior_period_end": prior_anchor.date().isoformat(),
        "unit": "NOK",
        "current": {},
        "prior": {},
        "sources": {},
    }
    for name, (field, selector) in _STATEMENT_SELECTORS.items():
        for side, wanted, tolerance in (("current", anchor, 3), ("prior", prior_anchor, 10)):
            matches = [
                row
                for row in eligible
                if row.get(field) == selector
                and abs((_period(row) - wanted).days) <= tolerance
                and str(row.get("consolidation_scope") or "consolidated").casefold() == "consolidated"
                and (name in _PER_SHARE or str(row.get("currency") or "NOK").upper() == "NOK")
            ]
            if not matches:
                continue
            chosen = max(matches, key=lambda row: str(row.get("_known") or row.get("known_at") or ""))
            value = _number(chosen.get("value"))
            if value is None:
                continue
            result[side][name] = value  # type: ignore[index]
            if side == "current":
                result["sources"][name] = str(chosen.get("source_url") or chosen.get("source_id") or "")  # type: ignore[index]
    return result if result["current"] else {}


# Pillar 3 metric -> (evidence path, conversion). Percent figures become ratios, as the analysis expects.
def pillar3_evidence(root: Path, instrument_id: str, decision_time: str | None) -> dict[str, object]:
    """Evidence built from the owner's confirmed Pillar 3 figures only."""

    queue = load_queue(root, instrument_id)
    figures = {str(item.get("metric")): item for item in confirmed_figures(queue, decision_time)}
    documents = {str(item.get("document_id")): item for item in queue.get("documents", ()) if isinstance(item, Mapping)}
    if not figures:
        return {}

    def citation(item: Mapping[str, object]) -> dict[str, object]:
        document = documents.get(str(item.get("document_id")), {})
        return {
            "source_locator": f"{document.get('source_url', '')} | {document.get('title', '')} | page {item.get('page')} | printed: {item.get('printed_text', '')} | confirmed by owner {item.get('decided_at')}",
            "source_url": document.get("source_url"),
            "sha256": document.get("sha256"),
            "document_title": document.get("title"),
            "page": item.get("page"),
            "printed_text": item.get("printed_text"),
            "confirmed_at": item.get("decided_at"),
            "period": item.get("period"),
        }

    def ratio(metric: str) -> float | None:
        item = figures.get(metric)
        value = _number(item.get("value")) if item else None
        return None if value is None else value / 100.0

    evidence: dict[str, object] = {}
    cet1 = ratio("cet1_ratio_pct")
    if cet1 is not None:
        evidence["cet1_ratio"] = cet1
        evidence["cet1_ratio_provenance"] = citation(figures["cet1_ratio_pct"])
    requirement = ratio("cet1_requirement_pct")
    if requirement is not None:
        evidence["cet1_requirement_ratio"] = requirement
        evidence["cet1_requirement_provenance"] = citation(figures["cet1_requirement_pct"])
    leverage = ratio("leverage_ratio_pct")
    if leverage is not None:
        evidence["leverage_ratio"] = leverage
    funding: dict[str, object] = {}
    provenance: dict[str, object] = {}
    for name, metric in (("lcr", "lcr_pct"), ("nsfr", "nsfr_pct"), ("deposit_to_loan_ratio", "deposit_to_loan_ratio_pct")):
        value = ratio(metric)
        if value is not None:
            funding[name] = value
            provenance[name] = citation(figures[metric])
    if funding:
        funding["provenance"] = provenance
        evidence["funding"] = funding
    credit: dict[str, object] = {}
    credit_provenance: dict[str, object] = {}
    for name, metric in (("stage_2_ratio_pct", "stage2_pct_gross_loans"), ("stage_3_ratio_pct", "stage3_pct_gross_loans")):
        value = ratio(metric)
        if value is not None:
            credit[name] = value
            credit_provenance[name] = citation(figures[metric])
    if credit:
        credit["provenance"] = credit_provenance
        evidence["credit"] = credit
    rwa = figures.get("rwa_nok")
    if rwa is not None and _number(rwa.get("value")) is not None:
        evidence["rwa_nok"] = _number(rwa.get("value"))
    return evidence


def merge_bank_economics_evidence(
    curated: Mapping[str, object] | None,
    statements: Mapping[str, object] | None,
    pillar3: Mapping[str, object] | None,
) -> dict[str, object]:
    """Curated filing evidence, then owner-confirmed Pillar 3 figures on top (field by field for nested blocks)."""

    merged: dict[str, object] = dict(curated or {})
    for key, value in (pillar3 or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            block = dict(merged[key])  # type: ignore[arg-type]
            for inner_key, inner_value in value.items():
                if inner_key == "provenance" and isinstance(block.get("provenance"), Mapping):
                    block["provenance"] = {**block["provenance"], **inner_value}  # type: ignore[dict-item]
                else:
                    block[inner_key] = inner_value
            merged[key] = block
        else:
            merged[key] = value
    if statements:
        merged["statements"] = dict(statements)
    return merged


def _available(facts: Mapping[str, object], name: str) -> float | None:
    item = facts.get(name)
    if isinstance(item, Mapping) and item.get("available") is not False:
        return _number(item.get("value"))
    return None


def _ownership_share(facts: Mapping[str, object]) -> float | None:
    from etf_cockpit.analysis.sparebank.claim import reconstruct_eierbrok

    reported = _available(facts, "eierbrok")
    if reported is not None:
        return reported
    owner = {name: _available(facts, name) for name in ("ec_capital", "overkursfond", "utjevningsfond")}
    own = {name: _available(facts, name) for name in ("sparebankens_fond", "gavefond", "kompensasjonsfond") if _available(facts, name) is not None}
    if any(value is None for value in owner.values()) or "sparebankens_fond" not in own:
        return None
    return reconstruct_eierbrok(owner, own)


def with_derived_owner_earnings(ec_facts: Mapping[str, object], statements: Mapping[str, object] | None) -> dict[str, object]:
    """Fill a missing EC-attributable result and EC count from the filing, each labelled ``derived``.

    EC result (only when the facts carry none):
    * if the issuer tags the ownerless primary-capital share of profit separately, the profit attributable to
      the owners of the parent is already the EC share, accepted when owners / (owners + ownerless) is within
      2 percentage points of the ownership fraction (otherwise ignored, the split is not trusted);
    * otherwise the book's simplified allocation (eq. 1.19, p. 12-13): ownership fraction x profit attributable
      to the owners (AT1 coupon not separated, a small overstatement).
    EC count (only when the facts carry no count): EC result / reported basic EPS, accepted only when the implied
    nominal value per certificate lies between NOK 1 and NOK 60 (a ten-fold scale error in the EPS tag fails).
    """

    facts = dict(ec_facts)
    current = statements.get("current") if isinstance(statements, Mapping) else None
    if not isinstance(current, Mapping):
        return facts
    template = next((item for item in facts.values() if isinstance(item, Mapping) and item.get("known_at")), {})
    period = statements.get("period_end")  # type: ignore[union-attr]

    def derived(value: float, unit: str, locator: str) -> dict[str, object]:
        return {
            "available": True, "value": value, "unit": unit, "period": period, "effective_at": period,
            "known_at": template.get("known_at"), "source_url": template.get("source_url"), "sha256": template.get("sha256"),
            "source_locator": locator, "derived": True,
        }

    share = _ownership_share(facts)
    if _available(facts, "ec_attributable_result") is None:
        owners = _number(current.get("profit_attributable_to_owners"))
        ownerless = _number(current.get("ownerless_result"))
        result = None
        locator = ""
        if owners is not None and ownerless is not None and share is not None and owners + ownerless > 0 and abs(owners / (owners + ownerless) - share) <= 0.02:
            result = owners
            locator = f"derived: profit attributable to owners of the parent; the issuer tags the ownerless share ({ownerless:,.0f}) separately and the split {owners / (owners + ownerless):.4f} matches the ownership fraction {share:.4f}"
        else:
            profit = owners if owners is not None else _number(current.get("net_profit"))
            if profit is not None and share is not None and 0.0 < share <= 1.0:
                result = profit * share
                name = "profit attributable to owners" if owners is not None else "net profit"
                locator = f"derived: eierbrok {share:.4f} x {name} (book eq. 1.19, p. 12-13); AT1 coupon not separated"
        if result is not None:
            facts["ec_attributable_result"] = derived(result, "NOK", locator)
    count_names = ("registered_ec_count", "outstanding_ec_count", "period_end_ec_count", "weighted_average_ec_count")
    result_value = _available(facts, "ec_attributable_result")
    eps = _number(current.get("basic_eps"))
    if all(_available(facts, name) is None for name in count_names) and result_value and result_value > 0 and eps and eps > 0:
        count = result_value / eps
        capital = _available(facts, "ec_capital")
        nominal = capital / count if capital else None
        if nominal and _NOMINAL_RANGE[0] <= nominal <= _NOMINAL_RANGE[1]:
            locator = f"derived: EC result / reported basic EPS {eps:g}; implied nominal {nominal:.2f} NOK per certificate; approximates the weighted average and is used as the outstanding count"
            facts["weighted_average_ec_count"] = derived(count, "EC", locator)
            facts["outstanding_ec_count"] = derived(count, "EC", locator)
    return facts
