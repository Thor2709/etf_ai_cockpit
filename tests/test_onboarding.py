from __future__ import annotations

from etf_cockpit.data.universe_store import support_decision
from etf_cockpit.app.pages.onboarding import OnboardingProfile, complete_onboarding, onboarding_page, validate_onboarding
import flet as ft
import etf_cockpit.app.pages.onboarding as onboarding_module


def test_supported_and_rejected_asset_decisions_are_explicit() -> None:
    assert support_decision("etf", "daily", False, False).supported is True
    assert support_decision("crypto", "daily", False, False).supported is False
    assert support_decision("stock", "intraday", False, False).supported is False
    assert support_decision("etf", "daily", True, False).risk_state == "high_risk_manual_review"


def test_onboarding_rejects_empty_scope_and_preserves_unresolved_symbols() -> None:
    report = validate_onboarding(OnboardingProfile("EUR", "EU", (), "balanced", "medium"))
    assert report.valid is False
    assert "asset_scope" in report.errors
    valid = validate_onboarding(OnboardingProfile("EUR", "EU", ("UNKNOWN",), "balanced", "medium"))
    assert valid.valid is True
    assert valid.unresolved_symbols == ("UNKNOWN",)


def test_offline_onboarding_persists_profile_and_disables_unresolved_tickers(tmp_path) -> None:
    profile = OnboardingProfile(
        "EUR", "Europe", ("both",), "balanced", "medium", tickers=("VWCE.DE", "UNKNOWN"),
    )
    result = complete_onboarding(profile, tmp_path, online=False)
    assert result.saved is True
    assert result.unresolved_symbols == ("UNKNOWN", "VWCE.DE")
    assert result.records[0].enabled is False
    assert result.records[1].enabled is False
    assert (tmp_path / "configs" / "onboarding.json").exists()


def test_offline_onboarding_keeps_configured_local_ticker_enabled(tmp_path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "universe.yaml").write_text(
        "etfs:\n  - id: VWCE\n    name: Vanguard\n    ticker: VWCE.DE\n    role: core\n",
        encoding="utf-8",
    )
    profile = OnboardingProfile("EUR", "Europe", ("etf",), "balanced", "medium", tickers=("VWCE.DE", "MISSING"))
    result = complete_onboarding(profile, tmp_path, online=False)
    assert result.unresolved_symbols == ("MISSING",)
    assert result.records[0].enabled is True
    assert result.records[1].enabled is False


def test_onboarding_ui_exposes_opt_in_online_validator_seam() -> None:
    control = onboarding_page(None, None, validator=lambda _ticker: True)

    def walk(item):
        if not isinstance(item, ft.Control):
            return
        yield item
        for attr in ("controls", "actions"):
            values = getattr(item, attr, None)
            if values:
                for child in values:
                    yield from walk(child)
        content = getattr(item, "content", None)
        if content is not None:
            yield from walk(content)

    toggle = next(item for item in walk(control) if isinstance(item, ft.Checkbox) and item.key == "onboarding.online-validation")
    assert toggle.value is False


def test_online_toggle_is_disabled_without_validator() -> None:
    control = onboarding_page(None, None)
    toggle = next(item for item in control.controls[0].content.controls if isinstance(item, ft.Checkbox) and item.key == "onboarding.online-validation")
    assert toggle.disabled is True
    assert "unavailable" in str(toggle.label).lower()


def test_onboarding_save_reloads_active_state(monkeypatch) -> None:
    class _Page:
        def __init__(self) -> None:
            self.updates = 0

        def update(self) -> None:
            self.updates += 1

    class _State:
        def __init__(self) -> None:
            self.applied: tuple[object, str] | None = None

        def apply_universe_config(self, config, revision: str) -> None:
            self.applied = (config, revision)

    refreshed_config = object()
    monkeypatch.setattr(onboarding_module, "load_config", lambda: refreshed_config)
    monkeypatch.setattr(
        onboarding_module,
        "complete_onboarding",
        lambda *args, **kwargs: onboarding_module.OnboardingResult(True, (), (), "onboarding-revision"),
    )
    state = _State()
    page = _Page()
    control = onboarding_page(page, state, validator=lambda _ticker: True)

    def walk(item):
        if not isinstance(item, ft.Control):
            return
        yield item
        for attr in ("controls", "actions"):
            for child in getattr(item, attr, ()) or ():
                yield from walk(child)
        content = getattr(item, "content", None)
        if content is not None:
            yield from walk(content)

    save = next(
        item
        for item in walk(control)
        if isinstance(item, ft.Button) and item.key == "onboarding.save"
    )
    save.on_click(None)
    assert state.applied == (refreshed_config, "onboarding-revision")
