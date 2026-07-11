from __future__ import annotations

import pandas as pd


def build_feature_drivers(scores: pd.DataFrame, ledger: pd.DataFrame | None = None) -> pd.DataFrame:
    frame = scores.copy()
    if "normalised_score_10" not in frame.columns and "score_10" in frame.columns:
        frame["normalised_score_10"] = frame["score_10"]
    frame["normalised_score"] = pd.to_numeric(frame.get("normalised_score_10"), errors="coerce")
    frame["direction"] = frame["normalised_score"].map(lambda value: "missing" if pd.isna(value) else "positive" if value >= 6.5 else "negative" if value < 4 else "mixed")
    frame["driver_text"] = frame.get("why", frame.get("driver_text", ""))
    frame["authority"] = frame.get("authority", "unknown")
    if ledger is not None and not ledger.empty:
        frame = frame.merge(ledger[["instrument_id", "component", "source_id"]], on=["instrument_id", "component"], how="left")
    return frame[[column for column in ("instrument_id", "component", "normalised_score", "direction", "authority", "driver_text", "source_id") if column in frame.columns]]
