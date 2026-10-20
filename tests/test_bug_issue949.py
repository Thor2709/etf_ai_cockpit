"""Issue #949: Flet 1.x is a breaking API rewrite; every flet* requirement must stay below 1.0."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest

from etf_cockpit.core import runtime
from etf_cockpit.core.runtime import UnsupportedFletVersionError, check_flet_version

ROOT = Path(__file__).resolve().parents[1]
LOCKED_FLET = (0, 85, 3)
_REQUIREMENT = re.compile(r"^\s*(flet[a-z0-9_-]*)\s*(.*?)\s*(?:#.*)?$", re.IGNORECASE)
_CLAUSE = re.compile(r"^(>=|<=|==|<|>|~=|!=)\s*(\d+(?:\.\d+)*)$")


def _version(text: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in text.split("."))
    return parts + (0,) * (3 - len(parts))


def _flet_specs(lines: list[str]) -> dict[str, list[tuple[str, tuple[int, ...]]]]:
    specs: dict[str, list[tuple[str, tuple[int, ...]]]] = {}
    for raw in lines:
        line = raw.strip().strip('",')
        match = _REQUIREMENT.match(line)
        if match is None or not match.group(1).lower().startswith("flet"):
            continue
        clauses = []
        for clause in filter(None, (item.strip() for item in match.group(2).split(","))):
            parsed = _CLAUSE.match(clause)
            assert parsed is not None, f"unparseable specifier {clause!r} in {raw!r}"
            clauses.append((parsed.group(1), _version(parsed.group(2))))
        specs[match.group(1).lower()] = clauses
    return specs


def _admits(clauses: list[tuple[str, tuple[int, ...]]], version: tuple[int, ...]) -> bool:
    checks = {
        ">=": lambda bound: version >= bound,
        ">": lambda bound: version > bound,
        "<=": lambda bound: version <= bound,
        "<": lambda bound: version < bound,
        "==": lambda bound: version == bound,
        "!=": lambda bound: version != bound,
        "~=": lambda bound: version >= bound and version[0] == bound[0],
    }
    return all(checks[operator](bound) for operator, bound in clauses)


def _has_upper_bound_below_one(clauses: list[tuple[str, tuple[int, ...]]]) -> bool:
    return any(
        (operator == "<" and bound <= (1, 0, 0))
        or (operator == "<=" and bound < (1, 0, 0))
        or (operator == "==" and bound < (1, 0, 0))
        for operator, bound in clauses
    )


def _sources() -> dict[str, list[str]]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "requirements.txt": (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines(),
        "pyproject.toml": list(pyproject["project"]["dependencies"]),
    }


@pytest.mark.parametrize("source", ["requirements.txt", "pyproject.toml"])
def test_every_flet_requirement_is_bounded_below_one_and_admits_the_lock(source: str) -> None:
    specs = _flet_specs(_sources()[source])
    assert {"flet", "flet-web"} <= set(specs), (source, sorted(specs))
    for name, clauses in specs.items():
        assert _has_upper_bound_below_one(clauses), (source, name, clauses)
        assert _admits(clauses, LOCKED_FLET), (source, name, clauses)
        assert not _admits(clauses, (1, 0, 4)), (source, name, clauses)


def test_every_optional_dependency_group_keeps_flet_below_one() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for group, items in pyproject["project"].get("optional-dependencies", {}).items():
        for name, clauses in _flet_specs(list(items)).items():
            assert _has_upper_bound_below_one(clauses), (group, name, clauses)


def test_version_check_rejects_flet_one_and_accepts_the_locked_release() -> None:
    check_flet_version("0.85.3")
    check_flet_version("0.28.0")
    for rejected in ("1.0.4", "1.0.0", "2.3", "", None, "dev"):
        with pytest.raises(UnsupportedFletVersionError, match=r"below 1\.0"):
            check_flet_version(rejected)


def test_runtime_start_fails_closed_on_installed_flet_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.metadata, "version", lambda name: "1.0.4")
    with pytest.raises(UnsupportedFletVersionError, match="1.0.4"):
        runtime.configure_runtime_environment()
    monkeypatch.setattr(runtime.metadata, "version", lambda name: "0.85.3")
    runtime.ensure_supported_flet_version()
