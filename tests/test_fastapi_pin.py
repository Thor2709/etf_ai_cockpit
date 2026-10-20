"""flet-web 0.85 constructs FastAPI(openapi_prefix=...), a keyword FastAPI removed in 0.145.

An unbounded transitive FastAPI let CI resolve 0.150.0 and the packaged smoke could not start
(TypeError: unexpected keyword argument 'openapi_prefix'). Every requirement source must keep it below 0.145.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
_BOUND = (0, 145)


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


@pytest.mark.parametrize("name", ["requirements.txt", "pyproject.toml"])
def test_fastapi_has_an_upper_bound_below_0_145(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    match = re.search(r"^\s*\"?fastapi\s*<\s*([0-9.]+)", text, re.MULTILINE)
    assert match, f"{name} must bound fastapi below 0.145"
    assert _version(match.group(1))[:2] <= _BOUND


def test_release_lock_pins_fastapi_below_0_145() -> None:
    text = (ROOT / "requirements-release.txt").read_text(encoding="utf-8")
    match = re.search(r"^fastapi==([0-9.]+)\s*$", text, re.MULTILINE)
    assert match, "requirements-release.txt must pin fastapi"
    assert _version(match.group(1))[:2] < _BOUND


def test_installed_fastapi_still_accepts_openapi_prefix() -> None:
    fastapi = pytest.importorskip("fastapi")
    app = fastapi.FastAPI(openapi_prefix="")
    assert app is not None
