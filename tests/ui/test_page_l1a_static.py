from __future__ import annotations

import re
from pathlib import Path


PAGE_MODULES = ("onboarding.py", "jobs.py", "settings.py", "import_export.py", "diagnostics.py")
PAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "etf_cockpit" / "app" / "pages"


def test_no_literals():
    violations = []
    for name in PAGE_MODULES:
        source = (PAGE_DIR / name).read_text(encoding="utf-8")
        patterns = (r"#[0-9a-fA-F]{6}", r"rgba\(", r"ft\.Colors\.(?!TRANSPARENT)", r"border_only", r"ft\.Border\(")
        for pattern in patterns:
            if re.search(pattern, source):
                violations.append(f"{name}: {pattern}")
        for value in re.findall(r"(?:spacing|padding)\s*=\s*(\d+)", source):
            if int(value) not in {0, 4, 8, 12, 16, 20, 24, 28}:
                violations.append(f"{name}: {value}")
    assert violations == []
