from __future__ import annotations

import re
from pathlib import Path


PAGE_MODULES = (
    "src/etf_cockpit/app/pages/data_health.py",
    "src/etf_cockpit/app/pages/provider_status.py",
    "src/etf_cockpit/app/pages/catalogue.py",
    "src/etf_cockpit/app/pages/filings.py",
    "src/etf_cockpit/app/pages/etf_disclosures.py",
    "src/etf_cockpit/app/pages/news_context.py",
    "src/etf_cockpit/app/pages/macro_factors.py",
    "src/etf_cockpit/app/pages/_l2_common.py",
)
ALLOWED_SPACING = {0, 4, 8, 12, 16, 20, 24, 28}


def test_no_literals() -> None:
    root = Path(__file__).parents[2]
    violations: list[str] = []
    for relative in PAGE_MODULES:
        source = (root / relative).read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), start=1):
            if re.search(r"#[0-9a-fA-F]{6}\b|rgba\s*\(|border_only|ft\.Border\s*\(", line):
                violations.append(f"{relative}:{line_number}: forbidden style literal")
            if re.search(r"ft\.Colors\.(?!TRANSPARENT\b)", line):
                violations.append(f"{relative}:{line_number}: direct Flet colour")
            for match in re.finditer(r"\b(?:spacing|padding|gap)\s*=\s*(\d+)\b", line):
                if int(match.group(1)) not in ALLOWED_SPACING:
                    violations.append(f"{relative}:{line_number}: spacing outside token set")
            for match in re.finditer(r"\b(?:width|height|size|radius|shadow)\s*=\s*(\d+(?:\.\d+)?)\b", line):
                violations.append(f"{relative}:{line_number}: literal size or shadow value")
    assert not violations, "\n".join(violations)
