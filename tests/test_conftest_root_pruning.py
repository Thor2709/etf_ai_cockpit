"""Isolated-root pruning must never delete a root whose owning test session is still alive."""

from __future__ import annotations

import os
import time

import conftest


def test_live_owner_root_is_kept_even_when_heartbeat_is_old(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(conftest, "ISOLATED_ROOTS", tmp_path)
    root = tmp_path / "gw9-live"
    root.mkdir()
    heartbeat = root / conftest._HEARTBEAT
    heartbeat.write_text(str(os.getpid()), encoding="ascii")
    old = time.time() - 10 * conftest._STALE_ROOT_SECONDS
    os.utime(heartbeat, (old, old))

    conftest._prune_stale_isolated_roots()

    assert root.is_dir()


def test_dead_owner_root_with_old_heartbeat_is_pruned(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(conftest, "ISOLATED_ROOTS", tmp_path)
    root = tmp_path / "gw9-dead"
    root.mkdir()
    heartbeat = root / conftest._HEARTBEAT
    heartbeat.write_text("0", encoding="ascii")
    old = time.time() - 10 * conftest._STALE_ROOT_SECONDS
    os.utime(heartbeat, (old, old))

    conftest._prune_stale_isolated_roots()

    assert not root.exists()


def test_pid_alive_reports_current_process_and_rejects_invalid() -> None:
    assert conftest._pid_alive(os.getpid())
    assert not conftest._pid_alive(0)
