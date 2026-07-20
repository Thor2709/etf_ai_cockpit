"""Transparent stock research analytics over canonical statement evidence.

The functions in this module deliberately return evidence dictionaries rather
than an action score. Every value carries a formula, period, source coverage
and confidence boundary. Missing inputs remain missing and structurally
inapplicable sectors are not forced through industrial formulas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import math
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import RAW_DIR
from etf_cockpit.data.statement_normalisation import statement_coverage, statement_view


STOCK_RESEARCH_SCHEMA_VERSION = "stock_research.v2"
STOCK_RESEARCH_IMPORT_DIR = RAW_DIR / "stock_research"
CONSENSUS_IMPORT_PATH = STOCK_RESEARCH_IMPORT_DIR / "consensus.csv"
GUIDANCE_IMPORT_PATH = STOCK_RESEARCH_IMPORT_DIR / "guidance.csv"
_SPECIAL_SECTORS = frozenset({"bank", "banks", "insurance", "insurer", "financial", "financials"})
_CONSENSUS_SOURCE_AUTHORITIES = frozenset(
    {
        "broker licensed",
        "broker_licensed",
        "licensed vendor",
        "licensed_vendor",
        "user supplied",
        "user-supplied",
        "user owned",
        "user_owned",
        "user-owned",
        "broker-licensed",
    }
)
_GUIDANCE_SOURCE_AUTHORITIES = frozenset({"company", "company official", "company_official", "official", "issuer"})
_REVIEWED_GUIDANCE_STATUSES = frozenset({"approved", "human_reviewed", "reviewed", "structured", "verified"})
_REJECTED_LICENCE_MARKERS = frozenset({"denied", "expired", "prohibited", "restricted", "unlicensed", "unknown"})
_GROWTH_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales"),
    "operating_profit": ("operating_profit", "operating_income", "ebit"),
    "free_cash_flow": ("free_cash_flow",),
    "net_income": ("net_income", "net_profit"),
    "shares_outstanding": ("shares_outstanding", "weighted_average_shares", "diluted_shares"),
    "earnings_per_share": ("earnings_per_share", "eps", "basic_eps", "diluted_eps"),
    "organic_revenue": ("organic_revenue", "organic_sales"),
    "acquisition_revenue": ("acquisition_revenue", "inorganic_revenue", "acquired_revenue"),
}


@dataclass(frozen=True)
class MetricEvidence:
    name: str
    value: float | None
    status: str
    formula: str
    period: str
    source_ids: tuple[str, ...]
    confidence: str
    applicability: str = "applicable"
    limitation: str = ""


def profitability_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    peer_frame: pd.DataFrame | None = None,
    tax_rate: float | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    latest = _latest_values(frame)
    histories = _histories(frame)
    metrics: dict[str, dict[str, object]] = {}
    revenue = latest.get("revenue")
    gross_profit = latest.get("gross_profit")
    operating_income = latest.get("operating_income")
    net_income = latest.get("net_income")
    assets = latest.get("assets")
    equity = latest.get("equity")
    debt = latest.get("debt")
    cash = latest.get("cash")
    cfo = latest.get("cash_from_operations")
    tax = tax_rate if tax_rate is not None else _tax_rate(latest)

    metrics["gross_margin"] = _ratio_metric("gross_margin", gross_profit, revenue, "gross_profit / revenue", frame, "revenue")
    metrics["operating_margin"] = _ratio_metric("operating_margin", operating_income, revenue, "operating_income / revenue", frame, "revenue")
    metrics["net_margin"] = _ratio_metric("net_margin", net_income, revenue, "net_income / revenue", frame, "revenue")
    metrics["roa"] = _ratio_metric("roa", net_income, assets, "net_income / assets", frame, "assets")
    metrics["roe"] = _ratio_metric("roe", net_income, equity, "net_income / equity", frame, "equity")
    invested_capital = _sum_if_present(equity, debt, -cash if cash is not None else None)
    roic = None if sector.casefold() in _SPECIAL_SECTORS else (None if operating_income is None or tax is None else operating_income * (1.0 - tax))
    metrics["roic"] = _ratio_metric(
        "roic",
        roic,
        invested_capital,
        "(operating_income * (1 - tax_rate)) / (equity + debt - cash)",
        frame,
        "equity",
        applicability="not_applicable" if sector.casefold() in _SPECIAL_SECTORS else "applicable",
        limitation="Special-sector adapter required." if sector.casefold() in _SPECIAL_SECTORS else "",
    )
    metrics["cash_conversion"] = _ratio_metric("cash_conversion", cfo, net_income, "cash_from_operations / net_income", frame, "cash_from_operations", zero_denominator_status="not_applicable")
    accrual_numerator = None if net_income is None or cfo is None else net_income - cfo
    metrics["accrual_ratio"] = _ratio_metric("accrual_ratio", accrual_numerator, assets, "(net_income - cash_from_operations) / assets", frame, "assets")
    exceptional = latest.get("exceptional_items")
    metrics["exceptional_item_dependence"] = _ratio_metric("exceptional_item_dependence", exceptional, net_income, "exceptional_items / net_income", frame, "exceptional_items", zero_denominator_status="not_applicable")
    margins = _derived_history(histories, "gross_profit", "revenue")
    metrics["margin_stability"] = _metric(
        "margin_stability",
        None if len(margins) < 2 else float(pd.Series(margins).std(ddof=0)),
        "population standard deviation of gross_margin history",
        frame,
        status_override="missing" if len(margins) == 0 else "not_applicable" if len(margins) == 1 else None,
        limitation="At least two comparable periods are required." if len(margins) < 2 else "",
    )

    peer_percentiles = {
        name: _peer_percentile(name, evidence.get("value"), peer_frame)
        for name, evidence in metrics.items()
        if evidence.get("value") is not None
    }
    components = _quality_components(latest, histories)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "metrics": metrics,
        "history": {name: values for name, values in {"gross_margin": margins, "operating_margin": _derived_history(histories, "operating_income", "revenue"), "net_margin": _derived_history(histories, "net_income", "revenue")}.items()},
        "peer_percentiles": peer_percentiles,
        "quality_components": components,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def balance_sheet_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    latest = _latest_values(frame)
    metrics: dict[str, dict[str, object]] = {}
    debt = latest.get("debt")
    cash = latest.get("cash")
    equity = latest.get("equity")
    current_assets = latest.get("current_assets")
    current_liabilities = latest.get("current_liabilities")
    receivables = latest.get("receivables")
    operating_income = latest.get("operating_income")
    interest_expense = latest.get("interest_expense")
    metrics["net_debt"] = _metric("net_debt", None if debt is None or cash is None else debt - cash, "debt - cash", frame)
    metrics["debt_to_equity"] = _ratio_metric("debt_to_equity", debt, equity, "debt / equity", frame, "debt")
    metrics["current_ratio"] = _ratio_metric("current_ratio", current_assets, current_liabilities, "current_assets / current_liabilities", frame, "current_assets")
    quick_assets = _sum_if_present(cash, receivables)
    metrics["quick_ratio"] = _ratio_metric("quick_ratio", quick_assets, current_liabilities, "(cash + receivables) / current_liabilities", frame, "cash")
    metrics["working_capital"] = _metric("working_capital", None if current_assets is None or current_liabilities is None else current_assets - current_liabilities, "current_assets - current_liabilities", frame)
    metrics["interest_coverage"] = _ratio_metric("interest_coverage", operating_income, interest_expense, "operating_income / interest_expense", frame, "operating_income", zero_denominator_status="not_applicable")

    special = sector.casefold() in _SPECIAL_SECTORS
    distress = _distress_metric(latest, frame, special)
    metrics["altman_like_distress"] = distress
    maturity = _maturity_timeline(latest, frame)
    stress = _stress_scenarios(latest, frame)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "metrics": metrics,
        "maturity_timeline": maturity,
        "stress_scenarios": stress,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def valuation_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    market_inputs: Mapping[str, object] | None = None,
    assumptions: Mapping[str, object] | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    latest = _latest_values(frame)
    market = {str(key): _float(value) for key, value in (market_inputs or {}).items()}
    assumption_values = {str(key): value for key, value in (assumptions or {}).items()}
    values = {**latest, **{key: value for key, value in market.items() if value is not None}}
    if values.get("net_debt") is None and values.get("debt") is not None and values.get("cash") is not None:
        values["net_debt"] = values["debt"] - values["cash"]
    relative_metrics = {
        "ev_to_sales": _ratio_metric("ev_to_sales", values.get("enterprise_value"), values.get("revenue"), "enterprise_value / revenue", frame, "enterprise_value"),
        "ev_to_ebitda": _ratio_metric("ev_to_ebitda", values.get("enterprise_value"), values.get("operating_income"), "enterprise_value / operating_income", frame, "enterprise_value"),
        "price_to_earnings": _ratio_metric("price_to_earnings", values.get("market_cap"), values.get("net_income"), "market_cap / net_income", frame, "market_cap", zero_denominator_status="not_applicable"),
        "price_to_book": _ratio_metric("price_to_book", values.get("market_cap"), values.get("equity"), "market_cap / equity", frame, "market_cap", zero_denominator_status="not_applicable"),
        "dividend_yield": _ratio_metric("dividend_yield", values.get("dividend_per_share"), values.get("share_price"), "dividend_per_share / share_price", frame, "dividend_per_share", zero_denominator_status="not_applicable"),
    }
    intrinsic = _intrinsic_value(values, assumption_values)
    reverse = _reverse_dcf(values, assumption_values)
    residual = _residual_income(values, assumption_values)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "relative_metrics": relative_metrics,
        "intrinsic_value": intrinsic,
        "reverse_dcf": reverse,
        "residual_income": residual,
        "model_disagreement": _model_disagreement(intrinsic, residual),
        "assumptions": assumption_values,
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def growth_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    """Return period-aligned reported growth without analyst assumptions.

    Aggregate values and per-share values are kept in separate series. A
    zero or negative prior period is reported as a base-effect state rather
    than being turned into a misleading percentage. Acquisition and organic
    growth are only calculated when the statement package contains explicit
    structured evidence for them.
    """

    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    periods = _period_rows(frame)
    aggregate = {
        name: _growth_series(periods, name, aliases, basis="aggregate")
        for name, aliases in {
            "revenue": ("revenue",),
            "operating_profit": ("operating_profit",),
            "free_cash_flow": ("free_cash_flow",),
        }.items()
    }
    per_share = {
        "earnings_per_share": _growth_series(
            periods,
            "earnings_per_share",
            ("earnings_per_share",),
            basis="per_share",
            derived_from=("net_income", "shares_outstanding"),
        ),
        "free_cash_flow_per_share": _growth_series(
            periods,
            "free_cash_flow_per_share",
            (),
            basis="per_share",
            derived_from=("free_cash_flow", "shares_outstanding"),
        ),
    }
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "statement_view": frame.attrs.get("statement_view", "latest_restated"),
        "periods": [period["period_key"] for period in periods],
        "series": {"aggregate": aggregate, "per_share": per_share},
        "organic_inorganic": _organic_inorganic_analysis(frame, periods),
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def build_stock_research_report(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    peer_frame: pd.DataFrame | None = None,
    market_inputs: Mapping[str, object] | None = None,
    assumptions: Mapping[str, object] | None = None,
    expectation_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None = None,
    guidance_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    frame = _statement_frame(statements, instrument_id, as_known_at=as_known_at)
    return {
        "schema_version": STOCK_RESEARCH_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "profitability": profitability_analysis(frame, instrument_id=instrument_id, sector=sector, peer_frame=peer_frame, as_known_at=as_known_at),
        "balance_sheet": balance_sheet_analysis(frame, instrument_id=instrument_id, sector=sector, as_known_at=as_known_at),
        "valuation": valuation_analysis(frame, instrument_id=instrument_id, market_inputs=market_inputs, assumptions=assumptions, as_known_at=as_known_at),
        "growth": growth_analysis(frame, instrument_id=instrument_id, as_known_at=as_known_at),
        "expectations": _expectations_report(frame, expectation_evidence, guidance_evidence, instrument_id=instrument_id, as_known_at=as_known_at),
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def load_stock_research_frame(path: object, *, instrument_id: str | None = None, as_known_at: str | date | None = None) -> pd.DataFrame:
    try:
        frame = pd.read_parquet(path) if path else pd.DataFrame()
    except (OSError, ValueError, ImportError):
        frame = pd.DataFrame()
    return _statement_frame(frame, instrument_id, as_known_at=as_known_at)


def load_optional_research_import(path: object, *, instrument_id: str | None = None) -> pd.DataFrame:
    """Load local optional evidence without granting it data authority."""

    try:
        candidate = Path(path)
    except TypeError:
        return _empty_optional_import(path, "rejected", "invalid_path")
    if not candidate.is_file():
        return _empty_optional_import(candidate, "missing", "file_not_found")
    try:
        checksum_before = _file_sha256(candidate)
        suffix = candidate.suffix.casefold()
        if suffix == ".csv":
            frame = pd.read_csv(candidate)
        elif suffix in {".json", ".jsonl"}:
            frame = pd.read_json(candidate, lines=suffix == ".jsonl")
        elif suffix == ".parquet":
            frame = pd.read_parquet(candidate)
        else:
            return _empty_optional_import(candidate, "rejected", f"unsupported_file_type:{suffix or 'none'}")
        checksum_after = _file_sha256(candidate)
    except (ImportError, OSError, UnicodeError, ValueError) as exc:
        return _empty_optional_import(candidate, "rejected", f"unreadable_import:{type(exc).__name__}")
    if checksum_before != checksum_after:
        return _empty_optional_import(candidate, "rejected", "file_changed_during_read")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return _empty_optional_import(candidate, "empty", "no_records")
    if instrument_id:
        if "instrument_id" not in frame.columns:
            return _empty_optional_import(candidate, "rejected", "missing_instrument_id")
        frame = frame[frame["instrument_id"].astype(str).eq(str(instrument_id))].copy()
        if frame.empty:
            return _empty_optional_import(candidate, "empty", "instrument_not_present")
    if "source_checksum" not in frame.columns:
        frame["source_checksum"] = checksum_after
    else:
        supplied = frame["source_checksum"].notna() & frame["source_checksum"].astype(str).str.strip().ne("")
        frame["source_checksum"] = frame["source_checksum"].where(supplied, checksum_after)
    frame = frame.reset_index(drop=True)
    frame.attrs.update({"import_path": str(candidate), "import_status": "loaded", "import_reason": "", "file_sha256": checksum_after})
    return frame


def _empty_optional_import(path: object, status: str, reason: str) -> pd.DataFrame:
    frame = pd.DataFrame()
    frame.attrs.update({"import_path": str(path), "import_status": status, "import_reason": reason})
    return frame


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _statement_frame(frame: pd.DataFrame, instrument_id: str | None, *, as_known_at: str | date | None = None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    view = "as_known_at" if as_known_at is not None else "latest_restated"
    result = statement_view(frame, view, as_known_at=as_known_at)
    if instrument_id and "instrument_id" in result.columns:
        result = result[result["instrument_id"].astype(str).eq(str(instrument_id))]
    result = result.reset_index(drop=True)
    result.attrs["statement_view"] = view
    if as_known_at is not None:
        result.attrs["as_known_at"] = pd.Timestamp(as_known_at).date().isoformat()
    return result


def _latest_values(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return {}
    result: dict[str, float] = {}
    ordered = frame.copy()
    for column in ("period_end", "filed", "fiscal_year", "period_key"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(["canonical_metric", "period_end", "filed", "fiscal_year", "period_key"], kind="stable", na_position="last")
    for metric, rows in ordered.groupby("canonical_metric", dropna=True):
        numeric = pd.to_numeric(rows["value"], errors="coerce").dropna()
        if not numeric.empty:
            result[str(metric)] = float(numeric.iloc[-1])
    return result


def _histories(frame: pd.DataFrame) -> dict[str, list[float]]:
    if frame.empty or "canonical_metric" not in frame.columns:
        return {}
    ordered = frame.copy()
    for column in ("period_end", "fiscal_year", "period_key"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(["period_end", "fiscal_year", "period_key"], kind="stable", na_position="last")
    result: dict[str, list[float]] = {}
    for metric, rows in ordered.groupby("canonical_metric", dropna=True):
        values = pd.to_numeric(rows["value"], errors="coerce").dropna().astype(float).tolist()
        if values:
            result[str(metric)] = values
    return result


def _period_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Build one deterministic, period-aligned row per statement period."""

    if frame.empty or "canonical_metric" not in frame.columns:
        return []
    work = frame.copy()
    for column, default in (("period_type", "unknown"), ("period_key", ""), ("period_end", ""), ("fiscal_year", "")):
        if column not in work.columns:
            work[column] = default
    work["__period_end"] = work["period_end"].fillna("").astype(str)
    work["__sort_end"] = pd.to_datetime(work["__period_end"], errors="coerce")
    work = work.sort_values(["__sort_end", "__period_end", "period_key", "canonical_metric", "source_id"], kind="stable", na_position="last")
    periods: list[dict[str, object]] = []
    grouped = work.groupby(["period_type", "period_key", "__period_end"], sort=False, dropna=False)
    for (period_type, period_key, period_end), rows in grouped:
        raw_values: dict[str, float] = {}
        raw_sources: dict[str, tuple[str, ...]] = {}
        for metric, metric_rows in rows.groupby("canonical_metric", dropna=True, sort=False):
            ordered = metric_rows.assign(__restatement_rank=metric_rows["restatement_kind"].map(_restatement_rank)).sort_values(["filed", "__restatement_rank", "accession", "source_id"], kind="stable", na_position="last")
            numeric = ordered.assign(__numeric=pd.to_numeric(ordered["value"], errors="coerce")).dropna(subset=["__numeric"])
            if numeric.empty:
                continue
            raw_values[str(metric)] = float(numeric.iloc[-1]["__numeric"])
            raw_sources[str(metric)] = tuple(sorted({str(value) for value in numeric["source_id"].dropna() if str(value)}))

        values: dict[str, float] = {}
        sources: dict[str, tuple[str, ...]] = {}
        formulas: dict[str, str] = {}
        for logical, aliases in _GROWTH_ALIASES.items():
            for alias in aliases:
                if alias in raw_values:
                    values[logical] = raw_values[alias]
                    sources[logical] = raw_sources.get(alias, ())
                    formulas[logical] = f"reported {alias}"
                    break
        if "earnings_per_share" not in values and {"net_income", "shares_outstanding"} <= values.keys() and values["shares_outstanding"] != 0:
            values["earnings_per_share"] = values["net_income"] / values["shares_outstanding"]
            sources["earnings_per_share"] = tuple(sorted(set(sources.get("net_income", ())) | set(sources.get("shares_outstanding", ()))))
            formulas["earnings_per_share"] = "net_income / shares_outstanding"

        first = rows.iloc[0]
        fiscal_year = str(first.get("fiscal_year", "") or "")
        aliases = {str(period_key), str(period_end)}
        if fiscal_year and fiscal_year not in {"nan", "None"}:
            aliases.update({fiscal_year, f"FY{fiscal_year}"})
        flags: list[str] = []
        for column in ("acquisition_flag", "inorganic_flag", "divestiture_flag", "transaction_flag"):
            if column in rows and any(_truthy(value) for value in rows[column]):
                flags.append(column)
        for metric in ("acquisition_revenue", "inorganic_revenue", "acquired_revenue"):
            if metric in raw_values and raw_values[metric] != 0:
                flags.append(metric)
        periods.append(
            {
                "period_type": str(period_type),
                "period_key": str(period_key),
                "period_end": str(period_end),
                "period_aliases": sorted(alias for alias in aliases if alias),
                "values": values,
                "source_ids": sources,
                "formulas": formulas,
                "flags": sorted(set(flags)),
            }
        )
    return periods


def _growth_series(
    periods: list[dict[str, object]],
    name: str,
    aliases: tuple[str, ...],
    *,
    basis: str,
    derived_from: tuple[str, str] | None = None,
) -> dict[str, object]:
    history: list[dict[str, object]] = []
    for period in periods:
        values = period.get("values", {})
        if not isinstance(values, Mapping):
            continue
        value = next((_float(values.get(alias)) for alias in aliases if _float(values.get(alias)) is not None), None)
        formula = next((str(period.get("formulas", {}).get(alias, "")) for alias in aliases if alias in period.get("formulas", {})), "")
        source_ids = next((tuple(period.get("source_ids", {}).get(alias, ())) for alias in aliases if alias in period.get("source_ids", {})), ())
        if value is None and derived_from and all(_float(values.get(item)) is not None for item in derived_from):
            numerator = _float(values[derived_from[0]])
            denominator = _float(values[derived_from[1]])
            if numerator is not None and denominator not in (None, 0):
                value = numerator / denominator
                formula = f"{derived_from[0]} / {derived_from[1]}"
                source_ids = tuple(sorted(set(period.get("source_ids", {}).get(derived_from[0], ())) | set(period.get("source_ids", {}).get(derived_from[1], ()))))
        history.append(
            {
                "period_type": period["period_type"],
                "period_key": period["period_key"],
                "period_end": period["period_end"],
                "value": value,
                "basis": basis,
                "formula": formula or f"reported {name}",
                "source_ids": list(source_ids),
                "status": "available" if value is not None else "missing",
            }
        )
    growth: list[dict[str, object]] = []
    by_type: dict[str, list[dict[str, object]]] = {}
    for point in history:
        by_type.setdefault(str(point["period_type"]), []).append(point)
    for points in by_type.values():
        for prior, current in zip(points, points[1:]):
            prior_value = _float(prior["value"])
            current_value = _float(current["value"])
            comparison = "year_over_year" if current["period_type"] == "annual" else "period_over_period"
            base_effect = "normal"
            status = "available"
            value: float | None
            if prior_value is None or current_value is None:
                value = None
                status = "missing"
                base_effect = "missing_period"
            elif prior_value == 0:
                value = None
                status = "base_effect"
                base_effect = "prior_zero"
            elif prior_value < 0:
                value = None
                status = "base_effect"
                base_effect = "prior_negative"
            else:
                value = current_value / prior_value - 1.0
                if current_value < 0:
                    base_effect = "current_negative"
            growth.append(
                {
                    "period_type": current["period_type"],
                    "period_key": current["period_key"],
                    "period_end": current["period_end"],
                    "base_period_key": prior["period_key"],
                    "value": value,
                    "basis": basis,
                    "formula": "(current / prior) - 1",
                    "comparison": comparison,
                    "base_effect": base_effect,
                    "status": status,
                    "source_ids": sorted(set(prior.get("source_ids", [])) | set(current.get("source_ids", []))),
                    "execution_allowed": False,
                }
            )
    growth.sort(key=lambda item: (str(item["period_end"]), str(item["period_key"])))
    return {
        "basis": basis,
        "history": history,
        "growth": growth,
        "latest_growth": growth[-1] if growth else None,
        "status": "available" if any(point.get("value") is not None for point in history) else "missing",
        "formula": "(current / prior) - 1",
        "execution_allowed": False,
    }


def _organic_inorganic_analysis(frame: pd.DataFrame, periods: list[dict[str, object]]) -> dict[str, object]:
    organic = _growth_series(periods, "organic_revenue", ("organic_revenue",), basis="aggregate")
    acquired = _growth_series(periods, "acquisition_revenue", ("acquisition_revenue",), basis="aggregate")
    flags = [
        {"period_key": period["period_key"], "flags": period["flags"]}
        for period in periods
        if period.get("flags")
    ]
    has_organic = any(point.get("value") is not None for point in organic["history"])
    return {
        "status": "available" if has_organic else "unavailable",
        "organic_growth": organic,
        "inorganic_growth": acquired,
        "acquisition_flags": flags,
        "limitation": "Organic growth is unavailable without explicit organic-revenue or acquisition evidence; consolidated growth is not silently labelled organic." if not has_organic else "",
        "execution_allowed": False,
    }


def _expectations_report(
    statements: pd.DataFrame,
    expectation_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None,
    guidance_evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None,
    *,
    instrument_id: str | None,
    as_known_at: str | date | None,
) -> dict[str, object]:
    consensus_rows, consensus_rejected, cutoff = _prepare_optional_rows(expectation_evidence, instrument_id=instrument_id, as_known_at=as_known_at, guidance=False)
    guidance_rows, guidance_rejected, _ = _prepare_optional_rows(guidance_evidence, instrument_id=instrument_id, as_known_at=as_known_at, guidance=True)
    return {
        "as_known_at": cutoff,
        "consensus": _consensus_report(statements, consensus_rows, consensus_rejected, cutoff),
        "guidance": _guidance_report(guidance_rows, guidance_rejected),
        "execution_allowed": False,
    }


def _consensus_report(frame: pd.DataFrame, rows: list[dict[str, object]], rejected: list[str], cutoff: str | None) -> dict[str, object]:
    if not rows:
        return {"status": "unavailable", "metrics": {}, "accepted_records": 0, "rejected_records": rejected, "reason": "No licensed point-in-time consensus evidence was supplied.", "execution_allowed": False}
    periods = _period_rows(frame)
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((str(row["metric"]), str(row["period_key"])), []).append(row)
    metrics: dict[str, dict[str, object]] = {}
    for (metric, period_key), candidates in sorted(grouped.items()):
        ordered = sorted(candidates, key=lambda item: (str(item["available_at"]), str(item["source_id"])))
        latest_timestamp = ordered[-1]["available_at"]
        latest_rows = [item for item in ordered if item["available_at"] == latest_timestamp]
        latest_values = [float(item["value"]) for item in latest_rows if item.get("value") is not None]
        if not latest_values:
            continue
        latest = latest_rows[-1]
        actual = _actual_for_period(periods, metric, period_key)
        estimate = float(latest["value"])
        surprise = None
        if actual is not None:
            surprise = {"value": actual - estimate, "percent": None if estimate == 0 else actual / estimate - 1.0, "formula": "actual - estimate", "status": "available"}
        revision_value = float(latest["value"]) - float(ordered[0]["value"])
        revision = {"value": revision_value, "status": "available" if len(ordered) > 1 else "not_available", "formula": "latest estimate - earliest estimate"}
        dispersion = {"value": max(latest_values) - min(latest_values), "status": "available" if len(latest_values) > 1 else "not_available", "formula": "max(latest-vintage estimates) - min(latest-vintage estimates)"}
        staleness = _staleness(latest["available_at"], cutoff)
        item = {
            "period_key": period_key,
            "latest_value": estimate,
            "latest_available_at": latest["available_at"],
            "source_ids": sorted({str(candidate["source_id"]) for candidate in candidates}),
            "source_authorities": sorted({str(candidate["source_authority"]) for candidate in candidates}),
            "license_statuses": sorted({str(candidate["license_status"]) for candidate in candidates if candidate.get("license_status")}),
            "source_records": [
                {
                    "source_id": candidate["source_id"],
                    "source_authority": candidate["source_authority"],
                    "license_status": candidate["license_status"],
                    "source_checksum": candidate["source_checksum"],
                }
                for candidate in ordered
            ],
            "revision": revision,
            "dispersion": dispersion,
            "surprise": surprise or {"value": None, "percent": None, "status": "unavailable", "reason": "Reported actual for this period is unavailable."},
            "staleness": staleness,
            "revision_history": [{key: candidate[key] for key in ("value", "available_at", "source_id")} for candidate in ordered],
            "execution_allowed": False,
        }
        metrics.setdefault(metric, {})[period_key] = item
    return {
        "status": "available" if metrics else "unavailable",
        "metrics": metrics,
        "accepted_records": len(rows),
        "rejected_records": rejected,
        "source_ids": sorted({str(row["source_id"]) for row in rows}),
        "execution_allowed": False,
    }


def _guidance_report(rows: list[dict[str, object]], rejected: list[str]) -> dict[str, object]:
    if not rows:
        return {"status": "unavailable", "items": [], "accepted_records": 0, "rejected_records": rejected, "reason": "Guidance requires structured or human-reviewed evidence with provenance.", "execution_allowed": False}
    items = []
    for row in sorted(rows, key=lambda item: (str(item["available_at"]), str(item["source_id"]))):
        items.append(
            {
                "status": "available",
                "metric": row.get("metric"),
                "period_key": row.get("period_key"),
                "value": row.get("value"),
                "lower": row.get("lower"),
                "upper": row.get("upper"),
                "text": row.get("text", ""),
                "source_id": row["source_id"],
                "source_authority": row["source_authority"],
                "license_status": row["license_status"],
                "source_checksum": row.get("source_checksum"),
                "review_status": row["review_status"],
                "available_at": row["available_at"],
                "execution_allowed": False,
            }
        )
    return {"status": "available", "items": items, "accepted_records": len(items), "rejected_records": rejected, "execution_allowed": False}


def _prepare_optional_rows(
    evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame | None,
    *,
    instrument_id: str | None,
    as_known_at: str | date | None,
    guidance: bool,
) -> tuple[list[dict[str, object]], list[str], str | None]:
    if evidence is None:
        return [], [], _normalise_cutoff(as_known_at)
    cutoff = _normalise_cutoff(as_known_at)
    if as_known_at is not None and cutoff is None:
        return [], ["invalid_as_known_at"], None
    frame = _evidence_frame(evidence)
    valid: list[dict[str, object]] = []
    import_reason = _text(frame.attrs.get("import_reason"))
    rejected: list[str] = [f"import:{import_reason}"] if import_reason and import_reason != "file_not_found" else []
    for index, raw in enumerate(frame.to_dict("records")):
        row_instrument = _text(raw.get("instrument_id"))
        if instrument_id and row_instrument and row_instrument != str(instrument_id):
            rejected.append(f"row_{index}:instrument_mismatch")
            continue
        reason, row = _validate_optional_row(raw, index=index, cutoff=cutoff, guidance=guidance)
        if reason:
            rejected.append(reason)
        elif row is not None:
            valid.append(row)
    return valid, rejected, cutoff


def _validate_optional_row(raw: Mapping[str, object], *, index: int, cutoff: str | None, guidance: bool) -> tuple[str | None, dict[str, object] | None]:
    source_id = _text(_first_present(raw.get("source_id"), raw.get("source"), raw.get("citation")))
    source_authority = _text(_first_present(raw.get("source_authority"), raw.get("authority"), raw.get("ownership")))
    source_kind = _text(_first_present(raw.get("source_kind"), raw.get("source_type"))).casefold()
    provider = _text(_first_present(raw.get("provider"), raw.get("vendor"), raw.get("source_name"))).casefold()
    if not source_authority and source_kind in {"official", "company", "issuer"}:
        source_authority = source_kind
    authority_key = source_authority.casefold().replace("–", "-")
    allowed_authorities = _GUIDANCE_SOURCE_AUTHORITIES if guidance else _CONSENSUS_SOURCE_AUTHORITIES
    source_checksum = _text(_first_present(raw.get("source_checksum"), raw.get("checksum")))
    available_at = _normalise_timestamp(_first_present(raw.get("available_at"), raw.get("as_of"), raw.get("published_at")))
    supplied_licence = _text(_first_present(raw.get("license_status"), raw.get("licence_status")))
    licence_key = supplied_licence.casefold().replace("-", "_").replace(" ", "_")
    if source_kind in {"current_analyst", "current_analyst_field", "analyst_current"} or "yahoo" in provider or "yahoo" in source_id.casefold() or ("analyst" in provider and "point" not in source_kind):
        return f"row_{index}:current_or_restricted_provider_rejected", None
    if not source_id or not available_at or authority_key not in allowed_authorities or not _valid_checksum(source_checksum):
        return f"row_{index}:missing_or_unlicensed_provenance", None
    if any(marker in licence_key for marker in _REJECTED_LICENCE_MARKERS):
        return f"row_{index}:missing_or_unlicensed_provenance", None
    if cutoff and available_at > cutoff:
        return f"row_{index}:after_as_known_cutoff", None
    metric = _normalise_optional_metric(_first_present(raw.get("canonical_metric"), raw.get("metric"), raw.get("measure")))
    period_key = _text(_first_present(raw.get("period_key"), raw.get("period_end"), raw.get("fiscal_year")))
    value = _first_float(raw.get("value"), raw.get("estimate"), raw.get("forecast"))
    if not guidance and (not metric or not period_key or value is None):
        return f"row_{index}:missing_metric_period_or_value", None
    review_status = _text(_first_present(raw.get("review_status"), raw.get("review"))).casefold().replace(" ", "_")
    text = _text(_first_present(raw.get("guidance_text"), raw.get("text"), raw.get("statement")))
    lower = _first_float(raw.get("lower"), raw.get("low"))
    upper = _first_float(raw.get("upper"), raw.get("high"))
    if guidance and lower is not None and upper is not None and lower > upper:
        return f"row_{index}:invalid_guidance_range", None
    if guidance and value is not None and ((lower is not None and value < lower) or (upper is not None and value > upper)):
        return f"row_{index}:guidance_value_outside_range", None
    if guidance and not period_key:
        return f"row_{index}:missing_guidance_period", None
    if guidance and (review_status not in _REVIEWED_GUIDANCE_STATUSES or (value is None and lower is None and upper is None and not text)):
        return f"row_{index}:guidance_not_structured_or_reviewed", None
    if guidance and not metric:
        metric = _normalise_optional_metric(raw.get("guidance_type") or "guidance") or "guidance"
    return None, {
        "metric": metric,
        "period_key": period_key,
        "value": value,
        "lower": lower,
        "upper": upper,
        "text": text,
        "source_id": source_id,
        "source_authority": source_authority,
        "license_status": supplied_licence or _default_license_status(authority_key),
        "source_checksum": source_checksum,
        "available_at": available_at,
        "review_status": review_status,
    }


def _default_license_status(authority_key: str) -> str:
    if "user" in authority_key:
        return "user_owned"
    if "broker" in authority_key:
        return "broker_licensed"
    if "licensed" in authority_key:
        return "licensed_vendor"
    return "official"


def _actual_for_period(periods: list[dict[str, object]], metric: str, period_key: str) -> float | None:
    aliases = ("operating_profit",) if metric == "operating_profit" else ("earnings_per_share",) if metric == "earnings_per_share" else (metric,)
    for period in periods:
        if period_key in period.get("period_aliases", []) or period_key == period.get("period_key"):
            values = period.get("values", {})
            if isinstance(values, Mapping):
                for alias in aliases:
                    value = _float(values.get(alias))
                    if value is not None:
                        return value
    return None


def _staleness(available_at: str, cutoff: str | None) -> dict[str, object]:
    if not cutoff:
        return {"status": "not_evaluated", "days": None}
    days = max(0, (pd.Timestamp(cutoff) - pd.Timestamp(available_at)).days)
    return {"status": "available", "days": days, "as_known_at": cutoff}


def _evidence_frame(evidence: Iterable[object] | Mapping[str, object] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(evidence, pd.DataFrame):
        return evidence.copy()
    if isinstance(evidence, Mapping):
        records = evidence.get("records")
        if isinstance(records, Iterable) and not isinstance(records, (str, bytes, Mapping)):
            evidence = records
        else:
            return pd.DataFrame([dict(evidence)])
    if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes)):
        rows = [asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item) if isinstance(item, Mapping) else {} for item in evidence]
        return pd.DataFrame(rows)
    return pd.DataFrame()


def _normalise_optional_metric(value: object) -> str:
    key = _text(value).casefold().replace("-", "_").replace(" ", "_")
    return {
        "sales": "revenue",
        "operating_income": "operating_profit",
        "ebit": "operating_profit",
        "eps": "earnings_per_share",
        "diluted_eps": "earnings_per_share",
        "basic_eps": "earnings_per_share",
        "fcf": "free_cash_flow",
    }.get(key, key)


def _normalise_timestamp(value: object) -> str:
    if value is None or not _text(value):
        return ""
    if isinstance(value, (bool, int, float)):
        return ""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(timestamp):
        return ""
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def _valid_checksum(value: str) -> bool:
    checksum = value.casefold().removeprefix("sha256:")
    return len(checksum) == 64 and all(character in "0123456789abcdef" for character in checksum)


def _normalise_cutoff(value: str | date | None) -> str | None:
    if value is None:
        return None
    timestamp = _normalise_timestamp(value)
    return timestamp or None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if _float(value) is not None:
        return bool(_float(value))
    return _text(value).casefold() in {"1", "true", "yes", "y", "material"}


def _restatement_rank(value: object) -> int:
    return {"reported": 0, "restated": 1, "amended": 2, "corrected": 3}.get(_text(value).casefold(), 1)


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.api.types.is_scalar(value) and bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _first_present(*values: object) -> object | None:
    return next((value for value in values if _text(value)), None)


def _first_float(*values: object) -> float | None:
    return next((number for value in values if (number := _float(value)) is not None), None)


def _derived_history(histories: Mapping[str, list[float]], numerator: str, denominator: str) -> list[float]:
    numerators = histories.get(numerator, [])
    denominators = histories.get(denominator, [])
    return [float(numerator_value / denominator_value) for numerator_value, denominator_value in zip(numerators, denominators) if denominator_value != 0]


def _ratio_metric(name: str, numerator: float | None, denominator: float | None, formula: str, frame: pd.DataFrame, source_metric: str, *, applicability: str = "applicable", limitation: str = "", zero_denominator_status: str = "missing") -> dict[str, object]:
    if applicability != "applicable":
        return _metric(name, None, formula, frame, status_override="not_applicable", source_metric=source_metric, applicability=applicability, limitation=limitation)
    if numerator is None or denominator is None:
        return _metric(name, None, formula, frame, status_override="missing", source_metric=source_metric, limitation=limitation)
    if denominator == 0:
        return _metric(name, None, formula, frame, status_override=zero_denominator_status, source_metric=source_metric, limitation="Denominator is zero; the ratio is not defined.")
    return _metric(name, float(numerator / denominator), formula, frame, source_metric=source_metric, limitation=limitation)


def _metric(name: str, value: float | None, formula: str, frame: pd.DataFrame, *, status_override: str | None = None, source_metric: str | None = None, applicability: str = "applicable", limitation: str = "") -> dict[str, object]:
    source_ids = _source_ids(frame, source_metric or name)
    period = _period_label(frame)
    status = status_override or ("missing" if value is None else "negative" if value < 0 else "available")
    return asdict(MetricEvidence(name, value, status, formula, period, source_ids, "high" if value is not None and source_ids else "low", applicability, limitation))


def _source_ids(frame: pd.DataFrame, metric: str) -> tuple[str, ...]:
    if frame.empty or "canonical_metric" not in frame.columns or "source_id" not in frame.columns:
        return ()
    return tuple(sorted({str(value) for value in frame.loc[frame["canonical_metric"].astype(str).eq(metric), "source_id"].dropna() if str(value)}))


def _period_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "unavailable"
    for column in ("period_end", "period_key", "fiscal_year"):
        if column in frame and frame[column].notna().any():
            value = frame[column].dropna().astype(str).iloc[-1]
            if value:
                return value
    return "unavailable"


def _lineage(frame: pd.DataFrame) -> dict[str, object]:
    lineage = {
        "statement_view": frame.attrs.get("statement_view", "latest_restated"),
        "coverage": statement_coverage(frame),
        "source_ids": sorted({str(value) for value in frame.get("source_id", pd.Series(dtype="object")).dropna() if str(value)}),
        "execution_allowed": False,
    }
    if frame.attrs.get("as_known_at"):
        lineage["as_known_at"] = frame.attrs["as_known_at"]
    return lineage


def _tax_rate(values: Mapping[str, float]) -> float | None:
    tax_expense = values.get("tax_expense")
    pre_tax = values.get("income_before_tax")
    if tax_expense is None or pre_tax in (None, 0):
        return None
    return float(tax_expense / pre_tax)


def _sum_if_present(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return float(sum(value for value in values if value is not None))


def _float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _peer_percentile(metric: str, value: object, peer_frame: pd.DataFrame | None) -> float | None:
    observed = _float(value)
    if observed is None or not isinstance(peer_frame, pd.DataFrame) or peer_frame.empty:
        return None
    peer = _statement_frame(peer_frame, None)
    values = _latest_values(peer)
    if metric in values:
        peers = [values[metric]]
    else:
        histories = _histories(peer)
        peers = _derived_history(histories, "gross_profit", "revenue") if metric == "gross_margin" else []
    if not peers:
        return None
    return float(100.0 * (sum(item < observed for item in peers) + 0.5 * sum(item == observed for item in peers)) / len(peers))


def _quality_components(values: Mapping[str, float], histories: Mapping[str, list[float]]) -> dict[str, object]:
    components: dict[str, object] = {}
    for name, value in {
        "positive_net_income": values.get("net_income"),
        "positive_cash_from_operations": values.get("cash_from_operations"),
        "lower_leverage": _trend(histories.get("debt", []), descending=True),
        "improving_gross_margin": _trend(_derived_history(histories, "gross_profit", "revenue"), descending=False),
    }.items():
        components[name] = {"value": value if isinstance(value, bool) else value > 0 if isinstance(value, (int, float)) else value, "status": "available" if value is not None else "missing", "execution_allowed": False}
    return components


def _trend(values: list[float], *, descending: bool) -> bool | None:
    if len(values) < 2:
        return None
    return values[-1] < values[0] if descending else values[-1] > values[0]


def _maturity_timeline(values: Mapping[str, float], frame: pd.DataFrame) -> dict[str, object]:
    names = ("debt_due_1y", "debt_due_2_3y", "debt_due_4_5y", "debt_due_5y_plus")
    available = {name: values[name] for name in names if name in values}
    return {"status": "available" if available else "missing", "buckets": available, "formula": "reported debt maturity buckets", "source_ids": sorted({source for name in available for source in _source_ids(frame, name)}), "confidence": "high" if available else "low", "limitation": "Unavailable maturities are not replaced with zero." if not available else "", "execution_allowed": False}


def _distress_metric(values: Mapping[str, float], frame: pd.DataFrame, special: bool) -> dict[str, object]:
    if special:
        return _metric("altman_like_distress", None, "sector adapter required", frame, status_override="not_applicable", limitation="Altman-like industrial evidence is not applied to banks or insurers.")
    assets = values.get("assets")
    liabilities = values.get("liabilities")
    revenue = values.get("revenue")
    equity = values.get("equity")
    operating_income = values.get("operating_income")
    working_capital = None if values.get("current_assets") is None or values.get("current_liabilities") is None else values["current_assets"] - values["current_liabilities"]
    required = (working_capital, assets, values.get("retained_earnings"), operating_income, equity, liabilities, revenue)
    if any(value is None or assets == 0 or liabilities == 0 for value in required):
        return _metric("altman_like_distress", None, "transparent multi-factor distress evidence", frame, status_override="missing", limitation="All disclosed components are required; result is contextual, not a rating.")
    score = 1.2 * working_capital / assets + 1.4 * values["retained_earnings"] / assets + 3.3 * operating_income / assets + 0.6 * equity / liabilities + revenue / assets
    return _metric("altman_like_distress", score, "1.2*WC/assets + 1.4*retained_earnings/assets + 3.3*EBIT/assets + 0.6*equity/liabilities + revenue/assets", frame, limitation="Contextual distress evidence only; no credit-rating claim.")


def _stress_scenarios(values: Mapping[str, float], frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    revenue = values.get("revenue")
    operating_income = values.get("operating_income")
    debt = values.get("debt")
    interest = values.get("interest_expense")
    margin = None if revenue in (None, 0) or operating_income is None else operating_income / revenue
    scenarios: dict[str, dict[str, object]] = {}
    for name, revenue_factor, rate_add in (("revenue_down_20", 0.8, 0.0), ("refinance_rate_up_200bp", 1.0, 0.02)):
        if revenue is None or margin is None or interest is None or debt is None:
            scenarios[name] = {"status": "missing", "confidence": "low", "assumptions": {"revenue_factor": revenue_factor, "rate_add": rate_add}, "execution_allowed": False}
            continue
        stressed_revenue = revenue * revenue_factor
        stressed_operating_income = stressed_revenue * margin
        stressed_interest = interest + debt * rate_add
        scenarios[name] = {"status": "available", "confidence": "scenario_only", "assumptions": {"revenue_factor": revenue_factor, "rate_add": rate_add}, "stressed_revenue": stressed_revenue, "stressed_operating_income": stressed_operating_income, "stressed_interest": stressed_interest, "interest_coverage": None if stressed_interest == 0 else stressed_operating_income / stressed_interest, "execution_allowed": False}
    return scenarios


def _intrinsic_value(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    net_debt = values.get("net_debt")
    discount = _float(assumptions.get("discount_rate"))
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = int(assumptions.get("forecast_years", 0) or 0)
    scenarios = assumptions.get("scenarios")
    if fcf is None or shares is None or net_debt is None or discount is None or terminal_growth is None or years <= 0 or not isinstance(scenarios, Mapping) or not scenarios:
        return {"status": "unavailable", "confidence": "low", "reason": "free cash flow, share count, net debt, forecast and explicit scenario assumptions are required", "scenarios": {}, "execution_allowed": False}
    results: dict[str, dict[str, object]] = {}
    for name, raw in scenarios.items():
        if not isinstance(raw, Mapping) or _float(raw.get("growth")) is None:
            continue
        growth = float(raw["growth"])
        margin = _float(raw.get("margin"))
        cash_flow = fcf if margin is None else fcf * (margin / max(abs(values.get("operating_income", 1.0)), 1e-12))
        present_value = sum(cash_flow * (1.0 + growth) ** year / (1.0 + discount) ** year for year in range(1, years + 1))
        terminal_cash_flow = cash_flow * (1.0 + growth) ** years
        denominator = discount - terminal_growth
        if denominator <= 0:
            continue
        terminal_value = terminal_cash_flow * (1.0 + terminal_growth) / denominator
        enterprise_value = present_value + terminal_value / (1.0 + discount) ** years
        equity_value = enterprise_value - net_debt
        results[str(name)] = {"growth": growth, "margin": margin, "enterprise_value": enterprise_value, "equity_value": equity_value, "per_share": equity_value / shares, "confidence": "scenario_only", "execution_allowed": False}
    if not results:
        return {"status": "unavailable", "confidence": "low", "reason": "no valid scenario assumptions", "scenarios": {}, "execution_allowed": False}
    return {"status": "available", "confidence": "scenario_only", "forecast_years": years, "discount_rate": discount, "terminal_growth": terminal_growth, "scenarios": results, "execution_allowed": False}


def _reverse_dcf(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    target = values.get("market_cap")
    fcf = values.get("free_cash_flow")
    shares = values.get("shares_outstanding")
    net_debt = values.get("net_debt")
    discount = _float(assumptions.get("discount_rate"))
    terminal_growth = _float(assumptions.get("terminal_growth"))
    years = int(assumptions.get("forecast_years", 0) or 0)
    if target is None or fcf is None or shares is None or net_debt is None or discount is None or terminal_growth is None or years <= 0 or discount <= terminal_growth:
        return {"status": "unavailable", "confidence": "low", "execution_allowed": False}
    def equity_for(growth: float) -> float:
        pv = sum(fcf * (1.0 + growth) ** year / (1.0 + discount) ** year for year in range(1, years + 1))
        terminal = fcf * (1.0 + growth) ** years * (1.0 + terminal_growth) / (discount - terminal_growth)
        return pv + terminal / (1.0 + discount) ** years - net_debt
    low, high = -0.5, 1.0
    if not (equity_for(low) <= target <= equity_for(high)):
        return {"status": "unavailable", "confidence": "low", "reason": "market value is outside the bounded growth search", "execution_allowed": False}
    for _ in range(80):
        middle = (low + high) / 2.0
        if equity_for(middle) < target:
            low = middle
        else:
            high = middle
    return {"status": "available", "confidence": "scenario_only", "implied_growth": (low + high) / 2.0, "target_equity_value": target, "execution_allowed": False}


def _residual_income(values: Mapping[str, float], assumptions: Mapping[str, object]) -> dict[str, object]:
    book = values.get("equity")
    net_income = values.get("net_income")
    shares = values.get("shares_outstanding")
    cost = _float(assumptions.get("cost_of_equity", assumptions.get("discount_rate")))
    growth = _float(assumptions.get("terminal_growth"))
    years = int(assumptions.get("forecast_years", 0) or 0)
    if book is None or net_income is None or shares is None or cost is None or growth is None or years <= 0 or cost <= growth:
        return {"status": "unavailable", "confidence": "low", "execution_allowed": False}
    value = book
    residual = net_income - cost * book
    for year in range(1, years + 1):
        value += residual * (1.0 + growth) ** (year - 1) / (1.0 + cost) ** year
    terminal = residual * (1.0 + growth) ** years / (cost - growth)
    value += terminal / (1.0 + cost) ** years
    return {"status": "available", "confidence": "scenario_only", "equity_value": value, "per_share": value / shares, "execution_allowed": False}


def _model_disagreement(intrinsic: Mapping[str, object], residual: Mapping[str, object]) -> dict[str, object]:
    values = [result.get("per_share") for result in (intrinsic.get("scenarios", {}) or {}).values() if isinstance(result, Mapping) and result.get("per_share") is not None]
    if residual.get("per_share") is not None:
        values.append(residual["per_share"])
    return {"status": "available" if len(values) >= 2 else "unavailable", "range": [min(values), max(values)] if values else [], "confidence": "scenario_only" if values else "low", "execution_allowed": False}


__all__ = [
    "CONSENSUS_IMPORT_PATH",
    "GUIDANCE_IMPORT_PATH",
    "MetricEvidence",
    "STOCK_RESEARCH_IMPORT_DIR",
    "STOCK_RESEARCH_SCHEMA_VERSION",
    "balance_sheet_analysis",
    "build_stock_research_report",
    "growth_analysis",
    "load_optional_research_import",
    "load_stock_research_frame",
    "profitability_analysis",
    "valuation_analysis",
]
