"""Deterministic macro context derived from local, adjusted-price evidence.

This module deliberately reports context rather than forecasts or orders.  A
configured proxy is used only when its local price history is present; missing
bond, cash or gold proxies remain explicit unavailable states.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping

import pandas as pd

from etf_cockpit.features.regime import build_market_regime


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
) -> dict[str, object]:
    """Build a local macro context snapshot without network access.

    ``prices`` must contain ``date``, ``etf_id`` and ``adjusted_close``.  The
    calculations use the adjusted series exclusively.  Instrument metadata is
    optional and is used only to identify bond/cash and gold/defensive proxy
    candidates; the absence of metadata never turns an unavailable proxy into
    an inferred one.
    """

    required = {"date", "etf_id", "adjusted_close"}
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return _unavailable("No local adjusted-close price snapshot is available.")
    if "is_adjusted" in prices.columns and not prices["is_adjusted"].fillna(False).astype(bool).all():
        return _unavailable("The local price snapshot contains a non-adjusted price series.")

    frame = prices.loc[:, ["date", "etf_id", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame["etf_id"] = frame["etf_id"].astype(str).str.strip()
    frame = frame.dropna(subset=["date", "adjusted_close"])
    frame = frame[(frame["etf_id"] != "") & (frame["adjusted_close"] > 0)]
    if frame.empty:
        return _unavailable("The local price snapshot has no usable adjusted-close rows.")

    pivot = frame.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last").sort_index()
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)
    latest_date = pivot.index.max()
    filled = pivot.ffill(limit=5)
    latest_day = filled.iloc[-1]
    returns = filled.pct_change(fill_method=None)
    metadata = _metadata_by_id(instruments)
    proxy_rows = [_proxy_summary(name, pivot, returns, metadata) for name in _PROXY_KEYWORDS]
    breadth = _breadth_summary(pivot)
    volatility = _volatility_summary(returns)
    regime_frame = filled.rename_axis("date").stack().rename("adjusted_close").reset_index()
    regime_frame.columns = ["date", "etf_id", "adjusted_close"]
    regime = build_market_regime(regime_frame.dropna(), None)
    freshness_days = max(0, (date.today() - latest_date.date()).days)
    dashboard_label = _dashboard_label(regime.get("regime_score_10"))

    return {
        "status": "available_with_gaps" if any(row["status"] != "available" for row in proxy_rows) else "available",
        "as_of": latest_date.date().isoformat(),
        "freshness_days": freshness_days,
        "freshness_status": "fresh" if freshness_days <= 7 else "stale",
        "provenance": "local adjusted_close price snapshot",
        "proxy_rows": proxy_rows,
        "inflation_rates": _macro_observation_summary(observations, decision_time=latest_date),
        "breadth": breadth,
        "volatility": volatility,
        "regime": {
            "label": str(regime.get("regime_label", "Regime unavailable")),
            "dashboard_label": dashboard_label,
            "score_10": regime.get("regime_score_10"),
            "summary": str(regime.get("summary", "Regime unavailable.")),
        },
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
    }


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


def _proxy_summary(name: str, pivot: pd.DataFrame, returns: pd.DataFrame, metadata: dict[str, dict[str, str]]) -> dict[str, object]:
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
        "freshness_status": "fresh" if (date.today() - sample.index.max().date()).days <= 7 else "stale",
    }


def _breadth_summary(pivot: pd.DataFrame) -> dict[str, object]:
    if len(pivot) < 200:
        return {"status": "unavailable", "reason": "At least 200 local trading days are required.", "pct_above_sma200": None}
    filled = pivot.ffill(limit=5)
    latest = filled.iloc[-1]
    sma200 = filled.rolling(200, min_periods=200).mean().iloc[-1]
    values = (latest > sma200).dropna()
    return {
        "status": "available" if not values.empty else "unavailable",
        "pct_above_sma200": _rounded(values.mean() if not values.empty else None),
        "instrument_count": int(values.size),
        "provenance": "local adjusted_close price snapshot",
    }


def _volatility_summary(returns: pd.DataFrame) -> dict[str, object]:
    sample = returns.tail(20)
    values = sample.std(skipna=True).dropna() * (252**0.5)
    return {
        "status": "available" if not values.empty else "unavailable",
        "median_annualised": _rounded(values.median() if not values.empty else None),
        "instrument_count": int(values.size),
        "window_days": int(len(sample)),
        "provenance": "local adjusted_close price snapshot",
    }


def _rounded(value: object) -> float | None:
    try:
        if pd.isna(value):
            return None
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "as_of": None,
        "freshness_days": None,
        "freshness_status": "unavailable",
        "provenance": "local adjusted_close price snapshot",
        "proxy_rows": [{"proxy": name, "status": "unavailable", "instrument_ids": [], "reason": reason, "source": "local adjusted_close price snapshot", "freshness_status": "unavailable"} for name in _PROXY_KEYWORDS],
        "inflation_rates": {"status": "unavailable", "rows": [], "reason": reason},
        "breadth": {"status": "unavailable", "reason": reason, "pct_above_sma200": None},
        "volatility": {"status": "unavailable", "reason": reason, "median_annualised": None},
        "regime": {"label": "Regime unavailable", "dashboard_label": "unknown", "score_10": None, "summary": reason},
        "optional_fred": {"status": "unavailable", "message": "Optional FRED is probe-only and no network request was made.", "source": "FRED", "freshness_status": "unavailable"},
        "authority": "context_only",
        "context_only": True,
        "score_eligible": False,
        "execution_allowed": False,
        "executable_authority": False,
        "limitations": ["No local adjusted-close evidence was available."],
        "instrument_count": 0,
    }


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


def _macro_observation_summary(observations: Iterable[object], *, decision_time: pd.Timestamp) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for observation in observations:
        if hasattr(observation, "model_dump"):
            raw = observation.model_dump(mode="json")
        elif isinstance(observation, Mapping):
            raw = dict(observation)
        else:
            raw = {name: getattr(observation, name, None) for name in ("series_id", "value", "unit", "source_id", "available_at", "observed_at")}
        available_at = pd.to_datetime(raw.get("available_at"), errors="coerce", utc=True)
        if pd.isna(available_at) or available_at > decision_time:
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
                "available_at": raw.get("available_at"),
                "observed_at": raw.get("observed_at"),
                "freshness_status": "fresh" if (decision_time - available_at).days <= 7 else "stale",
            }
        )
    return {"status": "available" if rows else "unavailable", "rows": rows[-12:], "reason": None if rows else "No local inflation or rates observations matched."}


__all__ = ["build_macro_context", "macro_status"]
