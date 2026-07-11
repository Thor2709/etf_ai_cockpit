from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import DataQualityIssue, DataQualityReport
from etf_cockpit.data.provenance import calendar_staleness_status, metadata_from_frame, price_staleness_status

REQUIRED_PRICE_COLUMNS = {
    "date",
    "etf_id",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
}

REQUIRED_HOLDINGS_COLUMNS = {
    "as_of_date",
    "etf_id",
    "units",
    "market_price",
    "market_value_eur",
    "current_weight",
    "source",
}


def _business_days_between(start: date, end: date) -> int:
    if start >= end:
        return 0
    return len(pd.bdate_range(pd.Timestamp(start) + pd.offsets.BDay(1), pd.Timestamp(end)))


def validate_prices(
    prices: pd.DataFrame,
    *,
    as_of_date: date | None = None,
    max_stale_business_days: int | None = None,
    warning_stale_business_days: int = 3,
    block_stale_business_days: int = 10,
    min_history_days: int = 252,
) -> DataQualityReport:
    issues: list[DataQualityIssue] = []
    if prices.empty:
        return DataQualityReport(
            as_of_date=as_of_date or date.today(),
            issues=[DataQualityIssue("ALL", "block", "empty_prices", "No price rows are available.")],
        )

    missing = REQUIRED_PRICE_COLUMNS - set(prices.columns)
    if missing:
        return DataQualityReport(
            as_of_date=as_of_date or date.today(),
            issues=[DataQualityIssue("ALL", "block", "missing_columns", f"Missing price columns: {sorted(missing)}")],
        )

    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    effective_as_of = as_of_date or max(frame["date"])
    if max_stale_business_days is not None:
        block_stale_business_days = max_stale_business_days
        warning_stale_business_days = min(warning_stale_business_days, max_stale_business_days)
    latest_overall = max(frame["date"])
    overall_stale_days = _business_days_between(latest_overall, effective_as_of)

    for etf_id, group in frame.groupby("etf_id", sort=False):
        group = group.sort_values("date")
        latest = max(group["date"])
        stale_days = _business_days_between(latest, effective_as_of)
        if stale_days > block_stale_business_days:
            issues.append(
                DataQualityIssue(
                    etf_id,
                    "block",
                    "stale_data",
                    f"Latest price is {stale_days} business days old.",
                    latest,
                )
            )
        elif stale_days > warning_stale_business_days:
            issues.append(
                DataQualityIssue(
                    etf_id,
                    "warning",
                    "stale_data_warning",
                    f"Latest price is {stale_days} business days old.",
                    latest,
                )
            )
        if len(group) < min_history_days:
            issues.append(
                DataQualityIssue(
                    etf_id,
                    "block",
                    "insufficient_history",
                    f"Only {len(group)} rows available; {min_history_days} required for main signal.",
                    latest,
                )
            )
        bad_ohlc = group[
            (group["open"] <= 0)
            | (group["close"] <= 0)
            | (group["high"] < group["low"])
            | (group["high"] < group[["open", "close"]].max(axis=1))
            | (group["low"] > group[["open", "close"]].min(axis=1))
        ]
        if not bad_ohlc.empty:
            issues.append(DataQualityIssue(etf_id, "block", "invalid_ohlc", f"{len(bad_ohlc)} invalid OHLC rows."))

        adjusted_missing = group["adjusted_close"].isna() | (group["adjusted_close"] <= 0)
        if adjusted_missing.any():
            issues.append(
                DataQualityIssue(etf_id, "block", "missing_adjusted_close", "Adjusted close is missing or non-positive.")
            )

        if group["currency"].isna().any() or (group["currency"].astype(str).str.len() == 0).any():
            issues.append(DataQualityIssue(etf_id, "block", "missing_currency", "Currency metadata is missing."))

        dates = pd.DatetimeIndex(pd.to_datetime(group["date"]))
        expected = pd.bdate_range(dates.min(), dates.max())
        missing_days = expected.difference(dates)
        if len(missing_days) > 5:
            issues.append(
                DataQualityIssue(etf_id, "warning", "missing_trading_days", f"{len(missing_days)} expected days missing.")
            )

        returns = np.log(group["adjusted_close"].astype(float)).diff()
        rolling_median = returns.rolling(60, min_periods=30).median()
        mad = (returns - rolling_median).abs().rolling(60, min_periods=30).median()
        robust_sigma = 1.4826 * mad.replace(0, np.nan)
        outliers = (returns - rolling_median).abs() > 8 * robust_sigma
        if outliers.fillna(False).any():
            issues.append(DataQualityIssue(etf_id, "warning", "return_outlier", "One-day return exceeds 8 robust sigma."))

        if (group["volume"].fillna(0) == 0).any():
            issues.append(DataQualityIssue(etf_id, "warning", "zero_volume", "Volume is zero or missing for at least one row."))

    source_name = "mixed"
    if "source" in frame.columns and frame["source"].notna().any():
        sources = sorted({str(value) for value in frame["source"].dropna().unique()})
        source_name = sources[0] if len(sources) == 1 else "mixed"
    currency = "mixed"
    if "currency" in frame.columns and frame["currency"].notna().any():
        currencies = sorted({str(value) for value in frame["currency"].dropna().unique()})
        currency = currencies[0] if len(currencies) == 1 else "mixed"
    metadata = metadata_from_frame(
        frame,
        source_name=source_name,
        source_type="prices",
        as_of_date=latest_overall,
        currency=currency,
        provider_or_manual_source=source_name,
        staleness_status=price_staleness_status(overall_stale_days),
        age_days=overall_stale_days,
        notes="Daily prices: OK <= 3 trading days, warning 4-10, block > 10.",
    )
    return DataQualityReport(as_of_date=effective_as_of, issues=issues, dataset_metadata=[metadata])


def validate_holdings(
    config: AppConfig,
    holdings: pd.DataFrame,
    *,
    as_of_date: date | None = None,
    fx_rates: pd.DataFrame | None = None,
) -> DataQualityReport:
    issues: list[DataQualityIssue] = []
    if holdings.empty:
        return DataQualityReport(
            as_of_date=as_of_date or date.today(),
            issues=[DataQualityIssue("ALL", "block", "empty_holdings", "No portfolio holdings rows are available.")],
        )

    missing = REQUIRED_HOLDINGS_COLUMNS - set(holdings.columns)
    if missing:
        return DataQualityReport(
            as_of_date=as_of_date or date.today(),
            issues=[DataQualityIssue("ALL", "block", "missing_holdings_columns", f"Missing holdings columns: {sorted(missing)}")],
        )

    frame = holdings.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    latest_overall = max(frame["as_of_date"])
    effective_as_of = as_of_date or latest_overall
    age_days = max((effective_as_of - latest_overall).days, 0)
    if latest_overall > effective_as_of:
        issues.append(
            DataQualityIssue(
                "ALL",
                "block",
                "future_holdings_date",
                f"Holdings snapshot date {latest_overall} is after validation date {effective_as_of}.",
                latest_overall,
            )
        )

    numeric_columns = ["units", "market_price", "market_value_eur", "current_weight"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            issues.append(DataQualityIssue("ALL", "block", f"invalid_{column}", f"Holdings column {column} contains non-numeric values."))

    duplicate_etfs = frame[frame["etf_id"].duplicated()]["etf_id"].astype(str).unique()
    for etf_id in duplicate_etfs:
        issues.append(DataQualityIssue(etf_id, "block", "duplicate_holding", "ETF appears more than once in current holdings."))

    universe = config.universe.by_id()
    unknown_etfs = sorted(set(frame["etf_id"].astype(str)) - set(universe))
    for etf_id in unknown_etfs:
        issues.append(DataQualityIssue(etf_id, "block", "unknown_holding_etf", "Holding is not present in the configured ETF universe."))

    fx_lookup = _fx_lookup(fx_rates, effective_as_of)
    base_currency = config.targets.base_currency.upper()

    for _, row in frame.iterrows():
        etf_id = str(row["etf_id"])
        if row["units"] < 0 or row["market_price"] <= 0 or row["market_value_eur"] < 0 or row["current_weight"] < 0:
            issues.append(DataQualityIssue(etf_id, "block", "invalid_holding_value", "Units, price, value or weight is invalid."))

        holding_currency = _holding_currency(row, universe, base_currency)
        if not holding_currency:
            issues.append(DataQualityIssue(etf_id, "block", "missing_holding_currency", "Holding currency is missing."))
            holding_currency = base_currency

        fx_rate = 1.0
        fx_date: date | None = None
        if holding_currency != base_currency:
            fx_match = fx_lookup.get((holding_currency, base_currency))
            if fx_match is None:
                issues.append(
                    DataQualityIssue(
                        etf_id,
                        "block",
                        "missing_fx_rate",
                        f"{etf_id} uses {holding_currency}; a dated {holding_currency}/{base_currency} FX rate is required.",
                    )
                )
            else:
                fx_rate, fx_date = fx_match
                stale_days = _business_days_between(fx_date, effective_as_of)
                if stale_days > 10:
                    issues.append(
                        DataQualityIssue(
                            etf_id,
                            "block",
                            "stale_fx_rate",
                            f"{holding_currency}/{base_currency} FX rate is {stale_days} business days old.",
                            fx_date,
                        )
                    )
                elif stale_days > 3:
                    issues.append(
                        DataQualityIssue(
                            etf_id,
                            "warning",
                            "stale_fx_rate_warning",
                            f"{holding_currency}/{base_currency} FX rate is {stale_days} business days old.",
                            fx_date,
                        )
                    )

        expected_value = float(row["units"]) * float(row["market_price"]) * fx_rate
        market_value = float(row["market_value_eur"])
        tolerance = max(1.0, abs(market_value) * 0.01)
        if abs(expected_value - market_value) > tolerance:
            severity = "block" if abs(expected_value - market_value) > max(5.0, abs(market_value) * 0.05) else "warning"
            code = "holding_fx_value_mismatch" if holding_currency != base_currency else "holding_value_mismatch"
            rate_text = f" using {holding_currency}/{base_currency} rate {fx_rate:.6f} from {fx_date}" if holding_currency != base_currency and fx_date else ""
            issues.append(
                DataQualityIssue(
                    etf_id,
                    severity,
                    code,
                    f"Units multiplied by market price{rate_text} does not reconcile with market_value_eur.",
                )
            )

        etf = universe.get(etf_id)
        effective_limit = min(config.risks.portfolio_limits.max_single_etf_weight, etf.max_weight if etf else 1.0)
        if float(row["current_weight"]) > effective_limit:
            issues.append(
                DataQualityIssue(
                    etf_id,
                    "warning",
                    "current_concentration_violation",
                    f"{etf_id} current_weight {float(row['current_weight']):.0%} exceeds max_single_etf_weight {effective_limit:.0%}; shown as portfolio context, not an analysis block.",
                )
            )

    total_weight = float(frame["current_weight"].sum())
    if total_weight > 1.005:
        issues.append(
            DataQualityIssue(
                "ALL",
                "block",
                "holdings_weight_above_100",
                f"Current holdings weights sum to {total_weight:.2%}; holdings plus cash cannot exceed 100%.",
            )
        )

    implied_cash_weight = max(0.0, 1.0 - total_weight)
    cash_min = max(config.targets.cash_min_weight, config.risks.portfolio_limits.cash_min_weight)
    if implied_cash_weight + 0.005 < cash_min:
        issues.append(
            DataQualityIssue(
                "CASH",
                "warning",
                "cash_minimum_breached",
                f"Implied cash weight is {implied_cash_weight:.2%}; minimum cash policy is {cash_min:.2%}. This is context for portfolio construction.",
            )
        )

    value_sum = float(frame["market_value_eur"].sum())
    if value_sum > 0 and total_weight > 0:
        normalised_weight = frame["current_weight"] / total_weight
        value_weight = frame["market_value_eur"] / value_sum
        mismatched = (normalised_weight - value_weight).abs() > 0.02
        for _, row in frame[mismatched].iterrows():
            issues.append(
                DataQualityIssue(
                    str(row["etf_id"]),
                    "warning",
                    "holding_weight_value_mismatch",
                    "Current weight does not reconcile with market value share.",
                )
            )

    staleness = calendar_staleness_status("etf_holdings", age_days)
    if staleness == "block":
        issues.append(
            DataQualityIssue(
                "ALL",
                "block",
                "stale_holdings",
                f"Holdings snapshot is {age_days} calendar days old; block threshold is above 180 days.",
                latest_overall,
            )
        )
    elif staleness == "warning":
        issues.append(
            DataQualityIssue(
                "ALL",
                "warning",
                "stale_holdings_warning",
                f"Holdings snapshot is {age_days} calendar days old.",
                latest_overall,
            )
        )

    sources = sorted({str(value) for value in frame["source"].dropna().unique()}) if "source" in frame else []
    source_name = sources[0] if len(sources) == 1 else "mixed"
    metadata = metadata_from_frame(
        frame,
        source_name=source_name,
        source_type="portfolio_holdings",
        as_of_date=latest_overall,
        currency=config.targets.base_currency,
        provider_or_manual_source=source_name,
        staleness_status=staleness,
        age_days=age_days,
        notes="Portfolio holdings: current weights are context for analysis and must still reconcile with market value.",
    )
    return DataQualityReport(as_of_date=effective_as_of, issues=issues, dataset_metadata=[metadata])


def _holding_currency(row: pd.Series, universe: dict[str, object], base_currency: str) -> str:
    if "currency" in row.index and pd.notna(row["currency"]) and str(row["currency"]).strip():
        return str(row["currency"]).strip().upper()
    etf = universe.get(str(row["etf_id"]))
    currency = getattr(etf, "currency", None) if etf is not None else None
    return str(currency or base_currency).strip().upper()


def _fx_lookup(fx_rates: pd.DataFrame | None, effective_as_of: date) -> dict[tuple[str, str], tuple[float, date]]:
    if fx_rates is None or fx_rates.empty:
        return {}
    required = {"as_of_date", "base_currency", "quote_currency", "rate"}
    if not required.issubset(fx_rates.columns):
        return {}
    frame = fx_rates.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"], errors="coerce").dt.date
    frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
    frame["base_currency"] = frame["base_currency"].fillna("").astype(str).str.upper().str.strip()
    frame["quote_currency"] = frame["quote_currency"].fillna("").astype(str).str.upper().str.strip()
    frame = frame.dropna(subset=["as_of_date", "rate"])
    frame = frame[(frame["rate"] > 0) & (frame["as_of_date"] <= effective_as_of)]
    if frame.empty:
        return {}
    lookup: dict[tuple[str, str], tuple[float, date]] = {}
    for (base, quote), group in frame.groupby(["base_currency", "quote_currency"], sort=False):
        latest = group.sort_values("as_of_date").iloc[-1]
        lookup[(str(base), str(quote))] = (float(latest["rate"]), latest["as_of_date"])
    return lookup
