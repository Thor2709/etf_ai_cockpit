"""Free-source fetchers and parsers for normal-stock fundamentals (SEC EDGAR companyfacts, yfinance).

Each source returns plain period rows (one dict per reported period) in the single canonical field
set of ``stock_metrics``. Nothing here decides which source wins; ``stock_fundamentals`` merges them.
Network access is read-only and injectable so every parser has an offline test.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from etf_cockpit.analysis.stock_metrics import BALANCE_FIELDS, FLOW_FIELDS
from etf_cockpit.core.paths import STATEMENT_FACTS_PATH
from etf_cockpit.data.yfinance_provider import classify_provider_error

# Accounting-identity legs (cash roll-forward, balance identity). They default here so a config that
# predates them still ingests them; a configured entry of the same name wins.
IDENTITY_SEC_CONCEPTS: dict[str, list[str]] = {
    "cfi": ["NetCashProvidedByUsedInInvestingActivities"],
    "cff": ["NetCashProvidedByUsedInFinancingActivities"],
    "fx_effect": [
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "EffectOfExchangeRateOnCashAndCashEquivalents",
    ],
    "total_liabilities": ["Liabilities"],
}
IDENTITY_YF_LABELS: dict[str, list[str]] = {
    "cfi": ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"],
    "cff": ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"],
    "fx_effect": ["Effect Of Exchange Rate Changes"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
}
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass
class FetchResult:
    source: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | no_statements | not_found | error | unavailable
    reason: str = ""
    # statement name -> "<kind>: detail" for every statement that failed (kind: not_found | throttled | timeout | error | invalid);
    # a non-empty mapping with status "ok" means the statements that did arrive are partial.
    statement_errors: dict[str, str] = field(default_factory=dict)


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(value: object) -> str | None:
    if value is None:
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------------------------


def _first_label(frame: pd.DataFrame, labels: Sequence[str], column: object) -> float | None:
    for label in labels:
        if label in frame.index:
            value = _number(frame.at[label, column])
            if value is not None:
                return value
    return None


def _statement_rows(
    frames: Sequence[pd.DataFrame],
    labels: Mapping[str, Sequence[str]],
    period_type: str,
    currency: str,
    known_at: str,
    source_ref: str,
) -> list[dict[str, Any]]:
    columns: list[object] = []
    for frame in frames:
        if frame is not None and not frame.empty:
            columns.extend(c for c in frame.columns if c not in columns)
    rows = []
    for column in sorted(columns):
        end = _iso(column)
        if end is None:
            continue
        values: dict[str, float] = {}
        for name, names in labels.items():
            for frame in frames:
                if frame is None or frame.empty or column not in frame.columns:
                    continue
                found = _first_label(frame, names, column)
                if found is not None:
                    values[name] = found
                    break
        if not values:
            continue
        for name in ("capex", "dividends_paid", "da", "interest_expense"):
            if name in values:
                values[name] = abs(values[name])  # provider sign conventions differ; outflows/expenses are stored positive
        total_debt = values.pop("total_debt", None)
        lease = values.get("lease_liabilities")
        derived: dict[str, str] = {}
        if total_debt is not None:
            gross_debt = total_debt - (lease or 0.0)
            if gross_debt >= 0:
                values["ib_debt"] = gross_debt
                if lease is not None:
                    derived["ib_debt"] = "derived"  # total debt minus leases: leases are counted once, in lease_liabilities
        rows.append(
            {
                "period_end": end,
                "period_type": period_type,
                "fiscal_year": int(end[:4]),
                "currency": currency,
                "source": "yfinance",
                "known_at": known_at,
                "source_ref": source_ref,
                **({"value_status": json.dumps(derived, sort_keys=True)} if derived else {}),
                **values,
            }
        )
    return rows


def fetch_yfinance(
    symbol: str,
    config: Mapping[str, Any],
    *,
    now: datetime,
    ticker_factory: Callable[[str], Any] | None = None,
) -> FetchResult:
    """Annual and quarterly statements plus profile and analyst snapshot for one Yahoo symbol."""

    if ticker_factory is None:
        import yfinance  # imported lazily: optional runtime dependency, already a production requirement

        ticker_factory = yfinance.Ticker
    known_at = now.astimezone(timezone.utc).isoformat()
    ref = f"yfinance:{symbol}"
    result = FetchResult("yfinance")
    try:
        ticker = ticker_factory(symbol)
        info = dict(ticker.info or {})
    except Exception as exc:  # network and "quote not found" both end here, with the reason kept
        text = str(exc)
        kind = classify_provider_error(exc)
        result.status = "not_found" if kind == "not_found" else "error"
        result.reason = f"Yahoo returned no profile for {symbol} ({kind}): {text[:140]}"
        result.snapshot = {"known_at": known_at, "source": "yfinance", "status": result.status, "reason": result.reason}
        return result
    financial_currency = str(info.get("financialCurrency") or "").strip()
    quote_currency = str(info.get("currency") or "")
    snapshot: dict[str, Any] = {
        "known_at": known_at,
        "source": "yfinance",
        "quote_currency": quote_currency,
        "financial_currency": financial_currency,
        "long_name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "quote_type": info.get("quoteType"),
        "market_cap_provider": _number(info.get("marketCap")),
        "shares_outstanding": _number(info.get("sharesOutstanding")),
        "status": "ok",
        "reason": "",
    }
    if not info.get("quoteType") and not info.get("longName"):
        result.status = "not_found"
        result.reason = f"Yahoo has no company profile for {symbol} (delisted, renamed or wrong symbol)"
        snapshot.update(status=result.status, reason=result.reason)
        result.snapshot = snapshot
        return result

    statement_errors: dict[str, str] = {}

    def frame(name: str) -> pd.DataFrame:
        try:
            value = getattr(ticker, name)
        except Exception as exc:  # recorded per statement; the other statements are still used
            statement_errors[name] = f"{classify_provider_error(exc)}: {str(exc)[:100]}"
            return pd.DataFrame()
        if value is not None and not isinstance(value, pd.DataFrame):
            statement_errors[name] = f"invalid: expected a table, got {type(value).__name__}"
            return pd.DataFrame()
        return value if value is not None else pd.DataFrame()

    labels = {**IDENTITY_YF_LABELS, **(config.get("yfinance_labels", {}) or {})}
    annual = _statement_rows(
        [frame("income_stmt"), frame("cashflow"), frame("balance_sheet")], labels, "FY", financial_currency, known_at, ref
    )
    quarterly = _statement_rows(
        [frame("quarterly_income_stmt"), frame("quarterly_cashflow"), frame("quarterly_balance_sheet")],
        labels,
        "Q",
        financial_currency,
        known_at,
        ref,
    )
    result.rows = annual + quarterly
    result.statement_errors = dict(statement_errors)
    if result.rows and not financial_currency:
        result.rows = []
        result.status = "unavailable"
        result.reason = "financialCurrency is unavailable; statement values cannot be assigned a reporting currency"
        snapshot.update(status=result.status, reason=result.reason)
        result.snapshot = snapshot
        return result
    snapshot.update(_analyst_fields(ticker))
    detail = "; ".join(f"{name}: {text}" for name, text in sorted(statement_errors.items()))
    if not result.rows and statement_errors:
        kinds = {text.split(":", 1)[0] for text in statement_errors.values()}
        result.status = "not_found" if kinds == {"not_found"} else "error"
        result.reason = f"Yahoo statements for {symbol} failed: {detail}"
        snapshot.update(status=result.status, reason=result.reason)
    elif not result.rows:
        result.status = "no_statements"
        result.reason = f"Yahoo lists {symbol} but returns no income statement, balance sheet or cash flow"
        snapshot.update(status=result.status, reason=result.reason)
    elif statement_errors:
        result.reason = f"partial statements for {symbol}: {detail}"
        snapshot["reason"] = result.reason
    result.snapshot = snapshot
    return result


def _analyst_fields(ticker: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        trend = ticker.eps_trend
        if isinstance(trend, pd.DataFrame) and "0y" in trend.index:
            out["eps_current"] = _number(trend.at["0y", "current"])
            out["eps_90d_ago"] = _number(trend.at["0y", "90daysAgo"])
    except Exception:
        pass
    try:
        revisions = ticker.eps_revisions
        if isinstance(revisions, pd.DataFrame) and "0y" in revisions.index:
            out["revisions_up_30d"] = _number(revisions.at["0y", "upLast30days"])
            out["revisions_down_30d"] = _number(revisions.at["0y", "downLast30days"])
    except Exception:
        pass
    return out


def fetch_fx_rates(base: str, quote: str, *, days: int = 20, ticker_factory: Callable[[str], Any] | None = None) -> list[tuple[str, float]]:
    """Daily closes of ``base`` -> ``quote`` (quote units per one base unit) from Yahoo, newest last."""

    if ticker_factory is None:
        import yfinance

        ticker_factory = yfinance.Ticker
    history = ticker_factory(f"{base}{quote}=X").history(period=f"{max(days, 5)}d")
    if history is None or history.empty:
        return []
    return [(_iso(index) or "", float(value)) for index, value in history["Close"].dropna().items()]


# ---------------------------------------------------------------------------------------------
# SEC EDGAR companyfacts
# ---------------------------------------------------------------------------------------------


def _unit_values(concept: Mapping[str, Any], *, shares: bool) -> tuple[str, list[dict[str, Any]]]:
    units = concept.get("units", {}) or {}
    if shares:
        return "shares", list(units.get("shares", []))
    for name, entries in units.items():
        if name != "shares" and "/" not in name and entries:
            return name, list(entries)
    return "", []


def _valid_filed(value: Any) -> str | None:
    """A filing date only when it is a real ISO calendar date string; malformed values never win a period."""

    if not isinstance(value, str):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def parse_edgar_companyfacts(payload: Mapping[str, Any], config: Mapping[str, Any], *, source_ref: str,
                            preselected_vintage: bool = False) -> list[dict[str, Any]]:
    """Discrete quarters, fiscal years and balance sheets as originally filed (known_at = filing date).

    Cash-flow items are cumulative within the fiscal year in 10-Q filings, so every flow field is
    differenced along its cumulative chain (same start date): Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M.
    A value is taken from the earliest filing that reported it (as originally reported); later
    restatements never overwrite what was known earlier.

    ``preselected_vintage`` maps an already PIT-selected snapshot, including late
    restatements and comparatives. The caller must select visible facts first and
    stamp the resulting rows with that snapshot's filing knowledge time.
    """

    concepts = {**IDENTITY_SEC_CONCEPTS, **(config.get("sec_edgar_concepts", {}) or {})}
    gaap = (payload.get("facts", {}) or {}).get("us-gaap", {}) or {}
    dei = (payload.get("facts", {}) or {}).get("dei", {}) or {}
    currency = ""
    # Exclude late comparative-only facts: retaining them would postpone every
    # original value on a row because the storage contract has one known_at.
    max_lag = int((config.get("sec_edgar_rules", {}) or {}).get("max_original_filing_lag_days", 120))
    filing_ends: dict[tuple[str, str], str] = {}
    for concept_name in {name for names in concepts.values() for name in names}:
        for unit, facts in (gaap.get(concept_name, {}).get("units", {}) or {}).items():
            if unit == "shares" or "/" in unit:
                continue
            for fact in facts:
                end, filed = _valid_filed(fact.get("end")), _valid_filed(fact.get("filed"))
                if end and filed and end <= filed:
                    key = (filed, str(fact.get("accn") or ""))
                    filing_ends[key] = max(end, filing_ends.get(key, end))

    def original(end: str, filed: str, fact: Mapping[str, Any]) -> bool:
        if preselected_vintage:
            return end <= filed
        latest = filing_ends.get((filed, str(fact.get("accn") or "")), end)
        return end == latest and 0 <= _days(end, filed) <= max_lag
    selected_flow_concepts: dict[tuple[str, str, str], str] = {}
    flow_cumulative: dict[str, dict[tuple[str, str], tuple[float, str, str]]] = defaultdict(dict)
    def collect_flow(name: str, concept_names: Sequence[str]) -> dict[tuple[str, str], tuple[float, str, str]]:
        nonlocal currency
        merged: dict[tuple[str, str], tuple[float, str, str]] = {}
        for concept_name in concept_names:  # higher-priority concept wins per period
            concept = gaap.get(concept_name)
            if not concept:
                continue
            unit, entries = _unit_values(concept, shares=False)
            local: dict[tuple[str, str], tuple[float, str, str]] = {}
            for entry in entries:
                start, end, filed, value = entry.get("start"), entry.get("end"), _valid_filed(entry.get("filed")), _number(entry.get("val"))
                if not (start and end and filed) or value is None or not original(end, filed, entry):
                    continue
                key = (start, end)
                if key not in local or filed < local[key][1]:
                    local[key] = (value, filed, unit)
            for key, item in local.items():
                # As originally reported: the earliest-filed concept wins a period; a later-filed
                # lower-priority concept never suppresses it and the configured concept order
                # only breaks a same-filing tie.
                if key not in merged or item[1] < merged[key][1]:
                    merged[key] = item
                    selected_flow_concepts[(name, *key)] = concept_name
            currency = currency or unit
        return merged

    def collect_instant(concept_names: Sequence[str], *, shares: bool = False, source: Mapping[str, Any] | None = None) -> dict[str, tuple[float, str, str]]:
        nonlocal currency
        merged: dict[str, tuple[float, str, str]] = {}
        facts = gaap if source is None else source
        for concept_name in concept_names:
            concept = facts.get(concept_name)
            if not concept:
                continue
            unit, entries = _unit_values(concept, shares=shares)
            local: dict[str, tuple[float, str, str]] = {}
            ambiguous: set[str] = set()
            for entry in entries:
                end, filed, value = entry.get("end"), _valid_filed(entry.get("filed")), _number(entry.get("val"))
                if not (end and filed) or value is None or not original(end, filed, entry):
                    continue
                if end not in local or filed < local[end][1]:
                    local[end] = (value, filed, unit)
                    ambiguous.discard(end)
                elif filed == local[end][1] and value != local[end][0]:
                    # same period, same filing, different values (e.g. several share classes):
                    # insertion order must not decide, so the period is unavailable
                    ambiguous.add(end)
            for end, item in local.items():
                if end not in ambiguous:
                    if end not in merged or item[1] < merged[end][1]:
                        merged[end] = item
            if not shares:
                currency = currency or unit
        return merged

    for name in FLOW_FIELDS:
        names = list(concepts.get(name, []))
        if name == "capex":
            main = collect_flow(name, names)
            extra = collect_flow(name, list(concepts.get("capex_extra", [])))
            combined = dict(main)
            for key, (value, filed, unit) in extra.items():
                base = combined.get(key)
                if base is None:
                    # Intangible capex is retained separately, but it cannot stand in for the
                    # missing PP&E leg of total capex for this period.
                    continue
                elif unit != base[2]:
                    combined[key] = (0.0, max(filed, base[1]), "currency_mismatch")
                else:
                    combined[key] = (value + base[0], max(filed, base[1]), unit)
            flow_cumulative[name] = combined if main else {}
            # Keep intangible spend independently when PP&E spend is absent. Consumers must not
            # treat this component as a complete capex total.
            flow_cumulative["capex_extra"] = extra
        else:
            flow_cumulative[name] = collect_flow(name, names)

    # ----- cumulative chains -> discrete quarters and fiscal years -------------------------
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    statuses: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    # (field, quarter end) -> every candidate value; resolved once below so that the outcome never
    # depends on the order in which the filing facts or the chains were visited.
    quarter_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    def row(end: str, ptype: str) -> dict[str, Any]:
        entry = rows.setdefault(
            (end, ptype),
            {
                "period_end": end,
                "period_type": ptype,
                "fiscal_year": int(end[:4]),
                "currency": currency,
                "source": "sec_edgar",
                "source_ref": source_ref,
                # companyfacts holds only the us-gaap taxonomy and un-dimensioned (entity-wide) facts, so the
                # standard, the consolidated scope and "all share classes" are verified by the source structure
                "reporting_standard": "us-gaap",
                "consolidation_scope": "consolidated",
                "share_class": "all_classes",
                "_filed": [],
            },
        )
        return entry

    def concept_of(name: str, start: str, end: str) -> str | None:
        return selected_flow_concepts.get((name, start, end))

    def put_quarter(name: str, end: str, kind: str, value: float | None, unit: str, filed: Sequence[str], days: int, concepts: set[str | None]) -> None:
        row(end, "Q")
        quarter_candidates[(name, end)].append({"kind": kind, "value": value, "unit": unit, "filed": list(filed), "days": days, "concepts": concepts})

    for name, cumulative in flow_cumulative.items():
        chains: dict[str, list[tuple[str, float, str, str]]] = defaultdict(list)
        for (start, end), (value, filed, unit) in cumulative.items():
            chains[start].append((end, value, filed, unit))
        for start, links in sorted(chains.items()):
            links.sort()
            previous_end, previous_value, previous_filed, previous_unit = None, 0.0, "", ""
            for end, value, filed, unit in links:
                length = _days(start, end)
                if 345 <= length <= 385:
                    entry = row(end, "FY")
                    entry.setdefault("period_days", length)
                    if unit == "currency_mismatch":
                        entry[f"{name}_currency"] = unit
                    else:
                        entry[name] = value
                        if name == "net_income_parent":
                            entry["_income_concepts"] = {concept_of(name, start, end)}
                        entry[f"{name}_currency"] = unit
                    entry["_filed"].append(filed)
                if previous_end is None:
                    if 75 <= length <= 110:
                        # the first link is a discrete quarter; it is recorded as a direct fact below
                        previous_end, previous_value, previous_filed, previous_unit = end, value, filed, unit
                    else:
                        previous_end = ""  # chain does not start with a quarter (cannot difference)
                    continue
                if previous_end:
                    step = (date.fromisoformat(end) - date.fromisoformat(previous_end)).days
                    if 75 <= step <= 110:
                        if unit != previous_unit or unit == "currency_mismatch":
                            put_quarter(name, end, "inferred", None, "currency_mismatch", [filed, previous_filed], step, set())
                        else:
                            put_quarter(name, end, "inferred", value - previous_value, unit, [filed, previous_filed], step, {concept_of(name, start, end), concept_of(name, start, previous_end)})
                        previous_end, previous_value, previous_filed, previous_unit = end, value, filed, unit
                    else:
                        previous_end = ""
        # direct discrete quarters reported on their own (3-month facts), visited in a fixed order
        for (start, end), (value, filed, unit) in sorted(cumulative.items()):
            if 75 <= _days(start, end) <= 110:
                put_quarter(name, end, "direct", None if unit == "currency_mismatch" else value, unit, [filed], _days(start, end), {concept_of(name, start, end)})

    for (name, end), candidates in sorted(quarter_candidates.items()):
        entry = row(end, "Q")
        entry["_filed"].extend(item for candidate in candidates for item in candidate["filed"])
        # the duration belongs to the period, not to the value: it stays verified even when the value is conflicted
        entry.setdefault("period_days", min(candidates, key=lambda candidate: candidate["kind"] != "direct")["days"])
        units = {candidate["unit"] for candidate in candidates}
        if "currency_mismatch" in units or len(units) > 1:
            entry[f"{name}_currency"] = "currency_mismatch"
            statuses[(end, "Q")][name] = "conflicted"
            continue
        direct = [candidate for candidate in candidates if candidate["kind"] == "direct"]
        inferred = [candidate for candidate in candidates if candidate["kind"] == "inferred"]
        pool = [float(candidate["value"]) for candidate in candidates]
        if max(pool) - min(pool) > 0.005 * max(abs(item) for item in pool):
            # a reported quarter and its cumulative difference (or two chains) disagree: neither is guessed;
            # the tolerance is purely relative, so the verdict never depends on the monetary scale of the filing
            statuses[(end, "Q")][name] = "conflicted"
            continue
        chosen = (direct or inferred)[0]
        entry[name] = float(chosen["value"])
        entry[f"{name}_currency"] = chosen["unit"]
        if not direct:
            statuses[(end, "Q")][name] = "derived"
        if name == "net_income_parent":
            entry["_income_concepts"] = {concept for candidate in candidates for concept in candidate["concepts"]}

    # ----- balance sheet items ---------------------------------------------------------------
    equity = collect_instant(concepts.get("equity_parent", []))
    minority = collect_instant(concepts.get("minority_interest", []))
    total_assets = collect_instant(concepts.get("total_assets", []))
    total_liabilities = collect_instant(concepts.get("total_liabilities", []))
    cash = collect_instant(concepts.get("cash", []))
    sti = collect_instant(concepts.get("short_term_investments", []))
    debt_total_names = list(concepts.get("debt_total", []))
    debt_totals = {name: collect_instant([name]) for name in debt_total_names}
    debt_parts = {name: collect_instant([name]) for name in concepts.get("debt_parts", [])}
    lease_parts = {name: collect_instant([name]) for name in concepts.get("lease_parts", [])}
    shares = collect_instant(concepts.get("shares_outstanding", []), shares=True)

    for (end, ptype), entry in list(rows.items()):
        def pick(series: Mapping[str, tuple[float, str, str]]) -> tuple[float, str, str] | None:
            return series.get(end)

        for name, series in (("equity_parent", equity), ("minority_interest", minority), ("total_assets", total_assets), ("total_liabilities", total_liabilities), ("shares_outstanding", shares)):
            item = pick(series)
            if item is not None:
                entry[name] = item[0]
                entry[f"{name}_currency"] = item[2]
                entry["_filed"].append(item[1])
        minority_item = pick(minority)
        if (
            minority_item is not None
            and minority_item[0] > 0
            and any(
                {"NetIncomeLoss": "consolidated", "NetIncomeLossAvailableToCommonStockholdersBasic": "common_available"}.get(concept, "unverified") != "parent"
                for concept in entry.get("_income_concepts", {None})
            )
        ):
            # Only an explicitly parent-attributable selected fact can establish scope; a
            # positive non-controlling balance makes it unsafe for parent-equity multiples.
            entry.pop("net_income_parent", None)
            entry.pop("net_income_parent_currency", None)
        cash_item, sti_item = pick(cash), pick(sti)
        if cash_item is not None:
            entry["cash"] = cash_item[0]
            entry["cash_currency"] = cash_item[2]
            entry["_filed"].append(cash_item[1])
        if cash_item is not None and sti_item is not None:
            if cash_item[2] == sti_item[2]:
                entry["cash_sti"] = cash_item[0] + sti_item[0]
                entry["cash_sti_currency"] = cash_item[2]
            else:
                entry["cash_sti_currency"] = "currency_mismatch"
            entry["_filed"].extend([cash_item[1], sti_item[1]])

        lease_found = [(name, pick(series)) for name, series in lease_parts.items()]
        lease_found = [(name, item) for name, item in lease_found if item is not None]
        lease_currency: str | None = None
        lease_value = 0.0
        if lease_found:
            currencies = {item[2] for _, item in lease_found}
            if len(currencies) == 1:
                lease_currency = next(iter(currencies))
                lease_value = sum(item[0] for _, item in lease_found)
                entry["lease_liabilities"] = lease_value
                entry["lease_liabilities_currency"] = lease_currency
            else:
                entry["lease_liabilities_currency"] = "currency_mismatch"
            entry["_filed"].extend(item[1] for _, item in lease_found)

        debt_item = min(((name, pick(series)) for name, series in debt_totals.items() if pick(series) is not None),
                        key=lambda item: item[1][1], default=None)
        if debt_item is not None:
            debt_name, debt = debt_item
            assert debt is not None
            # DebtAndCapitalLeaseObligations already holds every debt part; LongTermDebt holds the
            # current and non-current long-term portions. Adding either part again double counts it.
            included_in_total = {
                "DebtAndCapitalLeaseObligations": set(debt_parts),
                "LongTermDebt": {"LongTermDebtNoncurrent", "LongTermDebtCurrent"},
            }.get(debt_name, {"LongTermDebtNoncurrent"})
            extra_names = [name for name in debt_parts if name not in included_in_total]
            extras = [(name, pick(debt_parts[name])) for name in extra_names]
            extras = [(name, item) for name, item in extras if item is not None]
            debt_items = [debt, *(item for _, item in extras)]
            comprehensive = debt_name == "DebtAndCapitalLeaseObligations"
            summed = bool(extras)
            if comprehensive and lease_currency == debt[2]:
                finance_leases = [item for name, item in lease_found if "FinanceLease" in name]
                debt_value = debt[0] - sum(item[0] for item in finance_leases)
                summed = summed or bool(finance_leases)
            else:
                debt_value = debt[0] + sum(item[0] for _, item in extras)
            if len({item[2] for item in debt_items}) != 1 or (comprehensive and lease_found and lease_currency != debt[2]):
                entry["ib_debt_currency"] = "currency_mismatch"
            else:
                entry["ib_debt"] = debt_value
                entry["ib_debt_currency"] = debt[2]
                if summed:
                    statuses[(end, ptype)]["ib_debt"] = "derived"  # a reported total plus optional parts: computed, not one reported fact
            entry["_filed"].extend([debt[1], *(item[1] for _, item in extras)])
        else:
            parts = [(name, pick(series)) for name, series in debt_parts.items()]
            parts = [(name, item) for name, item in parts if item is not None]
            if parts:
                if len({item[2] for _, item in parts}) == 1:
                    entry["ib_debt"] = sum(item[0] for _, item in parts)
                    entry["ib_debt_currency"] = parts[0][1][2]
                    found = {name for name, _ in parts}
                    # Both long-term portions are required components. companyfacts cannot tell "none" from
                    # "not reported" for an absent portion, so an absent required part is never counted as 0:
                    # the sum is partial. ShortTermBorrowings / CommercialPaper are optional supplements.
                    required = {"LongTermDebtNoncurrent", "LongTermDebtCurrent"} & set(debt_parts)
                    statuses[(end, ptype)]["ib_debt"] = "partial" if required - found else "derived"
                else:
                    entry["ib_debt_currency"] = "currency_mismatch"
                entry["_filed"].extend(item[1] for _, item in parts)
        reported_currencies = [
            str(entry.get(f"{name}_currency"))
            for name in FLOW_FIELDS + BALANCE_FIELDS
            if name != "shares_outstanding" and name in entry and entry.get(f"{name}_currency") not in (None, "currency_mismatch")
        ]
        if reported_currencies:
            entry["currency"] = max(reported_currencies, key=reported_currencies.count)
    output = []
    for key, entry in rows.items():
        entry.pop("_income_concepts", None)
        if statuses.get(key):
            entry["value_status"] = json.dumps(statuses[key], sort_keys=True)
        filed = [item for item in entry.pop("_filed") if item]
        if not filed:
            continue
        entry["known_at"] = max(filed)
        if not any(name in entry for name in FLOW_FIELDS + BALANCE_FIELDS) and "value_status" not in entry:
            continue
        output.append(entry)
    # A cover-page share count is a separate publication at its actual instant,
    # never a balance-sheet value backdated to the preceding fiscal period.
    # Keep every publication so the latest ambiguous filing can block an older
    # count. Values from different classes are never summed or guessed.
    publications: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    cover_names = (config.get("sec_edgar_rules", {}) or {}).get("dei_shares", ["EntityCommonStockSharesOutstanding"])
    for name in cover_names:
        _, facts = _unit_values(dei.get(name, {}), shares=True)
        for fact in facts:
            end, filed, value = fact.get("end"), _valid_filed(fact.get("filed")), _number(fact.get("val"))
            if end and filed and value is not None and end <= filed:
                publications[(end, filed)].append(fact)
    for (end, filed), facts in sorted(publications.items()):
        values = {_number(fact.get("val")) for fact in facts}
        conflicted = len(values) != 1 or any(fact.get("dimensions") or fact.get("segment") for fact in facts)
        value = next(iter(values)) if len(values) == 1 else None
        output.append({
            "period_end": end, "period_type": "SHARES", "fiscal_year": int(end[:4]),
            "currency": "", "source": "sec_dei", "source_ref": source_ref,
            "known_at": filed, "available_at": filed,
            "share_class": "unverified" if conflicted else "all_classes",
            **({"shares_outstanding": value} if value is not None and value > 0 else {}),
            **({"value_status": json.dumps({"shares_outstanding": "conflicted" if conflicted else "invalid"})}
               if conflicted or value is None or value <= 0 else {}),
        })
    return sorted(output, key=lambda item: (item["period_end"], item["period_type"]))


def sec_user_agent(config: Mapping[str, Any], environ: Mapping[str, str]) -> str | None:
    name = str((config.get("sources", {}) or {}).get("sec_edgar_user_agent_env") or "ETF_COCKPIT_SEC_EDGAR_USER_AGENT")
    value = str(environ.get(name, "") or "").strip()
    return value or None


def http_get_json(url: str, user_agent: str, *, timeout: float = 30.0, opener: Callable[..., Any] | None = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_cik(symbol: str, user_agent: str, *, fetch: Callable[[str, str], Any] = http_get_json) -> str | None:
    """CIK for a US ticker from SEC's own ticker file; non-US symbols (with an exchange suffix) have no CIK."""

    if not symbol or "." in symbol:
        return None
    mapping = fetch(SEC_TICKERS_URL, user_agent)
    wanted = symbol.upper()
    for item in (mapping.values() if isinstance(mapping, Mapping) else mapping):
        if str(item.get("ticker", "")).upper() == wanted:
            return str(int(item["cik_str"])).zfill(10)
    return None


def fetch_edgar(
    cik: str,
    config: Mapping[str, Any],
    *,
    user_agent: str | None,
    fetch: Callable[[str, str], Any] = http_get_json,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    result = FetchResult("sec_edgar")
    if not user_agent:
        result.status = "unavailable"
        result.reason = "SEC EDGAR needs a User-Agent: set ETF_COCKPIT_SEC_EDGAR_USER_AGENT to '<name> <contact>'"
        return result
    sleep(0.15)  # SEC fair-access: well under 10 requests per second
    try:
        payload = fetch(SEC_COMPANYFACTS_URL.format(cik=str(cik).zfill(10)), user_agent)
    except Exception as exc:
        result.status = "error"
        result.reason = f"SEC EDGAR companyfacts request for CIK {cik} failed: {str(exc)[:120]}"
        return result
    # SHARES publications are owned by sec_edgar_provider.parse_reported_shares (accession-level);
    # keeping the parser's copy here would store every filing twice (one canonical path).
    result.rows = [row for row in parse_edgar_companyfacts(payload, config, source_ref=f"sec_edgar:CIK{str(cik).zfill(10)}")
                   if row.get("period_type") != "SHARES"]
    result.snapshot = {"source": "sec_edgar", "entity": payload.get("entityName"), "cik": str(cik).zfill(10)}
    if not result.rows:
        result.status = "no_statements"
        result.reason = f"SEC EDGAR holds no us-gaap statement facts for CIK {cik}"
    return result


# ---------------------------------------------------------------------------------------------
# ESEF / IFRS statement facts (already imported into the statement-facts store; no network request)
# ---------------------------------------------------------------------------------------------

ESEF_SOURCE = "esef"
# The only concept net_income_parent may come from. It is parent-only by definition, which is what justifies the explicit
# ``observed`` state below; total ProfitLoss (parent + non-controlling) must never fill it, whatever the configuration says.
ESEF_PARENT_INCOME_CONCEPTS = frozenset({"ProfitLossAttributableToOwnersOfParent"})
_CURRENCY_UNIT = re.compile(r"^[A-Z]{3}$")
_MEMBER_SPEC = re.compile(r"^([A-Za-z0-9_]+)\[([A-Za-z0-9_]+)\]$")


def _esef_timestamp(value: object) -> pd.Timestamp | None:
    stamp = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(stamp) else stamp


def _esef_member(dimensions: object) -> str | None:
    """The member of a facts row whose only dimension is ComponentsOfEquityAxis; ``""`` for no dimension; None otherwise."""

    text = "" if dimensions is None or (isinstance(dimensions, float) and math.isnan(dimensions)) else str(dimensions).strip()
    if text in ("", "{}"):
        return ""
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"ifrs-full:ComponentsOfEquityAxis"}:
        return None
    return str(parsed["ifrs-full:ComponentsOfEquityAxis"]).split(":")[-1]


def _esef_spec(spec: str) -> tuple[str, str]:
    match = _MEMBER_SPEC.match(spec)
    return (match.group(1), match.group(2)) if match else (spec, "")


def parse_esef_statement_facts(facts: pd.DataFrame, config: Mapping[str, Any], *, source_ref: str) -> list[dict[str, Any]]:
    """Annual Period rows from ESEF/IFRS statement facts, as originally reported.

    ``known_at`` of a value is the registry ``date_added`` of the earliest filing that reported it; later
    comparatives and restatements never replace what was known earlier, and a row becomes visible only at the
    latest ``known_at`` among its values. Only consolidated, undimensioned ifrs-full facts qualify (plus the
    equity-axis member fallbacks named in ``esef_concepts``). A fact without a valid ``known_at`` or a numeric
    value is dropped; a field nobody tagged is simply absent (never zero), a disagreement is ``conflicted``.
    """

    concepts: dict[str, list[str]] = {name: list(items or []) for name, items in (config.get("esef_concepts", {}) or {}).items()}
    if "net_income_parent" in concepts:
        concepts["net_income_parent"] = [spec for spec in concepts["net_income_parent"] if spec in ESEF_PARENT_INCOME_CONCEPTS]
    rules = config.get("esef_rules", {}) or {}
    tolerance = float(rules.get("share_count_agreement", 0.01))
    absolute_fields = set(rules.get("absolute_value_fields", []) or [])
    if facts is None or facts.empty:
        return []

    wanted = {_esef_spec(spec) for specs in concepts.values() for spec in specs}
    prepared: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in facts.to_dict("records"):
        concept = str(record.get("concept") or "")
        if str(record.get("taxonomy") or "") != "ifrs-full" or str(record.get("consolidation_scope") or "") != "consolidated":
            continue
        member = _esef_member(record.get("dimensions"))
        if member is None or (concept, member) not in wanted:
            continue
        value = _number(record.get("value"))
        known = _esef_timestamp(record.get("known_at"))
        if value is None or known is None:
            continue
        start, end, instant = record.get("start"), record.get("end"), record.get("instant")
        prepared[(concept, member)].append(
            {
                "value": value,
                "known": known,
                "unit": str(record.get("unit") or ""),
                "start": str(start) if start else None,
                "end": str(end) if end else None,
                "instant": str(instant) if instant else None,
            }
        )

    def collect(name: str, *, kind: str, unit_ok: Callable[[str], bool]) -> dict[Any, tuple[float, pd.Timestamp, str, bool]]:
        """period key -> (value, known_at, unit, filings_agree); the earliest known_at wins, config order breaks a tie."""

        merged: dict[Any, tuple[float, pd.Timestamp, str, bool]] = {}
        for spec in (_esef_spec(item) for item in concepts.get(name, [])):
            local: dict[Any, list[dict[str, Any]]] = defaultdict(list)
            for item in prepared.get(spec, []):
                if not unit_ok(item["unit"]):
                    continue
                if kind == "flow":
                    if not (item["start"] and item["end"]):
                        continue
                    key: Any = (item["start"], item["end"])
                else:
                    key = item["instant"] or (item["end"] if not item["start"] else None)
                    if not key:
                        continue
                local[key].append(item)
            for key, items in local.items():
                first_known = min(item["known"] for item in items)
                earliest = [item for item in items if item["known"] == first_known]
                if len({item["value"] for item in earliest}) > 1 or len({item["unit"] for item in earliest}) > 1:
                    continue  # one filing, two different values for the same period: nothing is guessed
                agree = True
                if name == "shares_outstanding":
                    pool = [item["value"] for item in items]
                    agree = max(pool) - min(pool) <= tolerance * max(abs(value) for value in pool)
                if key not in merged or first_known < merged[key][1]:
                    merged[key] = (earliest[0]["value"], first_known, earliest[0]["unit"], agree)
        return merged

    def is_currency(unit: str) -> bool:
        return bool(_CURRENCY_UNIT.match(unit))

    flow = {name: collect(name, kind="flow", unit_ok=is_currency) for name in FLOW_FIELDS if concepts.get(name)}
    instant_names = ("equity_parent", "minority_interest", "total_assets", "total_liabilities", "cash", "debt_total", "debt_noncurrent", "debt_current", "lease_total", "lease_noncurrent", "lease_current")
    instant = {name: collect(name, kind="instant", unit_ok=is_currency) for name in instant_names if concepts.get(name)}
    if concepts.get("shares_outstanding"):
        instant["shares_outstanding"] = collect("shares_outstanding", kind="instant", unit_ok=lambda unit: unit == "shares")

    rows: dict[str, dict[str, Any]] = {}
    statuses: dict[str, dict[str, str]] = defaultdict(dict)
    known_of: dict[str, list[pd.Timestamp]] = defaultdict(list)

    for name, series in flow.items():
        for (start, end), (value, known, unit, _agree) in series.items():
            length = _days(start, end)
            if not 345 <= length <= 385:
                continue
            entry = rows.setdefault(
                end,
                {
                    "period_end": end,
                    "period_type": "FY",
                    "fiscal_year": int(end[:4]),
                    "currency": "",
                    "source": ESEF_SOURCE,
                    "source_ref": source_ref,
                    "reporting_standard": "ifrs",
                    "consolidation_scope": "consolidated",
                    "share_class": "all_classes",
                },
            )
            entry.setdefault("period_days", length)
            entry[name] = abs(value) if name in absolute_fields else value
            entry[f"{name}_currency"] = unit
            known_of[end].append(known)

    for end, entry in rows.items():
        def at(name: str, day: str = end) -> tuple[float, pd.Timestamp, str, bool] | None:
            return instant.get(name, {}).get(day)

        for name in ("equity_parent", "minority_interest", "total_assets", "total_liabilities", "cash"):
            item = at(name)
            if item is not None:
                entry[name], entry[f"{name}_currency"] = item[0], item[2]
                known_of[end].append(item[1])
        shares = at("shares_outstanding")
        if shares is not None:
            if shares[3]:
                entry["shares_outstanding"] = shares[0]
                known_of[end].append(shares[1])
            else:
                statuses[end]["shares_outstanding"] = "conflicted"
        # interest-bearing debt: a reported total, else non-current + current when both are tagged; one side alone is partial
        total = at("debt_total")
        if total is not None:
            entry["ib_debt"], entry["ib_debt_currency"] = total[0], total[2]
            known_of[end].append(total[1])
        else:
            parts = [item for item in (at("debt_noncurrent"), at("debt_current")) if item is not None]
            if parts:
                if len({item[2] for item in parts}) == 1:
                    entry["ib_debt"], entry["ib_debt_currency"] = sum(item[0] for item in parts), parts[0][2]
                    statuses[end]["ib_debt"] = "derived" if len(parts) == 2 else "partial"
                else:
                    entry["ib_debt_currency"] = "currency_mismatch"
                known_of[end].extend(item[1] for item in parts)
        lease = at("lease_total")
        lease_parts = [item for item in (at("lease_noncurrent"), at("lease_current")) if item is not None]
        if lease is not None:
            entry["lease_liabilities"], entry["lease_liabilities_currency"] = lease[0], lease[2]
            known_of[end].append(lease[1])
        elif len(lease_parts) == 2:  # one side alone is not the liability: it stays unavailable
            if lease_parts[0][2] == lease_parts[1][2]:
                entry["lease_liabilities"], entry["lease_liabilities_currency"] = lease_parts[0][0] + lease_parts[1][0], lease_parts[0][2]
                statuses[end]["lease_liabilities"] = "derived"
            else:
                entry["lease_liabilities_currency"] = "currency_mismatch"
            known_of[end].extend(item[1] for item in lease_parts)
        reported = [
            str(entry[f"{name}_currency"])
            for name in FLOW_FIELDS + BALANCE_FIELDS
            if name != "shares_outstanding" and name in entry and entry.get(f"{name}_currency") not in (None, "currency_mismatch")
        ]
        if reported:
            entry["currency"] = max(reported, key=reported.count)

    output: list[dict[str, Any]] = []
    for end, entry in rows.items():
        if "net_income_parent" in entry:
            # ProfitLossAttributableToOwnersOfParent is parent-only by definition: the explicit state tells the store
            # that the ownership scope is verified, so a positive non-controlling interest does not drop the value
            statuses[end].setdefault("net_income_parent", "observed")
        entry["known_at"] = max(known_of[end]).isoformat(timespec="microseconds")
        if statuses.get(end):
            entry["value_status"] = json.dumps(statuses[end], sort_keys=True)
        output.append(entry)
    return sorted(output, key=lambda item: item["period_end"])


def fetch_esef(
    instrument_id: str,
    config: Mapping[str, Any],
    *,
    facts: pd.DataFrame | None = None,
    facts_path: Path | None = None,
    root: Path | None = None,
) -> FetchResult:
    """ESEF/IFRS annual periods for one instrument from the imported statement-facts store (no network).

    With ``root`` the store is ``<root>/data/clean/statement_facts.parquet``; the process-wide path is used only without one."""

    result = FetchResult(ESEF_SOURCE)
    if facts is None:
        path = Path(facts_path) if facts_path else (Path(root) / "data" / "clean" / "statement_facts.parquet" if root else Path(STATEMENT_FACTS_PATH))
        if not path.exists():
            result.status, result.reason = "unavailable", f"no ESEF statement facts store at {path}"
            return result
        try:
            facts = pd.read_parquet(path)
        except Exception as exc:
            result.status, result.reason = "error", f"ESEF statement facts store unreadable: {str(exc)[:120]}"
            return result
    if "instrument_id" not in facts.columns:
        result.status, result.reason = "error", "ESEF statement facts store has no instrument_id column"
        return result
    own = facts[facts["instrument_id"].astype(str) == str(instrument_id)]
    if own.empty:
        result.status, result.reason = "unavailable", f"no ESEF statement facts imported for {instrument_id}"
        return result
    result.rows = parse_esef_statement_facts(own, config, source_ref=f"esef:filings_xbrl_org:{instrument_id}")
    result.snapshot = {"source": ESEF_SOURCE, "entity": instrument_id}
    if not result.rows:
        result.status, result.reason = "no_statements", f"ESEF facts for {instrument_id} hold no mapped annual statement values"
    return result
