"""Compatibility entry point for the application filing importer."""
from __future__ import annotations

from etf_cockpit.application import official_filing_import as _implementation

globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_implementation.main())
