from __future__ import annotations

import math

import numpy as np
import pandas as pd

from etf_cockpit.data.duckdb_store import load_holdings


def current_holdings() -> pd.DataFrame:
    return load_holdings()


def portfolio_value_with_coverage(holdings: pd.DataFrame | None) -> dict[str, object]:
    """Sum EUR market values without treating a missing value as zero.

    ``status`` is ``available`` only when every holding has a finite value;
    otherwise ``value`` is ``None`` and ``partial_value`` carries the sum of the
    priced holdings next to the ``missing_count`` that makes it incomplete.
    """
    if holdings is None or "market_value_eur" not in holdings.columns:
        return {"status": "unavailable", "value": None, "partial_value": None, "priced_count": 0, "missing_count": 0,
                "reason": "market_value_eur is unavailable."}
    values = pd.to_numeric(holdings["market_value_eur"], errors="coerce")
    if values.empty:  # an empty, correctly shaped frame is explicit evidence of no positions
        return {"status": "available", "value": 0.0, "partial_value": 0.0, "priced_count": 0, "missing_count": 0, "reason": None}
    finite = np.isfinite(values.to_numpy(dtype=float))
    priced = int(finite.sum())
    missing = int(len(values) - priced)
    partial_value = float(values[finite].sum()) if priced else None
    if missing == 0 and partial_value is not None and math.isfinite(partial_value):
        return {"status": "available", "value": partial_value, "partial_value": partial_value, "priced_count": priced,
                "missing_count": 0, "reason": None}
    if priced == 0:
        return {"status": "unavailable", "value": None, "partial_value": None, "priced_count": 0, "missing_count": missing,
                "reason": "No holding has a finite market value."}
    return {"status": "partial", "value": None, "partial_value": partial_value, "priced_count": priced,
            "missing_count": missing, "reason": f"{missing} holding(s) have a missing or invalid market value."}


def portfolio_value(holdings: pd.DataFrame) -> float | None:
    """Total EUR value, or ``None`` when any component value is missing."""
    value = portfolio_value_with_coverage(holdings)["value"]
    return float(value) if isinstance(value, float) else None
