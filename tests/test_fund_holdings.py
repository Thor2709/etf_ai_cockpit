from __future__ import annotations

import pandas as pd

from etf_cockpit.data.fund_holdings import normalise_holdings


def test_full_holdings_are_normalised_and_partial_data_is_explicit() -> None:
    full = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "weight": [0.6, 0.4]}), "VWCE", "2026-07-10", "issuer")
    partial = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [0.4]}), "VWCE", "2026-07-10", "vendor")
    invalid = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [-1.0]}), "VWCE", "2026-07-10", "issuer")
    assert full.completeness == "full"
    assert partial.completeness == "partial"
    assert invalid.completeness == "invalid"
    assert full.frame.iloc[0]["instrument_id"] == "VWCE"
