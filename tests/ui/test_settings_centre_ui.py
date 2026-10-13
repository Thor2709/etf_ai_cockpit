from __future__ import annotations

import importlib
import json
from datetime import date

import flet as ft
import pandas as pd

from etf_cockpit.app.pages.onboarding import onboarding_page
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.application.backtest_service import _empty_backtest_report
from etf_cockpit.application.snapshot_builder import CockpitSnapshot, build_snapshot
from etf_cockpit.core.config import load_config


def _walk(control):
    """Walk a rebuilt page: PageView chrome/body, kit Fields (popup menus) and nested content."""
    if hasattr(control, "body") and hasattr(control, "chrome"):
        yield from _walk(control.body)
        return
    if isinstance(control, ft.Control):
        yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for child in getattr(control, "actions", ()) or ():
        yield from _walk(child)
    for item in getattr(control, "items", ()) or ():
        yield from _walk(item)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _walk_all_views(view):
    """Walk every segment of a PageView (the rebuilt pages render one segment at a time)."""
    seen: list = list(_walk(view))
    for group in view.chrome.segment_groups:
        for name in group.items:
            group.on_change(name)
            seen.extend(_walk(view))
        group.on_change(group.selected)
    return seen


def _fields(controls):
    """Kit ``Field`` columns by label, with their option labels."""
    result = {}
    for control in controls:
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "Field":
            options = [
                str(getattr(getattr(item, "content", None), "value", ""))
                for node in _walk(control)
                for item in (getattr(node, "items", ()) or ())
            ]
            result[str(data["label"])] = options
    return result


def _metadata_snapshot() -> CockpitSnapshot:
    config = load_config()
    empty = pd.DataFrame()
    return CockpitSnapshot(
        config=config,
        prices=empty,
        holdings=empty,
        features=empty,
        latest_features=empty,
        data_report=DataQualityReport(as_of_date=date.today(), issues=[]),
        signals=[],
        forecasts=empty,
        backtest=_empty_backtest_report("Settings release metadata does not use backtest results."),
        model_status={},
        model_inventory=[],
    )


def test_settings_centre_exposes_staged_controls_without_plaintext_credentials() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    controls = _walk_all_views(settings_page(None, state))
    by_key = {getattr(control, "key", None): control for control in controls if getattr(control, "key", None)}

    assert {
        "settings.output-currency",
        "settings.asset-scopes",
        "settings.risk-profile",
        "settings.horizon",
        "settings.analysis-depth",
        "settings.preview",
        "settings.save",
        "settings.manage-credentials",
        "settings.version",
    } <= set(by_key)
    assert by_key["settings.manage-credentials"].disabled is True
    assert "ISSUE-0176" in str(getattr(by_key["settings.manage-credentials"], "tooltip", ""))
    assert not any(isinstance(control, ft.TextField) and "api key" in str(control.label or "").lower() for control in controls)
    text = "\n".join(str(getattr(control, "value", "") or getattr(control, "text", "")) for control in controls)
    assert "execution_allowed=false" in text
    assert "Preview" in text
    assert "new analysis/selection run" in text


def test_onboarding_uses_canonical_settings_options() -> None:
    controls = _walk_all_views(onboarding_page(None, None))
    fields = _fields(controls)
    texts = [str(getattr(control, "value", "") or getattr(control, "text", "")) for control in controls]

    assert "Output currency" in fields
    assert "Asset scope" in fields
    assert fields["Asset scope"] == ["stock", "etf", "fund", "bond", "stock+etf", "all"]
    for label in ("Risk profile", "Target horizon", "Analysis depth"):
        assert label in texts
    # Segmented option labels map one-to-one onto the canonical settings values.
    assert {"Safe", "Safe-Medium", "Medium", "Medium-Aggressive", "Aggressive"} <= set(texts)
    assert {"1W", "1M", "3M", "6M", "9M", "2Y", "5Y"} <= set(texts)


def test_settings_centre_surfaces_unsupported_legacy_migration(tmp_path, monkeypatch) -> None:
    page_module = importlib.import_module("etf_cockpit.app.pages.settings")
    onboarding = tmp_path / "configs" / "onboarding.json"
    onboarding.parent.mkdir(parents=True)
    onboarding.write_text(
        json.dumps({"profile": {"base_currency": "ZZZ", "asset_scope": ["options"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(page_module, "ROOT", tmp_path)
    monkeypatch.setattr(
        page_module,
        "describe_release_evidence",
        lambda _root: {"verification": "unavailable", "version": "unavailable", "notices": "unavailable", "notices_path": "unavailable"},
    )
    monkeypatch.setattr(
        page_module,
        "legal_terms_report",
        lambda _root: {"status": "unavailable", "review_status": "manual_review", "registry_sha256": "unavailable"},
    )
    monkeypatch.setattr(
        page_module,
        "supply_chain_intake_report",
        lambda _root: {
            "status": "unavailable",
            "review_status": "manual_review",
            "component_count": 0,
            "dependency_count": 0,
            "registry_sha256": "unavailable",
            "third_party_notices": "unavailable",
        },
    )
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    controls = _walk_all_views(page_module.settings_page(None, state))
    text = "\n".join(str(getattr(control, "value", "") or getattr(control, "text", "")) for control in controls)

    assert "manual review" in text.lower()
    assert "SETTINGS_CURRENCY_UNSUPPORTED" in text


def test_settings_release_metadata_shows_changelog_excerpt_and_unavailable_rebuild() -> None:
    snapshot = _metadata_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    controls = _walk_all_views(settings_page(None, state))
    text = "\n".join(str(getattr(control, "value", "") or getattr(control, "text", "")) for control in controls)

    assert "Changelog excerpt:" in text
    assert "## Unreleased" in text
    assert "Last rebuild timestamp: unavailable (source checkout; no packaged build metadata)" in text
