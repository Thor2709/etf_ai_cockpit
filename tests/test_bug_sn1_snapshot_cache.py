"""#960 E104 N001: the shared snapshot must be stored under the fingerprint read BEFORE the build."""

from __future__ import annotations

import pytest

from etf_cockpit.app import state as state_module


@pytest.fixture
def harness(monkeypatch):
    fingerprint = {"value": 1}
    builds: list[int] = []
    hooks: dict[str, object] = {"during_build": None}

    def fake_build():
        builds.append(fingerprint["value"])
        hook = hooks["during_build"]
        if hook is not None:
            hook(len(builds))
        return {"built_with": builds[-1], "n": len(builds)}

    monkeypatch.setattr(state_module, "_data_fingerprint", lambda: (fingerprint["value"],))
    monkeypatch.setattr(state_module, "build_snapshot", fake_build)
    monkeypatch.setattr(state_module, "_SHARED_SNAPSHOT", {})
    return fingerprint, builds, hooks


def test_input_change_during_build_rebuilds_on_next_call(harness):
    fingerprint, builds, hooks = harness

    def change_once_on_first_and_second_build(n):
        fingerprint["value"] = 1 + n  # inputs keep moving while building

    hooks["during_build"] = change_once_on_first_and_second_build
    state_module._shared_snapshot()
    assert len(builds) == 2  # rebuilt once within the call
    assert not state_module.shared_snapshot_is_current()  # still moving: not pinned as current
    hooks["during_build"] = None
    state_module._shared_snapshot()
    assert len(builds) == 3
    assert state_module._shared_snapshot()["built_with"] == fingerprint["value"]
    assert state_module.shared_snapshot_is_current()


def test_change_during_single_build_is_picked_up_by_one_rebuild(harness):
    fingerprint, builds, hooks = harness
    hooks["during_build"] = lambda n: fingerprint.__setitem__("value", 2) if n == 1 else None
    snapshot = state_module._shared_snapshot()
    assert builds == [1, 2]
    assert snapshot["built_with"] == 2
    assert state_module.shared_snapshot_is_current()


def test_unchanged_inputs_reuse_snapshot(harness):
    _, builds, _ = harness
    first = state_module._shared_snapshot()
    assert state_module._shared_snapshot() is first
    assert len(builds) == 1
    assert state_module.shared_snapshot_is_current()


def test_stored_key_is_pre_build_fingerprint(harness):
    fingerprint, _, hooks = harness
    hooks["during_build"] = lambda n: fingerprint.__setitem__("value", 99) if n == 1 else None
    stored_keys = []
    original = state_module._shared_snapshot

    state_module._shared_snapshot()
    stored_keys.append(state_module._SHARED_SNAPSHOT["key"])
    assert original is state_module._shared_snapshot
    # second (final) build started with fingerprint 99, so the stored key is the pre-build value of that build
    assert stored_keys == [(99,)]

    # and with a build that changes inputs on every attempt, the key stays at the pre-build value, not the current one
    hooks["during_build"] = lambda n: fingerprint.__setitem__("value", fingerprint["value"] + 1)
    fingerprint["value"] = 5
    state_module._SHARED_SNAPSHOT.clear()
    state_module._shared_snapshot()
    assert state_module._SHARED_SNAPSHOT["key"] != state_module._data_fingerprint()
