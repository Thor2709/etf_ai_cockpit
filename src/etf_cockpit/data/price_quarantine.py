from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.provenance import sha256_dataframe
from etf_cockpit.data.validation import invalid_ohlc_mask


def quarantine_invalid_adjusted_close(result: ProviderResult):
    """Reject whole instruments with an invalid freshly fetched adjustment basis."""
    frame = result.data
    if frame is None or frame.empty or "etf_id" not in frame.columns:
        return result, None
    adjusted = pd.to_numeric(
        frame.get("adjusted_close", pd.Series(float("nan"), index=frame.index)), errors="coerce"
    )
    bad = adjusted.isna() | ~np.isfinite(adjusted) | adjusted.le(0)
    rejected = frame["etf_id"].isin(frame.loc[bad, "etf_id"])
    if not rejected.any():
        return result, None
    quarantined = frame.loc[rejected].copy()
    quarantined["quarantine_reason"] = "invalid_adjusted_close"
    clean = frame.loc[~rejected].reset_index(drop=True)
    metadata = dataclasses.replace(result.metadata, checksum=sha256_dataframe(clean)) if result.metadata else None
    return dataclasses.replace(result, data=clean, metadata=metadata), quarantined


def quarantine_invalid_ohlc(result: ProviderResult):
    """Split vendor rows with impossible OHLC values off the import; return (clean result, quarantined rows)."""
    frame = result.data
    needed = {"open", "high", "low", "close"}
    if frame is None or not needed.issubset(frame.columns):
        return result, None
    bad = invalid_ohlc_mask(frame)
    if not bad.any():
        return result, None
    quarantined = frame.loc[bad].copy()
    quarantined["quarantine_reason"] = "invalid_ohlc"
    clean = frame.take(np.flatnonzero(~bad.to_numpy()))
    clean.index = pd.RangeIndex(len(clean))  # as reset_index(drop=True), without a second copy
    metadata = dataclasses.replace(result.metadata, checksum=sha256_dataframe(clean)) if result.metadata else None
    return dataclasses.replace(result, data=clean, metadata=metadata), quarantined
