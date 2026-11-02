"""Compatibility entry point for the application sparebank refresh service."""
from __future__ import annotations

from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(_REPOSITORY_ROOT / "src"), str(_REPOSITORY_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from etf_cockpit.application import sparebank_refresh as _implementation

globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_implementation.main())
