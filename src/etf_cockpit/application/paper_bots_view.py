"""Read model of the paper bots for presentation (application; ADR-0002): forward record plus the labelled replay."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from etf_cockpit.core.paths import ROOT


def load_paper_bots_view(root: Path | None = None, *, as_of: datetime | None = None) -> dict[str, Any]:
    """Return the read-only Bots view data; any failure is an explicit unavailable state, never a partial guess."""

    try:
        from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

        return build_paper_bots_overview(root or ROOT, as_of=as_of)
    except Exception as exc:  # the view must always render
        return {
            "forward": {
                "status": "unavailable", "track": "forward", "label": None, "caveat": None, "as_of": None,
                "reason": f"Paper bot performance unavailable: {type(exc).__name__}.", "bots": [], "execution_allowed": False,
            },
            "replay": None,
            "expectations": [],
            "execution_allowed": False,
        }


__all__ = ["load_paper_bots_view"]
