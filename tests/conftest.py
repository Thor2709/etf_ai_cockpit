from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import uuid
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_repo_pytest_temp = ROOT / "logs" / "pytest_system_tmp"
if os.name == "nt" and len(str(_repo_pytest_temp)) > 90:
    # Linked worktrees can exceed Windows' legacy path limit before the test
    # payload is created. Keep the same deterministic case layout in the
    # system temp directory when the repository path itself is too long.
    PYTEST_TEMP = Path(tempfile.gettempdir()) / "etf_ai_cockpit_pytest"
else:
    PYTEST_TEMP = _repo_pytest_temp
PYTEST_TEMP.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(PYTEST_TEMP)
os.environ["TMP"] = str(PYTEST_TEMP)
os.environ["TMPDIR"] = str(PYTEST_TEMP)
tempfile.tempdir = str(PYTEST_TEMP)


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    path = PYTEST_TEMP / "cases" / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    request.addfinalizer(lambda: shutil.rmtree(path, ignore_errors=True))
    return path


@pytest.fixture
def isolated_runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Opt-in isolation for mutable application state used by integration tests."""

    runtime_root = tmp_path / "runtime"
    for name in ("cache", "logs", "artifacts", "data"):
        path = runtime_root / name
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(f"ETF_COCKPIT_{name.upper()}_DIR", str(path))
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("ETF_COCKPIT_OFFLINE", "1")
    monkeypatch.delenv("YAHOO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return runtime_root


@pytest.fixture
def reserved_tcp_port() -> Iterator[socket.socket]:
    """Keep an ephemeral loopback port reserved until fixture teardown."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        yield reservation


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    groups = {
        "environment": ("environment", "dependency", "lock"),
        "sqlite": ("sqlite", "database", "db_"),
        "flet": ("flet", "ui_", "smoke_app"),
        "ports": ("port", "socket"),
        "package": ("package", "wheel", "release_gate"),
        "concurrency": ("concurrency", "thread", "atomic"),
    }
    for item in items:
        nodeid = item.nodeid.lower()
        matched = next((name for name, tokens in groups.items() if any(token in nodeid for token in tokens)), None)
        if matched is not None:
            item.add_marker(pytest.mark.serial)
            item.add_marker(pytest.mark.xdist_group(matched))

    # The parallel pilot opts into this exact selected-nodeid evidence.  Do
    # not emit it for ordinary test runs, and avoid concurrent worker writes:
    # xdist's controller performs collection on the authoritative item list.
    manifest_value = os.getenv("ETF_COCKPIT_PILOT_NODEID_MANIFEST")
    worker_input = getattr(config, "workerinput", None)
    if not manifest_value or (
        worker_input is not None and worker_input.get("workerid") != "gw0"
    ):
        return
    nodeids = [item.nodeid.replace("\\", "/") for item in items]
    if len(nodeids) != len(set(nodeids)):
        raise RuntimeError("parallel pilot selected-nodeid manifest contains duplicates")
    destination = Path(manifest_value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(nodeids, sort_keys=False) + "\n", encoding="utf-8")
