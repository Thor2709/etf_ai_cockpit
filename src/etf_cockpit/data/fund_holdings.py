from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class HoldingsNormalisationResult:
    frame: pd.DataFrame
    completeness: str
    source: str
    as_of: str
    warnings: tuple[str, ...]
    source_id: str


def normalise_holdings(frame: pd.DataFrame, instrument_id: str, as_of: str, source: str) -> HoldingsNormalisationResult:
    if frame.empty or not {"security", "weight"}.issubset(frame.columns):
        return HoldingsNormalisationResult(pd.DataFrame(), "invalid", source, as_of, ("missing_security_or_weight",), "")
    clean = frame[["security", "weight"]].copy()
    clean["security"] = clean["security"].astype(str).str.strip()
    clean["weight"] = pd.to_numeric(clean["weight"], errors="coerce")
    if clean["weight"].isna().any() or (clean["weight"] < 0).any() or (clean["weight"] > 100).any():
        return HoldingsNormalisationResult(pd.DataFrame(), "invalid", source, as_of, ("weight_out_of_range",), "")
    if clean["weight"].max() > 1:
        clean["weight"] = clean["weight"] / 100
    total = float(clean["weight"].sum())
    completeness = "full" if 0.99 <= total <= 1.01 else "partial" if 0 < total < 0.99 else "invalid"
    if completeness == "invalid":
        return HoldingsNormalisationResult(pd.DataFrame(), completeness, source, as_of, ("weights_not_usable",), "")
    clean["instrument_id"] = instrument_id
    clean["as_of"] = as_of
    clean["source"] = source
    source_id = hashlib.sha256(f"{instrument_id}:{as_of}:{source}:{clean.to_json()}".encode()).hexdigest()[:20]
    warnings = () if completeness == "full" else ("partial_top_holdings",)
    return HoldingsNormalisationResult(clean, completeness, source, as_of, warnings, source_id)
