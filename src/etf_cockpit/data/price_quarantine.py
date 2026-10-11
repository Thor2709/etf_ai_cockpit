from __future__ import annotations

import dataclasses

from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.provenance import sha256_dataframe


def quarantine_invalid_ohlc(result: ProviderResult):
    """Split vendor rows with impossible OHLC values off the import; return (clean result, quarantined rows)."""
    frame = result.data
    needed = {"open", "high", "low", "close"}
    if frame is None or not needed.issubset(frame.columns):
        return result, None
    bad = (
        (frame["open"] <= 0)
        | (frame["close"] <= 0)
        | (frame["high"] < frame["low"])
        | (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
    )
    if not bad.any():
        return result, None
    quarantined = frame.loc[bad].copy()
    quarantined["quarantine_reason"] = "invalid_ohlc"
    clean = frame.loc[~bad].reset_index(drop=True)
    metadata = dataclasses.replace(result.metadata, checksum=sha256_dataframe(clean)) if result.metadata else None
    return dataclasses.replace(result, data=clean, metadata=metadata), quarantined
