"""Document parser entry points for KID, SFDR and index-methodology evidence imports; imported lazily by presentation (application; ADR-0002)."""

from __future__ import annotations

from etf_cockpit.parsers.index_methodology import (
    apply_methodology_holdings_assessment as apply_methodology_holdings_assessment,
    parse_index_methodology as parse_index_methodology,
)
from etf_cockpit.parsers.priips_kid import parse_priips_kid as parse_priips_kid
from etf_cockpit.parsers.sfdr import parse_sfdr as parse_sfdr
