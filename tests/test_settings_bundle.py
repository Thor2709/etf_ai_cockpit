from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
import yaml

from etf_cockpit.application.settings import (
    ANALYSIS_DEPTHS,
    ASSET_SCOPES,
    HORIZONS,
    RISK_PROFILES,
    SettingsBundle,
    SettingsError,
    load_settings_bundle,
    load_settings_bundle_with_issues,
    migrate_legacy_settings,
    preview_settings,
    save_settings,
    settings_export,
    settings_run_identity,
)
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
from etf_cockpit.core.versioning import (
    VersionRegistryError,
    build_run_manifest,
    build_version_registry,
    settings_bound_run_id,
    write_run_manifest,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _settings_revision(bundle: SettingsBundle) -> str:
    payload = bundle.model_dump(mode="json", exclude={"revision"})
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_settings_document(root: Path, bundle: SettingsBundle) -> None:
    document = {
        "schema_version": bundle.schema_version,
        "semantic_version": bundle.semantic_version,
        "settings_version": bundle.settings_version,
        "revision": bundle.revision,
        "controls": bundle.controls.model_dump(mode="json"),
        "execution_allowed": False,
    }
    path = root / "configs" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")


def test_settings_defaults_and_enums_are_typed_and_execution_stays_disabled(tmp_path: Path) -> None:
    bundle = load_settings_bundle(tmp_path)

    assert bundle.schema_version == "settings_bundle.v1"
    assert bundle.semantic_version == "1.0.0"
    assert bundle.controls.output_currency == "EUR"
    assert bundle.controls.asset_scopes == ("stock", "etf")
    assert bundle.controls.risk_profile == "medium"
    assert bundle.controls.horizon == "3M"
    assert bundle.controls.analysis_depth == "medium"
    assert bundle.execution_allowed is False
    assert ASSET_SCOPES == ("stock", "etf", "fund", "bond")
    assert RISK_PROFILES == ("safe", "safe_medium", "medium", "medium_aggressive", "aggressive")
    assert HORIZONS == ("1W", "1M", "3M", "6M", "9M", "2Y", "5Y")
    assert ANALYSIS_DEPTHS == ("quick", "medium", "high", "full")

    for field, value, code in (
        ("output_currency", "NOT-CURRENCY", "SETTINGS_CURRENCY_UNSUPPORTED"),
        ("risk_profile", "reckless", "SETTINGS_SAFETY_BOUND_VIOLATION"),
        ("horizon", "forever", "SETTINGS_SCHEMA_INVALID"),
        ("analysis_depth", "unbounded", "SETTINGS_SCHEMA_INVALID"),
        ("macro_provider", "unregistered_paid_feed", "SETTINGS_PROVIDER_UNSUPPORTED"),
    ):
        candidate = bundle.controls.model_copy(update={field: value})
        with pytest.raises(SettingsError) as error:
            preview_settings(bundle.model_copy(update={"controls": candidate}), expected_revision=bundle.revision, root=tmp_path)
        assert error.value.code == code


def test_legacy_onboarding_migration_is_deterministic_and_reports_unknown_values(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "configs" / "onboarding.json",
        {
            "profile": {
                "base_currency": "eur",
                "asset_scope": ["both"],
                "risk_profile": "balanced",
                "horizon": "long",
            }
        },
    )
    migrated, issues = migrate_legacy_settings(tmp_path)
    assert issues == ()
    assert migrated.controls.output_currency == "EUR"
    assert migrated.controls.asset_scopes == ("stock", "etf")
    assert migrated.controls.risk_profile == "medium"
    assert migrated.controls.horizon == "9M"
    assert migrated.controls.analysis_depth == "medium"
    assert not (tmp_path / "configs" / "settings.yaml").exists()

    _write_json(
        tmp_path / "configs" / "onboarding.json",
        {"profile": {"base_currency": "ZZZ", "asset_scope": ["options"], "risk_profile": "unknown", "horizon": "soon"}},
    )
    migrated_again, issues_again = migrate_legacy_settings(tmp_path)
    assert migrated_again.controls.output_currency == "EUR"
    assert {issue.code for issue in issues_again} == {
        "SETTINGS_CURRENCY_UNSUPPORTED",
        "SETTINGS_MIGRATION_REVIEW_REQUIRED",
    }
    assert {issue.field for issue in issues_again} >= {"output_currency", "asset_scopes", "risk_profile", "horizon"}

    loaded, surfaced_issues = load_settings_bundle_with_issues(tmp_path)
    assert loaded == migrated_again
    assert surfaced_issues == issues_again


def test_settings_revision_is_portable_across_companion_line_endings(tmp_path: Path) -> None:
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    lf_path = lf_root / "configs" / "universe.yaml"
    crlf_path = crlf_root / "configs" / "universe.yaml"
    lf_path.parent.mkdir(parents=True)
    crlf_path.parent.mkdir(parents=True)
    document = "etfs:\n- id: IE00B4L5Y983\n"
    lf_path.write_bytes(document.encode("utf-8"))
    crlf_path.write_bytes(document.replace("\n", "\r\n").encode("utf-8"))

    lf_bundle, lf_issues = migrate_legacy_settings(lf_root)
    crlf_bundle, crlf_issues = migrate_legacy_settings(crlf_root)

    assert lf_issues == crlf_issues == ()
    assert lf_bundle.universe == crlf_bundle.universe
    assert lf_bundle.revision == crlf_bundle.revision


def test_shipped_version_zero_defaults_do_not_erase_legacy_onboarding(tmp_path: Path) -> None:
    default = load_settings_bundle(tmp_path)
    settings_path = tmp_path / "configs" / "settings.yaml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": default.schema_version,
                "semantic_version": default.semantic_version,
                "settings_version": 0,
                "revision": default.revision,
                "controls": default.controls.model_dump(mode="json"),
                "execution_allowed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "configs" / "onboarding.json",
        {"profile": {"base_currency": "GBP", "asset_scope": ["all"], "risk_profile": "growth", "horizon": "long"}},
    )

    effective = load_settings_bundle(tmp_path)

    assert effective.settings_version == 0
    assert effective.controls.output_currency == "GBP"
    assert effective.controls.asset_scopes == ASSET_SCOPES
    assert effective.controls.risk_profile == "aggressive"
    assert effective.controls.horizon == "9M"
    assert yaml.safe_load(settings_path.read_text(encoding="utf-8"))["controls"]["output_currency"] == "EUR"


def test_preview_save_reload_is_atomic_versioned_and_revision_checked(tmp_path: Path) -> None:
    current = load_settings_bundle(tmp_path)
    changed_controls = current.controls.model_copy(
        update={"horizon": "6M", "analysis_depth": "high", "asset_scopes": ("stock", "etf", "fund", "bond")}
    )
    candidate = current.model_copy(update={"controls": changed_controls})

    preview = preview_settings(candidate, expected_revision=current.revision, root=tmp_path)
    assert preview.valid is True
    assert preview.creates_new_run is True
    assert preview.before_revision == current.revision
    assert {"controls.horizon", "controls.analysis_depth", "controls.asset_scopes"} <= set(preview.changed_fields)
    assert preview.execution_allowed is False

    result = save_settings(candidate, expected_revision=current.revision, root=tmp_path)
    assert result.saved is True
    assert result.revision != current.revision
    assert result.settings_version == 1
    assert result.execution_allowed is False
    assert preview.after_revision == result.revision
    assert (tmp_path / "configs" / "settings.yaml").is_file()
    snapshots = list((tmp_path / "data" / "derived" / "settings_versions").glob("1-*.json"))
    assert len(snapshots) == 1
    reloaded = load_settings_bundle(tmp_path)
    assert reloaded.revision == result.revision
    assert reloaded.controls == changed_controls

    with pytest.raises(SettingsError) as error:
        save_settings(candidate, expected_revision=current.revision, root=tmp_path)
    assert error.value.code == "SETTINGS_REVISION_CONFLICT"
    assert len(list((tmp_path / "data" / "derived" / "settings_versions").glob("*.json"))) == 1


@pytest.mark.parametrize("secret_name", ["api_key", "api-key", "private_key", "refresh_token", "consumer_secret"])
def test_secret_fields_are_forbidden_and_exports_are_redacted(tmp_path: Path, secret_name: str) -> None:
    bundle = load_settings_bundle(tmp_path)
    payload = bundle.model_dump(mode="json")
    payload["providers"] = {
        "providers": {
            "prices": {"active_provider": "local", "base_url": "", "symbols_map": {}, secret_name: "raw-secret"}
        }
    }
    with pytest.raises(SettingsError) as error:
        SettingsBundle.from_mapping(payload)
    assert error.value.code == "SETTINGS_SECRET_FIELD_FORBIDDEN"

    with pytest.raises(SettingsError) as save_error:
        save_settings(payload, expected_revision=bundle.revision, root=tmp_path)
    assert save_error.value.code == "SETTINGS_SECRET_FIELD_FORBIDDEN"
    assert not (tmp_path / "configs" / "data_providers.yaml").exists()
    assert not list((tmp_path / "data" / "derived" / "settings_versions").glob("*.json"))

    exported = json.dumps(settings_export(bundle), sort_keys=True).lower()
    assert "api_key" not in exported
    assert "secret" not in exported
    assert "execution_allowed\": false" in exported


def test_populated_secret_field_in_companion_provider_yaml_is_rejected(tmp_path: Path) -> None:
    provider_path = tmp_path / "configs" / "data_providers.yaml"
    provider_path.parent.mkdir(parents=True)
    provider_path.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "prices": {
                        "active_provider": "local",
                        "base_url": "",
                        "symbols_map": {},
                        "private_key": "raw-secret",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SettingsError) as error:
        load_settings_bundle(tmp_path)

    assert error.value.code == "SETTINGS_SECRET_FIELD_FORBIDDEN"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("output_currency", "ZZZ", "SETTINGS_CURRENCY_UNSUPPORTED"),
        ("risk_profile", "reckless", "SETTINGS_SAFETY_BOUND_VIOLATION"),
        ("horizon", "forever", "SETTINGS_SCHEMA_INVALID"),
        ("analysis_depth", "unbounded", "SETTINGS_SCHEMA_INVALID"),
        ("macro_provider", "paid_unknown", "SETTINGS_PROVIDER_UNSUPPORTED"),
    ],
)
def test_persisted_settings_are_fully_validated_on_load(tmp_path: Path, field: str, value: str, code: str) -> None:
    current = load_settings_bundle(tmp_path)
    invalid = current.model_copy(
        update={"controls": current.controls.model_copy(update={field: value}), "revision": ""}
    )
    invalid = invalid.model_copy(update={"revision": _settings_revision(invalid)})
    _write_settings_document(tmp_path, invalid)

    with pytest.raises(SettingsError) as error:
        load_settings_bundle(tmp_path)

    assert error.value.code == code


def test_settings_identity_is_stable_and_declares_downstream_availability(tmp_path: Path) -> None:
    bundle = load_settings_bundle(tmp_path)
    first = settings_run_identity(bundle)
    second = settings_run_identity(bundle)
    assert first == second
    assert first["settings_schema_version"] == "settings_bundle.v1"
    assert first["settings_revision"] == bundle.revision
    assert first["settings_snapshot_id"].startswith("settings:")
    assert first["currency_effect_status"] == "unavailable_issue_0173"
    assert first["risk_effect_status"] == "unavailable_issue_0174"
    assert first["depth_effect_status"] == "unavailable_issue_0175"
    assert first["execution_allowed"] is False

    registry = build_version_registry(tmp_path, code_revision="fixture")
    manifest = build_run_manifest("settings_run", [], registry=registry, root=tmp_path)
    assert manifest["settings"] == first
    write_run_manifest("settings_run", [], registry=registry, root=tmp_path)
    changed = bundle.model_copy(
        update={"controls": bundle.controls.model_copy(update={"horizon": "6M"}), "revision": ""}
    )
    with pytest.raises(VersionRegistryError, match="different content"):
        write_run_manifest(
            "settings_run",
            [],
            registry=registry,
            root=tmp_path,
            settings_identity=settings_run_identity(SettingsBundle.from_mapping(changed.model_dump(mode="json"))),
        )


def test_semantic_settings_change_allocates_a_distinct_immutable_run_id(tmp_path: Path) -> None:
    current = load_settings_bundle(tmp_path)
    first_id = settings_bound_run_id("features_latest", root=tmp_path)
    first_manifest = write_run_manifest(first_id, (), root=tmp_path)

    candidate = current.model_copy(
        update={"controls": current.controls.model_copy(update={"horizon": "6M"})}
    )
    save_settings(candidate, expected_revision=current.revision, root=tmp_path)
    second_id = settings_bound_run_id("features_latest", root=tmp_path)
    second_manifest = write_run_manifest(second_id, (), root=tmp_path)

    assert first_id != second_id
    assert first_manifest != second_manifest
    assert first_manifest.is_file() and second_manifest.is_file()


def test_atomic_group_precondition_fails_before_any_destination_is_replaced(tmp_path: Path) -> None:
    destination = tmp_path / "configs" / "settings.yaml"
    destination.parent.mkdir(parents=True)
    destination.write_text("old\n", encoding="utf-8")
    request = AtomicWriteRequest(destination, b"new\n", lambda path: path.read_bytes())

    with pytest.raises(RuntimeError, match="revision changed"):
        atomic_write_group((request,), precondition=lambda: (_ for _ in ()).throw(RuntimeError("revision changed")))

    assert destination.read_text(encoding="utf-8") == "old\n"
