from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import struct
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from etf_cockpit.app.router import PAGES  # noqa: E402

APP_TITLE = "ETF AI Evidence Cockpit"
SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


BLANK_VARIANCE_THRESHOLD = 4.0
FLUTTER_ERROR_MARKERS = (
    "flutter error",
    "exception caught by",
    "rendering library",
    "widgets library",
    "renderflex overflowed",
    "unbounded",
    "assertion failed",
)


def _decode_png_luma(data: bytes) -> tuple[int, int, list[bytearray]]:
    """Decode a non-interlaced 8-bit RGB/RGBA/grey PNG into per-row luma bytes."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG file.")
    position = 8
    header: tuple[int, ...] | None = None
    compressed = bytearray()
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError("PNG has no IHDR chunk.")
    width, height, depth, colour, _compression, _filter, interlace = header
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour)
    if depth != 8 or channels is None or interlace:
        raise ValueError("Unsupported PNG format for blank-canvas detection.")
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    previous = bytearray(stride)
    rows: list[bytearray] = []
    offset = 0
    for _ in range(height):
        method = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        if method == 1:
            for index in range(channels, stride):
                line[index] = (line[index] + line[index - channels]) & 255
        elif method == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 255
        elif method == 3:
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 255
        elif method == 4:
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                up = previous[index]
                corner = previous[index - channels] if index >= channels else 0
                estimate = left + up - corner
                dl, du, dc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                predictor = left if dl <= du and dl <= dc else (up if du <= dc else corner)
                line[index] = (line[index] + predictor) & 255
        elif method != 0:
            raise ValueError(f"Unsupported PNG filter {method}.")
        previous = line
        if channels >= 3:
            rows.append(
                bytearray(
                    (line[i] * 299 + line[i + 1] * 587 + line[i + 2] * 114) // 1000
                    for i in range(0, stride, channels)
                )
            )
        else:
            rows.append(bytearray(line[i] for i in range(0, stride, channels)))
    return width, height, rows


def canvas_luma_variance(data: bytes, *, margin: int = 3, sample_step: int = 1) -> float:
    """Return the luminance variance of the content area (frame margin excluded)."""
    width, height, rows = _decode_png_luma(data)
    left, right = min(margin, width // 4), max(width - margin, width * 3 // 4)
    top, bottom = min(margin, height // 4), max(height - margin, height * 3 // 4)
    values = [
        rows[y][x]
        for y in range(top, bottom, sample_step)
        for x in range(left, right, sample_step)
    ]
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def blank_canvas_reason(png_bytes: bytes, console_messages: list[str]) -> str | None:
    """Return why a captured route must fail closed, or None when it looks rendered."""
    flutter = [m for m in console_messages if any(k in m.lower() for k in FLUTTER_ERROR_MARKERS)]
    if flutter:
        return f"Flutter error logged in browser console: {flutter[0][:300]}"
    variance = canvas_luma_variance(png_bytes)
    if variance < BLANK_VARIANCE_THRESHOLD:
        return f"Blank canvas: content-area pixel variance {variance:.3f} < {BLANK_VARIANCE_THRESHOLD:g}."
    return None


class CaptureDriver(Protocol):
    console_errors: list[str]
    console_messages: list[str]

    async def capture(
        self,
        url: str,
        png_path: Path,
        *,
        width: int,
        height: int,
        timeout_s: float,
        settle_ms: int,
    ) -> list[str]: ...


def route_to_slug(route: str) -> str:
    """Map a route to a stable filesystem-safe PNG filename stem."""
    if not route.startswith("/"):
        raise ValueError(f"Route must start with '/': {route!r}")
    slug = route.strip("/").replace("/", "-") or "home"
    if not SAFE_SLUG.fullmatch(slug):
        raise ValueError(f"Route cannot be mapped to a safe filename: {route!r}")
    return slug


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render Flet app routes to headless PNG screenshots.")
    parser.add_argument("--routes", nargs="+", help="Routes to render; defaults to every router.PAGES route.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/ui-render"))
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1200)
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=15000,
        help="Additional wait after the app title appears (default: 15000).",
    )
    parser.add_argument("--browser", help="Chromium-family executable path or command name.")
    parser.add_argument("--timeout-s", type=float, default=60.0, help="Seconds to wait for each route title.")
    return parser


def resolve_browser(explicit: str | None) -> Path:
    candidates: list[str] = []
    if explicit:
        candidate_path = Path(explicit).expanduser()
        if candidate_path.is_file():
            return candidate_path.resolve()
        found = shutil.which(explicit)
        if found:
            return Path(found).resolve()
        raise FileNotFoundError(f"Chromium-family browser not found: {explicit}")

    if os.name == "nt":
        candidates.append("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    candidates.extend(("msedge", "chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"))
    for candidate in candidates:
        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_file():
            return candidate_path.resolve()
        found = shutil.which(candidate)
        if found:
            return Path(found).resolve()
    raise FileNotFoundError("No Chromium-family browser found; pass its executable with --browser.")


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _index_row(route: str, png: str, *, ok: bool, error: str | None, console_errors: list[str]) -> dict[str, Any]:
    return {
        "route": route,
        "png": png,
        "ok": ok,
        "error": error,
        "console_errors": console_errors,
    }


def write_index(out_dir: Path, rows: list[dict[str, Any]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    temporary = index_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(index_path)
    return index_path


async def render_routes(
    routes: list[str],
    out_dir: Path,
    driver: CaptureDriver,
    *,
    base_url: str,
    width: int,
    height: int,
    timeout_s: float,
    settle_ms: int,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for route in routes:
        png_name = f"{route_to_slug(route)}.png"
        png_path = out_dir / png_name
        try:
            try:
                errors = await asyncio.wait_for(
                    driver.capture(
                        f"{base_url.rstrip('/')}{route}",
                        png_path,
                        width=width,
                        height=height,
                        timeout_s=timeout_s,
                        settle_ms=settle_ms,
                    ),
                    timeout=timeout_s,
                )
            except TimeoutError as exc:
                if str(exc):
                    raise
                raise TimeoutError(f"Route capture exceeded {timeout_s:g} seconds.") from exc
            rows.append(_index_row(route, png_name, ok=True, error=None, console_errors=list(errors)))
        except Exception as exc:  # Each requested route must have an explicit result.
            rows.append(
                _index_row(
                    route,
                    png_name,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    console_errors=list(getattr(driver, "console_errors", [])),
                )
            )
    write_index(out_dir, rows)
    return rows


class DevToolsDriver:
    def __init__(self, websocket: Any, *, command_timeout_s: float = 60.0) -> None:
        self.websocket = websocket
        self.command_timeout_s = command_timeout_s
        self._command_id = 0
        self.console_errors: list[str] = []
        self.console_messages: list[str] = []

    @classmethod
    async def connect(
        cls,
        debug_port: int,
        *,
        timeout_s: float,
        width: int,
        height: int,
        browser_process: subprocess.Popen[Any],
        browser_log: Any,
    ) -> DevToolsDriver:
        deadline = time.monotonic() + timeout_s
        version_url = f"http://127.0.0.1:{debug_port}/json/version"
        while True:
            if browser_process.poll() is not None:
                browser_log.seek(0)
                output = browser_log.read(3000).decode("utf-8", errors="replace").strip()
                detail = f" Browser output: {output}" if output else ""
                raise RuntimeError(
                    f"Chromium browser exited with code {browser_process.returncode} before exposing DevTools.{detail}"
                )
            try:
                with urllib.request.urlopen(version_url, timeout=1) as response:
                    json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for Chromium DevTools endpoint.")
                await asyncio.sleep(0.2)

        with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=2) as response:
            targets = json.loads(response.read().decode("utf-8"))
        target = next((item for item in targets if item.get("type") == "page"), None)
        if target is None or not target.get("webSocketDebuggerUrl"):
            raise RuntimeError("Chromium DevTools did not expose a page target.")

        import websockets

        websocket = await asyncio.wait_for(
            websockets.connect(
                target["webSocketDebuggerUrl"],
                origin=f"http://127.0.0.1:{debug_port}",
                open_timeout=timeout_s,
                max_size=None,
            ),
            timeout=timeout_s,
        )
        driver = cls(websocket, command_timeout_s=timeout_s)
        await driver.command("Page.enable")
        await driver.command("Runtime.enable")
        await driver.command("Log.enable")
        await driver.command(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        return driver

    def _record_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Runtime.consoleAPICalled":
            parts = [
                arg.get("value", arg.get("description", ""))
                for arg in params.get("args", [])
            ]
            text = " ".join(str(part) for part in parts if part)
            self.console_messages.append(f"[{params.get('type')}] {text}")
            if params.get("type") == "error":
                self.console_errors.append(text)
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exception = details.get("exception", {})
            text = str(details.get("text") or exception.get("description") or "Uncaught page exception")
            self.console_messages.append(f"[exception] {text}")
            self.console_errors.append(text)
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            self.console_messages.append(f"[log:{entry.get('level')}] {entry.get('text', '')}")
            if entry.get("level") == "error":
                self.console_errors.append(str(entry.get("text", "Browser console error")))

    async def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._command_id += 1
        command_id = self._command_id
        deadline = time.monotonic() + self.command_timeout_s
        await asyncio.wait_for(
            self.websocket.send(
                json.dumps({"id": command_id, "method": method, "params": params or {}})
            ),
            timeout=self.command_timeout_s,
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"DevTools {method} did not respond within {self.command_timeout_s:g} seconds.")
            raw = await asyncio.wait_for(self.websocket.recv(), timeout=remaining)
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"DevTools {method} failed: {message['error']}")
                return message.get("result", {})
            self._record_event(message)

    async def _drain_events(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.websocket.recv(), timeout=min(0.1, deadline - time.monotonic()))
            except TimeoutError:
                continue
            self._record_event(json.loads(raw))

    async def capture(
        self,
        url: str,
        png_path: Path,
        *,
        width: int,
        height: int,
        timeout_s: float,
        settle_ms: int,
    ) -> list[str]:
        self.console_errors = []
        self.console_messages = []
        # Reset to a blank document so the previous route's title cannot satisfy the readiness wait.
        navigation = await self.command("Page.navigate", {"url": url})
        if navigation.get("errorText"):
            raise RuntimeError(str(navigation["errorText"]))
        deadline = time.monotonic() + timeout_s
        title = ""
        while time.monotonic() < deadline:
            evaluation = await self.command(
                "Runtime.evaluate",
                {"expression": "document.title", "returnByValue": True},
            )
            title = str(evaluation.get("result", {}).get("value", ""))
            if title == APP_TITLE:
                break
            await asyncio.sleep(0.2)
        else:
            raise TimeoutError(f"App title did not become {APP_TITLE!r} before timeout; last title={title!r}.")

        await self._drain_events(settle_ms / 1000)
        screenshot = await self.command(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True, "captureBeyondViewport": True},
        )
        png_path.write_bytes(base64.b64decode(screenshot["data"]))
        png_path.with_suffix(".console.txt").write_text(chr(10).join(self.console_messages), encoding="utf-8")
        # A 10% scale probe keeps the pure-Python PNG decode fast; blankness survives downscaling.
        probe = await self.command(
            "Page.captureScreenshot",
            {
                "format": "png",
                "fromSurface": True,
                "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 0.1},
            },
        )
        reason = blank_canvas_reason(base64.b64decode(probe["data"]), self.console_messages)
        if reason is not None:
            raise RuntimeError(reason)
        return list(self.console_errors)

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self.command("Browser.close"), timeout=2)
        except Exception:
            pass
        try:
            await self.websocket.close()
        except Exception:
            pass


class FailedDriver:
    def __init__(self, message: str) -> None:
        self.message = message
        self.console_errors: list[str] = []
        self.console_messages: list[str] = []

    async def capture(self, *_args: Any, **_kwargs: Any) -> list[str]:
        raise RuntimeError(self.message)


async def _wait_for_app(process: subprocess.Popen[Any], port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Flet app process exited with code {process.returncode} before becoming ready.")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError):
            await asyncio.sleep(0.2)
    raise TimeoutError(f"Flet app did not start listening on {url} within {timeout_s:g} seconds.")


def _stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            pass
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _save_app_log(app_log: Any, out_dir: Path) -> None:
    """Keep the app process stdout/stderr next to the PNGs and echo its tail."""
    try:
        app_log.seek(0)
        text = app_log.read().decode("utf-8", errors="replace")
        app_log.close()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "app.log").write_text(text, encoding="utf-8")
        tail = text.strip().splitlines()[-15:]
        if tail:
            print(f"App output tail ({out_dir / 'app.log'}):", file=sys.stderr)
            print(chr(10).join(tail), file=sys.stderr)
    except OSError as exc:
        print(f"UI render could not save app log: {exc}", file=sys.stderr)


async def run_harness(args: argparse.Namespace, browser_path: Path) -> int:
    routes = args.routes if args.routes is not None else list(PAGES)
    unknown = [route for route in routes if route not in PAGES]
    if unknown:
        print(f"Unknown route(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

    out_dir = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
    app_port = free_local_port()
    debug_port = free_local_port()
    while debug_port == app_port:
        debug_port = free_local_port()
    app_environment = os.environ.copy()
    existing_pythonpath = app_environment.get("PYTHONPATH", "")
    app_environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(SOURCE_ROOT), existing_pythonpath) if value
    )
    app_environment.update(
        {
            "ETF_COCKPIT_VIEW": "web",
            "ETF_COCKPIT_PORT": str(app_port),
            "ETF_COCKPIT_OPEN_BROWSER": "0",
        }
    )

    app_process: subprocess.Popen[Any] | None = None
    browser_process: subprocess.Popen[Any] | None = None
    driver: DevToolsDriver | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    browser_log: Any = None
    app_log: Any = None
    startup_error: str | None = None
    cleanup_error: str | None = None
    rows: list[dict[str, Any]] = []
    try:
        app_log = tempfile.TemporaryFile(prefix="etf-cockpit-ui-render-app-")
        app_process = subprocess.Popen(
            [sys.executable, "-m", "etf_cockpit.main"],
            cwd=PROJECT_ROOT,
            env=app_environment,
            stdout=app_log,
            stderr=subprocess.STDOUT,
        )
        await _wait_for_app(app_process, app_port, args.timeout_s)
        profile = tempfile.TemporaryDirectory(prefix="etf-cockpit-ui-render-")
        browser_log = tempfile.TemporaryFile(prefix="etf-cockpit-ui-render-log-")
        browser_args = [
            str(browser_path),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile.name}",
            "about:blank",
        ]
        if sys.platform.startswith("linux"):
            browser_args.insert(1, "--no-sandbox")
        browser_process = subprocess.Popen(
            browser_args,
            stdout=browser_log,
            stderr=subprocess.STDOUT,
        )
        driver = await DevToolsDriver.connect(
            debug_port,
            timeout_s=args.timeout_s,
            width=args.width,
            height=args.height,
            browser_process=browser_process,
            browser_log=browser_log,
        )
        rows = await render_routes(
            routes,
            out_dir,
            driver,
            base_url=f"http://127.0.0.1:{app_port}",
            width=args.width,
            height=args.height,
            timeout_s=args.timeout_s,
            settle_ms=args.settle_ms,
        )
    except Exception as exc:
        startup_error = f"{type(exc).__name__}: {exc}"
        failed_driver = FailedDriver(startup_error)
        rows = await render_routes(
            routes,
            out_dir,
            failed_driver,
            base_url="http://127.0.0.1:0",
            width=args.width,
            height=args.height,
            timeout_s=args.timeout_s,
            settle_ms=args.settle_ms,
        )
        print(f"UI render startup failed: {startup_error}", file=sys.stderr)
    finally:
        try:
            if driver is not None:
                await driver.close()
        finally:
            try:
                _stop_process(browser_process)
            finally:
                try:
                    _stop_process(app_process)
                finally:
                    try:
                        if profile is not None:
                            profile.cleanup()
                    except OSError as exc:
                        cleanup_error = f"{type(exc).__name__}: {exc}"
                        print(f"UI render temporary profile cleanup failed: {cleanup_error}", file=sys.stderr)
                    finally:
                        if browser_log is not None:
                            browser_log.close()
                        if app_log is not None:
                            _save_app_log(app_log, out_dir)

    if startup_error or cleanup_error:
        return 1
    failures = sum(not row["ok"] for row in rows)
    print(f"Rendered {len(rows) - failures}/{len(rows)} route(s); index: {out_dir / 'index.json'}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.width <= 0 or args.height <= 0 or args.timeout_s <= 0 or args.settle_ms < 0:
        parser.error("width, height, and timeout must be positive; settle-ms cannot be negative")
    try:
        browser_path = resolve_browser(args.browser)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if importlib.util.find_spec("websockets") is None:
        print("The 'websockets' package is required to drive Chromium DevTools.", file=sys.stderr)
        return 2
    return asyncio.run(run_harness(args, browser_path))


if __name__ == "__main__":
    raise SystemExit(main())
