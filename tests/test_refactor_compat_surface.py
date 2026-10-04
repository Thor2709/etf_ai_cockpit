"""Compatibility surface for the architecture refactor.

``tests/fixtures/refactor_surface/compat_names_v1.json`` lists every name that src/, tests/ and
scripts/ consumed (imports, module attributes and monkeypatch targets) from the modules the refactor
moves, at origin/main 5e501154.  While code moves behind compatibility shims those names must stay
reachable through the old module paths.  Removing a name is a deliberate final-phase change that
first migrates every consumer and then edits the fixture in the same commit.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "refactor_surface" / "compat_names_v1.json"
SURFACE = json.loads(FIXTURE.read_text(encoding="utf-8"))["modules"]


@pytest.mark.parametrize("module_name", sorted(SURFACE))
def test_legacy_module_keeps_consumed_names(module_name: str) -> None:
    module = importlib.import_module(module_name)
    missing = [name for name in SURFACE[module_name] if not hasattr(module, name)]
    assert not missing, f"{module_name} lost consumed names: {missing}"
