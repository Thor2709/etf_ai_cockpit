from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_build_and_generated_native_launcher_use_cmd_only() -> None:
    script = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")
    lowered = script.lower()

    assert "powershell" not in lowered
    assert "start-sleep" not in lowered
    assert "timeout /t 1 /nobreak" in lowered


def test_broken_venv_backup_remains_timestamped_and_package_gates_are_intact() -> None:
    script = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")
    lowered = script.lower()

    assert "venv_broken_" in lowered
    assert "%date%" in lowered
    assert "%time%" in lowered
    assert 'move ".venv"' in lowered
    assert 'pip.exe" install -r requirements.txt' in lowered
    assert 'pip.exe" install -r requirements-parsers.txt' in lowered
    assert "flet.exe\" pack" in lowered
    assert "if errorlevel 1 exit /b 1" in lowered
