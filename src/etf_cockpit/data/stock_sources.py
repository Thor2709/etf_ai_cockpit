"""Free-source fetchers and parsers for normal-stock fundamentals (SEC EDGAR companyfacts, yfinance).

Each source returns plain period rows (one dict per reported period) in the single canonical field
set of ``stock_metrics``. Nothing here decides which source wins; ``stock_fundamentals`` merges them.
Network access is read-only and injectable so every parser has an offline test.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from etf_cockpit.analysis.stock_metrics import BALANCE_FIELDS, FLOW_FIELDS

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass
class FetchResult:
    source: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | no_statements | not_found | error | unavailable
    reason: str = ""


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
        if total_debt is not None:
            values["ib_debt"] = total_debt - (lease or 0.0)
        rows.append(
            {
                "period_end": end,
                "period_type": period_type,
                "fiscal_year": int(end[:4]),
                "currency": currency,
                "source": "yfinance",
                "known_at": known_at,
                "source_ref": source_ref,
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
        result.status = "not_found" if "404" in text or "Not Found" in text else "error"
        result.reason = f"Yahoo returned no profile for {symbol}: {text[:140]}"
        result.snapshot = {"known_at": known_at, "source": "yfinance", "status": result.status, "reason": result.reason}
        return result
    financial_currency = str(info.get("financialCurrency") or info.get("currency") or "")
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

    def frame(name: str) -> pd.DataFrame:
        try:
            value = getattr(ticker, name)
            return value if isinstance(value, pd.DataFrame) else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    labels = config.get("yfinance_labels", {})
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
    snapshot.update(_analyst_fields(ticker))
    if not result.rows:
        result.status = "no_statements"
        result.reason = f"Yahoo lists {symbol} but returns no income statement, balance sheet or cash flow"
        snapshot.update(status=result.status, reason=result.reason)
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


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def parse_edgar_companyfacts(payload: Mapping[str, Any], config: Mapping[str, Any], *, source_ref: str) -> list[dict[str, Any]]:
    """Discrete quarters, fiscal years and balance sheets as originally filed (known_at = filing date).

    Cash-flow items are cumulative within the fiscal year in 10-Q filings, so every flow field is
    differenced along its cumulative chain (same start date): Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M.
    A value is taken from the earliest filing that reported it (as originally reported); later
    restatements never overwrite what was known earlier.
    """

    concepts = config.get("sec_edgar_concepts", {})
    gaap = (payload.get("facts", {}) or {}).get("us-gaap", {}) or {}
    dei = (payload.get("facts", {}) or {}).get("dei", {}) or {}
    currency = ""
    flow_cumulative: dict[str, dict[tuple[str, str], tuple[float, str]]] = defaultdict(dict)
    instants: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)

    def collect_flow(name: str, concept_names: Sequence[str]) -> dict[tuple[str, str], tuple[float, str]]:
        nonlocal currency
        merged: dict[tuple[str, str], tuple[float, str]] = {}
        for concept_name in concept_names:  # higher-priority concept wins per period
            concept = gaap.get(concept_name)
            if not concept:
                continue
            unit, entries = _unit_values(concept, shares=False)
            local: dict[tuple[str, str], tuple[float, str]] = {}
            for entry in entries:
                start, end, filed, value = entry.get("start"), entry.get("end"), entry.get("filed"), _number(entry.get("val"))
                if not (start and end and filed) or value is None:
                    continue
                key = (start, end)
                if key not in local or filed < local[key][1]:
                    local[key] = (value, filed)
            for key, item in local.items():
                merged.setdefault(key, item)
            currency = currency or unit
        return merged

    def collect_instant(concept_names: Sequence[str], *, shares: bool = False, source: Mapping[str, Any] | None = None) -> dict[str, tuple[float, str]]:
        merged: dict[str, tuple[float, str]] = {}
        facts = gaap if source is None else source
        for concept_name in concept_names:
            concept = facts.get(concept_name)
            if not concept:
                continue
            _unit, entries = _unit_values(concept, shares=shares)
            local: dict[str, tuple[float, str]] = {}
            for entry in entries:
                end, filed, value = entry.get("end"), entry.get("filed"), _number(entry.get("val"))
                if not (end and filed) or value is None:
                    continue
                if end not in local or filed < local[end][1]:
                    local[end] = (value, filed)
            for end, item in local.items():
                merged.setdefault(end, item)
        return merged

    for name in FLOW_FIELDS:
        names = list(concepts.get(name, []))
        if name == "capex":
            main = collect_flow(name, names)
            extra = collect_flow(name, list(concepts.get("capex_extra", [])))
            combined = dict(main)
            for key, (value, filed) in extra.items():
                base = combined.get(key)
                combined[key] = (value + (base[0] if base else 0.0), max(filed, base[1]) if base else filed)
            flow_cumulative[name] = combined if main else {}
        else:
            flow_cumulative[name] = collect_flow(name, names)

    # ----- cumulative chains -> discrete quarters and fiscal years -------------------------
    rows: dict[tuple[str, str], dict[str, Any]] = {}

    def row(end: str, ptype: str) -> dict[str, Any]:
        entry = rows.setdefault(
            (end, ptype),
            {"period_end": end, "period_type": ptype, "fiscal_year": int(end[:4]), "currency": currency, "source": "sec_edgar", "source_ref": source_ref, "_filed": []},
        )
        return entry

    for name, cumulative in flow_cumulative.items():
        chains: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for (start, end), (value, filed) in cumulative.items():
            chains[start].append((end, value, filed))
        for start, links in chains.items():
            links.sort()
            previous_end, previous_value, previous_filed = None, 0.0, ""
            for end, value, filed in links:
                length = _days(start, end)
                if 345 <= length <= 385:
                    entry = row(end, "FY")
                    entry[name] = value
                    entry["_filed"].append(filed)
                if previous_end is None:
                    expected_first = 75 <= length <= 110
                    if expected_first:
                        entry = row(end, "Q")
                        entry[name] = value
                        entry["_filed"].append(filed)
                        previous_end, previous_value, previous_filed = end, value, filed
                    else:
                        previous_end = ""  # chain does not start with a quarter (cannot difference)
                    continue
                if previous_end:
                    step = (date.fromisoformat(end) - date.fromisoformat(previous_end)).days
                    if 75 <= step <= 110:
                        entry = row(end, "Q")
                        entry[name] = value - previous_value
                        entry["_filed"].extend([filed, previous_filed])
                        previous_end, previous_value, previous_filed = end, value, filed
                    else:
                        previous_end = ""
                # direct discrete quarters reported on their own (3-month facts with a later start)
        for (start, end), (value, filed) in cumulative.items():
            if 75 <= _days(start, end) <= 110:
                entry = row(end, "Q")
                if name not in entry:
                    entry[name] = value
                    entry["_filed"].append(filed)

    # ----- balance sheet items ---------------------------------------------------------------
    equity = collect_instant(concepts.get("equity_parent", []))
    minority = collect_instant(concepts.get("minority_interest", []))
    total_assets = collect_instant(concepts.get("total_assets", []))
    cash = collect_instant(concepts.get("cash", []))
    sti = collect_instant(concepts.get("short_term_investments", []))
    debt_total = collect_instant(concepts.get("debt_total", []))
    debt_parts = [collect_instant([part]) for part in concepts.get("debt_parts", [])]
    lease_parts = [collect_instant([part]) for part in concepts.get("lease_parts", [])]
    shares = collect_instant(concepts.get("shares_outstanding", []), shares=True)
    cover = collect_instant(["EntityCommonStockSharesOutstanding"], shares=True, source=dei)

    ends = {end for (end, _t) in rows} | set(equity)
    for (end, ptype), entry in list(rows.items()):
        def pick(series: Mapping[str, tuple[float, str]]) -> tuple[float, str] | None:
            return series.get(end)

        for name, series in (("equity_parent", equity), ("minority_interest", minority), ("total_assets", total_assets), ("shares_outstanding", shares)):
            item = pick(series)
            if item is not None:
                entry[name] = item[0]
                entry["_filed"].append(item[1])
        if "shares_outstanding" not in entry:
            for cover_end, (value, filed) in cover.items():
                # cover-page count of the filing that reports this period: filed within 120 days after the period end
                if 0 <= (date.fromisoformat(filed) - date.fromisoformat(end)).days <= 120 and (date.fromisoformat(cover_end) >= date.fromisoformat(end)):
                    entry["shares_outstanding"] = value
                    entry["_filed"].append(filed)
                    break
        cash_item, sti_item = pick(cash), pick(sti)
        if cash_item is not None:
            entry["cash_sti"] = cash_item[0] + (sti_item[0] if sti_item else 0.0)
            entry["_filed"].append(cash_item[1])
        debt = pick(debt_total)
        if debt is not None:
            entry["ib_debt"] = debt[0]
            entry["_filed"].append(debt[1])
        else:
            parts = [item for item in (pick(series) for series in debt_parts) if item is not None]
            if parts:
                entry["ib_debt"] = sum(item[0] for item in parts)
                entry["_filed"].extend(item[1] for item in parts)
        lease_found = [item for item in (pick(series) for series in lease_parts) if item is not None]
        if lease_found:
            entry["lease_liabilities"] = sum(item[0] for item in lease_found)
            entry["_filed"].extend(item[1] for item in lease_found)
    del ends

    output = []
    for entry in rows.values():
        filed = [item for item in entry.pop("_filed") if item]
        if not filed:
            continue
        entry["known_at"] = max(filed)
        if not any(name in entry for name in FLOW_FIELDS + BALANCE_FIELDS):
            continue
        output.append(entry)
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
    result.rows = parse_edgar_companyfacts(payload, config, source_ref=f"sec_edgar:CIK{str(cik).zfill(10)}")
    result.snapshot = {"source": "sec_edgar", "entity": payload.get("entityName"), "cik": str(cik).zfill(10)}
    if not result.rows:
        result.status = "no_statements"
        result.reason = f"SEC EDGAR holds no us-gaap statement facts for CIK {cik}"
    return result
