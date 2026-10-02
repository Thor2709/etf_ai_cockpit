"""Contracts that keep parallel test execution isolated, explicit and self-cleaning."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

import conftest
from etf_cockpit.core import paths

CHECKOUT = Path(__file__).resolve().parents[1]
TESTS = CHECKOUT / "tests"


def test_product_paths_resolve_to_the_private_project_root() -> None:
    isolated = Path(os.environ["ETF_COCKPIT_ROOT"])
    assert isolated.resolve() != CHECKOUT
    assert paths.ROOT == isolated.resolve()
    assert paths.DATA_DIR.resolve().is_relative_to(isolated.resolve())
    for name in ("configs", "data", "artifacts", "logs", "exports", "backups"):
        assert not conftest._is_link(isolated / name), f"{name} must be private, not linked"
    # Read-only checkout content stays reachable, including the markers that enable checkout-only checks.
    assert (isolated / "configs" / "universe.yaml").is_file()
    assert (isolated / "tests").is_dir()
    assert (isolated / ".git").exists()


def test_write_guard_flags_checkout_paths_including_writes_through_links() -> None:
    isolated = Path(os.environ["ETF_COCKPIT_ROOT"])
    assert conftest._checkout_write(CHECKOUT / "docs" / "x.md") is not None
    assert conftest._checkout_write(isolated / "docs" / "x.md") is not None  # linked into the checkout
    assert conftest._checkout_write(isolated / "data" / "x.parquet") is None
    assert conftest._checkout_write(conftest.PYTEST_TEMP / "x") is None
    assert conftest._checkout_write(CHECKOUT / "src" / "__pycache__" / "x.pyc") is None


def test_write_guard_treats_copy_sources_and_read_only_sqlite_as_reads(monkeypatch) -> None:
    violations: list[str] = []
    monkeypatch.setitem(conftest._guard_state, "violations", violations)
    monkeypatch.setitem(conftest._guard_state, "active", True)
    outside = conftest.PYTEST_TEMP / "copy-target"
    conftest._write_guard_hook("shutil.copyfile", (CHECKOUT / "configs" / "universe.yaml", outside))
    conftest._write_guard_hook("sqlite3.connect", (f"file:{CHECKOUT / 'data' / 'x.sqlite3'}?mode=ro",))
    assert violations == []
    conftest._write_guard_hook("shutil.copyfile", (outside, CHECKOUT / "configs" / "universe.yaml"))
    conftest._write_guard_hook("sqlite3.connect", (str(CHECKOUT / "data" / "x.sqlite3"),))
    assert len(violations) == 2


def test_isolated_root_removal_never_follows_links(tmp_path: Path) -> None:
    target = tmp_path / "checkout-content"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    root = conftest.ISOLATED_ROOTS / f"contract-{os.getpid()}"
    root.mkdir(parents=True)
    conftest._link(target, root / "linked")
    (root / "data").mkdir()
    (root / "data" / "private.txt").write_text("private", encoding="utf-8")

    conftest._remove_isolated_root(root)

    assert not root.exists()
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_isolated_root_removal_refuses_paths_outside_the_isolated_roots(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="refusing to remove"):
        conftest._remove_isolated_root(tmp_path)
    with pytest.raises(RuntimeError, match="refusing to remove"):
        conftest._remove_isolated_root(CHECKOUT)


def test_shared_resource_groups_are_justified_and_current() -> None:
    for group, (reason, files) in conftest.SHARED_RESOURCE_GROUPS.items():
        assert reason.strip(), f"group {group} needs a reason"
        assert len(files) >= 2, f"group {group} must merge at least two files"
        for file in files:
            assert (CHECKOUT / file).is_file(), f"group {group} names a missing file: {file}"


def test_every_explicit_serial_marker_states_its_reason() -> None:
    unexplained = []
    for path in TESTS.rglob("test_*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if re.match(r"\s*(@pytest\.mark\.serial|pytestmark\s*=.*mark\.serial)", line):
                context = lines[max(0, index - 3) : index]
                if not any(item.strip().startswith("#") for item in context):
                    unexplained.append(f"{path.relative_to(CHECKOUT).as_posix()}:{index + 1}")
    assert unexplained == []


def test_scheduling_scope_is_the_file_unless_a_resource_group_merges_it() -> None:
    assert conftest._scheduling_scope("tests/test_x.py::test_a[p]") == "tests/test_x.py"
    assert conftest._scheduling_scope("tests\\ui\\test_y.py::TestC::test_b") == "tests/ui/test_y.py"


def test_file_durations_are_well_formed() -> None:
    payload = json.loads((TESTS / "file_durations.json").read_text(encoding="utf-8"))
    assert payload["unit"] == "seconds"
    assert payload["files"]
    assert all(key.startswith("tests/") and key.endswith(".py") for key in payload["files"])
    assert all(value >= 0 for value in payload["files"].values())


def test_data_seed_key_is_deterministic_and_seeded_data_is_private() -> None:
    assert conftest._seed_key() == conftest._seed_key()
    assert not conftest._is_link(Path(os.environ["ETF_COCKPIT_ROOT"]) / "data")


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="fd-relative removal is resolved via /proc")
def test_write_guard_resolves_fd_relative_removal_against_its_directory(tmp_path: Path, monkeypatch) -> None:
    # shutil.rmtree on Linux removes relative names against a directory fd, not the cwd.
    violations: list[str] = []
    monkeypatch.setitem(conftest._guard_state, "violations", violations)
    monkeypatch.setitem(conftest._guard_state, "active", True)
    directory = os.open(tmp_path, os.O_RDONLY)
    try:
        conftest._write_guard_hook("os.remove", ("journal.json", directory))
        conftest._write_guard_hook("os.rmdir", ("data", directory))
    finally:
        os.close(directory)
    assert violations == []
    conftest._write_guard_hook("os.remove", (str(CHECKOUT / "journal.json"), None))
    assert len(violations) == 1


def test_stale_roots_are_pruned_by_heartbeat_and_live_roots_are_kept() -> None:
    stale = conftest.ISOLATED_ROOTS / f"stale-{os.getpid()}"
    live = conftest.ISOLATED_ROOTS / f"live-{os.getpid()}"
    for root in (stale, live):
        root.mkdir(parents=True)
        (root / conftest._HEARTBEAT).touch()
    old = time.time() - conftest._STALE_ROOT_SECONDS - 60
    os.utime(stale / conftest._HEARTBEAT, (old, old))
    try:
        conftest._prune_stale_isolated_roots()
        assert not stale.exists()
        assert live.exists()
        assert Path(os.environ["ETF_COCKPIT_ROOT"]).exists()
    finally:
        conftest._remove_isolated_root(live)


def test_shards_partition_every_scope_exactly_once_and_balance_recorded_time() -> None:
    weights = conftest._file_weights()
    scopes = {conftest._scheduling_scope(f"{path}::x") for path in weights} | {"tests/test_brand_new_file.py"}
    for total in (2, 3, 4):
        assignment = conftest._shard_assignment(total)
        owners = {scope: conftest._shard_of(scope, total, assignment) for scope in scopes}
        assert set(owners.values()) == set(range(1, total + 1))
        loads = [sum(weights.get(scope, 0.0) for scope in scopes if owners[scope] == shard) for shard in range(1, total + 1)]
        assert max(loads) - min(loads) <= max(weights.values())  # LPT bound: within one file of balance


def _use_durations(monkeypatch, tmp_path: Path, payload: dict, workers: str | None) -> None:
    path = tmp_path / "file_durations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(conftest, "_DURATIONS_PATH", path)
    if workers is None:
        monkeypatch.delenv(conftest._XDIST_MAX_ENV, raising=False)
    else:
        monkeypatch.setenv(conftest._XDIST_MAX_ENV, workers)


_SERIAL_HEAVY = {
    "unit": "seconds",
    "files": {
        "tests/test_serial_heavy.py": 60.0,
        "tests/test_p1.py": 40.0,
        "tests/test_p2.py": 40.0,
        "tests/test_p3.py": 40.0,
        "tests/test_p4.py": 40.0,
    },
    "serial_files": {"tests/test_serial_heavy.py": 60.0},
}


def test_serial_aware_shards_still_partition_every_scope_for_every_shard_count(monkeypatch, tmp_path) -> None:
    _use_durations(monkeypatch, tmp_path, _SERIAL_HEAVY, "4")
    scopes = set(_SERIAL_HEAVY["files"]) | {"tests/test_brand_new_file.py"}
    for total in (1, 2, 3, 4):
        assignment = conftest._shard_assignment(total)
        assert assignment == conftest._shard_assignment(total)  # deterministic
        owners = {scope: conftest._shard_of(scope, total, assignment) for scope in scopes}
        assert all(1 <= shard <= total for shard in owners.values())
        assert set(assignment) == set(_SERIAL_HEAVY["files"])  # unknown files fall to the stable hash


def test_serial_seconds_weigh_as_many_times_heavier_as_there_are_workers(monkeypatch, tmp_path) -> None:
    _use_durations(monkeypatch, tmp_path, _SERIAL_HEAVY, "4")
    aware = conftest._shard_assignment(2)
    # Weights 60 (serial) vs 4 x 10 (parallel / 4): the serial file fills a shard on its own.
    assert aware["tests/test_serial_heavy.py"] == 1
    assert {aware[f"tests/test_p{index}.py"] for index in (1, 2, 3, 4)} == {2}
    _use_durations(monkeypatch, tmp_path, _SERIAL_HEAVY, "8")  # more workers: parallel files get lighter still
    assert conftest._shard_assignment(2) == aware


def test_missing_serial_key_or_worker_count_keeps_the_plain_duration_balancing(monkeypatch, tmp_path) -> None:
    plain = {"unit": "seconds", "files": _SERIAL_HEAVY["files"]}
    _use_durations(monkeypatch, tmp_path, plain, "4")
    without_key = conftest._shard_assignment(2)
    assert without_key != {"tests/test_serial_heavy.py": 1, **{f"tests/test_p{i}.py": 2 for i in (1, 2, 3, 4)}}
    _use_durations(monkeypatch, tmp_path, _SERIAL_HEAVY, None)  # no worker source: 1 worker, equal weights
    assert conftest._shard_assignment(2) == without_key
    _use_durations(monkeypatch, tmp_path, _SERIAL_HEAVY, "not-a-number")
    assert conftest._shard_assignment(2) == without_key
    _use_durations(monkeypatch, tmp_path, {"unit": "seconds"}, "4")  # no durations at all
    assert conftest._shard_assignment(3) == {}


@pytest.mark.parametrize("value", ["0/3", "4/3", "x/3", "1"])
def test_invalid_shard_values_are_rejected(value: str) -> None:
    with pytest.raises(pytest.UsageError):
        conftest._parse_shard(value)


def test_test_processes_do_not_leak_the_shard_to_pytest_subprocesses() -> None:
    # Tests that launch pytest themselves must collect the whole suite, whatever shard runs them.
    assert conftest._SHARD_ENV not in os.environ


def test_abandoned_seed_lock_is_reclaimed_after_the_stale_age(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(conftest, "DATA_SEEDS", tmp_path)
    seed = tmp_path / "abcdef"
    lock = tmp_path / "abcdef.lock"
    lock.touch()
    old = time.time() - conftest._SEED_LOCK_STALE_SECONDS - 5
    os.utime(lock, (old, old))
    monkeypatch.setattr(conftest, "_create_isolated_root", lambda: (_ for _ in ()).throw(AssertionError("no build")))
    conftest._build_data_seed(seed)  # abandoned lock: reclaimed, this call does not build
    assert not lock.exists() and not seed.exists()
    assert conftest._SEED_BUILD_TIMEOUT_SECONDS <= conftest._SEED_LOCK_STALE_SECONDS


def test_isolated_roots_and_seeds_live_outside_the_checkout() -> None:
    for path in (conftest.ISOLATED_ROOTS, conftest.DATA_SEEDS, Path(os.environ["ETF_COCKPIT_ROOT"])):
        assert not path.resolve().is_relative_to(CHECKOUT), path
