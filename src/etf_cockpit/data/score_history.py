from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ScoreHistoryWriteResult:
    path: Path
    rows_written: int
    run_id: str
    snapshot_hash: str


_COLUMNS = ["run_id", "run_completed_at", "instrument_id", "final_combined_score_10", "final_action", "blocked_by", "snapshot_hash"]


def append_score_run(scores: pd.DataFrame, run_id: str, created_at: str, *, root: Path) -> ScoreHistoryWriteResult:
    path = root / "data" / "derived" / "score_history.parquet"
    frame = scores.copy()
    if "instrument_id" not in frame.columns or "final_combined_score_10" not in frame.columns:
        raise ValueError("score history requires instrument_id and final_combined_score_10")
    frame["final_combined_score_10"] = pd.to_numeric(frame["final_combined_score_10"], errors="coerce")
    frame = frame.dropna(subset=["instrument_id", "final_combined_score_10"])
    frame["run_id"] = run_id
    frame["run_completed_at"] = created_at
    for column in ("final_action", "blocked_by"):
        if column not in frame.columns:
            frame[column] = ""
    snapshot_hash = hashlib.sha256(frame.sort_values("instrument_id").to_json().encode()).hexdigest()
    frame["snapshot_hash"] = snapshot_hash
    frame = frame[_COLUMNS]
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=_COLUMNS)
    duplicate = existing[(existing.get("run_id", "") == run_id) & (existing.get("snapshot_hash", "") == snapshot_hash)] if not existing.empty else pd.DataFrame()
    if not duplicate.empty:
        return ScoreHistoryWriteResult(path, 0, run_id, snapshot_hash)
    combined = pd.concat([existing, frame], ignore_index=True).drop_duplicates(subset=["run_id", "instrument_id"], keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return ScoreHistoryWriteResult(path, len(frame), run_id, snapshot_hash)


def score_history_frame(*, root: Path) -> pd.DataFrame:
    path = root / "data" / "derived" / "score_history.parquet"
    if not path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=_COLUMNS)
    return frame.reindex(columns=[column for column in _COLUMNS if column in frame.columns]).copy()
