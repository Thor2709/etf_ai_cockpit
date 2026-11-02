"""Application facades for the MCP data views and writes.

Open defaults: data health is as of today with a three-day staleness threshold;
price imports default to the canonical ``prices`` dataset. Every path is local
and every operation uses the same services as the application.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

from etf_cockpit.application.data_readiness import evaluate_readiness, load_inputs, load_thresholds
from etf_cockpit.application.data_service import DataService
from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.health import build_data_health, filter_data_health_rows
from etf_cockpit.data.provider_registry import ProviderRegistry


def _config(root: Path | None):
    return load_config(Path(root) / "configs") if root is not None else load_config()


def _storage_config(root: Path | None):
    # DataService stores bind at process startup. Refuse
    # a different session root rather than read or write another owner's store.
    if root is not None:
        from etf_cockpit.application.headless_session import require_storage_root

        require_storage_root(root)
    return _config(root)


def data_health_view(*, root: Path | None = None, dataset: str | None = None, stale_after_days: int = 3) -> dict[str, object]:
    report = build_data_health(_config(root), Path(root or ROOT), stale_after_days=stale_after_days)
    rows = filter_data_health_rows(report, dataset=dataset)
    as_of = getattr(report, "as_of_date", None)
    return {"as_of": as_of, "rows": rows, "unavailable": as_of is None or not bool(rows)}


def data_provider_status_view(*, root: Path | None = None, probe: bool = False) -> tuple[dict[str, object], ...]:
    registry = ProviderRegistry(_config(root).data_providers)
    if probe:
        return registry.status_rows(registry.probe_all())
    # The default path reports configured capabilities only. It does not invoke provider probes.
    from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority

    capabilities = []
    for dataset, section in sorted(registry.config.providers.items()):
        provider = str(section.active_provider or "none").strip().lower()
        configured = provider not in {"", "none"}
        authority = SourceAuthority.OFFICIAL if provider in {"sec_edgar", "filings_xbrl_org", "index_provider"} else SourceAuthority.VENDOR
        capabilities.append(
            ProviderCapability(
                provider_id=provider if configured else str(dataset),
                dataset_type=str(dataset),
                status="unavailable",
                authority=authority,
                configured=configured,
                entitlement="not_probed" if configured else "disabled",
                rate_limit_note="probe not run",
                last_success_at=None,
                error_fingerprint=None,
                secret_present=bool(str(section.api_key or "").strip()),
                message="Capability probe not run." if configured else "Provider disabled by configuration.",
            )
        )
    return registry.status_rows(capabilities)


def validate_prices_view(*, root: Path | None = None) -> dict[str, object]:
    report = DataService(_storage_config(root)).validate_prices()
    return {
        "status": report.status,
        "analysis_allowed": report.analysis_allowed,
        "as_of_date": report.as_of_date,
        "issues": [asdict(issue) for issue in report.issues],
        "dataset_metadata": [asdict(item) for item in report.dataset_metadata],
        "unavailable_reason": "stored price data unavailable" if report.status == "Unavailable" else None,
    }


def data_readiness_view(start: date, end: date, *, every: int | None = None, root: Path | None = None) -> dict[str, object]:
    report = evaluate_readiness(load_inputs(Path(root or ROOT)), start, end, load_thresholds(Path(root) / "configs" / "data_readiness_v1.yaml") if root is not None else load_thresholds(), every=every)
    return {"summary": report.summary(), "failed_dates": report.failed_dates(), "interval": report.interval}


def preview_local_import(path: Path, dataset_type: str = "prices", *, root: Path | None = None) -> dict[str, object]:
    result = DataService(_storage_config(root)).import_local_file(Path(path), dataset_type, commit=False)
    data = result.data
    rows = len(data) if isinstance(data, pd.DataFrame) else None
    columns = list(data.columns) if isinstance(data, pd.DataFrame) else None
    return {
        "status": result.status,
        "dataset_type": dataset_type,
        "provider": result.provider_name,
        "rows": rows,
        "columns": columns,
        "message": result.message,
        "valid": bool(result.ok and data is not None),
        "execution_allowed": False,
    }


def commit_local_import(path: Path, dataset_type: str = "prices", *, root: Path | None = None) -> dict[str, object]:
    result = DataService(_storage_config(root)).import_local_file(Path(path), dataset_type, commit=True)
    return {"status": result.status, "dataset_type": dataset_type, "provider": result.provider_name, "message": result.message, "execution_allowed": False}


def rollback_preview(*, root: Path | None = None) -> dict[str, object]:
    from etf_cockpit.data.import_pipeline import SNAPSHOTS_DIR

    config = _storage_config(root)
    candidates = sorted((SNAPSHOTS_DIR / "prices").glob("*_previous_*.parquet"), key=lambda item: item.name)
    if not candidates:
        return {"available": False, "unavailable_reason": "No previous clean price snapshot is available to roll back."}
    frame = pd.read_parquet(candidates[-1])
    validation = DataService(config).validate_prices(frame)
    return {
        "available": True,
        "snapshot_name": candidates[-1].name,
        "rows": len(frame),
        "validation_status": validation.status,
        "analysis_allowed": validation.analysis_allowed,
    }


def rollback_prices(*, root: Path | None = None) -> str:
    # This is the canonical restore operation; preview is performed before it by MCP dispatch.
    return DataService(_storage_config(root)).rollback_latest_price_import()


def backfill_score_history(start: date, end: date, *, every: int = 5, workers: int = 1, force: bool = False, root: Path | None = None) -> object:
    from etf_cockpit.application.score_backfill import backfill_score_history as run_backfill

    return run_backfill(Path(root or ROOT), start, end, every=every, workers=workers, force=force)


__all__ = [
    "backfill_score_history", "commit_local_import", "data_health_view", "data_provider_status_view",
    "data_readiness_view", "preview_local_import", "rollback_preview", "rollback_prices", "validate_prices_view",
]
