from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import smoke_app


def test_source_smoke_preserves_selected_install(tmp_path, monkeypatch):
    root = tmp_path / "install"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "universe.yaml").write_text("etfs: []\n", encoding="utf-8")
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(root))
    captured = {}
    python = Path(smoke_app.sys.executable)
    process = SimpleNamespace(args=[str(python)])

    def spawn(command, **kwargs):
        captured.update(kwargs)
        captured["command"] = command
        return process

    monkeypatch.setattr(smoke_app.launcher_core, "resolve_python", lambda _: python)
    monkeypatch.setattr(smoke_app.subprocess, "Popen", spawn)
    monkeypatch.setattr(smoke_app, "_wait_for_process_ready", lambda proc, *_: proc)
    assert smoke_app._ensure_source_ready(8611, 1) is process
    assert captured["env"]["ETF_COCKPIT_ROOT"] == str(root.resolve())
    assert captured["env"]["ETF_COCKPIT_OPEN_BROWSER"] == "0"
    assert captured["env"]["ETF_COCKPIT_PORT"] == "8611"
    assert captured["command"][1] == str(smoke_app.ROOT / "scripts" / "run_app.py")


def test_launcher_smoke_preserves_selected_install(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "universe.yaml").write_text("etfs: []\n", encoding="utf-8")
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))
    captured = {}
    python = Path(smoke_app.sys.executable)
    process = SimpleNamespace(args=[str(python)])

    def spawn(command, **kwargs):
        captured.update(kwargs)
        return process

    monkeypatch.setattr(smoke_app.launcher_core, "_launch_command", lambda *_, **__: ([str(python)], smoke_app.ROOT))
    monkeypatch.setattr(smoke_app.launcher_core, "_spawn", spawn)
    monkeypatch.setattr(smoke_app, "_wait_for_process_ready", lambda proc, *_: proc)
    assert smoke_app._ensure_mode_ready("source", 8611, 1) is process
    assert captured["env"]["ETF_COCKPIT_ROOT"] == str(tmp_path.resolve())


def test_smoke_without_selected_install_uses_checkout(monkeypatch):
    monkeypatch.delenv("ETF_COCKPIT_ROOT", raising=False)
    assert smoke_app._runtime_root() == smoke_app.ROOT


def test_smoke_rejects_data_only_root_before_starting(tmp_path, monkeypatch):
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))

    def unexpected_check():
        pytest.fail("Smoke continued despite an invalid selected root")

    monkeypatch.setattr(smoke_app, "verify_ui_action_inventory", unexpected_check)
    with pytest.raises(RuntimeError, match="must contain configs/universe.yaml"):
        smoke_app.main(["--port", "8611"])


def test_smoke_inventory_uses_current_code_contracts(tmp_path, monkeypatch):
    from etf_cockpit.core import ui_acceptance

    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))
    original_loader = ui_acceptance.load_ui_acceptance_contracts
    loaded_paths = []

    def load_contracts(path=None):
        loaded_paths.append(path)
        return original_loader(path)

    monkeypatch.setattr(ui_acceptance, "load_ui_acceptance_contracts", load_contracts)
    smoke_app.verify_ui_action_inventory()
    assert loaded_paths == [smoke_app.ROOT / "configs" / "ui_acceptance.yaml"]
