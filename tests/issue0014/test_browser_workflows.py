from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tests.issue0014._support import (
    ROOT,
    copy_repository_runtime,
    isolated_environment,
    run_offline_smoke,
)


def test_registered_routes_render_without_route_error_controls_or_events(tmp_path: Path) -> None:
    runtime_root = copy_repository_runtime(tmp_path / "browser-routes")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "issue0014" / "workflow_probe.py"), "routes"],
        cwd=runtime_root,
        env=isolated_environment(runtime_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.splitlines()[-1])
    assert payload["routes"] == ["/", "/training-centre"]
    assert payload["go_calls"] == payload["routes"]
    assert payload["route_error_keys"] == []
    assert payload["route_error_events"] == []
    assert Path(payload["root"]) == runtime_root


def test_real_loopback_http_startup_uses_offline_source_smoke(tmp_path: Path) -> None:
    runtime_root = copy_repository_runtime(tmp_path / "browser-smoke")

    completed = run_offline_smoke(
        runtime_root,
        runtime_root / "scripts" / "smoke_app.py",
    )

    assert "smoke_ok mode=offline" in completed.stdout
    assert "http://127.0.0.1:" in completed.stdout
    assert runtime_root.is_relative_to(tmp_path)
    assert (runtime_root / "logs").is_dir()
    assert all(path.is_relative_to(runtime_root) for path in (runtime_root / "logs").rglob("*"))
