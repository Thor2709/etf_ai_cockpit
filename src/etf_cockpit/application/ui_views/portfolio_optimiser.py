from __future__ import annotations

from etf_cockpit.portfolio.optimiser import OPTIMISER_MODEL_VERSION


def portfolio_optimiser_view() -> dict[str, str | None]:
    return {"model_version": OPTIMISER_MODEL_VERSION, "unavailable_reason": None}
