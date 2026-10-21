"""Bughunt E (#986): Windows build, launcher and first run."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from etf_cockpit.core import install_defaults
from scripts import launcher_core, smoke_app

ROOT = Path(__file__).resolve().parents[1]
APP = "ETF_AI_Cockpit"
IDENTITY = "0123456789abcdef0123456789abcdef"
FORBIDDEN_PORTS = {8550, 8580, 8601}


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _generated(label: str) -> str:
    """Rebuild the batch file a ``:write_*_launcher`` routine writes, as cmd would expand its echo lines."""
    script = _read("scripts/build_windows.bat")
    body = script.partition(f":{label}\n")[2] if f":{label}\n" in script else script.partition(f":{label}\r\n")[2]
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith(") >"):
            break
        match = re.match(r"\s*echo (.*)$", line)
        if match:
            text = match.group(1).replace("%APPNAME%", APP)
            text = text.replace("%LAUNCHER_REQ_PARSERS%", "requirements-parsers.txt")
            text = text.replace("%LAUNCHER_REQ%", "requirements.txt")
            text = text.replace("%%", "%")
            lines.append(re.sub(r"\^(.)", r"\1", text))
    assert lines, label
    return "\r\n".join(lines) + "\r\n"


def _errorlevel_inside_blocks(text: str) -> list[str]:
    depth, found = 0, []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(")"):
            depth = max(0, depth - 1)
        if depth and "%ERRORLEVEL%" in line:
            found.append(line)
        if line.endswith("("):
            depth += 1
    return found


# E119-N001: generated runner propagates the app's exit code ---------------------------------------


def test_generated_runners_and_launchers_never_expand_errorlevel_inside_blocks() -> None:
    texts = {
        "native": _generated("write_native_launcher"),
        "source": _generated("write_source_launcher"),
        "Run_EXE": _read("Run_ETF_AI_Cockpit_EXE.bat"),
        "Launch_Latest": _read("Launch_Latest_ETF_AI_Cockpit.bat"),
        "ETF_AI_Cockpit": _read("ETF_AI_Cockpit.bat"),
        "build": _read("scripts/build_windows.bat").partition(":write_source_launcher")[0],
    }
    assert {name: _errorlevel_inside_blocks(text) for name, text in texts.items()} == {name: [] for name in texts}


@pytest.mark.skipif(os.name != "nt", reason="requires Windows: runs the generated cmd runner")
@pytest.mark.parametrize("code", [7, 0])
def test_generated_native_runner_propagates_app_exit_code(tmp_path: Path, code: int) -> None:
    runner = _generated("write_native_launcher")
    launch_line = next(line for line in runner.splitlines() if line.startswith('".venv') and "launcher_core.py" in line)
    runner = runner.replace(launch_line, f"cmd /c exit /b {code}")
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    exe = tmp_path / "native" / APP / f"{APP}.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (tmp_path / "run.bat").write_bytes(runner.encode())

    result = subprocess.run(
        ["cmd", "/c", str(tmp_path / "run.bat")],
        cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == code


# E019-N002: build without PyInstaller is not a native success --------------------------------------


def test_build_without_native_pack_routes_to_the_source_launcher_and_never_claims_a_native_exe() -> None:
    # RL2 contract: a build without PyInstaller fails OR routes to the source launcher; never reports native success.
    # GT4 chose the source-launcher route (PyInstaller is not an authorised dependency), so the guard announces it
    # and the native artefacts are only written when the pack is ready.
    script = _read("scripts/build_windows.bat").replace("\r\n", "\n")
    guard = re.search(r'if not "!NATIVE_PACK_READY!"=="1" \(\n(?:.*\n)*?\)\n', script)
    assert guard is not None
    assert "native EXE not built ^(PyInstaller absent^); portable source launcher only" in guard.group(0)
    assert "exit /b" not in guard.group(0)
    assert guard.start() < script.index("OUTDIR_FINAL%.staging")
    assert guard.start() < script.index("Portable folder created")
    assert "skipping Flet native pack" not in script
    assert "requirements-release.txt^)" not in script  # PyInstaller is in no requirements file
    # The native runner and the build record are conditional on the pack being ready.
    assert 'if "%NATIVE_PACK_READY%"=="1" (\n  call :write_native_launcher' in script
    assert '"native_exe": "absent"' in script and '"native_exe": "present"' in script
    assert script.index('"native_exe": "absent"') > script.index("call :write_source_launcher")


# E019-N001: a foreign HTTP 200 is not reused -----------------------------------------------------


class _Serve:
    def __init__(self, identity: str | None) -> None:
        served = f"/cockpit-instance-{identity}.txt" if identity else None

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = identity.encode() if served and self.path == served else b"hello from another app"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        assert self.port not in FORBIDDEN_PORTS
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_Serve":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _record(root: Path, port: int, identity: str = IDENTITY) -> None:
    path = root / "data" / "runtime" / "web_instance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": port, "pid": os.getpid(), "identity": identity}), encoding="utf-8")


def test_foreign_http_200_on_the_port_is_not_reused(tmp_path: Path) -> None:
    with _Serve(identity=None) as foreign:
        decision = launcher_core.choose_launch_port("127.0.0.1", foreign.port)
        recorded = launcher_core.choose_launch_port("127.0.0.1", foreign.port, runtime_root=tmp_path)
        _record(tmp_path, foreign.port)
        with_record = launcher_core.choose_launch_port("127.0.0.1", foreign.port, runtime_root=tmp_path)

    for result in (decision, recorded, with_record):
        assert result.reuse_existing is False
        assert result.port != foreign.port
        assert "unverified" in result.reason


def test_server_serving_the_recorded_identity_is_reused(tmp_path: Path) -> None:
    with _Serve(identity=IDENTITY) as app:
        _record(tmp_path, app.port)
        decision = launcher_core.choose_launch_port("127.0.0.1", app.port, runtime_root=tmp_path)
        _record(tmp_path, app.port + 1)
        wrong_port = launcher_core.choose_launch_port("127.0.0.1", app.port, runtime_root=tmp_path)
        _record(tmp_path, app.port, identity="f" * 32)
        wrong_identity = launcher_core.choose_launch_port("127.0.0.1", app.port, runtime_root=tmp_path)

    assert decision.reuse_existing is True and decision.port == app.port
    assert wrong_port.reuse_existing is False
    assert wrong_identity.reuse_existing is False


def test_fallback_port_search_skips_reserved_ports(monkeypatch) -> None:
    monkeypatch.setattr(launcher_core, "is_tcp_port_busy", lambda host, port: False)

    assert launcher_core._find_free_port("127.0.0.1", 8580) == 8581
    assert launcher_core._find_free_port("127.0.0.1", 8601) == 8602


# E019-N004: a failed rebuild keeps the last good dist ----------------------------------------------


def _dist(path: Path, marker: str, *, exe: bool = True) -> Path:
    (path / APP).mkdir(parents=True)
    if exe:
        (path / APP / f"{APP}.exe").write_text(marker, encoding="utf-8")
    (path / "marker.txt").write_text(marker, encoding="utf-8")
    return path


def test_failed_rebuild_keeps_the_last_good_dist(tmp_path: Path) -> None:
    final = _dist(tmp_path / "flet_dist", "good")
    staged = _dist(tmp_path / "flet_dist.staging", "broken", exe=False)

    with pytest.raises(RuntimeError, match="last good build was kept"):
        launcher_core.promote_staged_directory(staged, final, require=f"{APP}/{APP}.exe")

    assert (final / "marker.txt").read_text(encoding="utf-8") == "good"
    assert (final / APP / f"{APP}.exe").is_file()


def test_validated_rebuild_is_promoted_and_previous_build_is_kept(tmp_path: Path) -> None:
    final = _dist(tmp_path / "flet_dist", "good")
    staged = _dist(tmp_path / "flet_dist.staging", "new")

    result = launcher_core.promote_staged_directory(staged, final, require=f"{APP}/{APP}.exe")

    assert result.status == "promoted" and result.path == final.resolve()
    assert (final / "marker.txt").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "flet_dist_previous" / "marker.txt").read_text(encoding="utf-8") == "good"
    assert not staged.exists()


def test_locked_last_good_dist_is_never_removed_and_the_new_build_gets_a_fresh_name(tmp_path: Path, monkeypatch) -> None:
    final = _dist(tmp_path / "flet_dist", "good")
    staged = _dist(tmp_path / "flet_dist.staging", "new")
    real_rename = Path.rename

    def rename(self: Path, target):
        if self == final.resolve():
            raise PermissionError("simulated lock")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)

    result = launcher_core.promote_staged_directory(staged, final, require=f"{APP}/{APP}.exe")

    assert result.status == "alternate" and result.path != final.resolve()
    assert (final / "marker.txt").read_text(encoding="utf-8") == "good"
    assert (result.path / "marker.txt").read_text(encoding="utf-8") == "new"


def test_build_script_stages_both_outputs_and_promotes_after_validation() -> None:
    script = _read("scripts/build_windows.bat")
    assert 'prepare-output-dir "%NATIVE_OUT_ROOT%"' not in script
    assert 'prepare-output-dir "%OUTDIR%"' not in script
    assert script.index("pyi-set_version.exe") < script.index('promote-output-dir "!NATIVE_STAGE!"')
    assert script.index("smoke_app.py") < script.index('promote-output-dir "%OUTDIR%"')
    assert 'promote-output-dir "%OUTDIR%" "%OUTDIR_FINAL%"' in script


# E119-N002: a missing upgrade YAML is restored ------------------------------------------------------


def _portable_layout(tmp_path: Path, monkeypatch, *, pristine: tuple[str, ...]) -> Path:
    package = tmp_path / "package"
    module = package / "app" / "src" / "etf_cockpit" / "core" / "install_defaults.py"
    owner = package / "configs"
    owner.mkdir(parents=True)
    kept = install_defaults.UPGRADE_CONFIGS[:-1]
    for name in kept:
        (owner / name).write_text("owner: true\n", encoding="utf-8")
    (package / "app" / "configs").mkdir(parents=True)
    for name in pristine:
        (package / "app" / "configs" / name).write_text("pristine: true\n", encoding="utf-8")
    monkeypatch.setattr(install_defaults, "__file__", str(module))
    return package


def test_missing_upgrade_yaml_is_restored_from_the_pristine_copy(tmp_path: Path, monkeypatch) -> None:
    missing = install_defaults.UPGRADE_CONFIGS[-1]
    package = _portable_layout(tmp_path, monkeypatch, pristine=(missing,))

    restored = install_defaults.ensure_install_defaults(package)

    assert restored == (package / "configs" / missing,)
    assert (package / "configs" / missing).read_text(encoding="utf-8") == "pristine: true\n"
    assert (package / "configs" / install_defaults.UPGRADE_CONFIGS[0]).read_text(encoding="utf-8") == "owner: true\n"


def test_missing_upgrade_yaml_without_any_pristine_copy_fails_closed(tmp_path: Path, monkeypatch) -> None:
    package = _portable_layout(tmp_path, monkeypatch, pristine=())
    # The search also walks above tmp_path (into the checkout), so use a name no bundle ships.
    absent = "zz_rl2_absent_default_v1.yaml"
    monkeypatch.setattr(install_defaults, "UPGRADE_CONFIGS", (*install_defaults.UPGRADE_CONFIGS[:-1], absent))

    with pytest.raises(FileNotFoundError, match=absent):
        install_defaults.ensure_install_defaults(package)
    assert not (package / "configs" / absent).exists()


def test_portable_package_ships_pristine_configs_and_first_run_requirements() -> None:
    script = _read("scripts/build_windows.bat")
    assert 'call :copy_required configs "%OUTDIR%\\app\\configs"' in script
    copy_list = next(line for line in script.splitlines() if line.lstrip().startswith("for %%f in (README.md"))
    for name in re.findall(r"install\s+-r\s+(\S+)", _read("scripts/first_run_setup.bat")):
        assert name in copy_list  # V8 E.C4.S19.N001


# E119-N003 / E019-N003 / E019-N005: fallbacks and shortcut icon -------------------------------------


def test_generated_source_launcher_falls_back_to_the_packaged_exe() -> None:
    source = _generated("write_source_launcher")
    assert "goto exe_fallback" in source
    assert "--mode portable-native" in source and "set RC=%ERRORLEVEL%" in source
    assert "exit /b %RC%" in source


@pytest.mark.parametrize(
    "text",
    [
        _generated("write_native_launcher"),
        _read("Run_ETF_AI_Cockpit_EXE.bat"),
        _read("Launch_Latest_ETF_AI_Cockpit.bat"),
    ],
)
def test_py313_is_probed_so_its_absence_falls_back_instead_of_failing(text: str) -> None:
    probe = text.index('py -3.13 -c "import sys"')
    assert probe < text.index("py -3.13 scripts\\launcher_core.py") if "py -3.13 scripts" in text else probe < text.index("py -3.13 \"%HELPER%\"")


def test_native_batch_fallback_does_not_reuse_an_unverified_server() -> None:
    for text in (_generated("write_native_launcher"), _read("Run_ETF_AI_Cockpit_EXE.bat")):
        assert "cannot be verified" in text
        assert 'start "" "%URL%"\r\n  exit /b 0' not in text.split(":start_exe")[0]


def test_shortcut_icon_and_latest_default_follow_the_current_version() -> None:
    shortcut = _read("scripts/create_desktop_shortcut.ps1")
    assert "v0.1.0" not in shortcut and "portable_outdir.txt" in shortcut
    assert "v0.1.0" not in _read("Launch_Latest_ETF_AI_Cockpit.bat")


# E119-N004: smoke first-run exercises the setup batch's contract -----------------------------------


def test_first_run_smoke_validates_the_setup_batch_contract(tmp_path: Path, monkeypatch) -> None:
    smoke_app._verify_first_run_setup()

    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_app.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "first_run_setup.bat").write_text(
        '"pip.exe" install -r requirements-dev.txt\r\n".venv\\Scripts\\python.exe" scripts\\run_app.py --smoke\r\n',
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "build_windows.bat").write_text("rem packages nothing\r\n", encoding="utf-8")
    monkeypatch.setattr(smoke_app, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="missing file: requirements-dev.txt"):
        smoke_app._verify_first_run_setup()
    (tmp_path / "requirements-dev.txt").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not copy"):
        smoke_app._verify_first_run_setup()
    (tmp_path / "scripts" / "build_windows.bat").write_text("copy requirements-dev.txt x\r\n", encoding="utf-8")
    smoke_app._verify_first_run_setup()


def test_smoke_exe_and_run_setup_flags_are_mode_scoped() -> None:
    ok = smoke_app.parse_args(["--mode", "portable-native", "--exe", "x.exe"])
    smoke_app._validate_smoke_args(ok)
    with pytest.raises(ValueError, match="--exe"):
        smoke_app._validate_smoke_args(smoke_app.parse_args(["--mode", "source", "--exe", "x.exe"]))
    with pytest.raises(ValueError, match="--run-setup"):
        smoke_app._validate_smoke_args(smoke_app.parse_args(["--mode", "source", "--run-setup"]))
