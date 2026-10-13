from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE_MODULES = (
    ROOT / "src/etf_cockpit/app/pages/instrument_detail.py",
    ROOT / "src/etf_cockpit/app/pages/signals.py",
    ROOT / "src/etf_cockpit/app/pages/screener.py",
    ROOT / "src/etf_cockpit/app/pages/strategy_builder.py",
)
ALLOWED_SPACING = {"0", "4", "8", "12", "16", "20", "24", "28"}


def test_no_literals() -> None:
    violations = []
    for path in PAGE_MODULES:
        source = path.read_text(encoding="utf-8")
        if re.search(r"#[0-9a-fA-F]{6}\b", source):
            violations.append(f"{path.name}: hex colour literal")
        if re.search(r"rgba\s*\(", source, flags=re.IGNORECASE):
            violations.append(f"{path.name}: rgba colour literal")
        if re.search(r"ft\.Colors\.(?!TRANSPARENT\b)[A-Za-z_]+", source):
            violations.append(f"{path.name}: direct Flet colour")
        if "border_only" in source:
            violations.append(f"{path.name}: border_only")
        if re.search(r"ft\.Border\s*\(", source):
            violations.append(f"{path.name}: direct Flet border")
        for match in re.finditer(r"\b(?:spacing|run_spacing|padding)\s*=\s*(-?\d+(?:\.\d+)?)", source):
            if match.group(1) not in ALLOWED_SPACING:
                violations.append(f"{path.name}: disallowed spacing or padding literal {match.group(1)}")

    assert not violations, "\n".join(violations)
