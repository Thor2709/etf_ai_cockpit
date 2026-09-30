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


def test_source_dashboard_refresh_analyse_score_and_export_journey(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    from etf_cockpit.app.state import AppState
    from etf_cockpit.chatgpt_bridge import export_pack
    from etf_cockpit.core.config import ProviderSection
    from etf_cockpit.data import import_pipeline, trade_candidate_analysis
    from etf_cockpit.data.providers import ProviderResult
    from etf_cockpit.services import build_snapshot
    import etf_cockpit.services as services_module

    events: list[str] = []
    snapshot = build_snapshot()

    class OfflineYFinance:
        def __init__(
            self,
            section: ProviderSection | None = None,
            default_currency: str | None = None,
            config=None,
        ) -> None:
            self.section = section or ProviderSection()
            self.config = config

        @classmethod
        def from_config(cls, config):
            return cls(config.data_providers.section("prices"), config=config)

        def fetch_prices(self, _symbols, _start, end):
            instruments = (
                list(self.section.symbols_map)
                if self.section.symbols_map
                else [item.id for item in self.config.universe.etfs]
            )
            dates = pd.bdate_range(end=pd.Timestamp(end), periods=260)
            rows = []
            for instrument_id in instruments:
                for index, day in enumerate(dates):
                    close = 100.0 + index * 0.1
                    rows.append(
                        {
                            "etf_id": instrument_id,
                            "date": day,
                            "open": close,
                            "high": close + 0.2,
                            "low": close - 0.2,
                            "close": close,
                            "adjusted_close": close,
                            "volume": 1000,
                            "currency": "USD",
                        }
                    )
            return ProviderResult(
                "yfinance",
                "prices",
                "ok",
                "Synthetic offline price fixture.",
                pd.DataFrame(rows),
            )

        def fetch_etf_metadata(self, _isins):
            return ProviderResult("yfinance", "etf_metadata", "unavailable", "No synthetic metadata fixture.")

        def fetch_etf_holdings(self, _isins):
            return ProviderResult("yfinance", "etf_holdings", "unavailable", "No synthetic holdings fixture.")

    monkeypatch.setattr(services_module, "YFinanceProvider", OfflineYFinance)
    monkeypatch.setattr(trade_candidate_analysis, "YFinanceProvider", OfflineYFinance)
    monkeypatch.setattr(services_module.DataService, "_reference_context", lambda _self: {
        "known_etfs": [], "isin_to_etf_id": {}, "ticker_to_etf_id": {}
    })
    monkeypatch.setattr(
        services_module,
        "commit_price_import",
        lambda result: import_pipeline.commit_price_import(
            result,
            clean_path=tmp_path / "clean" / "prices.parquet",
            compatibility_path=tmp_path / "clean" / "prices_compat.parquet",
            raw_dir=tmp_path / "raw" / "prices",
            snapshots_dir=tmp_path / "snapshots" / "prices",
        ),
    )
    candidate_path = tmp_path / "candidates.csv"
    pd.DataFrame([{"instrument_id": "SYNTH", "yahoo_symbol": "SYNTH"}]).to_csv(candidate_path, index=False)
    monkeypatch.setattr(trade_candidate_analysis, "latest_candidate_input", lambda: candidate_path)
    monkeypatch.setattr(trade_candidate_analysis, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        trade_candidate_analysis,
        "fetch_candidate_fundamentals",
        lambda candidates: pd.DataFrame(columns=["instrument_id"]).assign(
            instrument_id=candidates["instrument_id"].astype(str)
        ),
    )
    monkeypatch.setattr(state_module, "ACTIVITY_LOG_PATH", tmp_path / "logs" / "activity.jsonl")
    monkeypatch.setattr(state_module, "build_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(export_pack, "CHATGPT_EXPORTS_DIR", tmp_path / "exports")
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    monkeypatch.setattr(state, "_write_current_scoreboard", lambda: tmp_path / "scoreboard.csv")

    original_refresh = state.refresh_yfinance_data
    original_analyse = state.run_algorithm_scores
    original_export = state.export_audit_packet

    def refresh() -> str:
        events.append("refresh")
        return original_refresh()

    def analyse() -> str:
        events.append("analyse")
        return original_analyse()

    def export():
        events.append("report/export")
        return original_export()

    monkeypatch.setattr(state, "refresh_yfinance_data", refresh)
    monkeypatch.setattr(state, "run_algorithm_scores", analyse)
    monkeypatch.setattr(state, "export_audit_packet", export)
    page = SimpleNamespace(route="/", update=lambda: None)

    def run_action(_page, _state, _label, action) -> None:
        action()

    monkeypatch.setattr(dashboard, "_run_action", run_action)
    monkeypatch.setattr(dashboard, "_go_to", lambda _page, _state, route: events.append(f"score:{route}"))
    monkeypatch.setattr(
        dashboard,
        "_export_pack",
        lambda _page, target: target.export_audit_packet(),
    )

    workflow = dashboard._action_bar(page, state)
    secondary = dashboard._secondary_actions(page, state)
    for root, key in (
        (workflow, "dashboard.refresh-yfinance"),
        (workflow, "dashboard.run-algorithms"),
        (workflow, "dashboard.show-scores"),
        (secondary, "dashboard.export-audit"),
    ):
        _control_by_key(root, key).on_click(None)
    deadline = time.monotonic() + 15
    while state.current_activity is not None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert events == ["refresh", "analyse", "score:/signals", "report/export"]
    assert (tmp_path / "clean" / "prices.parquet").is_file()
    report_path = next((tmp_path / "reports").glob("yfinance_trade_candidate_analysis_*.csv"))
    scores = pd.read_csv(report_path)
    assert scores["instrument_id"].tolist() == ["SYNTH"]
    assert scores["technical_score"].notna().all()
    assert state.last_export_path is not None and state.last_export_path.is_file()
    from zipfile import ZipFile

    with ZipFile(state.last_export_path) as export_file:
        assert "01_portfolio_summary.json" in export_file.namelist()


def test_portfolio_import_and_reconcile_source_controls(monkeypatch, tmp_path: Path) -> None:
    from contextlib import nullcontext
    from datetime import datetime, timedelta, timezone

    from etf_cockpit.app.pages import import_export as import_export_module
    from etf_cockpit.data.contracts import SourceAuthority
    from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow

    monkeypatch.setattr(import_export_module, "ROOT", tmp_path)
    identity = IdentitySourceRow(
        row_id="identity-SEC-1",
        instrument_id="SEC-1",
        object_type="instrument",
        object_id="SEC-1",
        parent_object_id=None,
        relationship=None,
        identifiers={"isin": "US0000000001"},
        attributes={"ticker": "SEC-1", "exchange": "XNAS", "currency": "USD"},
        source="fixture",
        authority=SourceAuthority.OFFICIAL,
        source_id="fixture:SEC-1",
        valid_from="2020-01-01T00:00:00Z",
        available_at="2020-01-01T00:00:00Z",
    )
    with IdentityMasterStore(tmp_path) as identity_store:
        identity_store.import_rows((identity,))
    source_path = tmp_path / "portfolio.csv"
    pd.DataFrame(
        [
            {
                "Transaction Type": "BUY",
                "Trade ID": "broker-100",
                "Trade Date": "2024-01-02T10:00:00Z",
                "Account Number": "BROKER-A",
                "Symbol": "SEC-1",
                "ISIN": "US0000000001",
                "Currency": "USD",
                "Units": 3,
                "Price": 100,
                "Commission Amount": -3,
                "Net Amount": -303,
            }
        ]
    ).to_csv(source_path, index=False)

    class FilePicker:
        def __init__(self, **_kwargs) -> None:
            pass

        async def pick_files(self, **_kwargs):
            return [SimpleNamespace(path=str(source_path), name="portfolio.csv")]

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

    monkeypatch.setattr(import_export_module.ft, "FilePicker", FilePicker)
    monkeypatch.setattr(import_export_module, "_refresh_activity_shell", lambda *_args: None)
    page = SimpleNamespace(services=[], overlay=[], update=lambda: None)
    view = import_export_module.import_export_page(page, State())

    asyncio.run(_control_by_key(view, "import-export.import").on_click(None))
    assert "Preview valid: 1 rows" in _control_by_key(view, "import-export.preview-status").value
    _control_by_key(view, "import-export.commit").on_click(None)
    known_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    _control_by_key(view, "import-export.portfolio-known-at").value = known_at
    _control_by_key(view, "import-export.portfolio-reconcile").on_click(None)

    assert "source matched=" in _control_by_key(view, "import-export.portfolio-reconciliation-status").value
    assert "source matched=0/1" in _control_by_key(view, "import-export.portfolio-reconciliation-status").value
    assert "balanced=True" in _control_by_key(view, "import-export.portfolio-reconciliation-status").value


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
