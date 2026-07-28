from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import flet as ft
import pandas as pd

import etf_cockpit.app.pages.universe_manager as manager
import etf_cockpit.app.pages.dashboard as dashboard
from etf_cockpit.app.pages.universe_manager import universe_manager_page
from etf_cockpit.app.state import AppState
from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.models.forecast_scores import load_latest_forecasts
import etf_cockpit.services as services
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
    for attr in ("controls", "rows", "cells", "actions"):
        values = getattr(control, attr, None)
        if values:
            for child in values:
                yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_real_crud_controls_stage_changes_and_save_captured_revision(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda: UniverseStoreSnapshot((record,), "captured-revision", Path("store.json")))
    saved: list[tuple[tuple[UniverseRecord, ...], str]] = []

    def fake_save(records, expected_revision, **_kwargs):
        rows = tuple(records)
        saved.append((rows, expected_revision))
        revision = f"revision-{len(saved)}"
        return UniverseSaveResult(Path("store.json"), revision, len(rows))

    monkeypatch.setattr(manager, "save_universe", fake_save)
    page = _Page()
    root = universe_manager_page(page, _state())
    controls = {str(control.key): control for control in _walk(root) if control.key}
    buttons = {key: control for key, control in controls.items() if isinstance(control, ft.Button)}
    assert {
        "universe.add",
        "universe.save",
        "universe.edit.A",
        "universe.identity.A",
        "universe.classification.A",
        "universe.disable.A",
        "universe.remove.A",
    } <= set(buttons)
    assert "universe.allow-cross-tier-duplicates" in controls

    # Disable and add use the real callbacks, and neither callback invokes a
    # workflow service. The newly added record proves full add control wiring.
    buttons["universe.disable.A"].on_click(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    assert "universe.enable.A" in buttons
    buttons["universe.enable.A"].on_click(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    assert "universe.disable.A" in buttons
    buttons["universe.add"].on_click(None)
    assert page.overlay
    dialog = page.overlay[-1]
    fields = {str(control.label): control for control in _walk(dialog) if isinstance(control, ft.TextField) and control.label}
    fields["ID"].value = "B"
    fields["Name"].value = "Beta"
    fields["Yahoo ticker"].value = "B"
    fields["ISIN"].value = "NO0000000002"
    fields["ISIN status"].value = "verified"
    enabled_checkbox = next(control for control in _walk(dialog) if isinstance(control, ft.Checkbox) and control.label == "Enabled for normal workflows")
    enabled_checkbox.value = False
    next(control for control in _walk(dialog) if isinstance(control, ft.Button) and control.key == "universe.add-save").on_click(None)

    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    buttons["universe.save"].on_click(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    buttons["universe.save"].on_click(None)
    assert [revision for _rows, revision in saved] == ["captured-revision", "revision-1"]
    assert {row.instrument_id for row in saved[-1][0]} == {"A", "B"}
    assert next(row for row in saved[-1][0] if row.instrument_id == "B").enabled is False

    # Search and tier selection rebuild the one visible, horizontally scrollable table.
    query = next(control for control in _walk(root) if isinstance(control, ft.TextField) and control.label == "Search universe")
    assert not query.expand
    assert query.width == 520
    query.value = "Beta"
    query.on_change(None)
    tier = next(control for control in _walk(root) if isinstance(control, ft.Dropdown) and control.key == "universe.tier")
    assert [(option.key, option.text) for option in tier.options] == [
        ("primary", "Primary"),
        ("secondary", "Secondary"),
        ("sparebanken", "Sparebanken"),
    ]
    tier.value = "secondary"
    tier.on_select(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    assert "universe.identity.B" in buttons


def test_override_checkbox_rehydrates_from_store_snapshot(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(
        manager,
        "load_universe",
        lambda: UniverseStoreSnapshot((record,), "revision", Path("store.json"), True),
    )
    page = _Page()
    root = universe_manager_page(page, _state())
    checkbox = next(control for control in _walk(root) if isinstance(control, ft.Checkbox) and control.key == "universe.allow-cross-tier-duplicates")
    assert checkbox.value is True


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
        lambda: UniverseStoreSnapshot(
            records,
            "revision",
            Path("store.json"),
            policy_evidence=states,
            schema_version=3,
        ),
    )

    root = universe_manager_page(_Page(), _state())
    rendered = {
        str(control.value): control
        for control in _walk(root)
        if isinstance(control, ft.Text) and control.value
    }

    for state in ("current", "stale", "legacy_unmigrated", "unavailable", "manual_review"):
        assert state in rendered
    assert rendered["current"].color == manager.theme.GREEN
    assert rendered["manual_review"].color == manager.theme.AMBER
    assert rendered["stale"].tooltip == "version changed"


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
        lambda: UniverseStoreSnapshot(
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

    root = universe_manager_page(_Page(), _state())
    rendered = "\n".join(
        str(control.value)
        for control in _walk(root)
        if isinstance(control, ft.Text) and control.value
    )

    assert "Policy evidence requires manual_review" in rendered
    assert "store revision checksum mismatch" in rendered


def test_universe_identity_action_exposes_graph_conflict_review_and_authority(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda: UniverseStoreSnapshot((record,), "revision", Path("store.json")))
    monkeypatch.setattr(
        manager,
        "load_identity_projection",
        lambda _instrument_id: {
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
    root = universe_manager_page(page, _state())

    identity_button = next(
        control
        for control in _walk(root)
        if isinstance(control, ft.Button) and control.key == "universe.identity.A"
    )
    identity_button.on_click(None)

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
        ).color
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
        lambda: UniverseStoreSnapshot((record,), "revision", Path("store.json")),
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
    root = universe_manager_page(page, state)
    button = next(
        control
        for control in _walk(root)
        if isinstance(control, ft.Button) and control.key == "universe.classification.A"
    )
    button.on_click(None)

    dialog = page.overlay[-1]
    rendered = "\n".join(
        str(control.value)
        for control in _walk(dialog)
        if isinstance(control, ft.Text) and control.value
    )
    assert "industry->sector_low_confidence" in rendered
    assert "sector:financials" in rendered
    assert "execution_allowed=False" in rendered

    fields = {
        str(control.label): control
        for control in _walk(dialog)
        if isinstance(control, ft.TextField) and control.label
    }
    fields["Sector override"].value = "banks"
    fields["Override reason"].value = "Reviewed issuer activity"
    save = next(
        control
        for control in _walk(dialog)
        if isinstance(control, ft.Button) and control.key == "universe.classification-save"
    )
    save.on_click(None)

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
    monkeypatch.setattr(manager, "load_universe", lambda: UniverseStoreSnapshot((record,), "revision", Path("store.json")))

    root = universe_manager_page(_Page(), _state())
    tier = next(control for control in _walk(root) if isinstance(control, ft.Dropdown) and control.key == "universe.tier")
    table_scroll = next(control for control in _walk(root) if isinstance(control, ft.Row) and control.key == "universe.table-scroll")

    assert tier.value == "primary"
    assert table_scroll.scroll == ft.ScrollMode.AUTO
    assert any(isinstance(control, ft.DataTable) for control in _walk(table_scroll))


def test_save_reloads_active_state_and_marks_universe_cache_revision(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda: UniverseStoreSnapshot((record,), "captured", Path("store.json")))
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
    root = universe_manager_page(page, state)
    save_button = next(control for control in _walk(root) if isinstance(control, ft.Button) and control.key == "universe.save")
    save_button.on_click(None)
    assert state.snapshot.config is refreshed_config
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

    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    for name in ("backtest_results.csv", "equity_curves.csv"):
        (tmp_path / name).write_text("sentinel\n", encoding="utf-8")
        (tmp_path / f"{name}.meta.json").write_text(
            json.dumps({"schema_version": 1, "universe_revision": old_revision}), encoding="utf-8"
        )
    service = services.BacktestService(_state().snapshot.config, universe_revision=new_revision)
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
