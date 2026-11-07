"""Compatibility entry point for the application point-in-time history service."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(_REPOSITORY_ROOT / "src"), str(_REPOSITORY_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

_implementation = import_module("etf_cockpit.application.pit_history")

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
