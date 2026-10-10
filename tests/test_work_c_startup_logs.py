from pathlib import Path

from etf_cockpit.app import flet_app


def test_startup_log_directory_uses_install_root_not_working_directory(tmp_path, monkeypatch):
    log_dir = tmp_path / "install" / "logs"
    monkeypatch.setattr(flet_app, "LOG_DIR", log_dir)
    monkeypatch.chdir(tmp_path)

    assert flet_app._log_dir() == log_dir


def test_startup_diagnostics_are_written_under_install_root(tmp_path, monkeypatch):
    log_dir = tmp_path / "install" / "logs"
    monkeypatch.setattr(flet_app, "LOG_DIR", log_dir)
    monkeypatch.chdir(tmp_path)

    flet_app._startup_log("Local data could not be loaded")

    assert "Local data could not be loaded" in (log_dir / "startup.log").read_text(encoding="utf-8")
    assert not (tmp_path / "logs").exists()


def test_windowed_output_logs_are_written_under_install_root(tmp_path, monkeypatch):
    log_dir = tmp_path / "install" / "logs"
    monkeypatch.setattr(flet_app, "LOG_DIR", log_dir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(flet_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(flet_app.sys, "stdout", None)
    monkeypatch.setattr(flet_app.sys, "stderr", None)
    handles = []
    monkeypatch.setattr(flet_app, "_STDIO_HANDLES", handles)

    try:
        flet_app._attach_windowed_stdio()
        assert [Path(handle.name) for handle in handles] == [log_dir / "stdout.log", log_dir / "stderr.log"]
        flet_app.sys.stdout.write("Startup output\n")
        flet_app.sys.stderr.write("Startup failure\n")
        for handle in handles:
            handle.flush()
        assert (log_dir / "stdout.log").read_text(encoding="utf-8") == "Startup output\n"
        assert (log_dir / "stderr.log").read_text(encoding="utf-8") == "Startup failure\n"
        assert not (tmp_path / "logs").exists()
    finally:
        for handle in handles:
            handle.close()
