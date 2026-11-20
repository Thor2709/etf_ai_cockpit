"""Deterministic macro context derived from local, adjusted-price evidence.

This module deliberately reports context rather than forecasts or orders.  A
configured proxy is used only when its local price history is present; missing
bond, cash or gold proxies remain explicit unavailable states.
"""

from __future__ import annotations

from datetime import date
from itertools import groupby
from numbers import Integral
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from etf_cockpit.features.regime import build_market_regime, filtered_stress_probability, per_series_returns
from etf_cockpit.portfolio.benchmark_reference import (
    clip_to_decision_window,
    unavailable_reference_projection,
    validate_benchmark_reference,
)
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry


_PROXY_KEYWORDS = {
    "equity": ("equity", "stock", "world", "msci", "s&p", "sp500", "stoxx", "ftse"),
    "bond_cash": ("bond", "fixed income", "treasury", "cash", "money market", "aggregate"),
    "gold_defensive": ("gold", "precious", "commodity", "defensive"),
}


def macro_status() -> str:
    """Describe the authority boundary of the macro context workspace."""

    return "Local macro context is evidence-only; optional provider refresh is not required."


def build_macro_context(
    prices: pd.DataFrame,
    instruments: Iterable[object] = (),
    observations: Iterable[object] = (),
    *,
    benchmark_data_id: str | None = None,
    benchmark_reference: Mapping[str, object] | None = None,
    benchmark_registry: CanonicalBenchmarkRegistry | None = None,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Build a local macro context snapshot without network access.

    ``prices`` must contain ``date``, ``etf_id`` and ``adjusted_close``.  The
    calculations use the adjusted series exclusively.  Instrument metadata is
    optional and is used only to identify bond/cash and gold/defensive proxy
    candidates; the absence of metadata never turns an unavailable proxy into
    an inferred one.
    """

    required = {"date", "etf_id", "adjusted_close"}
    reference = dict(benchmark_reference or unavailable_reference_projection())
    canonical_benchmark_id = None
    if benchmark_data_id is not None or benchmark_reference is not None:
        canonical_benchmark_id = validate_benchmark_reference(
            benchmark_reference,
            benchmark_data_id,
            registry=benchmark_registry,
        )
        if canonical_benchmark_id is None:
            return _unavailable(
                "Canonical benchmark/cash resolution is unavailable.",
                benchmark_reference=reference,
            )
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return _unavailable("No local adjusted-close price snapshot is available.")
    if "is_adjusted" in prices.columns and not prices["is_adjusted"].map(_adjusted_flag_is_true).all():
        return _unavailable("The local price snapshot contains a non-adjusted price series.")

    price_columns = ["date", "etf_id", "adjusted_close"]
    if "known_at" in prices.columns:
        price_columns.append("known_at")
    frame = prices.loc[:, price_columns].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    if "known_at" in frame.columns:
        frame["known_at"] = pd.to_datetime(frame["known_at"], errors="coerce", utc=True)
    frame["etf_id"] = frame["etf_id"].astype(str).str.strip()
    required_timestamps = ["date", "adjusted_close"]
    if "known_at" in frame.columns:
        required_timestamps.append("known_at")
    frame = frame.dropna(subset=required_timestamps)
    decision_time = None
    if isinstance(benchmark_reference, Mapping):
        analysis = benchmark_reference.get("analysis")
        if isinstance(analysis, Mapping):
            parsed_decision_time = pd.to_datetime(analysis.get("decision_time"), errors="coerce", utc=True)
            if not pd.isna(parsed_decision_time):
                decision_time = parsed_decision_time
    freshness_as_of = as_of_date or (decision_time.date() if decision_time is not None else None)
    evaluation_cutoff = None
    if as_of_date is not None:
        evaluation_cutoff = pd.Timestamp(as_of_date, tz="UTC") + pd.Timedelta(days=1)
    observation_cutoff = decision_time
    if evaluation_cutoff is not None:
        observation_cutoff = evaluation_cutoff if observation_cutoff is None else min(observation_cutoff, evaluation_cutoff)
    if observation_cutoff is not None:
        frame = frame[frame["date"] < observation_cutoff]
        if "known_at" in frame.columns:
            frame = frame[frame["known_at"] < observation_cutoff]
    frame = frame[(frame["etf_id"] != "") & (frame["adjusted_close"] > 0)]
    if frame.empty:
        return _unavailable("The local price snapshot has no usable adjusted-close rows.")
    if "known_at" in frame.columns:
        # Several revisions of one close: the pivot below keeps the last row, which
        # must be the most recently known revision (never an input-order accident).
        frame = frame.sort_values(["date", "etf_id", "known_at"], kind="stable")
    frame = _clip_to_reference_window(frame, reference)
    if frame.empty:
        return _unavailable(
            "The declared benchmark calculation window is unavailable.",
            benchmark_reference=reference,
        )

    pivot = frame.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last").sort_index()
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)
    latest_date = pivot.index.max()
    # Returns and the regime panel use the UNFILLED closes: a forward fill would fabricate 0.0 returns
    # and make a stale benchmark look fresh to the regime staleness gate (A04-F1).
    latest_day = pivot.ffill(limit=5).iloc[-1]  # a level only, never a return input
    returns = per_series_returns(pivot)
    metadata = _metadata_by_id(instruments)
    proxy_rows = [_proxy_summary(name, pivot, returns, metadata, freshness_as_of) for name in _PROXY_KEYWORDS]
    breadth = _breadth_summary(pivot, freshness_as_of)
    volatility = _volatility_summary(returns, freshness_as_of)
    regime_frame = pivot.rename_axis("date").stack(future_stack=True).dropna().rename("adjusted_close").reset_index()
    regime_frame.columns = ["date", "etf_id", "adjusted_close"]
    regime = build_market_regime(
        regime_frame,
        None,
        max_forward_fill=5,
        benchmark_id=benchmark_data_id,
        benchmark_reference=benchmark_reference,
        benchmark_registry=benchmark_registry,
    )
    freshness_days = None if freshness_as_of is None else (freshness_as_of - latest_date.date()).days
    dashboard_label = _dashboard_label(regime.get("regime_score_10"))

    return {
        "status": "available_with_gaps" if any(row["status"] != "available" for row in proxy_rows) else "available",
        "as_of": latest_date.date().isoformat(),
        "freshness_days": freshness_days,
        "freshness_status": "unavailable" if freshness_days is None else "fresh" if freshness_days <= 7 else "stale",
        "provenance": "local adjusted_close price snapshot",
        "proxy_rows": proxy_rows,
        "inflation_rates": _macro_observation_summary(observations, decision_time=observation_cutoff),
        "breadth": breadth,
        "volatility": volatility,
        "regime": {
            "label": dashboard_label,
            "source_label": str(regime.get("regime_label", "Regime unavailable")),
            "dashboard_label": dashboard_label,
            "score_10": regime.get("regime_score_10"),
            "summary": str(regime.get("summary", "Regime unavailable.")),
        },
        # INT-19 shadow context: filtered (never smoothed) high-variance state probability of the benchmark.
        "stress_probability": filtered_stress_probability(returns[canonical_benchmark_id], latest_date)
        if canonical_benchmark_id in returns.columns
        else {"status": "unavailable", "probability": None, "reason": "Canonical benchmark series is unavailable.", "execution_allowed": False},
        "optional_fred": {
            "status": "unavailable",
            "message": "Optional FRED is probe-only and no network request was made.",
            "source": "FRED",
            "freshness_status": "unavailable",
        },
        "authority": "context_only",
        "context_only": True,
        "score_eligible": False,
        "execution_allowed": False,
        "executable_authority": False,
        "limitations": [
            "Macro context is descriptive and does not generate scores, expected returns or orders.",
            "Missing configured proxies remain unavailable; no silent vendor fallback is performed.",
            "Vintage-aware macro observations are supplied separately by MacroWarehouse.as_of().",
        ],
        "instrument_count": int(latest_day.dropna().size),
        "benchmark_data_id": benchmark_data_id,
        "benchmark_reference": reference,
    }


_TRUE_FLAGS = {"true", "t", "yes", "y", "1"}


def _adjusted_flag_is_true(value: object) -> bool:
    """Strict flag parsing: only an explicit true counts; text "False" is false."""

    if isinstance(value, str):
        return value.strip().lower() in _TRUE_FLAGS
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, Integral):
        return value == 1
    return False


def _utc_timestamp(value: object) -> pd.Timestamp:
    parsed = pd.Timestamp(str(value))
    return parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")


def _metadata_by_id(instruments: Iterable[object]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for instrument in instruments:
        if isinstance(instrument, Mapping):
            raw = dict(instrument)
        elif hasattr(instrument, "model_dump"):
            raw = instrument.model_dump()
        else:
            raw = {name: getattr(instrument, name, "") for name in ("id", "name", "ticker", "asset_class", "role", "theme")}
        identifier = str(raw.get("id") or "").strip()
        if identifier:
            result[identifier] = {key: str(value or "").lower() for key, value in raw.items()}
    return result


def _proxy_summary(
    name: str,
    pivot: pd.DataFrame,
    returns: pd.DataFrame,
    metadata: dict[str, dict[str, str]],
    freshness_as_of: date | None,
) -> dict[str, object]:
    candidates: list[str] = []
    for identifier in pivot.columns:
        if metadata and str(identifier) not in metadata:
            continue
        raw = metadata.get(str(identifier), {})
        searchable = " ".join([str(identifier).lower(), *raw.values()])
        if name == "equity" and not metadata:
            candidates.append(str(identifier))
        elif any(keyword in searchable for keyword in _PROXY_KEYWORDS[name]):
            candidates.append(str(identifier))
    if not candidates:
        return {
            "proxy": name,
            "status": "unavailable",
            "instrument_ids": [],
            "reason": "No locally configured price proxy matches this category.",
            "source": "local adjusted_close price snapshot",
            "provenance": "local adjusted_close price snapshot",
            "freshness_status": "unavailable",
        }
    sample = pivot[candidates].dropna(how="all")
    if sample.empty:
        return {"proxy": name, "status": "unavailable", "instrument_ids": candidates, "reason": "Proxy has no usable local history.", "source": "local adjusted_close price snapshot", "freshness_status": "unavailable"}
    proxy_returns = returns[candidates].tail(20)
    period_return = sample.iloc[-1].div(sample.iloc[max(0, len(sample) - 21)]).sub(1).median() if len(sample) > 1 else None
    volatility = proxy_returns.std(skipna=True).median() * (252**0.5) if not proxy_returns.empty else None
    return {
        "proxy": name,
        "status": "available",
        "instrument_ids": candidates,
        "period_return_20d": _rounded(period_return),
        "volatility_annualised": _rounded(volatility),
        "as_of": sample.index.max().date().isoformat(),
        "source": "local adjusted_close price snapshot",
        "provider_symbol": None,
        "provenance": "local adjusted_close price snapshot",
        "freshness_status": "unavailable" if freshness_as_of is None else "fresh" if (freshness_as_of - sample.index.max().date()).days <= 7 else "stale",
    }


def _breadth_summary(pivot: pd.DataFrame, freshness_as_of: date | None) -> dict[str, object]:
    if len(pivot) < 200:
        return {"status": "unavailable", "reason": "At least 200 local trading days are required.", "pct_above_sma200": None, "source": "local adjusted_close price snapshot", "freshness_status": "unavailable"}
    filled = pivot.ffill(limit=5)
    latest = filled.iloc[-1]
    sma200 = filled.rolling(200, min_periods=200).mean().iloc[-1]
    valid = latest.notna() & sma200.notna()
    values = (latest[valid] > sma200[valid]).dropna()
    as_of = pivot.index.max().date()
    return {
        "status": "available" if not values.empty else "unavailable",
        "pct_above_sma200": _rounded(values.mean() if not values.empty else None),
        "instrument_count": int(values.size),
        "as_of": as_of.isoformat(),
        "source": "local adjusted_close price snapshot",
        "provenance": "local adjusted_close price snapshot",
        "freshness_status": "unavailable" if freshness_as_of is None else "fresh" if (freshness_as_of - as_of).days <= 7 else "stale",
    }


def _volatility_summary(returns: pd.DataFrame, freshness_as_of: date | None) -> dict[str, object]:
    sample = returns.tail(20)
    values = sample.std(skipna=True).dropna() * (252**0.5)
    return {
        "status": "available" if not values.empty else "unavailable",
        "median_annualised": _rounded(values.median() if not values.empty else None),
        "instrument_count": int(values.size),
        "window_days": int(len(sample)),
        "as_of": returns.index.max().date().isoformat() if not returns.empty else None,
        "source": "local adjusted_close price snapshot",
        "provenance": "local adjusted_close price snapshot",
        "freshness_status": "unavailable" if freshness_as_of is None or returns.empty else "fresh" if (freshness_as_of - returns.index.max().date()).days <= 7 else "stale",
    }


def _rounded(value: object) -> float | None:
    try:
        if pd.isna(value):
            return None
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _unavailable(
    reason: str,
    *,
    benchmark_reference: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "status": "unavailable",
        "as_of": None,
        "freshness_days": None,
        "freshness_status": "unavailable",
        "provenance": "local adjusted_close price snapshot",
        "proxy_rows": [{"proxy": name, "status": "unavailable", "instrument_ids": [], "reason": reason, "source": "local adjusted_close price snapshot", "freshness_status": "unavailable"} for name in _PROXY_KEYWORDS],
        "inflation_rates": {"status": "unavailable", "rows": [], "reason": reason},
        "breadth": {"status": "unavailable", "reason": reason, "pct_above_sma200": None, "source": "local adjusted_close price snapshot", "freshness_status": "unavailable"},
        "volatility": {"status": "unavailable", "reason": reason, "median_annualised": None, "source": "local adjusted_close price snapshot", "freshness_status": "unavailable"},
        "regime": {"label": "Regime unavailable", "dashboard_label": "unknown", "score_10": None, "summary": reason},
        "benchmark_data_id": None,
        "benchmark_reference": dict(benchmark_reference or unavailable_reference_projection()),
        "optional_fred": {"status": "unavailable", "message": "Optional FRED is probe-only and no network request was made.", "source": "FRED", "freshness_status": "unavailable"},
        "authority": "context_only",
        "context_only": True,
        "score_eligible": False,
        "execution_allowed": False,
        "executable_authority": False,
        "limitations": ["No local adjusted-close evidence was available."],
        "instrument_count": 0,
    }


def _clip_to_reference_window(
    frame: pd.DataFrame,
    reference: Mapping[str, object],
) -> pd.DataFrame:
    analysis = reference.get("analysis")
    if reference.get("status") != "available":
        return frame
    if not isinstance(analysis, Mapping):
        return pd.DataFrame()
    start = analysis.get("start_date")
    end = analysis.get("end_date")
    decision_time = analysis.get("decision_time")
    if not all(isinstance(value, str) and value for value in (start, end, decision_time)):
        return pd.DataFrame()
    return clip_to_decision_window(
        frame,
        start_date=start,
        end_date=end,
        decision_time=decision_time,
    )


def _dashboard_label(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 8:
        return "risk-on"
    if value >= 6:
        return "neutral"
    if value >= 4:
        return "defensive"
    return "stressed"


def _macro_observation_summary(observations: Iterable[object], *, decision_time: pd.Timestamp | None) -> dict[str, object]:
    if decision_time is None:
        return {"status": "unavailable", "rows": [], "reason": "Evaluation decision time is unavailable."}
    rows: list[dict[str, object]] = []
    for observation in observations:
        if hasattr(observation, "model_dump"):
            raw = observation.model_dump(mode="json")
        elif isinstance(observation, Mapping):
            raw = dict(observation)
        else:
            raw = {name: getattr(observation, name, None) for name in ("series_id", "value", "unit", "source_id", "available_at", "observed_at", "country", "currency", "period_start")}
        available_at = pd.to_datetime(raw.get("available_at"), errors="coerce", utc=True)
        observed_at = pd.to_datetime(raw.get("observed_at"), errors="coerce", utc=True)
        if (
            pd.isna(available_at)
            or pd.isna(observed_at)
            or available_at >= decision_time
            or observed_at >= decision_time
        ):
            continue
        if str(raw.get("timezone_confidence") or "unknown").lower() not in {"exact", "assumed"}:
            continue
        if str(raw.get("availability_confidence") or "unknown").lower() not in {"exact", "assumed"}:
            continue
        series_id = str(raw.get("series_id") or "").lower()
        if not any(term in series_id for term in ("inflation", "cpi", "pce", "rate", "yield", "sofr", "policy")):
            continue
        rows.append(
            {
                "series_id": raw.get("series_id"),
                "value": raw.get("value"),
                "unit": raw.get("unit"),
                "source": raw.get("source_id") or "local macro warehouse",
                "provenance": "local macro warehouse bitemporal as_of selection",
                "country": raw.get("country"),
                "currency": raw.get("currency"),
                "period_start": raw.get("period_start"),
                "available_at": raw.get("available_at"),
                "observed_at": raw.get("observed_at"),
                "freshness_status": "fresh" if (decision_time - available_at).days <= 7 else "stale",
            }
        )
    selected, missing_jurisdiction = finalize_observation_rows(rows)
    return observation_summary_payload(selected, missing_jurisdiction)


INFLATION_ROWS_PER_SERIES = 12


def finalize_observation_rows(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    """Canonical selection of inflation/rates rows for the macro context.

    A row without a jurisdiction (country) is not usable context and is dropped (it is
    counted so the reason stays explicit).  Rows are ordered by period (observed
    time, then availability) within each series and jurisdiction, and the latest
    ``INFLATION_ROWS_PER_SERIES`` periods of each are kept.
    """

    usable: list[dict[str, object]] = []
    missing = 0
    for row in rows:
        country = str(row.get("country") or "").strip()
        if not country:
            missing += 1
            continue
        usable.append({**row, "country": country})
    usable.sort(
        key=lambda item: (
            str(item.get("series_id")),
            str(item["country"]),
            _utc_timestamp(item.get("observed_at")),
            _utc_timestamp(item.get("available_at")),
        )
    )
    selected: list[dict[str, object]] = []
    for _key, group in groupby(usable, key=lambda item: (item.get("series_id"), item["country"])):
        selected.extend(list(group)[-INFLATION_ROWS_PER_SERIES:])
    return selected, missing


def observation_summary_payload(rows: list[dict[str, object]], missing_jurisdiction: int) -> dict[str, object]:
    if rows:
        reason = None
    elif missing_jurisdiction:
        reason = "Matching inflation or rates observations lack a country/jurisdiction."
    else:
        reason = "No local inflation or rates observations matched."
    return {"status": "available" if rows else "unavailable", "rows": rows, "reason": reason}


def _exact_rows(rows: pd.DataFrame, series_id: str) -> pd.DataFrame:
    """The one gate for macro features: only exact-availability rows of the series."""

    if rows.empty or "availability_confidence" not in rows.columns:
        return rows.iloc[0:0]
    exact = rows[(rows["series_id"] == series_id) & (rows["availability_confidence"] == "exact")]
    return exact.sort_values(["period_start", "available_at"]).drop_duplicates("period_start", keep="last")


def macro_feature_value(rows: pd.DataFrame, *, series_id: str) -> dict[str, object]:
    """Return the latest exact-availability value of one series from ``MacroWarehouse.as_of`` rows.

    Rows whose ``availability_confidence`` is not ``exact`` (for example an inferred availability time)
    never feed a feature.  No row, or only barred rows, gives an explicit unavailable result.
    """

    unavailable = {"status": "unavailable", "series_id": series_id, "value": None, "execution_allowed": False}
    if rows.empty or "availability_confidence" not in rows.columns:
        return {**unavailable, "reason": "no macro observations were available at the decision time"}
    exact = _exact_rows(rows, series_id)
    if exact.empty:
        return {**unavailable, "reason": "no exact-availability observation for the series; inferred rows are barred"}
    latest = exact.sort_values("period_start").iloc[-1]
    return {
        "status": "available",
        "series_id": series_id,
        "value": float(latest["value"]),
        "period_start": str(latest["period_start"]),
        "available_at": str(latest["available_at"]),
        "execution_allowed": False,
    }


# INT-19 indicators.  Inputs are ``MacroWarehouse.as_of`` rows, so only vintages known at the cut-off
# are present; ``_exact_rows`` then bars rows whose availability is not exact.  A missing input
# makes the indicator unavailable; nothing is filled.
_LEVELS = {
    "baa_10y_spread": "BAA10Y",
    "hy_oas": "BAMLH0A0HYM2",
    "nfci": "NFCI",
    "vix": "VIXCLS",
    "cape": "SHILLER_CAPE",  # user-imported Shiller file
}
# id -> (long leg, short leg); both legs must share one period.
_SLOPES = {"slope_10y_2y": ("DGS10", "DGS2"), "slope_10y_3m": ("DGS10", "DGS3MO")}
INDICATOR_IDS = (*_SLOPES, *_LEVELS, "sahm_rule", "equity_risk_premium", "market_cap_to_gdp")
_SAHM_MONTHS = 15  # the current and the 12 preceding 3-month averages need fifteen consecutive months
_Outcome = tuple[float, str, dict[str, pd.Series]] | str


def _indicator_result(indicator_id: str, outcome: _Outcome) -> dict[str, object]:
    if isinstance(outcome, str):
        return {"status": "unavailable", "indicator_id": indicator_id, "value": None, "reason": outcome, "execution_allowed": False}
    value, unit, used = outcome
    return {
        "status": "available",
        "indicator_id": indicator_id,
        "value": float(value),
        "unit": unit,
        "inputs": {name: {"period_start": str(row["period_start"]), "available_at": str(row["available_at"])} for name, row in used.items()},
        "execution_allowed": False,
    }


def _latest_inputs(rows: pd.DataFrame, series_ids: tuple[str, ...]) -> dict[str, pd.Series] | str:
    found: dict[str, pd.Series] = {}
    for series_id in series_ids:
        exact = _exact_rows(rows, series_id)
        if exact.empty:
            return f"no exact-availability observation for {series_id} at the cut-off"
        found[series_id] = exact.iloc[-1]
    return found


def _sahm_rule(rows: pd.DataFrame) -> _Outcome:
    exact = _exact_rows(rows, "UNRATE")
    if exact.empty:
        return "no exact-availability observation for UNRATE at the cut-off"
    if set(exact["unit"]) != {"percent"}:
        return "UNRATE must be in percent"
    series = pd.Series(exact["value"].to_numpy(float), index=pd.to_datetime(exact["period_start"]).dt.to_period("M"))
    window = pd.period_range(end=series.index.max(), periods=_SAHM_MONTHS, freq="M")
    if not window.isin(series.index).all():
        return f"UNRATE needs {_SAHM_MONTHS} consecutive months at the cut-off"
    averages = series.loc[window].rolling(3).mean().dropna()
    # Current 3-month average less the lowest of the 12 preceding 3-month averages (current excluded).
    return float(averages.iloc[-1] - averages.iloc[:-1].min()), "percentage_points", {"UNRATE": exact.iloc[-1]}


def _slope(rows: pd.DataFrame, first: str, second: str) -> _Outcome:
    found = _latest_inputs(rows, (first, second))
    if isinstance(found, str):
        return found
    if found[first]["unit"] != found[second]["unit"]:
        return "the two series use different units"
    if found[first]["period_start"] != found[second]["period_start"]:
        return "the two series have different latest periods"
    unit = "percentage_points" if found[first]["unit"] == "percent" else str(found[first]["unit"])
    return float(found[first]["value"]) - float(found[second]["value"]), unit, found


def _equity_risk_premium(rows: pd.DataFrame) -> _Outcome:
    # Earnings yield from CAPE less the 10-year real yield, in percentage points.
    found = _latest_inputs(rows, ("SHILLER_CAPE", "DFII10"))
    if isinstance(found, str):
        return found
    cape, real_yield = float(found["SHILLER_CAPE"]["value"]), float(found["DFII10"]["value"])
    if cape <= 0 or found["DFII10"]["unit"] != "percent":
        return "CAPE must be positive and the real yield in percent"
    return 100.0 / cape - real_yield, "percentage_points", found


def _market_cap_to_gdp(rows: pd.DataFrame) -> _Outcome:
    found = _latest_inputs(rows, ("BOGZ1LM893064105Q",))
    if isinstance(found, str):
        return found
    market_cap = found["BOGZ1LM893064105Q"]
    # GDP of the same quarter as the latest market value, never a different quarter.
    same_quarter = _exact_rows(rows, "GDP")
    same_quarter = same_quarter[same_quarter["period_start"] == market_cap["period_start"]]
    if same_quarter.empty:
        return "no exact-availability GDP observation for the market value's quarter"
    gdp = same_quarter.iloc[-1]
    found["GDP"] = gdp
    if market_cap["unit"] != "millions_usd" or gdp["unit"] != "billions_usd" or float(gdp["value"]) <= 0:
        return "market value must be in millions_usd and a positive GDP in billions_usd"
    return float(market_cap["value"]) / (float(gdp["value"]) * 1000.0) * 100.0, "percent", found


def macro_indicator(rows: pd.DataFrame, indicator_id: str) -> dict[str, object]:
    """Compute one INT-19 indicator from the vintages in ``rows``, or return it as unavailable."""

    if indicator_id not in INDICATOR_IDS:
        raise ValueError(f"unknown macro indicator: {indicator_id}")
    outcome: _Outcome
    if indicator_id in _LEVELS:
        found = _latest_inputs(rows, (_LEVELS[indicator_id],))
        if isinstance(found, str):
            outcome = found
        else:
            (row,) = found.values()
            outcome = (float(row["value"]), str(row["unit"]), found)
    elif indicator_id in _SLOPES:
        outcome = _slope(rows, *_SLOPES[indicator_id])
    elif indicator_id == "sahm_rule":
        outcome = _sahm_rule(rows)
    elif indicator_id == "equity_risk_premium":
        outcome = _equity_risk_premium(rows)
    else:
        outcome = _market_cap_to_gdp(rows)
    return _indicator_result(indicator_id, outcome)


def macro_indicators(rows: pd.DataFrame) -> dict[str, dict[str, object]]:
    return {indicator_id: macro_indicator(rows, indicator_id) for indicator_id in INDICATOR_IDS}


__all__ = [
    "INDICATOR_IDS",
    "build_macro_context",
    "finalize_observation_rows",
    "macro_feature_value",
    "macro_indicator",
    "macro_indicators",
    "macro_status",
    "observation_summary_payload",
]
