from __future__ import annotations

import json

import pytest

from etf_cockpit.data.universe_store import support_decision
from etf_cockpit.app.pages.onboarding import OnboardingProfile, complete_onboarding, load_onboarding, onboarding_page, validate_onboarding
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
    assert load_onboarding(tmp_path).optional_provider_status == ()
    assert json.loads((tmp_path / "configs" / "onboarding.json").read_text(encoding="utf-8"))["unresolved_symbols"] == ["UNKNOWN", "VWCE.DE"]


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


def test_complete_offline_setup_persists_all_choices_and_disabled_execution(tmp_path) -> None:
    profile = OnboardingProfile(
        "EUR",
        "Europe",
        ("stock", "etf"),
        "medium",
        "3M",
        storage_location=str(tmp_path / "local-data"),
        hardware_profile="recommended",
        mandatory_providers=("manual_local",),
        optional_providers=("yfinance",),
        bootstrap_mode="bulk",
        encryption_preference="user_managed",
        backup_preference="encrypted",
    )

    result = complete_onboarding(profile, tmp_path, online=False)
    payload = json.loads((tmp_path / "configs" / "onboarding.json").read_text(encoding="utf-8"))

    assert result.saved is True
    assert result.optional_provider_status == (("yfinance", "not_configured"),)
    assert payload["schema_version"] == "onboarding.v2"
    assert payload["setup"]["storage_location"] == (tmp_path / "local-data").as_posix()
    assert payload["setup"]["hardware_profile"] == "recommended"
    assert payload["setup"]["providers"] == {
        "mandatory": ["manual_local"],
        "optional": ["yfinance"],
        "optional_status": {"yfinance": "not_configured"},
    }
    assert payload["setup"]["bootstrap"] == {"mode": "bulk", "offline": True}
    assert payload["setup"]["privacy"] == {"backup_preference": "encrypted", "encryption_preference": "user_managed"}
    assert payload["setup"]["execution"] == {
        "broker_write_enabled": False,
        "execution_allowed": False,
        "paper_enabled": False,
        "staged_execution_enabled": False,
    }
    assert payload["execution_allowed"] is False


def test_onboarding_load_fails_closed_for_partial_or_enabled_execution_settings(tmp_path) -> None:
    complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M"), tmp_path)
    path = tmp_path / "configs" / "onboarding.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    payload["setup"].pop("privacy")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        load_onboarding(tmp_path)

    complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M"), tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["setup"]["execution"]["execution_allowed"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="safety defaults"):
        load_onboarding(tmp_path)


def test_optional_quota_failure_is_visible_non_blocking_and_does_not_corrupt_prior_state(tmp_path) -> None:
    baseline = OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M")
    complete_onboarding(baseline, tmp_path)
    path = tmp_path / "configs" / "onboarding.json"
    before = path.read_bytes()

    quota_profile = OnboardingProfile(
        "EUR", "Europe", ("stock",), "medium", "3M", optional_providers=("yfinance",)
    )
    result = complete_onboarding(quota_profile, tmp_path, provider_status={"yfinance": "quota_exceeded"})
    assert result.saved is True
    assert result.optional_provider_status == (("yfinance", "quota_exceeded"),)
    assert load_onboarding(tmp_path).optional_provider_status == (("yfinance", "quota_exceeded"),)

    after_quota = path.read_bytes()
    with pytest.raises(ValueError, match="unsupported optional provider status"):
        complete_onboarding(quota_profile, tmp_path, provider_status={"yfinance": "corrupt"})
    assert path.read_bytes() == after_quota
    assert before != after_quota


def test_onboarding_round_trip_is_deterministic_and_rejects_unsafe_execution_choices(tmp_path) -> None:
    profile = OnboardingProfile(
        "EUR", "Europe", ("stock",), "medium", "3M",
        storage_location="data/local",
        encryption_preference="enabled",
        backup_preference="enabled",
    )
    complete_onboarding(profile, tmp_path)
    path = tmp_path / "configs" / "onboarding.json"
    first = path.read_bytes()
    loaded = load_onboarding(tmp_path)
    complete_onboarding(loaded, tmp_path)
    assert path.read_bytes() == first
    assert loaded.storage_location == "data/local"
    assert loaded.encryption_preference == "user_managed"
    assert loaded.backup_preference == "local"
    assert loaded.execution_allowed is False
    assert loaded.staged_execution_enabled is False

    with pytest.raises(ValueError, match="execution_allowed"):
        complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M", execution_allowed=True), tmp_path)
    with pytest.raises(ValueError, match="staged execution"):
        complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M", staged_execution_enabled=True), tmp_path)
