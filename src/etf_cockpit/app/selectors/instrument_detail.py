"""Compatibility alias: the instrument-detail view model is application code (ADR-0002).

The implementation lives in ``etf_cockpit.application.instrument_detail_view``.  This module object *is* that module,
so existing imports, private-name imports and monkeypatches through the old path keep working unchanged.
"""

import sys

from etf_cockpit.application import instrument_detail_view as _view

sys.modules[__name__] = _view
