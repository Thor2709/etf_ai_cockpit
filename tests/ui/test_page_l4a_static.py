from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGES = (
    "risk.py",
    "portfolio_optimiser.py",
    "stress_lab.py",
    "decision_journal.py",
    "forward_evidence.py",
    "operations.py",
)
ALLOWED_SPACING = {"0", "4", "8", "12", "16", "20", "24", "28"}


def test_no_literals() -> None:
    bad = []
    for name in PAGES:
        source = (ROOT / "src" / "etf_cockpit" / "app" / "pages" / name).read_text(encoding="utf-8")
        for pattern, label in (
            (r"#[0-9a-fA-F]{6}\b", "hex color"),
            (r"rgba\(", "rgba color"),
            (r"ft\.Colors\.(?!TRANSPARENT\b)", "Flet color"),
            (r"border_only", "border_only"),
            (r"ft\.Border\s*\(", "Flet border"),
        ):
            if re.search(pattern, source):
                bad.append(f"{name}: {label}")
        for match in re.finditer(r"\b(spacing|padding|width|height|size|radius|blur|shadow)\s*=\s*(\d+)\b", source):
            if match.group(2) not in ALLOWED_SPACING:
                bad.append(f"{name}: {match.group(1)}={match.group(2)}")
    assert not bad, "; ".join(bad)
