"""E1 P4: the faster text checks of ``_effective_availability`` equal the old ``astype(str).str.strip()`` form."""

from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.data.fx_data import _stripped_text


def test_stripped_text_equals_the_old_string_form():
    values = pd.Series(
        [" market_close_unrevised ", "", None, np.nan, pd.Timestamp("2026-11-06T23:59:59Z"), "live_ingestion", 3.5, " "] * 3,
        index=range(100, 124), dtype=object,
    )

    assert _stripped_text(values).equals(values.astype(str).str.strip())
