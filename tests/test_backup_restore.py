from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import uuid

import pytest

import etf_cockpit.data.backup_restore as backup_restore
from etf_cockpit.application.settings import load_settings_bundle, save_settings
from etf_cockpit.data.backup_restore import (
    apply_backup_retention,
    commit_incremental_restore,
    commit_restore,
    create_backup,
    create_encrypted_backup,
    create_incremental_backup,
    restore_encrypted_backup,
    run_disaster_recovery_drill,
    validate_encrypted_restore,
    validate_restore,
)


def _copy_repository_configs(destination: Path) -> Path:
    source = Path(__file__).parents[1] / "configs"
    config_dir = destination / "configs"
    config_dir.mkdir(parents=True)
    required = (
        "settings.yaml",
        "universe.yaml",
        "portfolio_targets.yaml",
        "risk_limits.yaml",
        "costs.yaml",
        "model_settings.yaml",
        "data_providers.yaml",
    )
    for name in required:
        shutil.copy2(source / name, config_dir / name)
    return config_dir


def _write_manifest_archive(
    archive_path: Path,
    payloads: dict[str, bytes],
    *,
    base_manifest_checksum: str | None = None,
) -> str:
    """Build a minimal archive manifest using the restore linkage contract."""

    checksums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    manifest: dict[str, object] = {
        "schema_version": 2 if base_manifest_checksum is not None else 1,
        "checksums": checksums,
        "excluded": [],
    }
    if base_manifest_checksum is not None:
        manifest["incremental"] = True
        manifest["base_manifest_checksum"] = base_manifest_checksum
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", manifest_bytes)
    return hashlib.sha256(manifest_bytes).hexdigest()


def _make_destination_with_configs(tmp_path: Path) -> tuple[Path, Path]:
    destination = tmp_path / "destination"
    return destination, _copy_repository_configs(destination)


@pytest.fixture(autouse=True)
def _isolated_temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep backup validation staging writable and isolated per test case."""

    temp_root = tmp_path / "system-temp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    monkeypatch.setenv("TEMP", str(temp_root))
    monkeypatch.setenv("TMP", str(temp_root))
    monkeypatch.setenv("TMPDIR", str(temp_root))

    def make_temp_dir(*, prefix: str = "tmp", **_: object) -> str:
        path = temp_root / f"{prefix}{uuid.uuid4().hex[:8]}"
        path.mkdir()
        return str(path)

    monkeypatch.setattr(tempfile, "mkdtemp", make_temp_dir)


def test_backup_restore_round_trip_and_manifest_checksums(tmp_path: Path) -> None:
    source = tmp_path / "data" / "safe.txt"
    source.parent.mkdir(parents=True)
    source.write_text("safe: true\n", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    manifest = create_backup([source], archive)
    preview = validate_restore(archive)
    assert preview.valid is True
    destination = tmp_path / "restored"
    result = commit_restore(preview, destination)
    assert result.restored == 1
    assert (destination / "data" / "safe.txt").read_text(encoding="utf-8") == "safe: true\n"
    assert manifest.checksums
    assert manifest.execution_allowed is False


def test_authentic_settings_bundle_round_trip_is_byte_identical(tmp_path: Path) -> None:
    repository_configs = Path(__file__).parents[1] / "configs"
    source_configs = tmp_path / "source" / "configs"
    destination = tmp_path / "destination"
    source_configs.mkdir(parents=True)
    destination_configs = destination / "configs"
    destination_configs.mkdir(parents=True)
    required = (
        "settings.yaml",
        "universe.yaml",
        "portfolio_targets.yaml",
        "risk_limits.yaml",
        "costs.yaml",
        "model_settings.yaml",
        "data_providers.yaml",
    )
    for name in required:
        payload = (repository_configs / name).read_bytes()
        (source_configs / name).write_bytes(payload)
        (destination_configs / name).write_bytes(payload)
    archive = tmp_path / "authentic.backup"
    create_backup([source_configs], archive)
    preview = validate_restore(archive)
    assert preview.valid is True, preview.errors
    result = commit_restore(preview, destination)
    assert result.ok is True
    for name in required:
        assert (destination_configs / name).read_bytes() == (source_configs / name).read_bytes()


def test_settings_revision_mismatch_is_rejected_before_writes(tmp_path: Path) -> None:
    repository_configs = Path(__file__).parents[1] / "configs"
    source_configs = tmp_path / "source" / "configs"
    destination = tmp_path / "destination"
    source_configs.mkdir(parents=True)
    destination_configs = destination / "configs"
    destination_configs.mkdir(parents=True)
    required = ("settings.yaml", "universe.yaml", "portfolio_targets.yaml", "risk_limits.yaml", "costs.yaml", "model_settings.yaml", "data_providers.yaml")
    for name in required:
        payload = (repository_configs / name).read_bytes()
        source_configs.joinpath(name).write_bytes(payload)
        destination_configs.joinpath(name).write_bytes(payload)
    settings = source_configs / "settings.yaml"
    settings.write_text(settings.read_text(encoding="utf-8").replace("revision: ", "revision: " + "0" * 64 + " # ", 1), encoding="utf-8")
    before = {name: destination_configs.joinpath(name).read_bytes() for name in required}
    archive = tmp_path / "mismatch.backup"
    create_backup([source_configs], archive)
    preview = validate_restore(archive, destination=destination)
    assert preview.valid is False
    assert any("settings_revision_mismatch" in error for error in preview.errors)
    result = commit_restore(preview, destination)
    assert result.ok is False
    assert {name: destination_configs.joinpath(name).read_bytes() for name in required} == before


def test_commit_restore_rechecks_companions_after_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination, destination_configs = _make_destination_with_configs(tmp_path)
    source_settings = tmp_path / "source" / "configs" / "settings.yaml"
    source_settings.parent.mkdir(parents=True)
    source_settings.write_bytes(destination_configs.joinpath("settings.yaml").read_bytes())
    archive = tmp_path / "settings-only.backup"
    create_backup([source_settings], archive)
    preview = validate_restore(archive, destination=destination)
    assert preview.valid is True, preview.errors

    settings_before = destination_configs.joinpath("settings.yaml").read_bytes()
    risk_limits = destination_configs / "risk_limits.yaml"
    original_validate_restore = backup_restore.validate_restore
    changed = False

    def validate_then_change(*args, **kwargs):
        nonlocal changed
        result = original_validate_restore(*args, **kwargs)
        if kwargs.get("destination") == destination and not changed:
            risk_limits.write_text(
                risk_limits.read_text(encoding="utf-8").replace("max_single_etf_weight: 0.35", "max_single_etf_weight: 0.34", 1),
                encoding="utf-8",
            )
            changed = True
        return result

    monkeypatch.setattr(backup_restore, "validate_restore", validate_then_change)
    result = commit_restore(preview, destination)
    assert result.ok is False
    assert "stale" in result.error or "revision" in result.error
    assert destination_configs.joinpath("settings.yaml").read_bytes() == settings_before


def test_restore_checksum_validator_rolls_back_on_post_write_mismatch(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "data" / "safe.txt"
    source.parent.mkdir(parents=True)
    source.write_text("new", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    create_backup([source], archive)
    destination = tmp_path / "restored"
    existing = destination / "data" / "safe.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("old", encoding="utf-8")
    preview = validate_restore(archive)

    import etf_cockpit.data.backup_restore as backup_restore

    original = backup_restore._checksum_validator

    def mismatch(expected: str, name: str):
        validator = original(expected, name)

        def validate(path: Path) -> None:
            path.write_bytes(b"tampered")
            validator(path)

        return validate

    monkeypatch.setattr(backup_restore, "_checksum_validator", mismatch)
    result = commit_restore(preview, destination)
    assert result.ok is False
    assert existing.read_text(encoding="utf-8") == "old"


def test_restore_rejects_zip_traversal(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../secret.txt", "bad")
    assert validate_restore(archive).valid is False


def test_commit_restore_rejects_destination_symlink_or_junction(tmp_path: Path) -> None:
    source = tmp_path / "source" / "data" / "x.txt"
    source.parent.mkdir(parents=True)
    source.write_text("must not escape", encoding="utf-8")
    archive = tmp_path / "payload.backup"
    create_backup([source], archive)
    preview = validate_restore(archive)

    destination = tmp_path / "destination"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = destination / "data"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as symlink_error:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"cannot create symlink ({symlink_error}) or directory junction ({completed.stderr.strip()})")

    result = commit_restore(preview, destination)
    assert result.ok is False
    assert any(token in result.error.casefold() for token in ("symlink", "reparse", "escapes destination root"))
    assert not (outside / "x.txt").exists()


def test_restore_rejects_unapproved_repository_payload_roots(tmp_path: Path) -> None:
    import hashlib
    import json
    import zipfile

    archive = tmp_path / "unapproved.zip"
    payload_name = "src/main.py"
    payload = b"print('not a restore payload')\n"
    checksums = {payload_name: hashlib.sha256(payload).hexdigest()}
    manifest = json.dumps({"schema_version": 1, "checksums": checksums}, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(payload_name, payload)
        z.writestr("manifest.json", manifest)
    preview = validate_restore(archive)
    assert preview.valid is False
    assert any("unapproved" in error for error in preview.errors)


def test_backup_manifest_is_deterministic_and_excludes_secret_and_caches(tmp_path: Path) -> None:
    data = tmp_path / "data" / "prices.csv"
    data.parent.mkdir(parents=True)
    data.write_text("x,1\n", encoding="utf-8")
    secret = tmp_path / "configs" / ".env"
    secret.parent.mkdir(parents=True)
    secret.write_text("TOKEN=do-not-export\n", encoding="utf-8")
    cache = tmp_path / "logs" / "run.log"
    cache.parent.mkdir(parents=True)
    cache.write_text("transient", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    manifest = create_backup([data, secret, cache], archive)
    assert list(manifest.checksums) == ["data/prices.csv"]
    assert manifest.schema_version == 1
    assert manifest.manifest_checksum


def test_failed_restore_does_not_replace_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "data" / "safe.txt"
    source.parent.mkdir(parents=True)
    source.write_text("new", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    create_backup([source], archive)
    destination = tmp_path / "restored"
    destination.mkdir()
    existing = destination / "data" / "safe.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("old", encoding="utf-8")
    preview = validate_restore(archive)
    preview = type(preview)(preview.archive, False, preview.entries, ("forced_failure",))
    result = commit_restore(preview, destination)
    assert result.ok is False
    assert existing.read_text(encoding="utf-8") == "old"


def test_backup_scans_contents_and_records_secret_exclusions(tmp_path: Path) -> None:
    payload = tmp_path / "configs" / "settings.yaml"
    payload.parent.mkdir(parents=True)
    payload.write_text("provider: local\napi_key: super-secret-token\n", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    manifest = create_backup([payload], archive)
    assert "configs/settings.yaml" in manifest.excluded
    assert "configs/settings.yaml" not in manifest.checksums
    with __import__("zipfile").ZipFile(archive) as z:
        assert all("super-secret-token" not in value.decode("utf-8", "ignore") for value in (z.read(name) for name in z.namelist()))


def test_secret_content_parses_structured_json_yaml_and_real_provider_config(tmp_path: Path) -> None:
    secret_content = backup_restore._secret_content
    assert secret_content(b'{"api_key":"real-token"}', tmp_path / "payload.json") is True
    assert secret_content(b'{"api_key":""}', tmp_path / "payload.json") is False
    assert secret_content(b'{"api_key":null}', tmp_path / "payload.json") is False
    assert secret_content(b"api_key: |\n  real-token\n", tmp_path / "payload.yaml") is True
    repository_config = Path(__file__).parents[1] / "configs" / "data_providers.yaml"
    assert secret_content(repository_config.read_bytes(), repository_config) is False

    payload = tmp_path / "data" / "payload.json"
    payload.parent.mkdir(parents=True)
    payload.write_text('{"api_key":"real-token"}\n', encoding="utf-8")
    manifest = create_backup([payload], tmp_path / "secret.backup")
    assert "data/payload.json" in manifest.excluded
    assert "data/payload.json" not in manifest.checksums


def test_backup_manifest_keeps_actual_version_and_changelog_metadata_paths(tmp_path: Path) -> None:
    version = tmp_path / "pyproject.toml"
    changelog = tmp_path / "CHANGELOG.md"
    version.write_text("[project]\nversion = '0.1.0'\n", encoding="utf-8")
    changelog.write_text("# Changes\n", encoding="utf-8")
    manifest = create_backup([version, changelog], tmp_path / "metadata.zip")
    assert set(manifest.checksums) == {"pyproject.toml", "CHANGELOG.md"}


def test_restore_rejects_unsupported_known_payload_schema_before_writes(tmp_path: Path) -> None:
    import json
    import zipfile

    archive = tmp_path / "unsupported.zip"
    payload_name = "configs/settings.json"
    payload = json.dumps({"schema_version": 999, "safe": True}).encode("utf-8")
    checksums = {payload_name: __import__("hashlib").sha256(payload).hexdigest()}
    manifest = json.dumps({"schema_version": 1, "checksums": checksums}, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(payload_name, payload)
        z.writestr("manifest.json", manifest)
    preview = validate_restore(archive)
    assert preview.valid is False
    assert any("schema" in error for error in preview.errors)
    destination = tmp_path / "restored"
    assert not destination.exists()


def test_restore_rejects_non_numeric_known_payload_schema_version(tmp_path: Path) -> None:
    import json
    import zipfile

    archive = tmp_path / "non-numeric-schema.zip"
    payload_name = "configs/settings.json"
    payload = json.dumps({"schema_version": "future", "safe": True}).encode("utf-8")
    checksums = {payload_name: __import__("hashlib").sha256(payload).hexdigest()}
    manifest = json.dumps({"schema_version": 1, "checksums": checksums}, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(payload_name, payload)
        z.writestr("manifest.json", manifest)
    preview = validate_restore(archive)
    assert preview.valid is False
    assert any("schema" in error for error in preview.errors)


def test_restore_rejects_unsupported_named_known_payload_schema_version(tmp_path: Path) -> None:
    import hashlib
    import json
    import zipfile

    archive = tmp_path / "named-schema.zip"
    payload_name = "configs/settings.json"
    payload = json.dumps({"schema_version": "settings_bundle.v999", "safe": True}).encode("utf-8")
    checksums = {payload_name: hashlib.sha256(payload).hexdigest()}
    manifest = json.dumps({"schema_version": 1, "checksums": checksums}, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(payload_name, payload)
        z.writestr("manifest.json", manifest)
    preview = validate_restore(archive)
    assert preview.valid is False
    assert any("unsupported_schema_version" in error for error in preview.errors)


def test_encrypted_backup_round_trip_and_wrong_key_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "data" / "journal.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"decision":"hold"}\n', encoding="utf-8")
    archive = tmp_path / "backups" / "encrypted.backup"

    manifest = create_encrypted_backup([source], archive, recovery_key="correct recovery key")
    assert manifest.encrypted is True
    assert validate_encrypted_restore(archive, "wrong recovery key").valid is False
    result = restore_encrypted_backup(archive, tmp_path / "restored", "correct recovery key")
    assert result.ok is True
    assert (tmp_path / "restored" / "data" / "journal.json").read_text(encoding="utf-8") == '{"decision":"hold"}\n'


def test_encrypted_partial_preview_checks_destination_consistency(tmp_path: Path) -> None:
    destination, destination_configs = _make_destination_with_configs(tmp_path)
    source_settings = tmp_path / "source" / "configs" / "settings.yaml"
    source_settings.parent.mkdir(parents=True)
    source_settings.write_bytes(destination_configs.joinpath("settings.yaml").read_bytes())
    key = "correct recovery key"
    archive = tmp_path / "settings-only.encrypted.backup"
    create_encrypted_backup([source_settings], archive, recovery_key=key)
    preview = validate_encrypted_restore(archive, key, destination=destination)
    assert preview.valid is True, preview.errors

    mismatch = tmp_path / "mismatch" / "configs" / "settings.yaml"
    mismatch.parent.mkdir(parents=True)
    mismatch.write_text(source_settings.read_text(encoding="utf-8").replace("revision: ", "revision: " + "0" * 64 + " # ", 1), encoding="utf-8")
    mismatch_archive = tmp_path / "mismatch.encrypted.backup"
    create_encrypted_backup([mismatch], mismatch_archive, recovery_key=key)
    mismatch_preview = validate_encrypted_restore(mismatch_archive, key, destination=destination)
    assert mismatch_preview.valid is False
    assert any("settings_revision_mismatch" in error for error in mismatch_preview.errors)


def test_config_validation_staging_cleans_up_and_excludes_destination_secrets(tmp_path: Path, monkeypatch) -> None:
    destination, destination_configs = _make_destination_with_configs(tmp_path)
    token = "stage-sentinel"
    (destination_configs / "credentials.json").write_text(json.dumps({"api_key": token}), encoding="utf-8")
    source_settings = tmp_path / "source" / "configs" / "settings.yaml"
    source_settings.parent.mkdir(parents=True)
    source_settings.write_bytes(destination_configs.joinpath("settings.yaml").read_bytes())
    archive = tmp_path / "settings-only.backup"
    create_backup([source_settings], archive)

    temp_root = Path(tempfile.gettempdir())
    before_temp = set(temp_root.glob("restore-config-*"))
    before_adjacent = set(destination.parent.glob("restore-config-*"))
    writes: list[tuple[Path, bytes]] = []
    copied_secrets: list[Path] = []
    original_write_bytes = Path.write_bytes
    original_copytree = shutil.copytree

    def record_write(path: Path, data: bytes) -> int:
        writes.append((path, data))
        return original_write_bytes(path, data)

    def observe_copytree(source: Path, target: Path, *args, **kwargs):
        result = original_copytree(source, target, *args, **kwargs)
        secret_target = Path(target) / "credentials.json"
        if secret_target.exists():
            copied_secrets.append(secret_target)
        return result

    monkeypatch.setattr(Path, "write_bytes", record_write)
    monkeypatch.setattr(shutil, "copytree", observe_copytree)
    preview = validate_restore(archive, destination=destination)
    assert preview.valid is True, preview.errors
    assert all(token.encode("utf-8") not in data for _, data in writes)
    assert all(path.name != "credentials.json" for path, _ in writes)
    assert copied_secrets == []
    assert set(temp_root.glob("restore-config-*")) == before_temp
    assert set(destination.parent.glob("restore-config-*")) == before_adjacent


def test_encrypted_backup_corruption_is_reported_without_writes(tmp_path: Path) -> None:
    source = tmp_path / "data" / "journal.json"
    source.parent.mkdir(parents=True)
    source.write_text("safe\n", encoding="utf-8")
    archive = tmp_path / "encrypted.backup"
    create_encrypted_backup([source], archive, recovery_key="correct recovery key")
    archive.write_bytes(archive.read_bytes()[:-4] + b"bad!")

    preview = validate_encrypted_restore(archive, "correct recovery key")
    assert preview.valid is False
    assert not (tmp_path / "restored").exists()


def test_incremental_backup_restores_base_then_changed_payloads(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    first = data / "first.txt"
    second = data / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    base_archive = tmp_path / "base.backup"
    base = create_backup([data], base_archive)
    second.write_text("changed", encoding="utf-8")
    incremental = create_incremental_backup([data], tmp_path / "incremental.backup", base)
    assert incremental.incremental is True
    assert list(incremental.checksums) == ["data/second.txt"]

    previews = [validate_restore(base_archive), validate_restore(tmp_path / "incremental.backup")]
    result = commit_incremental_restore(previews, tmp_path / "restored")
    assert result.ok is True
    assert (tmp_path / "restored" / "data" / "second.txt").read_text(encoding="utf-8") == "changed"


def test_incremental_restore_rejects_invalid_final_composition_without_writes(tmp_path: Path) -> None:
    destination, destination_configs = _make_destination_with_configs(tmp_path)
    base_archive = tmp_path / "base-configs.backup"
    required = (
        "settings.yaml",
        "universe.yaml",
        "portfolio_targets.yaml",
        "risk_limits.yaml",
        "costs.yaml",
        "model_settings.yaml",
        "data_providers.yaml",
    )
    base_manifest = create_backup([destination_configs / name for name in required], base_archive)
    base_preview = validate_restore(base_archive, destination=destination)
    assert base_preview.valid is True, base_preview.errors

    variant_a = tmp_path / "variant-a"
    shutil.copytree(destination, variant_a)
    bundle_a = load_settings_bundle(variant_a)
    risks = dict(bundle_a.risks)
    portfolio_limits = dict(risks["portfolio_limits"])
    portfolio_limits["max_single_etf_weight"] = 0.34
    risks["portfolio_limits"] = portfolio_limits
    save_settings(bundle_a.model_copy(update={"risks": risks}), expected_revision=bundle_a.revision, root=variant_a)
    increment_a = tmp_path / "increment-a.backup"
    increment_a_manifest_checksum = _write_manifest_archive(
        increment_a,
        {
            "configs/settings.yaml": (variant_a / "configs" / "settings.yaml").read_bytes(),
            "configs/risk_limits.yaml": (variant_a / "configs" / "risk_limits.yaml").read_bytes(),
        },
        base_manifest_checksum=base_manifest.manifest_checksum,
    )

    variant_b = tmp_path / "variant-b"
    shutil.copytree(destination, variant_b)
    bundle_b = load_settings_bundle(variant_b)
    targets = dict(bundle_b.targets)
    positions = dict(targets["positions"])
    vwce = dict(positions["VWCE"])
    vwce["soft_band"] = 0.06
    positions["VWCE"] = vwce
    targets["positions"] = positions
    save_settings(bundle_b.model_copy(update={"targets": targets}), expected_revision=bundle_b.revision, root=variant_b)
    increment_b = tmp_path / "increment-b.backup"
    _write_manifest_archive(
        increment_b,
        {
            "configs/settings.yaml": (variant_b / "configs" / "settings.yaml").read_bytes(),
            "configs/portfolio_targets.yaml": (variant_b / "configs" / "portfolio_targets.yaml").read_bytes(),
        },
        base_manifest_checksum=increment_a_manifest_checksum,
    )

    preview_a = validate_restore(increment_a, destination=destination)
    preview_b = validate_restore(increment_b, destination=destination)
    assert preview_a.valid is True, preview_a.errors
    assert preview_b.valid is True, preview_b.errors
    before = {
        name: (destination_configs / name).read_bytes()
        for name in ("settings.yaml", "risk_limits.yaml", "portfolio_targets.yaml")
    }
    result = commit_incremental_restore([base_preview, preview_a, preview_b], destination)
    assert result.ok is False
    assert "revision" in result.error or "consistency" in result.error
    assert {
        name: (destination_configs / name).read_bytes()
        for name in ("settings.yaml", "risk_limits.yaml", "portfolio_targets.yaml")
    } == before


def test_retention_keeps_newest_backups_and_recovery_drill_is_validated(tmp_path: Path) -> None:
    source = tmp_path / "data" / "safe.txt"
    source.parent.mkdir(parents=True)
    source.write_text("safe", encoding="utf-8")
    backups = tmp_path / "backups"
    backups.mkdir()
    for index in range(3):
        create_backup([source], backups / f"backup-{index}.backup")
    removed = apply_backup_retention(backups, keep=2)
    assert len(removed) == 1
    drill = run_disaster_recovery_drill([source], tmp_path / "drill", recovery_key="correct recovery key")
    assert drill.ok is True
    assert drill.restored_files == 1
