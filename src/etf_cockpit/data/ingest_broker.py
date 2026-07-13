from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import PORTFOLIOS_DIR


def import_holdings_csv(path: Path, *, destination: Path | None = None) -> Path:
    frame = pd.read_csv(path)
    return import_holdings_frame(frame, destination=destination)


def import_holdings_frame(frame: pd.DataFrame, *, destination: Path | None = None) -> Path:
    """Validate and publish an already-previewed canonical holdings frame."""

    required = {"as_of_date", "etf_id", "units", "market_price", "market_value_eur", "current_weight"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Holdings CSV missing columns: {sorted(missing)}")
    out = Path(destination) if destination is not None else PORTFOLIOS_DIR / "current_holdings.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(out, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path))
    return out
