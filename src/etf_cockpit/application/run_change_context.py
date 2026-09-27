"""Report-level upstream context for comparing two score runs.

Per-instrument upstream reasons live in ``etf_cockpit.data.run_changes``.  This
module adds the run-wide reasons that are not stored on score rows:

* data corrections, read point-in-time from the bitemporal anomaly ledger at
  each run's own completion time, so a later correction cannot explain an
  earlier run;
* causal dependency changes, diffed from the two runs' immutable manifests;
* paper/order state, which is not snapshotted per score run.  Its journal
  records caller-supplied ``occurred_at`` values but no trustworthy append-time
  cutoff, so the comparison is explicitly unavailable and no current state is
  substituted.

Everything here is informational and never grants execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.anomaly_ledger import AnomalyLedger
from etf_cockpit.data.run_changes import run_completion_time


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
        "paper_state": _fail_closed(lambda: _paper_state(history, current_run_id, previous_run_id, base)),
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
    parsed = run_completion_time(history, run_id)
    return None if parsed is None else parsed.isoformat()


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
    try:
        from etf_cockpit.core.versioning import verify_run_manifest_signature

        path = root / "data" / "derived" / "run_manifests" / f"{run_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
        if (
            not isinstance(payload, dict)
            or not verify_run_manifest_signature(payload)
            or payload.get("run_id") != run_id
            or payload.get("schema_version") not in {"1.0", "1.1"}
        ):
            return None
        dependencies = payload.get("dependencies")
        if not isinstance(dependencies, list):
            return None
        result: dict[str, tuple[str, str]] = {}
        for item in dependencies:
            if not isinstance(item, Mapping):
                return None
            artifact_id = item.get("artifact_id")
            version = item.get("version")
            content_hash = item.get("content_hash")
            if not all(isinstance(value, str) and value.strip() for value in (artifact_id, version, content_hash)):
                return None
            if artifact_id in result:
                return None
            result[artifact_id] = (version, content_hash)
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


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


def _paper_state(
    _history: pd.DataFrame,
    _current_run_id: str | None,
    _previous_run_id: str | None,
    _root: Path,
) -> dict[str, object]:
    note = "Paper/order state is unavailable for run comparison because journal timestamps are caller-supplied and can be back-dated."
    return {
        "status": "unavailable",
        "comparison": "unavailable",
        "reason": "the append-only paper journal has occurred_at but no trustworthy recorded_at cutoff",
        "note": note,
    }
