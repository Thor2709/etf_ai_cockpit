"""Issue #992: universe, restore, reconciliation-FX, preview-registry and stress-lab view contracts (E011 / E012)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

import etf_cockpit.app.pages.import_export as import_export_page_module
import etf_cockpit.app.pages.universe_manager as manager
from etf_cockpit.app.pages.import_export import fx_status_text, import_export_page
from etf_cockpit.app.pages.stress_lab import stress_lab_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.stress_lab import StressLabFacade, build_stress_scenario
from etf_cockpit.core.config import load_config
from etf_cockpit.data import import_export as import_export_data
from etf_cockpit.data import portfolio_imports
from etf_cockpit.data.backup_restore import RestorePreview, RestoreResult
from etf_cockpit.data.import_export import ImportPreview, ImportService
from etf_cockpit.data.universe_store import UniverseRecord, UniverseSaveResult, UniverseStoreSnapshot


class _Page:
    services: list = []

    def __init__(self) -> None:
        self.overlay: list[ft.Control] = []

    def update(self, *_args, **_kwargs) -> None:
        pass


def _walk(control):
    if not isinstance(control, ft.Control):
        return
    yield control
    for attr in ("controls", "rows", "cells", "actions", "items"):
        for child in getattr(control, attr, None) or ():
            yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _find(root, key):
    for item in _walk(root):
        if getattr(item, "key", None) == key:
            return item
    raise AssertionError(f"no control with key {key}")


def _texts(root) -> str:
    return "\n".join(str(item.value) for item in _walk(root) if isinstance(item, ft.Text) and item.value)


# ---------------------------------------------------------------------------
# E011-N001 universe manifest only on Save
# ---------------------------------------------------------------------------


def _universe_state():
    return SimpleNamespace(snapshot=SimpleNamespace(config=load_config()))


def _staged_import(monkeypatch, tmp_path):
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary")
    monkeypatch.setattr(manager, "load_universe", lambda *_a: UniverseStoreSnapshot((record,), "rev", tmp_path / "store.json"))
    monkeypatch.setattr(manager, "save_universe", lambda records, **_k: UniverseSaveResult(tmp_path / "store.json", "rev2", len(tuple(records))))
    manifests: list[object] = []
    monkeypatch.setattr(manager, "save_universe_manifest", manifests.append)
    page = _Page()
    root = manager.universe_manager_page(page, _universe_state()).body
    _find(root, "universe.import-paste").value = "canonical_id,name,ticker\nB,Beta,B\n"
    _find(root, "universe.import-chunk").value = "1"
    _find(root, "universe.import").on_click(None)
    dialog = page.overlay[-1]
    _find(dialog, "universe.import-resume").on_click(None)
    _find(dialog, "universe.import-stage").on_click(None)
    return root, manifests


def test_universe_manifest_unchanged_until_save(monkeypatch, tmp_path) -> None:  # E011-N001
    root, manifests = _staged_import(monkeypatch, tmp_path)
    assert "universe.edit.B" in {str(c.key) for c in _walk(root) if c.key}  # staged, not saved
    assert manifests == []  # staging alone writes nothing
    _find(root, "universe.save").on_click(None)
    assert len(manifests) == 1


def test_universe_discard_drops_pending_manifest(monkeypatch, tmp_path) -> None:  # E011-N001
    root, manifests = _staged_import(monkeypatch, tmp_path)
    _find(root, "universe.discard").on_click(None)
    _find(root, "universe.save").on_click(None)
    assert manifests == []
    assert "universe.edit.B" not in {str(c.key) for c in _walk(root) if c.key}


def test_universe_manifest_save_failure_stays_pending(monkeypatch, tmp_path) -> None:  # E011-N001 fail closed
    root, _ = _staged_import(monkeypatch, tmp_path)
    attempts: list[object] = []

    def failing(manifest):
        attempts.append(manifest)
        raise ValueError("manifest save failed")

    monkeypatch.setattr(manager, "save_universe_manifest", failing)
    _find(root, "universe.save").on_click(None)
    _find(root, "universe.save").on_click(None)  # retry
    assert len(attempts) == 2


# ---------------------------------------------------------------------------
# E011-N002 restore preview follows the path field
# ---------------------------------------------------------------------------


def test_restore_preview_follows_the_path_field(monkeypatch) -> None:  # E011-N002
    validated: list[Path] = []
    committed: list[Path] = []

    def fake_validate(archive, destination=None, **_kwargs):
        validated.append(Path(archive))
        return RestorePreview(Path(archive), True, ("data/x",), ())

    def fake_commit(preview, destination):
        committed.append(preview.archive)
        return RestoreResult(Path(destination), 1)

    monkeypatch.setattr(import_export_page_module, "validate_restore", fake_validate)
    monkeypatch.setattr(import_export_page_module, "commit_restore", fake_commit)
    snapshot = build_snapshot()
    view = import_export_page(_Page(), AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf))
    path = _find(view.body, "import-export.restore-path")
    path.value = "first.zip"
    _find(view.body, "import-export.restore-validate").on_click(None)
    assert _find(view.body, "import-export.restore-commit").data["disabled"] is False

    stale_commit = _find(view.body, "import-export.restore-commit").on_click
    path.value = "second.zip"
    path.on_change(None)
    assert _find(view.body, "import-export.restore-commit").data["disabled"] is True
    stale_commit(None)  # a stale handler must not restore the old archive either
    assert committed == []

    _find(view.body, "import-export.restore-validate").on_click(None)
    _find(view.body, "import-export.restore-commit").on_click(None)
    assert validated == [Path("first.zip"), Path("second.zip")]
    assert committed == [Path("second.zip")]


# ---------------------------------------------------------------------------
# E011-N003 FX not assessed is not zero
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((), "FX not assessed"),
        (("identity", "identity"), "FX unresolved=0 of 2"),
        (("identity", "missing", "conflicted"), "FX unresolved=2 of 3"),
    ],
)
def test_fx_not_assessed_is_never_shown_as_zero(statuses, expected) -> None:  # E011-N003
    text = fx_status_text(tuple(SimpleNamespace(status=status) for status in statuses))
    assert text == expected
    if not statuses:
        assert "0" not in text and "missing" not in text.casefold()


def test_reconciliation_status_says_not_assessed_without_fx_conversions(monkeypatch) -> None:  # E011-N003
    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication

    replay = SimpleNamespace(
        positions=(), cash=(), trial_balance=(), trial_balance_balanced=True, fx_conversions=(), missing_lot_identity=()
    )
    result = SimpleNamespace(discrepancies=(), replay=replay, matched_source_rows=0, active_source_rows=0)
    monkeypatch.setattr(PortfolioImportApplication, "reconcile", lambda _self, **_kw: result)
    snapshot = build_snapshot()
    view = import_export_page(_Page(), AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf))
    _find(view.body, "import-export.portfolio-reconcile").on_click(None)
    status = str(_find(view.body, "import-export.portfolio-reconciliation-status").value)
    assert "FX not assessed" in status
    assert "missing FX=0" not in status


# ---------------------------------------------------------------------------
# E011-N004 preview registries are bounded
# ---------------------------------------------------------------------------


def _preview(index: int) -> ImportPreview:
    return ImportPreview(f"p{index}", "prices", Path("x.csv"), True, 1, ("a",), (), pd.DataFrame({"a": [index]}))


def test_preview_registries_are_bounded_and_evict_oldest() -> None:  # E011-N004
    limit = import_export_data.PREVIEW_REGISTRY_LIMIT
    service = ImportService(Path("."))
    for index in range(limit + 5):
        service.register(_preview(index))
    for registry in (service._previews, import_export_data._PREVIEWS):
        assert len(registry) <= limit
        assert f"p{limit + 4}" in registry
        assert "p0" not in registry
    assert isinstance(portfolio_imports._PREVIEWS, import_export_data.BoundedPreviewRegistry)
    assert len(ImportService(Path("."))._previews) == 0  # a new session does not inherit another session's previews


# ---------------------------------------------------------------------------
# E012 stress lab
# ---------------------------------------------------------------------------


def _stress_view(monkeypatch, *, saved=None, holdings=None):
    monkeypatch.setattr(StressLabFacade, "list_saved", lambda _self: ())
    if saved is not None:
        monkeypatch.setattr(StressLabFacade, "load", lambda _self, scenario_id: saved)
    store: list[object] = []

    def fake_save(_self, scenario, *, expected_revision=0):
        store.append(scenario)
        return SimpleNamespace(revision=expected_revision + 1)

    monkeypatch.setattr(StressLabFacade, "save", fake_save)
    frame = holdings if holdings is not None else pd.DataFrame({"etf_id": ["AAA"], "current_weight": [1.0], "asset_class": ["equity"]})
    snapshot = SimpleNamespace(config=load_config(), holdings=frame, prices=pd.DataFrame(), latest_features=pd.DataFrame())
    return stress_lab_page(None, SimpleNamespace(snapshot=snapshot)), store


def _input(view, key) -> ft.TextField:
    return next(item for item in _walk(_find(view.body, key)) if isinstance(item, ft.TextField))


def _run_scenario(view) -> None:
    _input(view, "stress-lab.scenario-id").value = "S"
    _input(view, "stress-lab.name").value = "S"
    _input(view, "stress-lab.equity").value = "-10"
    _input(view, "stress-lab.notional").value = "1000"
    _find(view.body, "stress-lab.run").on_click(None)


def test_stress_outputs_invalidated_on_input_change(monkeypatch) -> None:  # E012 stale outputs
    view, _ = _stress_view(monkeypatch)
    _run_scenario(view)
    assert "Total P&L: " in _texts(view.body) and "-100.00" in _texts(view.body).replace("−", "-")
    _input(view, "stress-lab.loss-limit").value = "50"
    _find(view.body, "stress-lab.reverse").on_click(None)
    assert "Smallest shock" in _texts(view.body) or "threshold" in _texts(view.body).casefold()

    _input(view, "stress-lab.equity").on_change(None)  # any input edit
    rendered = _texts(view.body)
    assert "Total P&L" not in rendered
    assert "Scenario result unavailable until a scenario has been run." in rendered
    assert "Inputs changed" in rendered
    assert "Smallest shock that breaches" not in rendered


def test_stress_outputs_invalidated_by_notional_and_reverse_shock_change(monkeypatch) -> None:  # E012 stale outputs
    view, _ = _stress_view(monkeypatch)
    _run_scenario(view)
    _input(view, "stress-lab.notional").on_change(None)
    assert "Total P&L" not in _texts(view.body)


def test_loaded_shocks_keep_precision_and_scenario_fields_are_not_dropped(monkeypatch) -> None:  # E012
    scenario = build_stress_scenario(
        scenario_id="L",
        name="Loaded",
        shocks={"equity": -0.123456, "rates": 0.0033, "factor:momentum": -0.0625},
        horizon_days=5,
        version=3,
    )
    view, saved = _stress_view(monkeypatch, saved=SimpleNamespace(scenario=scenario, revision=7, updated_at="t"))
    _input(view, "stress-lab.scenario-id").value = "L"
    _find(view.body, "stress-lab.load").on_click(None)
    assert _input(view, "stress-lab.equity").value == "-12.3456"  # not rounded to -12.35
    assert _input(view, "stress-lab.rates").value == "0.33"
    _find(view.body, "stress-lab.save").on_click(None)
    assert len(saved) == 1
    again = saved[0]
    assert again.horizon_days == 5 and again.version == 3
    assert again.shocks["factor:momentum"] == pytest.approx(-0.0625)
    assert again.shocks["equity"] == pytest.approx(-0.123456)
    assert again.shocks["rates"] == pytest.approx(0.0033)

    # A different scenario ID does not inherit the loaded scenario's hidden attributes.
    _input(view, "stress-lab.scenario-id").on_change(None)
    _input(view, "stress-lab.scenario-id").value = "M"
    _find(view.body, "stress-lab.save").on_click(None)
    assert saved[-1].horizon_days == 1 and saved[-1].version == 1
    assert "factor:momentum" not in saved[-1].shocks


def test_historical_chart_includes_every_returned_factor() -> None:  # E012 missing chart factor
    from etf_cockpit.app.pages.stress_lab import stress_factor_categories

    labels = [label for label, _key in stress_factor_categories({"equity": 1.0, "factor:momentum": 2.0, "factor:value": 3.0})]
    assert labels[:7] == ["Equity", "Rates", "FX", "Credit", "Commodity", "Liquidity", "Residual"]
    assert labels[7:] == ["factor:momentum", "factor:value"]
    assert [label for label, _ in stress_factor_categories({})] == labels[:7]
