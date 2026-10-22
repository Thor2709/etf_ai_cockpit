"""Separate store of historical (as-of) score runs: ``historical_backfill`` provenance, never the live published history.

The score backfill (``application/score_backfill.py``) writes one complete score run per historical session here. The live
``score_history.parquet`` is never read or written by this module. Rows carry the same snapshot lineage as a live run plus the
provenance label and a point-in-time coverage summary, so the optional historical paper-bot replay can read them explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file

BACKFILL_PROVENANCE = "historical_backfill"
BACKFILL_HISTORY_RELATIVE_PATH = Path("data") / "derived" / "score_history_backfill.parquet"
BACKFILL_ELIGIBILITY_RELATIVE_PATH = Path("data") / "derived" / "score_history_backfill_eligibility.parquet"
BACKFILL_MANIFEST_RELATIVE_PATH = Path("data") / "derived" / "score_history_backfill_manifest.json"


def backfill_history_path(root: Path) -> Path:
    return Path(root) / BACKFILL_HISTORY_RELATIVE_PATH


def load_backfill_score_history(root: Path) -> pd.DataFrame:
    """The backfill store, restricted to rows that carry the ``historical_backfill`` provenance (fail closed otherwise)."""

    path = backfill_history_path(root)
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if frame.empty or "provenance" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["provenance"].astype(str).eq(BACKFILL_PROVENANCE)].reset_index(drop=True)


def load_backfill_eligibility(root: Path) -> pd.DataFrame:
    path = Path(root) / BACKFILL_ELIGIBILITY_RELATIVE_PATH
    return pd.read_parquet(path) if path.is_file() else pd.DataFrame()


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
    "backfill_history_path",
    "load_backfill_eligibility",
    "load_backfill_manifest",
    "load_backfill_score_history",
    "write_backfill_store",
]
