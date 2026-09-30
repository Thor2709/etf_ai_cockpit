from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest


def test_runtime_root_isolates_mutable_state_and_provider_environment(
    isolated_runtime_root: Path,
) -> None:
    assert os.environ["ETF_COCKPIT_CACHE_DIR"] == str(isolated_runtime_root / "cache")
    assert os.environ["ETF_COCKPIT_LOGS_DIR"] == str(isolated_runtime_root / "logs")
    assert os.environ["ETF_COCKPIT_ARTIFACTS_DIR"] == str(isolated_runtime_root / "artifacts")
    assert os.environ["ETF_COCKPIT_DATA_DIR"] == str(isolated_runtime_root / "data")
    assert os.environ["ETF_COCKPIT_OFFLINE"] == "1"
    assert os.environ["TZ"] == "UTC"
    assert "YAHOO_API_KEY" not in os.environ
    assert "OPENAI_API_KEY" not in os.environ


def test_reserved_tcp_port_rejects_competing_bind(reserved_tcp_port: socket.socket) -> None:
    host, port = reserved_tcp_port.getsockname()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as competitor:
        with pytest.raises(OSError):
            competitor.bind((host, port))


def test_environment_isolation_tests_run_in_parallel_on_a_private_project_root(
    request: pytest.FixtureRequest,
) -> None:
    # These fixtures are process-local, so the tests run in the parallel lane; the shared checkout
    # is protected by the per-process project root instead of serial execution.
    assert request.node.get_closest_marker("serial") is None
    checkout = Path(__file__).resolve().parents[1]
    assert Path(os.environ["ETF_COCKPIT_ROOT"]).resolve() != checkout
