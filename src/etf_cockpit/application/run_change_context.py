"""Report-level upstream context for comparing two score runs.

Per-instrument upstream reasons live in ``etf_cockpit.data.run_changes``.  This
module adds the run-wide reasons that are not stored on score rows:

* data corrections, read point-in-time from the bitemporal anomaly ledger at
  each run's own completion time, so a later correction cannot explain an
  earlier run;
* causal dependency changes, diffed from the two runs' immutable manifests;
* paper/order state, which is not snapshotted per score run.  Its journal can
  record back-dated events, so an as-of-run state cannot be reconstructed
  without look-ahead; only the current state is shown and the comparison is
  explicitly unavailable.

Everything here is informational and never grants execution authority.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.anomaly_ledger import AnomalyLedger


def upstream_run_context(
    history: pd.DataFrame,
    current_run_id: str | None,
    previous_run_id: str | None,
    *,
    root: Path | None = None,
) -> dict[str, object]:
    base = Path(root) if root is not None else ROOT
    return {
        "corrections": _fail_closed(lambda: _corrections(history, current_run_id, previous_run_id, base)),
        "dependencies": _fail_closed(lambda: _dependencies(current_run_id, previous_run_id, base)),
        "paper_state": _fail_closed(lambda: _paper_state(base)),
        "execution_allowed": False,
    }


def _fail_closed(section: Callable[[], dict[str, object]]) -> dict[str, object]:
    # Context is informational: any storage failure (including sqlite3
    # errors from a locked or damaged store) shows as unavailable instead of
    # breaking the What Changed page.
    try:
        return section()
    except Exception as exc:  # noqa: BLE001 - deliberate fail-closed boundary
        return {
            "status": "unavailable",
            "comparison": "unavailable",
            "reason": f"{type(exc).__name__}: context could not be read",
            "changed": False,
            "changed_artifacts": (),
        }


def _completed_at(history: pd.DataFrame, run_id: str | None) -> str | None:
    if not run_id or not isinstance(history, pd.DataFrame) or "run_id" not in history.columns:
        return None
    if "run_completed_at" not in history.columns:
        return None
    values = history.loc[history["run_id"].astype(str) == str(run_id), "run_completed_at"].dropna().astype(str)
    values = values[values.str.strip() != ""]
    if values.empty:
        return None
    parsed = pd.to_datetime(values.iloc[0], errors="coerce")
    # A knowledge-time cutoff needs an explicit timezone; a bare date or
    # naive time would be a guess, so it is treated as not recorded.
    if pd.isna(parsed) or parsed.tzinfo is None:
        return None
    return str(values.iloc[0])


def _readable(summary: Mapping[str, object]) -> bool:
    # The ledger reports counts whenever its store could be read, including a
    # clean run with zero findings; otherwise it returns only a reason.
    return "finding_count" in summary


def _corrections(
    history: pd.DataFrame,
    current_run_id: str | None,
    previous_run_id: str | None,
    root: Path,
) -> dict[str, object]:
    current_time = _completed_at(history, current_run_id)
    previous_time = _completed_at(history, previous_run_id)
    if current_time is None or previous_time is None:
        return {
            "status": "unavailable",
            "reason": "a run completion time with timezone is not recorded, so corrections cannot be read point-in-time",
            "changed": False,
        }
    ledger = AnomalyLedger()
    try:
        current = ledger.summary(root=root, decision_time=current_time)
        previous = ledger.summary(root=root, decision_time=previous_time)
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: anomaly ledger unreadable", "changed": False}
    if not (_readable(current) and _readable(previous)):
        unreadable = current if not _readable(current) else previous
        return {
            "status": "unavailable",
            "reason": str(unreadable.get("reason") or "anomaly ledger could not be read"),
            "changed": False,
        }
    return {
        "status": "available",
        "changed": current.get("invalidation_token") != previous.get("invalidation_token"),
        "current_corrections": current.get("correction_count"),
        "previous_corrections": previous.get("correction_count"),
        "current_unresolved": current.get("unresolved_count"),
        "previous_unresolved": previous.get("unresolved_count"),
    }


def _manifest_dependencies(run_id: str, root: Path) -> dict[str, tuple[object, object]] | None:
    path = root / "data" / "derived" / "run_manifests" / f"{run_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    dependencies = payload.get("dependencies") if isinstance(payload, Mapping) else None
    if not isinstance(dependencies, list):
        return None
    return {
        str(item.get("artifact_id")): (item.get("version"), item.get("content_hash"))
        for item in dependencies
        if isinstance(item, Mapping) and item.get("artifact_id")
    }


def _dependencies(current_run_id: str | None, previous_run_id: str | None, root: Path) -> dict[str, object]:
    if not current_run_id or not previous_run_id:
        return {"status": "unavailable", "reason": "no previous run to compare", "changed_artifacts": ()}
    current = _manifest_dependencies(str(current_run_id), root)
    previous = _manifest_dependencies(str(previous_run_id), root)
    if current is None or previous is None:
        return {
            "status": "unavailable",
            "reason": "a run manifest is missing or unreadable",
            "changed_artifacts": (),
        }
    changed = []
    for artifact_id in sorted(set(current) | set(previous)):
        if artifact_id not in previous:
            changed.append(f"{artifact_id}: added")
        elif artifact_id not in current:
            changed.append(f"{artifact_id}: removed")
        elif current[artifact_id] != previous[artifact_id]:
            old_version, _old_hash = previous[artifact_id]
            new_version, _new_hash = current[artifact_id]
            detail = f"version {old_version} -> {new_version}" if old_version != new_version else "content changed"
            changed.append(f"{artifact_id}: {detail}")
    return {"status": "available", "changed_artifacts": tuple(changed)}


def _paper_state(root: Path) -> dict[str, object]:
    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError

    note = (
        "Paper/order state is not snapshotted per score run and its journal can hold back-dated events, "
        "so a run-to-run comparison is unavailable; the current local paper state is shown for context."
    )
    try:
        ledger = PaperLedger(root)
        if not ledger.path.exists():
            return {"status": "unavailable", "comparison": "unavailable", "reason": "no local paper ledger", "note": note}
        orders = ledger.orders()
    except (OSError, PaperLedgerError, ValueError) as exc:
        return {"status": "unavailable", "comparison": "unavailable", "reason": f"{type(exc).__name__}: paper ledger unreadable", "note": note}
    counts = Counter(str(order.get("status", "unknown")) for order in orders)
    open_instruments = sorted(
        {
            str(order.get("instrument_id"))
            for order in orders
            if order.get("status") not in {"filled", "cancelled"} and order.get("instrument_id")
        }
    )
    return {
        "status": "current_only",
        "comparison": "unavailable",
        "order_counts": dict(sorted(counts.items())),
        "open_order_instruments": tuple(open_instruments),
        "note": note,
    }
