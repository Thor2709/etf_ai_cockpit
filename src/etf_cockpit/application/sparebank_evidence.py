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
}


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
                and str(row.get("currency") or "NOK").upper() == "NOK"
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


def with_derived_owner_earnings(ec_facts: Mapping[str, object], statements: Mapping[str, object] | None) -> dict[str, object]:
    """Fill a missing EC-attributable result by the book's simplified allocation (eq. 1.19, p. 12-13).

    Only when the filing facts carry no EC-attributable result: EC result = eierbrok x profit attributable to the
    owners of the parent. The fact is labelled ``derived``; the AT1 coupon is not separated (a small overstatement).
    """

    facts = dict(ec_facts)
    existing = facts.get("ec_attributable_result")
    if isinstance(existing, Mapping) and existing.get("available") is not False and _number(existing.get("value")) is not None:
        return facts
    current = statements.get("current") if isinstance(statements, Mapping) else None
    profit = None
    profit_name = ""
    if isinstance(current, Mapping):
        for name in ("profit_attributable_to_owners", "net_profit"):
            if _number(current.get(name)) is not None:
                profit, profit_name = _number(current.get(name)), name
                break
    from etf_cockpit.analysis.sparebank.claim import reconstruct_eierbrok

    share = None
    reported = facts.get("eierbrok")
    if isinstance(reported, Mapping) and reported.get("available") is not False:
        share = _number(reported.get("value"))
    if share is None:
        owner = {name: _number(facts[name].get("value")) for name in ("ec_capital", "overkursfond", "utjevningsfond") if isinstance(facts.get(name), Mapping) and _number(facts[name].get("value")) is not None}
        own = {name: _number(facts[name].get("value")) for name in ("sparebankens_fond", "gavefond", "kompensasjonsfond") if isinstance(facts.get(name), Mapping) and _number(facts[name].get("value")) is not None}
        share = reconstruct_eierbrok(owner, own) if len(owner) == 3 and "sparebankens_fond" in own else None
    if profit is None or share is None or not 0.0 < share <= 1.0:
        return facts
    template = next((item for item in facts.values() if isinstance(item, Mapping) and item.get("known_at")), {})
    facts["ec_attributable_result"] = {
        "available": True,
        "value": profit * share,
        "unit": "NOK",
        "period": statements.get("period_end"),  # type: ignore[union-attr]
        "effective_at": statements.get("period_end"),  # type: ignore[union-attr]
        "known_at": template.get("known_at"),
        "source_url": template.get("source_url"),
        "sha256": template.get("sha256"),
        "source_locator": f"derived: eierbrok {share:.4f} x {profit_name.replace('_', ' ')} (book eq. 1.19, p. 12-13); AT1 coupon not separated",
        "derived": True,
    }
    return facts
