from __future__ import annotations

import importlib
import json

import flet as ft

from etf_cockpit.app.pages.onboarding import onboarding_page
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    if isinstance(control, ft.Control):
        yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for child in getattr(control, "actions", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_settings_centre_exposes_staged_controls_without_plaintext_credentials() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    controls = list(_walk(settings_page(None, state)))
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
    controls = list(_walk(onboarding_page(None, None)))
    dropdowns = {str(control.label): control for control in controls if isinstance(control, ft.Dropdown)}

    assert "Output currency" in dropdowns
    assert "Asset scope" in dropdowns
    assert "Risk profile" in dropdowns
    assert "Target horizon" in dropdowns
    assert "Analysis depth" in dropdowns
    assert {option.key for option in dropdowns["Risk profile"].options} == {
        "safe", "safe_medium", "medium", "medium_aggressive", "aggressive"
    }
    assert {option.key for option in dropdowns["Target horizon"].options} == {"1W", "1M", "3M", "6M", "9M", "2Y", "5Y"}


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

    controls = list(_walk(page_module.settings_page(None, state)))
    text = "\n".join(str(getattr(control, "value", "") or getattr(control, "text", "")) for control in controls)

    assert "manual review" in text.lower()
    assert "SETTINGS_CURRENCY_UNSUPPORTED" in text
