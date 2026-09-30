"""Deterministic source-build journey and soak checks for ISSUE-0143.

The decision packet sets the soak budget at no more than 1 MiB of retained
tracemalloc growth and two additional process handles; see ISSUE-0143's
acceptance contract. The iteration count is fixed so the test stays bounded.
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import os
from pathlib import Path
import time
import tracemalloc
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.app.pages import dashboard
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.ui_acceptance import (
    load_ui_acceptance_contracts,
    validate_ui_acceptance_inventory,
)
from etf_cockpit.app.router import PAGES


MAX_TRACEMALLOC_GROWTH_BYTES: int = 1024 * 1024
MAX_ADDITIONAL_OPEN_HANDLES: int = 2
SOAK_ITERATIONS: int = 50


def _walk_controls(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)


def _control_by_key(root: object, key: str) -> object:
    return next(control for control in _walk_controls(root) if getattr(control, "key", None) == key)


def _count_open_handles() -> int:
    if os.name == "nt":
        from ctypes import wintypes

        count = ctypes.c_ulong(0)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_count = kernel32.GetProcessHandleCount
        get_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulong)]
        get_count.restype = wintypes.BOOL
        if not get_count(get_current_process(), ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(count.value)
    return len(list(Path("/proc/self/fd").iterdir()))


def test_source_dashboard_refresh_analyse_score_and_export_journey(monkeypatch) -> None:
    events: list[str] = []

    class JourneyState:
        last_message = "Ready"

        def refresh_yfinance_data(self) -> str:
            events.append("refresh")
            return "refreshed"

        def run_algorithm_scores(self) -> str:
            events.append("analyse")
            return "analysed"

        def export_audit_packet(self) -> str:
            events.append("report/export")
            return "exported"

    state = JourneyState()
    page = SimpleNamespace()

    def run_action(_page, _state, _label, action) -> None:
        action()

    monkeypatch.setattr(dashboard, "_run_action", run_action)
    monkeypatch.setattr(dashboard, "_go_to", lambda _page, _state, route: events.append(f"score:{route}"))
    monkeypatch.setattr(dashboard, "_export_pack", lambda _page, target: target.export_audit_packet())

    workflow = dashboard._action_bar(page, state)
    secondary = dashboard._secondary_actions(page, state)
    for root, key in (
        (workflow, "dashboard.refresh-yfinance"),
        (workflow, "dashboard.run-algorithms"),
        (workflow, "dashboard.show-scores"),
        (secondary, "dashboard.export-audit"),
    ):
        _control_by_key(root, key).on_click(None)

    assert events == ["refresh", "analyse", "score:/signals", "report/export"]


def test_portfolio_import_and_reconcile_source_controls(monkeypatch, tmp_path: Path) -> None:
    from contextlib import nullcontext

    from etf_cockpit.app.pages import import_export as import_export_module

    events: list[str] = []
    preview = SimpleNamespace(
        valid=True,
        rows=1,
        errors=(),
        import_type="portfolio_history",
        preview_id="preview-fixture",
        frame=pd.DataFrame(),
    )
    replay = SimpleNamespace(
        positions=(),
        cash=(),
        trial_balance=(),
        trial_balance_balanced=True,
        missing_lot_identity=(),
        fx_conversions=(),
    )
    reconciliation = SimpleNamespace(
        discrepancies=(),
        replay=replay,
        matched_source_rows=1,
        active_source_rows=1,
    )

    class PortfolioImports:
        def __init__(self, _root) -> None:
            pass

        def preview(self, *_args, **_kwargs):
            events.append("preview")
            return preview

        def commit(self, _preview):
            events.append("import")
            return SimpleNamespace(status="accepted", batch_id="batch-fixture", accepted=1, quarantined=0, duplicates=0, corrections=0)

        def reconcile(self, **_kwargs):
            events.append("reconcile")
            return reconciliation

    class FilePicker:
        def __init__(self, **_kwargs) -> None:
            pass

        async def pick_files(self, **_kwargs):
            return [SimpleNamespace(path=str(tmp_path / "portfolio.csv"), name="portfolio.csv")]

    class State:
        current_activity = None
        last_message = "Ready"

        def begin_activity(self, _label, _step):
            return SimpleNamespace(action_id="activity-fixture")

        def activity_publication(self, _action_id):
            return nullcontext()

        def update_activity(self, *_args, **_kwargs):
            pass

        def finish_activity(self, *_args, **_kwargs):
            pass

        def activity_was_cancelled(self, _action_id):
            return False

        def fail_activity(self, _label, exc, **_kwargs):
            raise exc

        def restore_cancelled_activity_message(self, _action_id):
            return None

        def release_activity(self, _action_id):
            pass

    monkeypatch.setattr(import_export_module, "PortfolioImportApplication", PortfolioImports)
    monkeypatch.setattr(import_export_module.ft, "FilePicker", FilePicker)
    monkeypatch.setattr(import_export_module, "bulk_cache_health", lambda _root: {
        "status": "ok",
        "object_count": 0,
        "manifest_count": 0,
        "staged_file_count": 0,
        "promoted_generation_count": 0,
    })
    monkeypatch.setattr(import_export_module, "_refresh_activity_shell", lambda *_args: None)
    page = SimpleNamespace(services=[], overlay=[], update=lambda: None)
    view = import_export_module.import_export_page(page, State())

    asyncio.run(_control_by_key(view, "import-export.import").on_click(None))
    _control_by_key(view, "import-export.commit").on_click(None)
    _control_by_key(view, "import-export.portfolio-reconcile").on_click(None)

    assert events == ["preview", "import", "reconcile"]
    assert "Canonical replay: 0 positions" in _control_by_key(view, "import-export.portfolio-reconciliation-status").value


def test_settings_page_previews_and_saves_local_settings(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app.pages import settings as settings_module
    from etf_cockpit.core.config import load_config

    config = load_config()
    monkeypatch.setattr(settings_module, "ROOT", tmp_path)
    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / "configs")
    monkeypatch.setattr(settings_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings_module, "load_config", lambda: config)
    monkeypatch.setattr(settings_module, "load_product_governance", lambda: SimpleNamespace(
        policy=SimpleNamespace(product=SimpleNamespace(canonical_name="fixture"))
    ))
    monkeypatch.setattr(settings_module, "load_authority_matrix", lambda: SimpleNamespace(
        policy=SimpleNamespace(adr_id="fixture", capabilities=()), checksum="fixture"
    ))
    monkeypatch.setattr(settings_module, "describe_release_evidence", lambda _root: {
        "verification": "available", "version": "fixture", "notices": "available", "notices_path": "notices"
    })
    monkeypatch.setattr(settings_module, "legal_terms_report", lambda _root: {
        "status": "available", "review_status": "reviewed", "registry_sha256": "fixture"
    })
    monkeypatch.setattr(settings_module, "supply_chain_intake_report", lambda _root: {
        "status": "available", "review_status": "reviewed", "component_count": 0,
        "dependency_count": 0, "registry_sha256": "fixture", "third_party_notices": "available"
    })
    monkeypatch.setattr(settings_module, "read_changelog_excerpt", lambda _root: "fixture")
    monkeypatch.setattr(settings_module, "read_rebuild_timestamp", lambda _root: "fixture")

    class Vault:
        def status(self):
            return {"status": "unavailable", "reason": "test fixture"}

    monkeypatch.setattr(settings_module, "CredentialVault", Vault)
    state = SimpleNamespace(snapshot=SimpleNamespace(config=config), last_message="Ready")
    view = settings_module.settings_page(SimpleNamespace(update=lambda: None), state)

    _control_by_key(view, "settings.risk-profile").value = "safe"
    _control_by_key(view, "settings.preview").on_click(None)
    _control_by_key(view, "settings.save").on_click(None)

    saved = settings_module.load_settings_bundle(tmp_path)
    assert saved.controls.risk_profile == "safe"
    assert (tmp_path / "configs" / "settings.yaml").is_file()


def test_bounded_file_guard_soak_stays_within_memory_and_handle_budgets(tmp_path: Path) -> None:
    guard_path = tmp_path / ".persistent.guard"
    handles_before = _count_open_handles()
    gc.collect()
    tracemalloc.start()
    before_bytes = tracemalloc.get_traced_memory()[0]
    started = time.monotonic()
    try:
        for _ in range(SOAK_ITERATIONS):
            with persistent_file_guard(guard_path, timeout_seconds=1):
                pass
        gc.collect()
        after_bytes = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    handles_after = _count_open_handles()

    assert after_bytes - before_bytes <= MAX_TRACEMALLOC_GROWTH_BYTES
    assert handles_after <= handles_before + MAX_ADDITIONAL_OPEN_HANDLES
    assert time.monotonic() - started < 60


def test_unreviewed_ui_contract_change_is_rejected() -> None:
    contracts = load_ui_acceptance_contracts()
    changed = tuple(
        contract.__class__(**{**contract.__dict__, "callback": "unreviewed_refresh"})
        if contract.key == "dashboard.refresh-yfinance"
        else contract
        for contract in contracts
    )

    with pytest.raises(ValueError, match="callback mismatch: dashboard.refresh-yfinance"):
        validate_ui_acceptance_inventory(
            changed,
            PAGES,
            source_root=Path(__file__).resolve().parents[1] / "src" / "etf_cockpit" / "app",
        )
