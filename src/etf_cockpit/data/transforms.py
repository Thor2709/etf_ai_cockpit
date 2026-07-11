from __future__ import annotations

import pandas as pd


def normalise_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalised = frame.copy()
    normalised["date"] = pd.to_datetime(normalised["date"]).dt.date
    for column in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        normalised[column] = pd.to_numeric(normalised[column], errors="coerce")
    return normalised
