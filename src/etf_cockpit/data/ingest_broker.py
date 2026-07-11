from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import PORTFOLIOS_DIR


def import_holdings_csv(path: Path) -> Path:
    frame = pd.read_csv(path)
    required = {"as_of_date", "etf_id", "units", "market_price", "market_value_eur", "current_weight"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Holdings CSV missing columns: {sorted(missing)}")
    out = PORTFOLIOS_DIR / "current_holdings.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)
    return out
