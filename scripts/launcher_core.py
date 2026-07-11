from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8550
APP_NAME = "ETF_AI_Cockpit"


@dataclass(frozen=True)
class LaunchPortDecision:
    host: str
    requested_port: int
    port: int
    url: str
    reuse_existing: bool
    reason: str


@dataclass(frozen=True)
class ReadyResult:
    ready: bool
    url: str
    elapsed_s: float
    message: str


@dataclass(frozen=True)
class BrowserOpenResult:
    ok: bool
    url: str
    message: str


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str


@dataclass(frozen=True)
class BuildDirResult:
    path: Path
    status: str
    message: str
    quarantined_path: Path | None = None


def resolve_app_root(start: Path | None = None) -> Path:
    env_root = os.getenv("ETF_COCKPIT_ROOT", "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    if start is not None:
        candidates.append(Path(start))
    candidates.append(Path.cwd())
    candidates.extend(Path(__file__).resolve().parents)

    for candidate in candidates:
        path = candidate.expanduser().resolve()
        if _is_app_root(path):
            return path
    checked = ", ".join(str(Path(candidate).expanduser()) for candidate in candidates[:5])
    raise RuntimeError(f"Could not resolve ETF AI Cockpit app root. Checked: {checked}")


def resolve_python(app_root: Path) -> Path:
    candidates = [
        app_root / ".venv" / "Scripts" / "python.exe",
        app_root / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Could not find a Python runtime. Create .venv or install Python 3.11+.")


def normalise_port(value: str | int | None, default: int = DEFAULT_PORT) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        port = int(str(value).strip())
    except Exception as exc:
        raise ValueError(f"ETF_COCKPIT_PORT must be an integer between 1024 and 65535, got {value!r}.") from exc
    if port < 1024 or port > 65535:
        raise ValueError(f"ETF_COCKPIT_PORT must be between 1024 and 65535, got {port}.")
    return port


def probe_http_ready(host: str, port: int, timeout_s: float = 1.0) -> bool:
    url = _url(host, port)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def is_tcp_port_busy(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def choose_launch_port(host: str, preferred: int, allow_reuse: bool = True) -> LaunchPortDecision:
    requested = normalise_port(preferred)
    if allow_reuse and probe_http_ready(host, requested):
        return LaunchPortDecision(host, requested, requested, _url(host, requested), True, "existing HTTP server is ready")
    if is_tcp_port_busy(host, requested):
        fallback = _find_free_port(host, requested + 1)
        return LaunchPortDecision(host, requested, fallback, _url(host, fallback), False, f"port {requested} is busy but not HTTP-ready")
    return LaunchPortDecision(host, requested, requested, _url(host, requested), False, f"port {requested} is free")


def wait_for_ready(host: str, port: int, timeout_s: int) -> ReadyResult:
    start = time.monotonic()
    url = _url(host, port)
    while time.monotonic() - start <= timeout_s:
        if probe_http_ready(host, port, timeout_s=1.0):
            elapsed = time.monotonic() - start
            return ReadyResult(True, url, elapsed, f"ready after {elapsed:.1f}s")
        time.sleep(1.0)
    elapsed = time.monotonic() - start
    return ReadyResult(False, url, elapsed, f"not ready after {elapsed:.1f}s")


def open_browser(url: str) -> BrowserOpenResult:
    try:
        opened = bool(webbrowser.open(url))
    except Exception as exc:
        return BrowserOpenResult(False, url, f"browser open failed: {type(exc).__name__}: {exc}")
    if not opened:
        return BrowserOpenResult(False, url, "browser controller returned false")
    return BrowserOpenResult(True, url, "browser open requested")


def find_project_exe_processes(app_root: Path) -> list[ProcessInfo]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", f"IMAGENAME eq {APP_NAME}.exe", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    processes: list[ProcessInfo] = []
    for line in result.stdout.splitlines():
        parts = [part.strip().strip('"') for part in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == f"{APP_NAME}.exe".lower():
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            processes.append(ProcessInfo(pid=pid, command=parts[0]))
    return processes


def prepare_build_directory(path: Path) -> BuildDirResult:
    target = path.resolve()
    if not target.exists():
        return BuildDirResult(target, "ready", f"{target} does not exist; ready to build")
    try:
        shutil.rmtree(target)
        return BuildDirResult(target, "removed", f"removed existing build directory {target}")
    except Exception as first_error:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantine = target.with_name(f"{target.name}_locked_{stamp}")
        try:
            target.rename(quarantine)
            return BuildDirResult(
                target,
                "quarantined",
                f"{target} was locked; moved it to {quarantine}",
                quarantined_path=quarantine,
            )
        except Exception as second_error:
            raise RuntimeError(
                f"Build directory is locked and could not be removed or quarantined: {target}. "
                f"Close any running {APP_NAME}.exe or Explorer window using that folder. "
                f"Remove failure: {type(first_error).__name__}: {first_error}; "
                f"quarantine failure: {type(second_error).__name__}: {second_error}"
            ) from second_error


def prepare_output_directory(path: Path, *, allow_alternate: bool = False) -> BuildDirResult:
    try:
        return prepare_build_directory(path)
    except RuntimeError as exc:
        if not allow_alternate:
            raise
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        alternate = path.resolve().with_name(f"{path.name}_{stamp}")
        return BuildDirResult(
            alternate,
            "alternate",
            f"{path.resolve()} is locked; using fresh output directory {alternate}. Reason: {exc}",
        )


def launch(
    *,
    mode: str,
    root: Path | None = None,
    host: str = DEFAULT_HOST,
    preferred_port: int | str | None = None,
    open_browser_flag: bool = True,
    timeout_s: int = 60,
    exe_path: Path | None = None,
) -> int:
    app_root = resolve_app_root(root)
    port = normalise_port(preferred_port or os.getenv("ETF_COCKPIT_PORT") or DEFAULT_PORT)
    decision = choose_launch_port(host, port, allow_reuse=True)
    print(f"launch_port requested={decision.requested_port} selected={decision.port} reason={decision.reason}")
    if decision.reuse_existing:
        if open_browser_flag:
            browser = open_browser(decision.url)
            print(browser.message)
            return 0 if browser.ok else 1
        print(f"existing_server_ready url={decision.url}")
        return 0

    command, cwd = _launch_command(app_root, mode, exe_path=exe_path)
    env = os.environ.copy()
    env["ETF_COCKPIT_ROOT"] = str(app_root)
    env["ETF_COCKPIT_VIEW"] = "web"
    env["ETF_COCKPIT_PORT"] = str(decision.port)
    env["ETF_COCKPIT_OPEN_BROWSER"] = "0"
    process = _spawn(command, cwd=cwd, env=env)
    print(f"started mode={mode} pid={process.pid} cwd={cwd} url={decision.url}")
    ready = wait_for_ready(host, decision.port, timeout_s)
    print(ready.message)
    if not ready.ready:
        if process.poll() is not None:
            print(f"ERROR: launched process exited with code {process.returncode} before readiness.")
        else:
            try:
                process.terminate()
            except Exception:
                pass
            print("ERROR: launched process was not HTTP-ready before timeout.")
        return 1
    if open_browser_flag:
        browser = open_browser(ready.url)
        print(browser.message)
        return 0 if browser.ok else 1
    print(f"ready url={ready.url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ETF AI Cockpit launcher helper")
    sub = parser.add_subparsers(dest="command")

    launch_parser = sub.add_parser("launch", help="Start or reuse the local web app.")
    launch_parser.add_argument("--mode", choices=["source", "native", "portable-native"], default="source")
    launch_parser.add_argument("--root", type=Path)
    launch_parser.add_argument("--host", default=DEFAULT_HOST)
    launch_parser.add_argument("--preferred-port", default=None)
    launch_parser.add_argument("--open-browser", choices=["0", "1"], default="1")
    launch_parser.add_argument("--timeout", type=int, default=60)
    launch_parser.add_argument("--exe", type=Path)

    prepare_parser = sub.add_parser("prepare-build-dir", help="Remove or quarantine a build output directory.")
    prepare_parser.add_argument("path", type=Path)

    output_parser = sub.add_parser("prepare-output-dir", help="Prepare an output directory and print the usable path.")
    output_parser.add_argument("path", type=Path)
    output_parser.add_argument("--allow-alternate", action="store_true")
    output_parser.add_argument("--path-file", type=Path)

    ready_parser = sub.add_parser("wait-ready", help="Wait for HTTP readiness.")
    ready_parser.add_argument("--host", default=DEFAULT_HOST)
    ready_parser.add_argument("--port", default=str(DEFAULT_PORT))
    ready_parser.add_argument("--timeout", type=int, default=60)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-build-dir":
            result = prepare_build_directory(args.path)
            print(result.message)
            return 0
        if args.command == "prepare-output-dir":
            result = prepare_output_directory(args.path, allow_alternate=args.allow_alternate)
            if result.status == "alternate":
                print(result.message, file=sys.stderr)
            if args.path_file is not None:
                args.path_file.parent.mkdir(parents=True, exist_ok=True)
                args.path_file.write_text(str(result.path), encoding="utf-8")
            print(str(result.path))
            return 0
        if args.command == "wait-ready":
            port = normalise_port(args.port)
            ready = wait_for_ready(args.host, port, args.timeout)
            print(ready.message)
            return 0 if ready.ready else 1
        return launch(
            mode=args.mode if args.command == "launch" else "source",
            root=args.root if args.command == "launch" else None,
            host=args.host if args.command == "launch" else DEFAULT_HOST,
            preferred_port=args.preferred_port if args.command == "launch" else None,
            open_browser_flag=(args.open_browser == "1") if args.command == "launch" else True,
            timeout_s=args.timeout if args.command == "launch" else 60,
            exe_path=args.exe if args.command == "launch" else None,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _is_app_root(path: Path) -> bool:
    return (
        (path / "configs").exists()
        and (path / "scripts").exists()
        and ((path / "src" / "etf_cockpit").exists() or (path / "app" / "src" / "etf_cockpit").exists())
    )


def _url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"


def _find_free_port(host: str, start_port: int) -> int:
    for port in range(max(1024, start_port), 65536):
        if not is_tcp_port_busy(host, port):
            return port
    raise RuntimeError("No free local TCP port was found.")


def _launch_command(app_root: Path, mode: str, *, exe_path: Path | None) -> tuple[list[str], Path]:
    if mode == "source":
        script = app_root / "scripts" / "run_app.py"
        if not script.exists():
            raise RuntimeError(f"Source launcher script was not found: {script}")
        return [str(resolve_python(app_root)), str(script)], app_root

    exe = exe_path or _default_native_exe(app_root, portable=(mode == "portable-native"))
    if exe is None or not exe.exists():
        raise RuntimeError(f"{APP_NAME}.exe was not found. Rebuild with scripts\\build_windows.bat first.")
    return [str(exe)], exe.parent


def _default_native_exe(app_root: Path, *, portable: bool) -> Path | None:
    candidates = []
    if portable:
        selected_file = app_root / "build" / "portable_outdir.txt"
        if selected_file.exists():
            selected_text = selected_file.read_text(encoding="utf-8").strip()
            if selected_text:
                selected_root = Path(selected_text).expanduser()
                if not selected_root.is_absolute():
                    selected_root = app_root / selected_root
                candidates.append(selected_root / "native" / APP_NAME / f"{APP_NAME}.exe")
        candidates.append(app_root / "native" / APP_NAME / f"{APP_NAME}.exe")
    else:
        selected_file = app_root / "build" / "native_outdir.txt"
        if selected_file.exists():
            selected_text = selected_file.read_text(encoding="utf-8").strip()
            if selected_text:
                selected_root = Path(selected_text).expanduser()
                if not selected_root.is_absolute():
                    selected_root = app_root / selected_root
                candidates.append(selected_root / APP_NAME / f"{APP_NAME}.exe")
    candidates.extend(
        [
            app_root / "build" / "flet_dist" / APP_NAME / f"{APP_NAME}.exe",
            app_root / "native" / APP_NAME / f"{APP_NAME}.exe",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _spawn(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    kwargs: dict[str, object] = {"cwd": str(cwd), "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
