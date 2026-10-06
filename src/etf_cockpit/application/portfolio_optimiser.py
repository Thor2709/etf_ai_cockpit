"""Application facade for the advisory portfolio optimiser workspace."""

from __future__ import annotations

import pandas as pd

from etf_cockpit.portfolio.optimiser import (
    METHODS,
    OptimiserConstraints,
    PortfolioOptimiser,
    returns_from_adjusted_prices,
)


def build_portfolio_optimiser(prices: pd.DataFrame | None) -> tuple[PortfolioOptimiser, pd.DataFrame]:
    """Build the domain service from the current adjusted-price snapshot."""

    returns = returns_from_adjusted_prices(prices if prices is not None else pd.DataFrame())
    return PortfolioOptimiser(returns), returns


__all__ = [
    "METHODS",
    "OptimiserConstraints",
    "PortfolioOptimiser",
    "build_portfolio_optimiser",
]
