"""Shared plumbing for the refactor parity goldens: isolated root, capture subprocess, golden comparison."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "refactor_parity"
REFRESH_ENV = "ETF_REFRESH_REFACTOR_GOLDENS"
CAPTURE_SCRIPT = Path(__file__).with_name("_capture.py")
CAPTURE_TIMEOUT_SECONDS = 600

_PRIVATE_DIRECTORIES = ("configs", "data", "artifacts", "logs", "exports", "backups")
# Never linked into the capture root: weights (availability must not depend on the developer machine),
# VCS state, the tests themselves and caches.
_SKIPPED_ENTRIES = {"models", "tests", ".git", ".hypothesis", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}

FLOAT_REL = 1e-9
FLOAT_ABS = 1e-12


def _tracked_files(directories: tuple[str, ...]) -> list[str] | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z", "--", *directories],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [item for item in completed.stdout.decode("utf-8").split("\0") if item]


def _link(source: Path, destination: Path) -> None:
    if source.is_dir():
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(source), str(destination))
        else:
            destination.symlink_to(source, target_is_directory=True)
    else:
        shutil.copy2(source, destination)


def build_capture_root(root: Path) -> Path:
    """Create a private project root: tracked configs/data copied, other top-level entries linked.

    Mirrors tests/conftest.py ``_create_isolated_root`` except that ``models/`` is NOT linked, so optional
    model availability is the same on every machine (no weights).  Nothing under the checkout is written.
    """

    root.mkdir(parents=True)
    for entry in REPO.iterdir():
        if entry.name not in _PRIVATE_DIRECTORIES and entry.name not in _SKIPPED_ENTRIES:
            _link(entry, root / entry.name)
    tracked = _tracked_files(("configs", "data"))
    if tracked is None:
        tracked = [path.relative_to(REPO).as_posix() for path in (REPO / "configs").rglob("*") if path.is_file()]
    for relative in tracked:
        source = REPO / relative
        if source.is_file():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for name in _PRIVATE_DIRECTORIES:
        (root / name).mkdir(exist_ok=True)
    return root


def remove_capture_root(root: Path) -> None:
    """Delete a capture root without following links back into the checkout."""

    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_symlink() or os.path.isjunction(entry):
            if os.path.isjunction(entry):
                os.rmdir(entry)
            else:
                entry.unlink()
    shutil.rmtree(root, ignore_errors=True)


def run_capture(root: Path, output: Path, *, now_offset_days: int = 0) -> dict[str, object]:
    # Start from a clean ETF_COCKPIT_* namespace: only the variables set below may influence the capture.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("ETF_COCKPIT_")}
    environment.update(
        {
            "ETF_COCKPIT_ROOT": str(root),
            "ETF_COCKPIT_OFFLINE": "1",
            "ETF_COCKPIT_OPEN_BROWSER": "0",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TZ": "UTC",
            "PYTHONPATH": os.pathsep.join(
                filter(None, [str(REPO / "src"), str(Path(__file__).resolve().parents[1]), environment.get("PYTHONPATH", "")])
            ),
        }
    )
    for name in ("YAHOO_API_KEY", "OPENAI_API_KEY"):
        environment.pop(name, None)
    completed = subprocess.run(
        [sys.executable, str(CAPTURE_SCRIPT), str(output), str(now_offset_days)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=CAPTURE_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise AssertionError(f"capture subprocess failed ({completed.returncode}):\n{completed.stderr[-4000:]}")
    return json.loads(output.read_text(encoding="utf-8"))


# --- golden fixtures --------------------------------------------------------------------------------


def refresh_requested() -> bool:
    return os.environ.get(REFRESH_ENV) == "1"


def _allow_checkout_writes_for_refresh() -> None:
    """Refresh mode writes into tests/fixtures, which tests/conftest.py's checkout write guard would flag."""

    state = getattr(sys.modules.get("conftest"), "_guard_state", None)
    if isinstance(state, dict):
        state["active"] = False


def assert_matches_golden(name: str, actual: dict[str, object], *, notes: str) -> None:
    """Compare ``actual`` with tests/fixtures/refactor_parity/<name>.json (``notes`` is documentation, not compared).

    With ETF_REFRESH_REFACTOR_GOLDENS=1 the fixture is rewritten and the test then fails on purpose, so a
    refresh can never pass silently.
    """

    path = FIXTURE_DIR / f"{name}.json"
    payload = json.loads(json.dumps({"notes": notes, **actual}, allow_nan=False))
    if refresh_requested():
        _allow_checkout_writes_for_refresh()
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_golden(payload) + "\n", encoding="utf-8", newline="\n")
        pytest.fail(f"golden {path.name} regenerated; re-run without {REFRESH_ENV} to verify it", pytrace=False)
    assert_section_matches_fixture(name, payload)


def dump_golden(value: object, level: int = 0) -> str:
    """Deterministic JSON text: one line per dict entry, lists of scalars on a single line (diff-friendly)."""

    pad = " " * (level + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{pad}{json.dumps(key, ensure_ascii=False)}: {dump_golden(item, level + 1)}" for key, item in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + " " * level + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ", ".join(json.dumps(item, ensure_ascii=False, allow_nan=False) for item in value) + "]"
        return "[\n" + ",\n".join(f"{pad}{dump_golden(item, level + 1)}" for item in value) + "\n" + " " * level + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def assert_section_matches_fixture(name: str, actual: dict[str, object]) -> None:
    expected = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    expected.pop("notes", None)
    actual = {key: value for key, value in actual.items() if key != "notes"}
    mismatches: list[str] = []
    compare(expected, actual, "$", mismatches)
    assert not mismatches, f"{name}.json: {len(mismatches)} difference(s); first ones:\n  " + "\n  ".join(mismatches[:25])


def compare(expected: object, actual: object, where: str, mismatches: list[str]) -> None:
    """Exact for str/int/bool/None/keys/order; approx (rel 1e-9, abs 1e-12) for floats."""

    if isinstance(expected, dict) and isinstance(actual, dict):
        if list(expected) != list(actual):
            mismatches.append(f"{where}: keys {list(expected)} != {list(actual)}")
            return
        for key in expected:
            compare(expected[key], actual[key], f"{where}.{key}", mismatches)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            mismatches.append(f"{where}: length {len(expected)} != {len(actual)}")
            return
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            compare(left, right, f"{where}[{index}]", mismatches)
    elif isinstance(expected, bool) or isinstance(actual, bool) or expected is None or actual is None:
        if expected is not actual:
            mismatches.append(f"{where}: {expected!r} != {actual!r}")
    elif isinstance(expected, float) or isinstance(actual, float):
        if not (isinstance(expected, (int, float)) and isinstance(actual, (int, float))) or not (
            float(actual) == pytest.approx(float(expected), rel=FLOAT_REL, abs=FLOAT_ABS)
        ):
            mismatches.append(f"{where}: {expected!r} != {actual!r}")
    elif expected != actual or type(expected) is not type(actual):
        mismatches.append(f"{where}: {expected!r} != {actual!r}")
