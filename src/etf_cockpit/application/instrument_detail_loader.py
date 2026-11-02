"""Headless loader for the canonical instrument-detail read model.

Open defaults: detail requests return the overview and score groups; missing
panels remain unavailable and are never replaced with synthetic values.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


_SECTIONS: dict[str, tuple[str, ...]] = {
    "overview": ("identity", "price", "market_clock"),
    "score": ("scores", "risk", "attribution", "history", "metric_history"),
    "forecast": ("forecasts", "backtests", "model_cards"),
    "signals": ("candle_evidence", "run_changes"),
    "features": ("feature_drivers",),
    "etf": ("etf_liquidity", "etf_economics", "etf_look_through", "etf_disclosures", "etf_structure", "etf_holdings", "etf_overlap"),
    "stock": ("fundamentals", "news", "events"),
    "valuation": ("valuation",),
    "bank": ("financial_institutions", "peer_cohort"),
    "fixed_income": ("fixed_income_terms", "fixed_income_market_data", "fixed_income_analytics", "fixed_income_risk"),
    "factor_risk": ("factor_risk",),
    "opportunity": ("opportunity",),
    "news": ("news", "events"),
}


def load_instrument_detail(
    snapshot: object,
    instrument_id: str,
    sections: Sequence[str] = ("overview", "score"),
) -> dict[str, Any]:
    """Select compact section groups from the existing detail application service."""

    selected = tuple(dict.fromkeys(str(value).strip().casefold() for value in sections))
    if not selected:
        selected = ("overview", "score")
    unknown = set(selected) - set(_SECTIONS)
    if unknown:
        raise ValueError("sections contains an unsupported value: " + ", ".join(sorted(unknown)))
    from etf_cockpit.application.instrument_detail_view import build_instrument_detail

    view = build_instrument_detail(snapshot, instrument_id)
    output: dict[str, Any] = {}
    for name in selected:
        values = {key: view.sections.get(key, {"status": "unavailable", "reason": "section_not_loaded"}) for key in _SECTIONS[name]}
        statuses = [value.get("status") if isinstance(value, Mapping) else None for value in values.values()]
        status = "available" if "available" in statuses or view.status == "available" and name == "overview" else "unavailable"
        output[name] = {"status": status, "data": values}
    return {
        "status": view.status,
        "instrument_id": view.instrument_id,
        "display_name": view.display_name,
        "identity": view.identity,
        "sections": output,
        "execution_allowed": False,
    }


__all__ = ["load_instrument_detail"]
