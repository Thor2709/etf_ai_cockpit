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
_FLOW_METRICS = {
    "net_interest_income",
    "operating_expenses",
    "impairment_losses",
    "net_profit",
    "profit_attributable_to_owners",
    "income_before_tax",
    "income_tax",
    "ownerless_result",
    "basic_eps",
}
_NOMINAL_RANGE = (1.0, 60.0)


def _is_undimensioned(row: Mapping[str, object]) -> bool:
    dimensions = row.get("dimensions")
    if dimensions is None:
        return True
    if isinstance(dimensions, float) and math.isnan(dimensions):
        return True
    return str(dimensions).strip() in {"", "{}"}


def _period(row: Mapping[str, object]) -> pd.Timestamp | None:
    value = row.get("end") or row.get("instant") or row.get("effective_at")
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else pd.Timestamp(parsed).normalize()


def _filing_identity(row: Mapping[str, object]) -> str | None:
    for field in ("filing_version", "sha256", "source_url"):
        value = row.get(field)
        if value is not None and str(value).strip():
            return f"{field}:{str(value).strip()}"
    return None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def statement_series(rows: Iterable[Mapping[str, object]], *, target_period: str | None = None) -> dict[str, object]:
    """Current and prior primary-statement values from one filing and one flow duration."""

    eligible = [row for row in rows if _is_undimensioned(row) and _period(row) is not None]
    anchors = [row for row in eligible if row.get("canonical_metric") == "net_interest_income"]
    if target_period:
        wanted_anchor = _date(target_period)
        matches = [row for row in anchors if _period(row) == wanted_anchor]
        anchor_row = max(matches, key=lambda row: str(row.get("_known") or row.get("known_at") or "")) if matches else None
    else:
        anchor_row = max(anchors, key=lambda row: (_period(row), str(row.get("_known") or row.get("known_at") or ""))) if anchors else None
    if anchor_row is None:
        return {}
    anchor = _period(anchor_row)
    filing_identity = _filing_identity(anchor_row)
    if filing_identity is None:
        return {"unavailable_reasons": {"statements": "STATEMENT_FILING_IDENTITY_MISSING"}}
    anchor_start = _date(anchor_row.get("start") or anchor_row.get("period_start"))
    prior_anchor = anchor - pd.DateOffset(years=1)
    result: dict[str, object] = {
        "period_end": anchor.date().isoformat(),
        "prior_period_end": prior_anchor.date().isoformat(),
        "filing_identity": filing_identity,
        "duration_start": anchor_start.date().isoformat() if anchor_start is not None else None,
        "unit": "NOK",
        "current": {},
        "prior": {},
        "sources": {},
        "unavailable_reasons": {},
    }
    for name, (field, selector) in _STATEMENT_SELECTORS.items():
        for side, wanted, tolerance in (("current", anchor, 3), ("prior", prior_anchor, 10)):
            matches = []
            for row in eligible:
                row_period = _period(row)
                if (
                    row.get(field) != selector
                    or abs((row_period - wanted).days) > tolerance
                    or _filing_identity(row) != filing_identity
                    or str(row.get("consolidation_scope") or "consolidated").casefold() != "consolidated"
                    or (name not in _PER_SHARE and str(row.get("currency") or "NOK").upper() != "NOK")
                ):
                    continue
                if name in _FLOW_METRICS:
                    row_start = _date(row.get("start") or row.get("period_start"))
                    expected_start = anchor_start - pd.DateOffset(years=1) if side == "prior" and anchor_start is not None else anchor_start
                    if anchor_start is None or row_start is None or row_period != wanted or row_start != expected_start:
                        continue
                matches.append(row)
            if not matches:
                result["unavailable_reasons"][name] = (  # type: ignore[index]
                    "STATEMENT_FLOW_DURATION_MISMATCH" if name in _FLOW_METRICS else "STATEMENT_FILING_OR_PERIOD_MISMATCH"
                )
                continue
            chosen = max(matches, key=lambda row: str(row.get("_known") or row.get("known_at") or ""))
            value = _number(chosen.get("value"))
            if value is None:
                result["unavailable_reasons"][name] = "STATEMENT_VALUE_INVALID"  # type: ignore[index]
                continue
            result[side][name] = value  # type: ignore[index]
            if side == "current":
                result["sources"][name] = str(chosen.get("source_locator") or chosen.get("source_url") or chosen.get("source_id") or "")  # type: ignore[index]
    return result if result["current"] else {}


# Pillar 3 metric -> (evidence path, conversion). Percent figures become ratios, as the analysis expects.
def pillar3_evidence(
    root: Path,
    instrument_id: str,
    decision_time: str | None,
    *,
    target_period: str | None = None,
) -> dict[str, object]:
    """Evidence built only from confirmed Pillar 3 figures for the reporting period."""

    queue = load_queue(root, instrument_id)
    confirmed = confirmed_figures(queue, decision_time)
    documents = {str(item.get("document_id")): item for item in queue.get("documents", ()) if isinstance(item, Mapping)}
    if not confirmed:
        return {}
    if target_period is None:
        return {"unavailable_reasons": {"pillar3": "PILLAR3_REPORTING_PERIOD_REQUIRED"}}

    target = _date(target_period)
    target_key = target.date().isoformat() if target is not None else str(target_period).strip()
    matching = [item for item in confirmed if str(item.get("period") or "").strip()[:10] == target_key[:10]]
    figures: dict[str, Mapping[str, object]] = {}
    for item in matching:
        metric = str(item.get("metric"))
        current = figures.get(metric)
        if current is None or str(item.get("decided_at") or "") > str(current.get("decided_at") or ""):
            figures[metric] = item
    if not figures:
        return {
            "unavailable_reasons": {
                str(item.get("metric")): "PILLAR3_REPORTING_PERIOD_MISMATCH" for item in confirmed
            }
        }

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
    result_value = _available(facts, "ec_attributable_result")
    eps = _number(current.get("basic_eps"))
    if _available(facts, "weighted_average_ec_count") is None and result_value and result_value > 0 and eps and eps > 0:
        count = result_value / eps
        capital = _available(facts, "ec_capital")
        nominal = capital / count if capital else None
        if nominal and _NOMINAL_RANGE[0] <= nominal <= _NOMINAL_RANGE[1]:
            locator = f"derived: EC result / reported basic EPS {eps:g}; implied nominal {nominal:.2f} NOK per certificate; approximates the weighted-average count only"
            facts["weighted_average_ec_count"] = derived(count, "EC", locator)
    return facts


def review_pillar3_figure(root: Path, instrument_id: str, figure_id: str, decision: str) -> dict[str, object]:
    """Record the owner's decision on one proposed figure (``confirmed`` or ``rejected``); only confirmed figures count."""

    from etf_cockpit.data.pillar3_queue import decide

    return decide(root, instrument_id, figure_id, decision)
