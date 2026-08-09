from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))
sys.path.insert(0, str(ROOT))

from scripts import launcher_core  # noqa: E402

REQUIRED_GROUP_LABELS = [
    "Primary tier - ETFs",
    "Primary tier - stocks/equity certificates",
    "Secondary tier - ETFs",
    "Secondary tier - stocks/equity certificates",
    "Sparebanken - Norwegian savings-bank equity-certificate issuers",
]
SMOKE_MODES = ("source", "native", "portable-native", "launcher", "first-run", "offline")
EXPECTED_TITLE = "ETF AI Evidence Cockpit"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local smoke checks for ETF AI Cockpit.")
    parser.add_argument("--mode", choices=SMOKE_MODES, default="source")
    parser.add_argument("--port", default=os.getenv("ETF_COCKPIT_PORT", "8550"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--keep-running", action="store_true", help="Keep a source process started by this smoke check running.")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_smoke_args(args)
    verify_ui_action_inventory()
    verify_expected_title()

    requested_port = launcher_core.normalise_port(args.port)
    decision = launcher_core.choose_launch_port("127.0.0.1", requested_port, allow_reuse=True)
    port = decision.port
    print(f"smoke_port requested={decision.requested_port} selected={decision.port} reason={decision.reason}")
    process: subprocess.Popen | None = None
    try:
        if args.mode in {"source", "offline"}:
            process = _ensure_source_ready(
                port,
                args.timeout,
                already_ready=decision.reuse_existing,
                offline=args.mode == "offline",
            )
        elif args.mode == "first-run":
            _verify_first_run_setup()
            process = _ensure_source_ready(port, args.timeout, already_ready=decision.reuse_existing)
        elif args.mode == "launcher":
            process = _ensure_mode_ready("source", port, args.timeout, already_ready=decision.reuse_existing)
        else:
            process = _ensure_mode_ready(args.mode, port, args.timeout, already_ready=decision.reuse_existing)
        ready = launcher_core.wait_for_ready("127.0.0.1", port, min(args.timeout, 10))
        if not ready.ready:
            print(f"ERROR: HTTP readiness failed for {ready.url}: {ready.message}", file=sys.stderr)
            return 1
        _fetch_root(ready.url)
        _verify_score_groups()
        print(f"smoke_ok mode={args.mode} url={ready.url}")
        return 0
    finally:
        if process is not None and not args.keep_running:
            _terminate_process(process)


def _ensure_source_ready(
    port: int,
    timeout: int,
    *,
    already_ready: bool = False,
    offline: bool = False,
) -> subprocess.Popen | None:
    if already_ready or launcher_core.probe_http_ready("127.0.0.1", port):
        return None
    python = launcher_core.resolve_python(ROOT)
    env = os.environ.copy()
    env["ETF_COCKPIT_ROOT"] = str(ROOT)
    env["ETF_COCKPIT_VIEW"] = "web"
    env["ETF_COCKPIT_PORT"] = str(port)
    env["ETF_COCKPIT_OPEN_BROWSER"] = "0"
    env.setdefault("ETF_COCKPIT_SMOKE_MODE", "1")
    if offline:
        env["ETF_COCKPIT_OFFLINE"] = "1"
    process = subprocess.Popen([str(python), str(ROOT / "scripts" / "run_app.py")], cwd=str(ROOT), env=env)
    verify_process_path(process, python)
    try:
        return _wait_for_process_ready(process, port, timeout)
    except BaseException:
        _terminate_process(process)
        raise


def _ensure_mode_ready(mode: str, port: int, timeout: int, *, already_ready: bool = False) -> subprocess.Popen | None:
    if already_ready or launcher_core.probe_http_ready("127.0.0.1", port):
        return None
    command, cwd = launcher_core._launch_command(ROOT, mode, exe_path=None)
    env = os.environ.copy()
    env["ETF_COCKPIT_ROOT"] = str(ROOT)
    env["ETF_COCKPIT_VIEW"] = "web"
    env["ETF_COCKPIT_PORT"] = str(port)
    env["ETF_COCKPIT_OPEN_BROWSER"] = "0"
    env["ETF_COCKPIT_SMOKE_MODE"] = "1"
    process = launcher_core._spawn(command, cwd=cwd, env=env)
    verify_process_path(process, Path(command[0]))
    try:
        return _wait_for_process_ready(process, port, timeout)
    except BaseException:
        _terminate_process(process)
        raise


def _terminate_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _wait_for_process_ready(process: subprocess.Popen, port: int, timeout: int) -> subprocess.Popen:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"smoke process exited before readiness with code {process.returncode}")
        if launcher_core.probe_http_ready("127.0.0.1", port):
            return process
        time.sleep(1)
    raise RuntimeError(f"smoke process did not become ready on port {port} within {timeout}s")


def _fetch_root(url: str) -> None:
    with urllib.request.urlopen(url, timeout=5) as response:
        if int(response.status) >= 500:
            raise RuntimeError(f"HTTP root returned status {response.status}")


def _validate_smoke_args(args: argparse.Namespace) -> None:
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero")
    if args.keep_running and args.mode not in {"source", "offline", "first-run"}:
        raise ValueError("--keep-running is only supported for source-backed smoke modes")


def _verify_first_run_setup() -> None:
    setup_script = ROOT / "scripts" / "first_run_setup.bat"
    if not setup_script.exists():
        raise RuntimeError(f"First-run setup script was not found: {setup_script}")


def verify_expected_title() -> None:
    source_path = _source_root() / "etf_cockpit" / "app" / "flet_app.py"
    expected_assignment = f'page.title = "{EXPECTED_TITLE}"'
    if not source_path.exists() or expected_assignment not in source_path.read_text(encoding="utf-8"):
        raise RuntimeError(f"Flet page title is not configured as {EXPECTED_TITLE!r}: {source_path}")


def verify_ui_action_inventory() -> None:
    from etf_cockpit.core.ui_acceptance import build_main_ui_action_inventory, ui_command_contracts

    inventory = build_main_ui_action_inventory()
    commands = ui_command_contracts(inventory)
    if not inventory or len(commands) != len(inventory):
        raise RuntimeError("UI action inventory is empty or has unbound commands")
    if any(item.execution_allowed is not False for item in inventory):
        raise RuntimeError("UI action inventory attempted to grant execution authority")


def _source_root() -> Path:
    for candidate in (ROOT / "src", ROOT / "app" / "src"):
        if (candidate / "etf_cockpit").exists():
            return candidate
    return ROOT / "src"


def verify_process_path(process: subprocess.Popen | object, expected_path: Path) -> None:
    args = getattr(process, "args", None)
    command = args[0] if isinstance(args, (list, tuple)) and args else args
    if not command:
        raise RuntimeError("smoke process did not expose an executable path")
    actual_path = Path(str(command)).resolve()
    if actual_path != expected_path.resolve():
        raise RuntimeError(f"smoke process used unexpected executable: {actual_path}")


def _verify_score_groups() -> None:
    from etf_cockpit.core.config import load_config
    from etf_cockpit.signals.simple_scores import build_simple_instrument_scores, group_simple_scores

    import pandas as pd

    scores = build_simple_instrument_scores(load_config(), [], pd.DataFrame(), pd.DataFrame())
    groups = group_simple_scores(scores)
    labels = [group.label for group in groups]
    missing = [label for label in REQUIRED_GROUP_LABELS if label not in labels]
    if missing:
        raise RuntimeError(f"Simple Scores group labels missing: {missing}")
    sparebanken = next(group for group in groups if group.label == REQUIRED_GROUP_LABELS[-1])
    by_id = {score.display_id: score for score in sparebanken.scores}
    if "AURG" not in by_id or by_id["AURG"].isin != "needs_verification":
        raise RuntimeError("Sparebanken group did not preserve AURG needs_verification ISIN.")
    if "NONG" not in by_id or by_id["NONG"].source_group != "Sparebanken":
        raise RuntimeError("NONG was not moved into the Sparebanken group.")


if __name__ == "__main__":
    raise SystemExit(main())
