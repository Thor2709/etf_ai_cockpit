from __future__ import annotations

import json

import pytest

from etf_cockpit.data.universe_store import load_universe, support_decision
from etf_cockpit.app.pages.onboarding import OnboardingProfile, ProviderQuotaExceeded, TickerValidationResult, complete_onboarding, load_onboarding, onboarding_page, validate_onboarding
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


def test_legacy_positional_ticker_is_normalised_to_a_loadable_scope(tmp_path) -> None:
    result = complete_onboarding(
        OnboardingProfile("EUR", "Europe", ("WAT",), "balanced", "medium"),
        tmp_path,
    )

    assert result.saved is True
    assert load_onboarding(tmp_path).tickers == ("WAT",)
    payload = json.loads((tmp_path / "configs" / "onboarding.json").read_text(encoding="utf-8"))
    assert payload["profile"]["asset_scope"] == ["stock"]


def test_invalid_asset_scope_writes_nothing(tmp_path) -> None:
    with pytest.raises(ValueError, match="asset_scope"):
        complete_onboarding(
            OnboardingProfile("EUR", "Europe", ("not a scope!",), "balanced", "medium"),
            tmp_path,
        )

    assert not list(tmp_path.rglob("onboarding*.json"))
    assert not (tmp_path / "configs" / "universe_store.json").exists()


def test_offline_onboarding_persists_profile_and_disables_unresolved_tickers(tmp_path) -> None:
    profile = OnboardingProfile(
        "EUR", "Europe", ("both",), "balanced", "medium", tickers=("VWCE.DE", "UNKNOWN"),
    )
    result = complete_onboarding(profile, tmp_path, online=False)
    assert result.saved is True
    assert result.unresolved_symbols == ("UNKNOWN", "VWCE.DE")
    by_ticker = {record.ticker: record for record in result.records}
    assert by_ticker["UNKNOWN"].enabled is False
    assert by_ticker["VWCE.DE"].enabled is False
    assert by_ticker["MSFT"].enabled is True
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
    by_ticker = {record.ticker: record for record in result.records}
    assert by_ticker["VWCE.DE"].enabled is True
    assert by_ticker["MISSING"].enabled is False


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


def test_onboarding_page_constructs_from_empty_cwd_with_bundled_policy(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    control = onboarding_page(None, None)
    assert isinstance(control, ft.Column)
    assert "Data source policy unavailable" not in str(control)


def test_persisted_hardware_profile_is_used_by_onboarding_readiness(tmp_path, monkeypatch) -> None:
    complete_onboarding(
        OnboardingProfile(
            "EUR", "Europe", ("stock",), "medium", "3M",
            storage_location="selected", hardware_profile="recommended",
        ),
        tmp_path,
    )
    observed: dict[str, object] = {}

    def report(_root, *, requested_profile="auto"):
        observed["requested_profile"] = requested_profile
        return {
            "selected_profile": {"profile_id": requested_profile, "job_memory_limit_mb": 1, "job_disk_limit_mb": 1, "job_cpu_limit": 1},
            "selected_status": "supported",
            "snapshot": {"cpu_cores": 1, "memory_available_mb": 1, "memory_total_mb": 1, "disk_free_mb": 1},
            "profiles": [],
            "benchmarks": {"status": "unavailable", "timing_record_count": 0},
            "generated_cache": {"status": "unavailable"},
            "limitations": [],
        }

    monkeypatch.setattr(onboarding_module, "resource_profile_report", report)
    monkeypatch.chdir(tmp_path)
    onboarding_page(None, None)
    assert observed["requested_profile"] == "recommended"


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
        backup_preference="local",
    )

    result = complete_onboarding(profile, tmp_path, online=False)
    selected_root = tmp_path / "local-data"
    payload = json.loads((selected_root / "configs" / "onboarding.json").read_text(encoding="utf-8"))

    assert result.saved is True
    assert result.storage_root == selected_root.as_posix()
    assert result.optional_provider_status == (("yfinance", "not_configured"),)
    assert not (tmp_path / "configs" / "onboarding.json").exists()
    assert (tmp_path / "configs" / "onboarding-location.json").exists()
    assert load_onboarding(tmp_path).storage_location == selected_root.as_posix()
    assert load_onboarding(selected_root).storage_location == selected_root.as_posix()
    assert payload["schema_version"] == "onboarding.v2"
    assert payload["setup"]["storage_location"] == selected_root.as_posix()
    assert payload["setup"]["resolved_storage_root"] == selected_root.as_posix()
    assert payload["setup"]["hardware_profile"] == "recommended"
    assert payload["setup"]["providers"] == {
        "mandatory": ["manual_local"],
        "optional": ["yfinance"],
        "optional_status": {"yfinance": "not_configured"},
    }
    assert payload["setup"]["bootstrap"]["mode"] == "bulk"
    assert payload["setup"]["bootstrap"]["status"] == "unavailable"
    assert "Select a local" in payload["setup"]["bootstrap"]["message"]
    assert payload["setup"]["bootstrap"]["execution_allowed"] is False
    assert payload["setup"]["privacy"] == {"backup_preference": "local", "encryption_preference": "user_managed"}
    assert payload["setup"]["execution"] == {
        "broker_write_enabled": False,
        "execution_allowed": False,
        "paper_enabled": False,
        "staged_execution_enabled": False,
    }
    assert payload["execution_allowed"] is False


def test_valid_bulk_bootstrap_is_explicitly_unavailable_without_price_writes(tmp_path) -> None:
    source = tmp_path / "official-prices.csv"
    source.write_text(
        "date,instrument_id,adjusted_close\n2026-08-07,VWCE,100.25\n2026-08-08,VWCE,101.00\n",
        encoding="utf-8",
    )
    profile = OnboardingProfile(
        "EUR",
        "Europe",
        ("etf",),
        "medium",
        "3M",
        storage_location="selected-bulk",
        bootstrap_mode="bulk",
        bulk_source_path="official-prices.csv",
    )

    result = complete_onboarding(profile, tmp_path)
    selected_root = tmp_path / "selected-bulk"
    payload = json.loads((selected_root / "configs" / "onboarding.json").read_text(encoding="utf-8"))

    assert result.bootstrap is not None
    assert result.bootstrap.status == "unavailable"
    assert result.bootstrap.rows == 0
    assert result.bootstrap.market_data_status == "unavailable"
    assert not (selected_root / "data" / "clean" / "prices.parquet").exists()
    assert "zero price files" in result.bootstrap.message
    assert payload["setup"]["bootstrap"]["source_path"] == source.as_posix()
    assert payload["setup"]["bootstrap"]["execution_allowed"] is False
    assert payload["execution_allowed"] is False


@pytest.mark.parametrize("location", ("../escape", "https://example.test/data", r"\\server\share"))
def test_storage_location_rejects_traversal_uri_and_unc(tmp_path, location: str) -> None:
    with pytest.raises(ValueError, match="storage_location"):
        complete_onboarding(
            OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M", storage_location=location),
            tmp_path,
        )
    assert not (tmp_path / "configs" / "onboarding-location.json").exists()


def test_group_publish_failure_leaves_all_onboarding_outputs_absent(tmp_path, monkeypatch) -> None:
    def fail_group(*_args, **_kwargs):
        raise OSError("injected grouped publish failure")

    monkeypatch.setattr(onboarding_module, "atomic_write_group", fail_group)
    with pytest.raises(OSError, match="injected grouped publish failure"):
        complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M"), tmp_path)

    assert not list(tmp_path.rglob("onboarding*.json"))
    assert not (tmp_path / "configs" / "universe_store.json").exists()


@pytest.mark.parametrize("preference", ("disabled", "encrypted"))
def test_unsupported_backup_preference_fails_before_any_write(tmp_path, preference: str) -> None:
    with pytest.raises(ValueError, match="no onboarding writes"):
        complete_onboarding(
            OnboardingProfile(
                "EUR", "Europe", ("stock",), "medium", "3M", backup_preference=preference
            ),
            tmp_path,
        )
    assert not list(tmp_path.rglob("onboarding*.json"))
    assert not (tmp_path / "configs" / "universe_store.json").exists()


def test_descendant_symlink_fails_before_onboarding_writes(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    clean = tmp_path / "data" / "clean"
    clean.parent.mkdir(parents=True)
    try:
        clean.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="symlink"):
        complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M"), tmp_path)
    assert not list(tmp_path.rglob("onboarding*.json"))
    assert not (tmp_path / "configs" / "universe_store.json").exists()


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


def test_online_quota_exception_is_non_blocking_visible_and_not_retried(tmp_path) -> None:
    calls: list[str] = []

    def quota_validator(ticker: str) -> bool:
        calls.append(ticker)
        raise ProviderQuotaExceeded("yfinance")

    profile = OnboardingProfile(
        "EUR",
        "Europe",
        ("stock",),
        "medium",
        "3M",
        tickers=("ONE", "TWO"),
        optional_providers=("yfinance",),
        bootstrap_mode="bulk",
    )
    result = complete_onboarding(profile, tmp_path, online=True, validator=quota_validator)
    payload = json.loads((tmp_path / "configs" / "onboarding.json").read_text(encoding="utf-8"))

    assert calls == ["ONE"]
    assert result.saved is True
    assert result.optional_provider_status == (("yfinance", "quota_exceeded"),)
    assert result.bootstrap is not None and result.bootstrap.status == "unavailable"
    assert load_onboarding(tmp_path).optional_provider_status == (("yfinance", "quota_exceeded"),)
    assert payload["setup"]["providers"]["optional_status"] == {"yfinance": "quota_exceeded"}
    assert payload["execution_allowed"] is False


def test_ui_typed_quota_result_is_visible_and_saves_offline_setup(tmp_path, monkeypatch) -> None:
    class _Page:
        def __init__(self) -> None:
            self.updates = 0

        def update(self) -> None:
            self.updates += 1

    calls: list[str] = []

    def quota_validator(ticker: str) -> TickerValidationResult:
        calls.append(ticker)
        return TickerValidationResult("quota_unavailable", "yfinance")

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

    page = _Page()
    control = onboarding_page(page, None, validator=quota_validator)
    controls = tuple(walk(control))
    toggle = next(item for item in controls if isinstance(item, ft.Checkbox) and item.key == "onboarding.online-validation")
    ticker_field = next(item for item in controls if isinstance(item, ft.TextField) and item.label == "Initial tickers (comma separated)")
    save = next(item for item in controls if isinstance(item, ft.Button) and item.key == "onboarding.save")
    status = next(item for item in controls if isinstance(item, ft.Text) and item.key == "onboarding.status")
    toggle.value = True
    ticker_field.value = "ONE, TWO"
    monkeypatch.chdir(tmp_path)

    save.on_click(None)

    payload = json.loads((tmp_path / "configs" / "onboarding.json").read_text(encoding="utf-8"))
    assert calls == ["ONE"]
    assert page.updates == 1
    assert "quota_exceeded" in str(status.value)
    assert "mandatory setup was not blocked" in str(status.value)
    assert payload["setup"]["providers"]["optional_status"] == {"yfinance": "quota_exceeded"}
    assert payload["execution_allowed"] is False


def test_onboarding_round_trip_is_deterministic_and_rejects_unsafe_execution_choices(tmp_path) -> None:
    profile = OnboardingProfile(
        "EUR", "Europe", ("stock",), "medium", "3M",
        storage_location="data/local",
        encryption_preference="enabled",
        backup_preference="enabled",
    )
    result = complete_onboarding(profile, tmp_path)
    selected_root = tmp_path / "data" / "local"
    path = selected_root / "configs" / "onboarding.json"
    first = path.read_bytes()
    loaded = load_onboarding(tmp_path)
    complete_onboarding(loaded, tmp_path)
    assert path.read_bytes() == first
    assert loaded.storage_location == "data/local"
    assert loaded.encryption_preference == "user_managed"
    assert loaded.backup_preference == "local"
    assert loaded.execution_allowed is False
    assert loaded.staged_execution_enabled is False
    assert (selected_root / "configs" / "universe_store.json").is_file()
    assert not (tmp_path / "configs" / "onboarding.json").exists()
    assert result.bootstrap is not None
    assert result.bootstrap.status == "ready"
    assert result.bootstrap.market_data_status == "unavailable"
    assert {record.instrument_id for record in load_universe(selected_root).records} >= {"VWCE", "MSFT"}
    assert not (selected_root / "data" / "clean" / "prices.parquet").exists()

    with pytest.raises(ValueError, match="execution_allowed"):
        complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M", execution_allowed=True), tmp_path)
    with pytest.raises(ValueError, match="staged execution"):
        complete_onboarding(OnboardingProfile("EUR", "Europe", ("stock",), "medium", "3M", staged_execution_enabled=True), tmp_path)
