from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts import launcher_core


def test_normalise_port_validates_user_input() -> None:
    assert launcher_core.normalise_port(None) == 8550
    assert launcher_core.normalise_port("8551") == 8551
    with pytest.raises(ValueError):
        launcher_core.normalise_port("not-a-port")
    with pytest.raises(ValueError):
        launcher_core.normalise_port("80")


def test_choose_launch_port_reuses_ready_existing_http(monkeypatch) -> None:
    monkeypatch.setattr(launcher_core, "probe_http_ready", lambda host, port, timeout_s=1.0: True)
    monkeypatch.setattr(launcher_core, "is_tcp_port_busy", lambda host, port: True)

    decision = launcher_core.choose_launch_port("127.0.0.1", 8550)

    assert decision.reuse_existing is True
    assert decision.port == 8550
    assert decision.url == "http://127.0.0.1:8550/"


def test_choose_launch_port_falls_back_when_preferred_port_is_busy_but_not_http_ready(monkeypatch) -> None:
    monkeypatch.setattr(launcher_core, "probe_http_ready", lambda host, port, timeout_s=1.0: False)
    monkeypatch.setattr(launcher_core, "is_tcp_port_busy", lambda host, port: port == 8550)

    decision = launcher_core.choose_launch_port("127.0.0.1", 8550)

    assert decision.reuse_existing is False
    assert decision.requested_port == 8550
    assert decision.port == 8551
    assert "busy but not HTTP-ready" in decision.reason


def test_resolve_app_root_accepts_source_and_portable_layouts(tmp_path, monkeypatch) -> None:
    source_root = _make_source_root(tmp_path / "source")
    portable_root = _make_portable_root(tmp_path / "portable")

    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(source_root))
    assert launcher_core.resolve_app_root() == source_root.resolve()

    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(portable_root))
    assert launcher_core.resolve_app_root() == portable_root.resolve()


def test_prepare_build_directory_quarantines_locked_folder(tmp_path, monkeypatch) -> None:
    target = tmp_path / "flet_dist"
    target.mkdir()
    (target / "locked.txt").write_text("locked", encoding="utf-8")

    def raise_locked(_path: Path) -> None:
        raise PermissionError("simulated lock")

    monkeypatch.setattr(shutil, "rmtree", raise_locked)

    result = launcher_core.prepare_build_directory(target)

    assert result.status == "quarantined"
    assert not target.exists()
    assert result.quarantined_path is not None
    assert result.quarantined_path.exists()
    assert (result.quarantined_path / "locked.txt").read_text(encoding="utf-8") == "locked"


def test_prepare_output_directory_can_use_fresh_alternate_when_locked(tmp_path, monkeypatch) -> None:
    target = tmp_path / "portable"
    target.mkdir()

    def raise_locked(_path: Path):
        raise RuntimeError("simulated locked folder")

    monkeypatch.setattr(launcher_core, "prepare_build_directory", raise_locked)

    result = launcher_core.prepare_output_directory(target, allow_alternate=True)

    assert result.status == "alternate"
    assert result.path.parent == target.parent
    assert result.path.name.startswith("portable_")
    assert result.path != target.resolve()


def test_batch_launchers_delegate_readiness_to_launcher_core() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("ETF_AI_Cockpit.bat", "Run_ETF_AI_Cockpit_EXE.bat", "Launch_Latest_ETF_AI_Cockpit.bat", "scripts/build_windows.bat"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "launcher_core.py" in text, relative


def test_root_native_launchers_use_selected_native_output_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("ETF_AI_Cockpit.bat", "Run_ETF_AI_Cockpit_EXE.bat"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "build\\native_outdir.txt" in text, relative
        assert 'set /p NATIVE_OUTDIR=<"%NATIVE_OUTDIR_FILE%"' in text, relative
        assert "set EXE=%NATIVE_OUTDIR%\\ETF_AI_Cockpit\\ETF_AI_Cockpit.exe" in text, relative
        assert '--exe "%EXE%"' in text, relative


def test_latest_launcher_uses_portable_output_selected_by_build() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "Launch_Latest_ETF_AI_Cockpit.bat").read_text(encoding="utf-8")

    assert "build\\portable_outdir.txt" in text
    assert 'set /p PORTABLE=<"%PORTABLE_OUTDIR_FILE%"' in text
    assert "set RUNNER=%PORTABLE%\\Run_ETF_AI_Cockpit_EXE.bat" in text
    assert 'call "%RUNNER%"' in text
    assert 'set ETF_COCKPIT_ROOT=%PORTABLE%' in text


def test_default_native_exe_uses_build_selected_output_manifest(tmp_path) -> None:
    root = _make_source_root(tmp_path / "app")
    selected = root / "build" / "flet_dist_20260710_200611" / "ETF_AI_Cockpit"
    selected.mkdir(parents=True)
    executable = selected / "ETF_AI_Cockpit.exe"
    executable.write_bytes(b"native")
    (root / "build").mkdir(exist_ok=True)
    (root / "build" / "native_outdir.txt").write_text(str(selected.parents[0]), encoding="utf-8")

    assert launcher_core._default_native_exe(root, portable=False) == executable.resolve()


def test_default_portable_exe_uses_build_selected_output_manifest(tmp_path) -> None:
    root = _make_source_root(tmp_path / "app")
    selected = root / "build" / "portable_20260710_200611" / "native" / "ETF_AI_Cockpit"
    selected.mkdir(parents=True)
    executable = selected / "ETF_AI_Cockpit.exe"
    executable.write_bytes(b"portable-native")
    (root / "build" / "portable_outdir.txt").write_text(str(selected.parents[1]), encoding="utf-8")

    assert launcher_core._default_native_exe(root, portable=True) == executable.resolve()


def test_windows_build_uses_fresh_native_staging_when_default_is_locked() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build_windows.bat").read_text(encoding="utf-8")

    assert "setlocal EnableExtensions EnableDelayedExpansion" in text
    assert "set NATIVE_OUT_ROOT=build\\flet_dist" in text
    assert "set NATIVE_OUT_ROOT_FILE=build\\native_outdir.txt" in text
    assert 'prepare-output-dir "%NATIVE_OUT_ROOT%" --allow-alternate --path-file "%NATIVE_OUT_ROOT_FILE%"' in text
    assert 'set /p NATIVE_OUT_ROOT=<"%NATIVE_OUT_ROOT_FILE%"' in text
    assert '--distpath "!NATIVE_OUT_ROOT!"' in text
    assert "set NATIVE_DIST=!NATIVE_OUT_ROOT!\\%APPNAME%" in text
    assert 'if exist "!NATIVE_DIST!\\%APPNAME%.exe" set NATIVE_PACK_READY=1' in text
    assert '> "%NATIVE_OUT_ROOT_FILE%" echo !NATIVE_OUT_ROOT!' in text


def _make_source_root(path: Path) -> Path:
    (path / "src" / "etf_cockpit").mkdir(parents=True)
    (path / "configs").mkdir()
    (path / "scripts").mkdir()
    return path


def _make_portable_root(path: Path) -> Path:
    (path / "app" / "src" / "etf_cockpit").mkdir(parents=True)
    (path / "configs").mkdir()
    (path / "scripts").mkdir()
    return path
