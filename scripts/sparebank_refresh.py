"""Compatibility entry point for the application sparebank refresh service."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(_REPOSITORY_ROOT / "src"), str(_REPOSITORY_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

_implementation = import_module("etf_cockpit.application.sparebank_refresh")

globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
load_sparebank_records = _implementation.load_sparebank_records
_resolve_lei = _implementation._resolve_lei


def refresh_sparebanks(*args, **kwargs):
    """Forward the compatibility module's patchable loader and LEI resolver."""
    kwargs.setdefault("record_loader", load_sparebank_records)
    kwargs.setdefault("lei_resolver", _resolve_lei)
    return _implementation.refresh_sparebanks(*args, **kwargs)


def rescore_sparebanks_at(*args, **kwargs):
    """Delegate with the compatibility module's patchable record loader."""
    kwargs.setdefault("record_loader", load_sparebank_records)
    return _implementation.rescore_sparebanks_at(*args, **kwargs)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_implementation.main())
