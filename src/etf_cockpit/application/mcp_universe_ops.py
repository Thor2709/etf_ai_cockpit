"""Application operations for MCP universe search, staging and import.

Open defaults: universe pages contain 25 records; bulk imports accept the
existing local CSV/XLSX/paste formats and never call identity providers.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.savings_bank_universe import missing_savings_banks, sync as sync_savings_banks
from etf_cockpit.data.universe_import import (
    build_universe_manifest,
    dry_run_universe_import,
    save_universe_manifest,
)
from etf_cockpit.data.universe_store import (
    UniverseRecord,
    add_record,
    disable_record,
    edit_record,
    load_universe,
    save_universe,
    validate_universe,
)


def universe_snapshot() -> dict[str, object]:
    snapshot = load_universe(Path(ROOT))
    return {"records": snapshot.records, "revision": snapshot.revision, "integrity_errors": snapshot.integrity_errors}


def preview_universe_change(
    action: str,
    instrument_id: str | None = None,
    fields: Mapping[str, object] | None = None,
    *,
    expected_revision: str | None = None,
) -> dict[str, object]:
    snapshot = load_universe(Path(ROOT))
    if expected_revision is not None and expected_revision != snapshot.revision:
        raise ValueError("universe revision changed; request a fresh preview")
    if snapshot.integrity_errors:
        raise ValueError("universe integrity errors block edits")
    values = dict(fields or {})
    if action == "add":
        if not isinstance(instrument_id, str) or not instrument_id.strip():
            instrument_id = str(values.get("instrument_id") or "")
        values.setdefault("instrument_id", instrument_id)
        record = UniverseRecord(**values)
        candidate = add_record(snapshot.records, record, allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates)
    elif action == "edit":
        if not instrument_id:
            raise ValueError("instrument_id is required for edit")
        candidate = edit_record(snapshot.records, instrument_id, allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates, **values)
    elif action == "disable":
        if not instrument_id:
            raise ValueError("instrument_id is required for disable")
        candidate = disable_record(snapshot.records, instrument_id, allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates)
    elif action == "enable":
        if not instrument_id:
            raise ValueError("instrument_id is required for enable")
        candidate = edit_record(snapshot.records, instrument_id, allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates, enabled=True)
    else:
        raise ValueError("action must be add, edit, disable, or enable")
    report = validate_universe(candidate, allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates)
    before = {item.instrument_id: asdict(item) for item in snapshot.records}
    after = {item.instrument_id: asdict(item) for item in candidate}
    changed = [
        {"instrument_id": key, "before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)
    ]
    return {"action": action, "changes": changed, "valid": report.valid, "errors": list(report.errors), "warnings": list(report.warnings), "expected_revision": snapshot.revision}


def commit_universe_change(
    action: str,
    instrument_id: str | None = None,
    fields: Mapping[str, object] | None = None,
    *,
    expected_revision: str | None = None,
) -> dict[str, object]:
    preview = preview_universe_change(action, instrument_id, fields, expected_revision=expected_revision)
    if not preview["valid"]:
        raise ValueError("universe validation failed")
    revision = str(preview["expected_revision"])
    snapshot = load_universe(Path(ROOT))
    values = dict(fields or {})
    if action == "add":
        resolved_id = instrument_id or str(values.get("instrument_id") or "")
        values.setdefault("instrument_id", resolved_id)
        candidate = add_record(snapshot.records, UniverseRecord(**values), allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates)
    elif action == "edit":
        candidate = edit_record(snapshot.records, str(instrument_id or ""), allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates, **values)
    elif action == "disable":
        candidate = disable_record(snapshot.records, str(instrument_id or ""), allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates)
    else:
        candidate = edit_record(snapshot.records, str(instrument_id or ""), allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates, enabled=True)
    result = save_universe(candidate, revision, root=Path(ROOT), allow_cross_tier_duplicates=snapshot.allow_cross_tier_duplicates, policy_profiles=snapshot.policy_profiles)
    return {"revision": result.revision, "backup_path": str(result.backup_path), "instrument_id": instrument_id, "execution_allowed": False}


def lookup_instrument_view(identifier: str) -> dict[str, object]:
    from etf_cockpit.application.stock_service import lookup_instrument, universe_values

    resolution = lookup_instrument(identifier)
    current = load_universe(Path(ROOT))
    values = universe_values(resolution, [item.instrument_id for item in current.records])
    return {"resolution": resolution, "chosen": getattr(resolution, "chosen", None), "in_universe": bool(values.get("in_universe", False)), "proposed_fields": values}


def identity_view(instrument_id: str) -> dict[str, object]:
    from etf_cockpit.application.identity_views import load_classification_projection, load_identity_projection
    from etf_cockpit.application.market_clock import build_market_clock_diagnostics

    identity = load_identity_projection(instrument_id, storage_root=Path(ROOT), universe_root=Path(ROOT))
    classification = load_classification_projection(instrument_id, storage_root=Path(ROOT), universe_root=Path(ROOT))
    clock = build_market_clock_diagnostics(identity, decision_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    return {"identity": identity, "classification": classification, "membership": {"in_universe": instrument_id in {item.instrument_id for item in load_universe(Path(ROOT)).records}}, "market_clock": clock}


def preview_universe_import(
    source: object,
    *,
    source_kind: str | None = None,
    provider_name: str = "",
    correction_overlays: Mapping[int | str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    if source == "savings_bank_gap":
        rows = missing_savings_banks(Path(ROOT))
        return {"source_kind": "savings_bank_gap", "candidates": rows, "errors": [], "valid": bool(rows), "expected_revision": load_universe(Path(ROOT)).revision}
    report = dry_run_universe_import(source, source_kind=source_kind, provider_name=provider_name, correction_overlays=correction_overlays)
    manifest = build_universe_manifest(report)
    return {
        "source_kind": report.source_kind,
        "source_name": report.source_name,
        "source_checksum": report.source_checksum,
        "source_rows": len(report.source_rows),
        "candidates": report.records,
        "errors": report.errors,
        "warnings": report.warnings,
        "valid": report.valid,
        "manifest_id": manifest.manifest_id,
        "expected_revision": load_universe(Path(ROOT)).revision,
    }


def commit_universe_import(
    source: object,
    *,
    source_kind: str | None = None,
    provider_name: str = "",
    correction_overlays: Mapping[int | str, Mapping[str, object]] | None = None,
    expected_revision: str | None = None,
) -> dict[str, object]:
    if source == "savings_bank_gap":
        saved = sync_savings_banks(Path(ROOT), apply=True)
        return {"manifest": None, "save_result": {"records_saved": len(saved)}, "execution_allowed": False}
    current = load_universe(Path(ROOT))
    if expected_revision is not None and expected_revision != current.revision:
        raise ValueError("universe revision changed; request a fresh preview")
    report = dry_run_universe_import(source, source_kind=source_kind, provider_name=provider_name, correction_overlays=correction_overlays)
    if not report.valid or not report.records:
        raise ValueError("universe import has errors or no resolved candidates")
    manifest = build_universe_manifest(report)
    ids = {item.instrument_id.casefold() for item in current.records}
    candidates = tuple(item for item in report.records if item.instrument_id.casefold() not in ids)
    if not candidates:
        raise ValueError("universe import contains no new instruments")
    combined = add_record(current.records, candidates[0], allow_cross_tier_duplicates=current.allow_cross_tier_duplicates)
    for record in candidates[1:]:
        combined = add_record(combined, record, allow_cross_tier_duplicates=current.allow_cross_tier_duplicates)
    save_result = save_universe(combined, current.revision, root=Path(ROOT), allow_cross_tier_duplicates=current.allow_cross_tier_duplicates, policy_profiles=current.policy_profiles)
    manifest_result = save_universe_manifest(manifest, root=Path(ROOT))
    return {"manifest": manifest_result, "save_result": save_result, "execution_allowed": False}


__all__ = [
    "commit_universe_change", "commit_universe_import", "identity_view", "lookup_instrument_view",
    "preview_universe_change", "preview_universe_import", "universe_snapshot",
]
