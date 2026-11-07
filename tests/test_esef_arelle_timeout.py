"""Arelle child start-up is bounded separately from the validation bound (fail closed on both)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from etf_cockpit.parsers import esef_ixbrl

# Child start-up is simulated by sleeping in the worker; bounds are small so the tests stay fast.
START_DELAY = 3.0
VALIDATION_BOUND = 1.5
STARTUP_BOUND = 60.0


def _ok(messages) -> None:
    messages.put({"status": "ok", "messages": ()})


def slow_start_worker(path, messages, ready=None) -> None:
    """Start-up (import) takes longer than the validation bound; validation is then instant."""

    time.sleep(START_DELAY)
    if ready is not None:
        ready.set()
    _ok(messages)


def slow_validation_worker(path, messages, ready=None) -> None:
    """Start-up is instant; validation never finishes within its bound."""

    if ready is not None:
        ready.set()
    time.sleep(60.0)
    _ok(messages)


def never_ready_worker(path, messages, ready=None) -> None:
    """Start-up never completes."""

    time.sleep(60.0)
    _ok(messages)


def test_slow_child_startup_does_not_consume_validation_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_worker", slow_start_worker)

    result = esef_ixbrl._run_arelle_validation(tmp_path / "x.xbri", VALIDATION_BOUND, startup_timeout_seconds=STARTUP_BOUND)

    assert result == ()


def test_slow_validation_after_startup_still_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_worker", slow_validation_worker)

    with pytest.raises(TimeoutError, match="validation exceeded"):
        esef_ixbrl._run_arelle_validation(tmp_path / "x.xbri", 0.5, startup_timeout_seconds=STARTUP_BOUND)


def test_startup_that_never_completes_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_worker", never_ready_worker)

    with pytest.raises(TimeoutError, match="start-up exceeded"):
        esef_ixbrl._run_arelle_validation(tmp_path / "x.xbri", VALIDATION_BOUND, startup_timeout_seconds=0.5)


def test_startup_bound_is_a_conservative_module_constant() -> None:
    assert esef_ixbrl._ARELLE_STARTUP_TIMEOUT_SECONDS >= 30.0
    assert esef_ixbrl._ARELLE_VALIDATION_TIMEOUT_SECONDS == 8.0
