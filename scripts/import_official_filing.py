"""Compatibility entry point for the application filing importer."""
from __future__ import annotations

import sys

from etf_cockpit.application import official_filing_import as _implementation

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
