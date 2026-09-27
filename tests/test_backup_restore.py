from __future__ import annotations

from pathlib import Path

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
