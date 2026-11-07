"""Compatibility import for the canonical portfolio data-readiness gate.

Both import paths resolve to the same module so existing application callers
and their injected evaluators keep using the gate enforced by the recorders.
Portfolio code imports the lower-layer module directly (ADR-0002).
"""

from __future__ import annotations

import sys

from etf_cockpit.portfolio import paper_bots_readiness

sys.modules[__name__] = paper_bots_readiness
