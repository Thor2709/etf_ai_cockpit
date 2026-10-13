
import pytest

from etf_cockpit.core import install_defaults, runtime
from etf_cockpit.core.migrations import default_migration_context, run_migrations


def test_owner_upgrade_is_atomic_preserves_records_and_is_idempotent(tmp_path, monkeypatch):
    root = tmp_path / "install"
    configs = root / "configs"
    configs.mkdir(parents=True)
    custom = configs / "sparebank_scorecard_v1.yaml"
    custom.write_bytes(b"owner_custom: true\n")
    universe = configs / "universe.yaml"
    universe.write_bytes(b"etfs: []\n")
    records = root / "data" / "clean" / "instrument_identity.csv"
    records.parent.mkdir(parents=True)
    records.write_bytes(b"instrument_id,isin\nlegacy,\n")
    original = {path: path.read_bytes() for path in (custom, universe, records)}
    publish = install_defaults.atomic_write_group

    def fail_publication(requests, **kwargs):
        def fail(state, _journal):
            if state == "prepared":
                raise OSError("simulated upgrade failure")
        return publish(requests, lifecycle_hook=fail, **kwargs)

    monkeypatch.setattr(install_defaults, "atomic_write_group", fail_publication)
    with pytest.raises(OSError, match="simulated upgrade failure"):
        install_defaults.ensure_install_defaults(root)
    assert all(path.read_bytes() == value for path, value in original.items())
    assert not (configs / "analysis_depth_profiles.yaml").exists()
    monkeypatch.setattr(install_defaults, "atomic_write_group", publish)
    monkeypatch.setattr(runtime, "ROOT", root)
    monkeypatch.setattr(runtime, "LOG_DIR", root / "logs")
    monkeypatch.setattr(runtime, "ensure_project_dirs", lambda: None)
    runtime.configure_runtime_environment()
    assert all((configs / name).is_file() for name in install_defaults.UPGRADE_CONFIGS)
    assert all(path.read_bytes() == value for path, value in original.items())
    context = default_migration_context(root)
    run_migrations(context)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
              for path in root.rglob("*") if path.is_file()}
    runtime.configure_runtime_environment()
    assert run_migrations(context).applied_versions == ()
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
             for path in root.rglob("*") if path.is_file()}
    assert after == before
    assert all(path.read_bytes() == value for path, value in original.items())
