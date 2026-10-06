"""Document parser entry points for KID, SFDR and index-methodology evidence imports (application; ADR-0002).

Each parser module is imported only when its entry point is first requested (PEP 562), so a callback that needs one
parser does not load the others.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etf_cockpit.parsers.index_methodology import (
        apply_methodology_holdings_assessment,
        parse_index_methodology,
    )
    from etf_cockpit.parsers.priips_kid import parse_priips_kid
    from etf_cockpit.parsers.sfdr import parse_sfdr

__all__ = [
    "apply_methodology_holdings_assessment",
    "parse_index_methodology",
    "parse_priips_kid",
    "parse_sfdr",
]


def __getattr__(name: str) -> object:
    if name == "parse_priips_kid":
        from etf_cockpit.parsers.priips_kid import parse_priips_kid

        return parse_priips_kid
    if name in ("parse_index_methodology", "apply_methodology_holdings_assessment"):
        from etf_cockpit.parsers import index_methodology

        return getattr(index_methodology, name)
    if name == "parse_sfdr":
        from etf_cockpit.parsers.sfdr import parse_sfdr

        return parse_sfdr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
