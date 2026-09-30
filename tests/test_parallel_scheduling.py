"""Contracts that keep parallel test execution isolated, explicit and self-cleaning."""

from __future__ import annotations

import json
import os
import re
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
