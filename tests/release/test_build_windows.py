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
    assert "pyinstaller.exe\" --noconfirm --clean" in lowered
    assert "etf_ai_cockpit.spec" in lowered
    assert "pyi-set_version.exe" in lowered
    assert "if errorlevel 1 exit /b 1" in lowered


def test_pyinstaller_spec_resolves_resources_without_relying_on_missing_file() -> None:
    spec = (ROOT / "ETF_AI_Cockpit.spec").read_text(encoding="utf-8")

    assert "globals().get('SPECPATH'" in spec or 'globals().get("SPECPATH"' in spec


def test_windows_build_packages_third_party_notices() -> None:
    script = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8").lower()

    assert "third_party_notices.md" in script
