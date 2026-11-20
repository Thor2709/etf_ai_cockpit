"""Separate store of historical (as-of) score runs: ``historical_backfill`` provenance, never the live published history.

The score backfill (``application/score_backfill.py``) writes one complete score run per historical session here. The live
``score_history.parquet`` is never read or written by this module. Rows carry the same snapshot lineage as a live run plus the
provenance label and a point-in-time coverage summary, so the optional historical paper-bot replay can read them explicitly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file

BACKFILL_PROVENANCE = "historical_backfill"
FORWARD_PROVENANCE = "forward_nightly"  # nightly forward score runs (SDD C4); never read by the historical replay
STORE_PROVENANCES = frozenset({BACKFILL_PROVENANCE, FORWARD_PROVENANCE})
BACKFILL_HISTORY_RELATIVE_PATH = Path("data") / "derived" / "score_history_backfill.parquet"
BACKFILL_ELIGIBILITY_RELATIVE_PATH = Path("data") / "derived" / "score_history_backfill_eligibility.parquet"
BACKFILL_MANIFEST_RELATIVE_PATH = Path("data") / "derived" / "score_history_backfill_manifest.json"


def backfill_history_path(root: Path) -> Path:
    return Path(root) / BACKFILL_HISTORY_RELATIVE_PATH


def load_backfill_score_history(root: Path, provenances: Collection[str] = (BACKFILL_PROVENANCE,)) -> pd.DataFrame:
    """The backfill store, restricted to rows whose provenance is in ``provenances`` (fail closed otherwise).

    The default serves the historical replay; readiness, the forward recorder and the writer pass ``STORE_PROVENANCES``.
    """

    path = backfill_history_path(root)
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if frame.empty or "provenance" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["provenance"].astype(str).isin(set(provenances))].reset_index(drop=True)


def load_backfill_eligibility(root: Path, provenances: Collection[str] = (BACKFILL_PROVENANCE,)) -> pd.DataFrame:
    """The eligibility log, filtered like the history; a legacy row without a provenance counts as historical."""

    path = Path(root) / BACKFILL_ELIGIBILITY_RELATIVE_PATH
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if frame.empty:
        return frame
    labels = frame["provenance"] if "provenance" in frame.columns else pd.Series(None, index=frame.index, dtype=object)
    labels = labels.where(labels.notna(), BACKFILL_PROVENANCE).astype(str)
    return frame.loc[labels.isin(set(provenances))].reset_index(drop=True)


def run_content_hash(frame: pd.DataFrame) -> str:
    """``snapshot_hash`` of one score run: its rows without ``snapshot_hash``, in a canonical order."""

    canonical = frame.drop(columns=["snapshot_hash"], errors="ignore").sort_values("instrument_id", kind="stable")
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    return hashlib.sha256(canonical.to_json(orient="records", date_format="iso", default_handler=str).encode("utf-8")).hexdigest()


def load_backfill_manifest(root: Path) -> dict[str, object]:
    path = Path(root) / BACKFILL_MANIFEST_RELATIVE_PATH
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _validate_manifest(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def write_backfill_store(root: Path, history: pd.DataFrame, eligibility: pd.DataFrame, manifest: dict[str, object]) -> Path:
    """Replace the three backfill files (history, eligibility log, manifest) as one atomic group.

    A crash cannot leave history without its eligibility rows or manifest. The live score history is not touched.
    """

    root = Path(root)
    atomic_write_group(
        [
            AtomicWriteRequest(root / BACKFILL_HISTORY_RELATIVE_PATH, parquet_payload(history), validate_parquet_file),
            AtomicWriteRequest(root / BACKFILL_ELIGIBILITY_RELATIVE_PATH, parquet_payload(eligibility), validate_parquet_file),
            AtomicWriteRequest(
                root / BACKFILL_MANIFEST_RELATIVE_PATH,
                json.dumps(manifest, indent=2, sort_keys=True, default=str).encode("utf-8"),
                _validate_manifest,
            ),
        ]
    )
    return root / BACKFILL_HISTORY_RELATIVE_PATH


__all__ = [
    "BACKFILL_ELIGIBILITY_RELATIVE_PATH",
    "BACKFILL_HISTORY_RELATIVE_PATH",
    "BACKFILL_MANIFEST_RELATIVE_PATH",
    "BACKFILL_PROVENANCE",
    "FORWARD_PROVENANCE",
    "STORE_PROVENANCES",
    "backfill_history_path",
    "load_backfill_eligibility",
    "load_backfill_manifest",
    "load_backfill_score_history",
    "run_content_hash",
    "write_backfill_store",
]
