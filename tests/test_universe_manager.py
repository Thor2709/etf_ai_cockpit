from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import flet as ft
import pandas as pd
import pytest

import etf_cockpit.app.pages.universe_manager as manager
import etf_cockpit.app.pages.dashboard as dashboard
from etf_cockpit.app.pages.onboarding import overlay_universe_config
from etf_cockpit.app.pages.universe_manager import universe_manager_page
from etf_cockpit.app.state import AppState
from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.models.forecast_scores import load_latest_forecasts
from etf_cockpit.application.backtest_service import BacktestService
import etf_cockpit.application.backtest_service as backtest_service
from etf_cockpit.signals.simple_scores import _backtest_trust_lookup
from etf_cockpit.core.config import (
    AppConfig,
    CostConfig,
    ETFConfig,
    ModelSettings,
    PortfolioTargets,
    RiskLimits,
    UISettings,
    UniverseConfig,
)
from etf_cockpit.data.universe_store import (
    PolicyEvidence,
    UniverseRecord,
    UniverseSaveResult,
    UniverseStoreSnapshot,
)


class _Page:
    def __init__(self) -> None:
        self.overlay: list[ft.Control] = []
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


def _state() -> SimpleNamespace:
    config = AppConfig(
        universe=UniverseConfig(etfs=[ETFConfig(id="A", name="Alpha", ticker="A", role="core")]),
        targets=PortfolioTargets(),
        risks=RiskLimits(),
        costs=CostConfig(),
        models=ModelSettings(),
        ui=UISettings(),
        chatgpt_schema={},
    )
    return SimpleNamespace(snapshot=SimpleNamespace(config=config))


def _walk(control: ft.Control):
    if not isinstance(control, ft.Control):
        return
    yield control
    for attr in ("controls", "rows", "cells", "actions", "items"):
        values = getattr(control, attr, None)
        if values:
            for child in values:
                yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _keyed(root: ft.Control) -> dict[str, ft.Control]:
    """Every keyed control below ``root`` (kit buttons are containers, so no type filter)."""
    return {str(control.key): control for control in _walk(root) if control.key}


def _texts(root: ft.Control) -> str:
    return "\n".join(str(control.value) for control in _walk(root) if isinstance(control, ft.Text) and control.value)


def _fill(root: ft.Control, **values: str) -> None:
    keyed = _keyed(root)
    for name, value in values.items():
        keyed[name].value = value


def test_selected_universe_overlay_retains_non_default_risk_and_cost_config() -> None:
    active = _state().snapshot.config
    active.risks.signal_limits.min_confidence_for_buy = 0.91
    active.costs.cost_model.default_spread_bps = 17.0
    selected = active.model_copy(update={"universe": UniverseConfig(etfs=[])})

    merged = overlay_universe_config(active, selected)

    assert merged.universe.etfs == []
    assert merged.risks.signal_limits.min_confidence_for_buy == 0.91
    assert merged.costs.cost_model.default_spread_bps == 17.0


def test_real_crud_controls_stage_changes_and_save_captured_revision(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "captured-revision", Path("store.json")))
    saved: list[tuple[tuple[UniverseRecord, ...], str]] = []

    def fake_save(records, expected_revision, **_kwargs):
        rows = tuple(records)
        saved.append((rows, expected_revision))
        revision = f"revision-{len(saved)}"
        return UniverseSaveResult(Path("store.json"), revision, len(rows))

    monkeypatch.setattr(manager, "save_universe", fake_save)
    page = _Page()
    root = universe_manager_page(page, _state()).body
    controls = _keyed(root)
    assert {
        "universe.add",
        "universe.save",
        "universe.edit.A",
        "universe.identity.A",
        "universe.classification.A",
        "universe.enabled.A",
        "universe.remove.A",
    } <= set(controls)
    assert "universe.allow-cross-tier-duplicates" in controls
    label = next(control for control in _walk(root) if isinstance(control, ft.Text) and "cross-tier duplicate" in str(control.value))
    assert "ticker" in str(label.value).lower() and "verified isin" in str(label.value).lower()
    assert "instrument ids stay globally unique" in str(label.tooltip).lower()

    # The Enabled toggle and the add dialog use the real callbacks, and neither invokes a workflow service.
    assert controls["universe.enabled.A"].data["on"] is True
    controls["universe.enabled.A"].on_click(None)
    assert _keyed(root)["universe.enabled.A"].data["on"] is False
    _keyed(root)["universe.enabled.A"].on_click(None)
    assert _keyed(root)["universe.enabled.A"].data["on"] is True
    _keyed(root)["universe.add"].on_click(None)
    assert page.overlay
    dialog = page.overlay[-1]
    _fill(dialog, **{"universe.field.instrument_id": "B", "universe.field.name": "Beta", "universe.field.ticker": "B", "universe.field.isin": "NO0000000002", "universe.field.isin_status": "verified"})
    _keyed(dialog)["universe.field.enabled"].on_click(None)  # on -> off
    _keyed(dialog)["universe.add-save"].on_click(None)

    _keyed(root)["universe.save"].on_click(None)
    _keyed(root)["universe.save"].on_click(None)
    assert [revision for _rows, revision in saved] == ["captured-revision", "revision-1"]
    assert {row.instrument_id for row in saved[-1][0]} == {"A", "B"}
    assert next(row for row in saved[-1][0] if row.instrument_id == "B").enabled is False

    # Search and tier selection rebuild the one visible table.
    query = _keyed(root)["universe.search"]
    assert isinstance(query, ft.TextField)
    query.value = "Beta"
    query.on_change(None)
    tier = _keyed(root)["universe.tier"]
    assert [(option.key, option.text) for option in tier.options] == [
        ("all", "All tiers"),
        ("primary", "Primary"),
        ("secondary", "Secondary"),
        ("sparebanken", "Sparebanken"),
    ]
    tier.value = "secondary"
    tier.on_select(None)
    assert "universe.identity.B" in _keyed(root)


def test_import_wizard_dry_run_and_stage_are_local_only(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json")))
    manifests = []
    monkeypatch.setattr(manager, "save_universe_manifest", manifests.append)
    page = _Page()
    state = _state()
    state.workflow_calls = 0
    state.provider_calls = 0
    state.broker_calls = 0
    root = universe_manager_page(page, state).body

    _fill(root, **{"universe.import-paste": "ticker,name\nB,Beta\n", "universe.import-overlays": '{"1":{"canonical_id":"B"}}', "universe.import-chunk": "1"})
    _keyed(root)["universe.import"].on_click(None)  # Preview import: dry-run, then the preview dialog
    dialog = page.overlay[-1]

    rendered = _texts(dialog)
    assert "Dry-run: 1 source rows, 1 resolved" in rendered
    assert "execution_allowed=False" in rendered
    assert "Added" in rendered
    assert manifests == []
    _keyed(dialog)["universe.import-resume"].on_click(None)
    _keyed(dialog)["universe.import-stage"].on_click(None)

    assert len(manifests) == 1
    assert manifests[0].source_rows == ({"ticker": "B", "name": "Beta"},)
    assert manifests[0].correction_overlays == {1: {"canonical_id": "B"}}
    assert manifests[0].mapping_confidence == {1: "canonical_id"}
    assert state.workflow_calls == 0
    assert state.provider_calls == 0
    assert state.broker_calls == 0


def test_import_stage_does_not_mutate_live_records_when_manifest_save_fails(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json")))
    monkeypatch.setattr(manager, "save_universe_manifest", lambda _manifest: (_ for _ in ()).throw(ValueError("manifest save failed")))
    page = _Page()
    root = universe_manager_page(page, _state()).body
    _fill(root, **{"universe.import-paste": "canonical_id,name,ticker\nB,Beta,B\n", "universe.import-chunk": "1"})
    _keyed(root)["universe.import"].on_click(None)
    dialog = page.overlay[-1]
    buttons = _keyed(dialog)
    buttons["universe.import-resume"].on_click(None)
    buttons["universe.import-stage"].on_click(None)

    assert "universe.edit.B" not in _keyed(root)
    assert "manifest save failed" in _texts(dialog)


def test_import_wizard_pauses_resumes_and_cancel_never_stages_partial_rows(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json")))
    manifests = []
    monkeypatch.setattr(manager, "save_universe_manifest", manifests.append)
    page = _Page()
    state = _state()
    state.workflow_calls = 0
    state.provider_calls = 0
    state.broker_calls = 0
    root = universe_manager_page(page, state).body
    _fill(root, **{"universe.import-paste": "canonical_id,name,ticker\n" + "".join(f"B{index},Beta {index},B{index}\n" for index in range(5)), "universe.import-chunk": "2"})
    _keyed(root)["universe.import"].on_click(None)
    dialog = page.overlay[-1]
    buttons = _keyed(dialog)
    buttons["universe.import-resume"].on_click(None)
    progress = buttons["universe.import-progress"]
    assert progress.value == "Progress: 2/5 (paused)"
    buttons["universe.import-resume"].on_click(None)
    assert progress.value == "Progress: 4/5 (paused)"
    buttons["universe.import-cancel"].on_click(None)
    assert progress.value == "Progress: 4/5 (cancelled)"
    buttons["universe.import-resume"].on_click(None)
    buttons["universe.import-stage"].on_click(None)

    rendered = _texts(dialog)
    assert "Complete all import chunks before staging" in rendered
    assert manifests == []
    assert state.workflow_calls == 0
    assert state.provider_calls == 0
    assert state.broker_calls == 0


def test_override_checkbox_rehydrates_from_store_snapshot(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(
        manager,
        "load_universe",
        lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json"), True),
    )
    page = _Page()
    root = universe_manager_page(page, _state()).body
    toggle = _keyed(root)["universe.allow-cross-tier-duplicates"]
    assert toggle.data["on"] is True


def test_universe_table_distinguishes_policy_evidence_states(monkeypatch) -> None:
    records = tuple(
        UniverseRecord(
            instrument_id,
            instrument_id,
            f"NO000000000{index}",
            "verified",
            instrument_id,
            "stock",
            "primary",
        )
        for index, instrument_id in enumerate(
            ("CURRENT", "STALE", "LEGACY", "UNAVAILABLE", "REVIEW"),
            start=1,
        )
    )
    states = (
        PolicyEvidence("CURRENT", "current", "current policy", recompute_required=False),
        PolicyEvidence("STALE", "stale", "version changed"),
        PolicyEvidence("LEGACY", "legacy_unmigrated", "legacy profile"),
        PolicyEvidence("UNAVAILABLE", "unavailable", "no profile"),
        PolicyEvidence("REVIEW", "manual_review", "tampered profile"),
    )
    monkeypatch.setattr(
        manager,
        "load_universe",
        lambda *_args: UniverseStoreSnapshot(
            records,
            "revision",
            Path("store.json"),
            policy_evidence=states,
            schema_version=3,
        ),
    )

    root = universe_manager_page(_Page(), _state()).body
    rendered = _texts(root)
    assert rendered.count("Pending refresh") == 2  # stale and legacy_unmigrated
    assert rendered.count("Manual review") == 1  # manual_review
    tooltips = [str(control.tooltip) for control in _walk(root) if getattr(control, "tooltip", None)]
    for state, reason in (
        ("current", "current policy"),
        ("stale", "version changed"),
        ("legacy_unmigrated", "legacy profile"),
        ("unavailable", "no profile"),
        ("manual_review", "tampered profile"),
    ):
        assert any(f"Policy evidence: {state} · {reason}" in text for text in tooltips)


def test_universe_store_integrity_failure_is_visible_as_manual_review(
    monkeypatch,
) -> None:
    record = UniverseRecord(
        "A",
        "Alpha",
        "NO0000000001",
        "verified",
        "A",
        "stock",
        "primary",
    )
    monkeypatch.setattr(
        manager,
        "load_universe",
        lambda *_args: UniverseStoreSnapshot(
            (record,),
            "tampered-revision",
            Path("store.json"),
            policy_evidence=(
                PolicyEvidence("A", "manual_review", "store revision checksum mismatch"),
            ),
            schema_version=3,
            integrity_errors=("store revision checksum mismatch",),
        ),
    )

    monkeypatch.setattr(manager, "save_universe", lambda *_args, **_kwargs: pytest.fail("invalid snapshot reached save"))
    root = universe_manager_page(_Page(), _state()).body
    rendered = _texts(root)

    assert "Policy evidence requires manual_review" in rendered
    assert "store revision checksum mismatch" in rendered
    _keyed(root)["universe.save"].on_click(None)
    assert "Save blocked: store revision checksum mismatch" in _texts(root)


def test_universe_identity_action_exposes_graph_conflict_review_and_authority(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json")))
    monkeypatch.setattr(
        manager,
        "load_identity_projection",
        lambda _instrument_id, **_kwargs: {
            "status": "available",
            "identity_confidence": "manual_review",
            "identity_resolution_state": "quarantined",
            "identity_objects": [{"object_type": "listing", "object_id": "LISTING-XOSL"}],
            "identity_conflicts": [{"conflict_id": "conflict-1", "reason_code": "duplicate_identity"}],
            "identity_history": [{"event_type": "ticker_changed"}],
            "identity_reviews": [{"decision_id": "review-1", "reviewer": "local-user"}],
            "execution_allowed": False,
        },
    )
    page = _Page()
    root = universe_manager_page(page, _state()).body

    _keyed(root)["universe.identity.A"].on_click(None)

    rendered_controls = [
        control for control in _walk(page.overlay[-1]) if isinstance(control, ft.Text) and control.value
    ]
    rendered = "\n".join(str(control.value) for control in rendered_controls)
    assert "LISTING-XOSL" in rendered
    assert "conflict-1" in rendered
    assert "review-1" in rendered
    assert "execution_allowed=False" in rendered
    assert (
        next(
            control
            for control in rendered_controls
            if "resolution=quarantined" in str(control.value)
        ).style.color
        == manager.theme.AMBER
    )


def test_universe_classification_action_exposes_fallback_and_saves_versioned_override(
    monkeypatch,
    tmp_path,
) -> None:
    record = UniverseRecord(
        "A",
        "Alpha",
        "NO0000000001",
        "verified",
        "A",
        "stock",
        "primary",
        "",
        True,
        "daily",
        "EUR",
        "NO",
        "Financials",
        "",
        "",
    )
    monkeypatch.setattr(
        manager,
        "load_universe",
        lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json")),
    )
    monkeypatch.setattr(manager, "ROOT", tmp_path)
    projections = [
        {
            "status": "available",
            "classification": {
                "instrument_type": "stock",
                "asset_class": "equity",
                "sector": "financials",
                "industry": None,
                "strategy_labels": ["quality"],
                "classification_confidence": 0.82,
                "fallback_path": ["industry->sector_low_confidence"],
                "sector_adapter_allowed": True,
                "execution_allowed": False,
            },
            "sector_adapter_route": {
                "allowed": True,
                "adapter_id": "sector:financials",
                "execution_allowed": False,
            },
            "execution_allowed": False,
        },
        {
            "status": "available",
            "classification": {
                "instrument_type": "stock",
                "asset_class": "equity",
                "sector": "banks",
                "dependent_scores_invalidated": True,
                "execution_allowed": False,
            },
            "execution_allowed": False,
        },
    ]
    monkeypatch.setattr(
        manager,
        "load_classification_projection",
        lambda _instrument_id, **_kwargs: projections.pop(0),
    )
    captured = []

    def fake_save(_root, overrides):
        captured.extend(overrides)
        return {
            "status": "saved",
            "record_ids": ("record-1",),
            "dependent_scores_invalidated": True,
            "execution_allowed": False,
        }

    monkeypatch.setattr(manager, "save_classification_overrides", fake_save)
    page = _Page()
    state = _state()
    invalidated: list[tuple[str, Path]] = []
    state.invalidate_classification_scores = (
        lambda instrument_id, *, root: invalidated.append((instrument_id, root))
    )
    root = universe_manager_page(page, state).body
    _keyed(root)["universe.classification.A"].on_click(None)

    dialog = page.overlay[-1]
    rendered = "\n".join(
        str(control.value)
        for control in _walk(dialog)
        if isinstance(control, ft.Text) and control.value
    )
    assert "industry->sector_low_confidence" in rendered
    assert "sector:financials" in rendered
    assert "execution_allowed=False" in rendered

    _fill(dialog, **{"universe.override.sector": "banks", "universe.override.reason": "Reviewed issuer activity"})
    _keyed(dialog)["universe.classification-save"].on_click(None)

    assert len(captured) == 1
    assert captured[0].instrument_id == "A"
    assert captured[0].field == "sector"
    assert captured[0].value == "banks"
    assert all(item.dependent_score_keys == ("classification:A:*",) for item in captured)
    assert invalidated == [("A", tmp_path)]
    assert "classification-dependent scores are invalid" in str(
        next(
            control
            for control in _walk(root)
            if isinstance(control, ft.Text) and "classification-dependent" in str(control.value)
        ).value
    )


def test_universe_tier_filter_uses_visible_scrollable_table(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "revision", Path("store.json")))

    root = universe_manager_page(_Page(), _state()).body
    keyed = _keyed(root)
    host = keyed["universe.table-host"]

    assert keyed["universe.tier"].value == "all"
    # the kit DataTable scrolls its own virtualised rows inside the card
    assert any(isinstance(control, ft.ListView) for control in _walk(host))
    assert (keyed["universe.table"].data or {}).get("kit") == "DataTable"


def test_save_reloads_active_state_and_marks_universe_cache_revision(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda *_args: UniverseStoreSnapshot((record,), "captured", Path("store.json")))
    refreshed_config = _state().snapshot.config
    refreshed_config.universe.etfs[0].enabled = False
    monkeypatch.setattr(manager, "load_config", lambda: refreshed_config)
    monkeypatch.setattr(
        manager,
        "save_universe",
        lambda records, expected_revision, **_kwargs: UniverseSaveResult(Path("store.json"), "saved-revision", len(tuple(records))),
    )

    state = AppState(
        snapshot=SimpleNamespace(
            config=_state().snapshot.config,
            prices=pd.DataFrame({"etf_id": ["A"]}),
            holdings=pd.DataFrame({"etf_id": ["A"]}),
            features=pd.DataFrame({"etf_id": ["A"]}),
            latest_features=pd.DataFrame({"etf_id": ["A"]}),
            signals=[SimpleNamespace(etf_id="A")],
            forecasts=pd.DataFrame({"etf_id": ["A"]}),
            universe_revision="captured",
        ),
        selected_etf="A",
    )
    state.universe_cache_revision = "captured"
    state.workflow_calls = 0
    page = _Page()
    root = universe_manager_page(page, state).body
    _keyed(root)["universe.save"].on_click(None)
    assert state.snapshot.config.universe == refreshed_config.universe
    assert state.snapshot.config.universe.enabled_ids == []
    assert state.universe_cache_revision == "saved-revision"
    assert state.workflow_calls == 0


def test_universe_revision_invalidates_dated_forecast_and_backtest_caches(tmp_path, monkeypatch) -> None:
    old_revision = "old-universe"
    new_revision = "new-universe"
    forecast_path = tmp_path / "forecast_results_yfinance_20260713.csv"
    forecast_path.write_text("etf_id,model_name\nA,baseline\n", encoding="utf-8")
    (tmp_path / f"{forecast_path.name}.meta.json").write_text(
        json.dumps({"schema_version": 1, "universe_revision": old_revision}), encoding="utf-8"
    )
    assert load_latest_forecasts(directory=tmp_path, universe_revision=new_revision).empty

    monkeypatch.setattr(backtest_service, "BACKTESTS_DIR", tmp_path)
    for name in ("backtest_results.csv", "equity_curves.csv"):
        (tmp_path / name).write_text("sentinel\n", encoding="utf-8")
        (tmp_path / f"{name}.meta.json").write_text(
            json.dumps({"schema_version": 1, "universe_revision": old_revision}), encoding="utf-8"
        )
    service = BacktestService(_state().snapshot.config, universe_revision=new_revision)
    assert service._load_cached_backtest() is None


def test_apply_universe_config_marks_backtest_stale() -> None:
    config = _state().snapshot.config
    report = BacktestReport(
        results=pd.DataFrame({"strategy_name": ["sentinel"]}),
        equity_curves=pd.DataFrame({"signal_strategy": [1.0]}),
        trade_log=pd.DataFrame({"trade": [1]}),
        signal_log=pd.DataFrame({"signal": [1]}),
        ai_added_value=True,
    )
    state = AppState(
        snapshot=SimpleNamespace(
            config=config,
            prices=pd.DataFrame(),
            holdings=pd.DataFrame(),
            features=pd.DataFrame(),
            latest_features=pd.DataFrame(),
            signals=[],
            forecasts=pd.DataFrame(),
            backtest=report,
            universe_revision="old",
        ),
        selected_etf="A",
    )
    state.apply_universe_config(config, "new")
    assert state.snapshot.backtest.results.empty
    assert state.snapshot.backtest.quality_label == "stale_universe"


def test_downstream_consumers_reject_stale_candidate_and_signal_log_cache(tmp_path, monkeypatch) -> None:
    old_revision = "old-universe"
    new_revision = "new-universe"
    candidate = tmp_path / "yfinance_candidate_forecasts_20260713.csv"
    candidate.write_text(
        "etf_id,model_name,status,model_allowed_in_score\nA,baseline,ok,true\n",
        encoding="utf-8",
    )
    (tmp_path / f"{candidate.name}.meta.json").write_text(
        json.dumps({"schema_version": 1, "universe_revision": old_revision}), encoding="utf-8"
    )
    monkeypatch.setattr(dashboard, "FORECASTS_DIR", tmp_path)
    state = SimpleNamespace(
        snapshot=SimpleNamespace(universe_revision=new_revision, forecasts=pd.DataFrame()),
        universe_cache_revision=new_revision,
    )
    assert dashboard._valid_model_pairs(state) == 0

    results = tmp_path / "backtest_results.csv"
    results.write_text(
        "strategy_name,backtest_quality,n_walk_forward_periods\nsignal_strategy,high,3\n",
        encoding="utf-8",
    )
    (tmp_path / f"{results.name}.meta.json").write_text(
        json.dumps({"schema_version": 1, "universe_revision": new_revision}), encoding="utf-8"
    )
    signal_log = tmp_path / "signal_log.csv"
    signal_log.write_text("etf_id\nA\n", encoding="utf-8")
    (tmp_path / f"{signal_log.name}.meta.json").write_text(
        json.dumps({"schema_version": 1, "universe_revision": old_revision}), encoding="utf-8"
    )
    lookup = _backtest_trust_lookup(tmp_path, universe_revision=new_revision)
    assert "A" not in lookup
    assert "__strategy__" in lookup
