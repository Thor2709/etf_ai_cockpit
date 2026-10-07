from __future__ import annotations

import ast
import re
from pathlib import Path


PAGE_MODULES = (
    "backtests.py",
    "training_centre.py",
    "feature_catalogue.py",
    "data_models.py",
)
PAGE_DIR = Path(__file__).parents[2] / "src" / "etf_cockpit" / "app" / "pages"
ALLOWED_SPACING = {0, 4, 8, 12, 16, 20, 24, 28}


def test_no_literals() -> None:
    for filename in PAGE_MODULES:
        source = (PAGE_DIR / filename).read_text(encoding="utf-8")
        assert re.search(r"#[0-9a-fA-F]{6}", source) is None
        assert "rgba(" not in source
        assert "ft.Colors." not in source.replace("ft.Colors.TRANSPARENT", "")
        assert "border_only" not in source
        assert "ft.Border(" not in source
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or not node.arg:
                continue
            if node.arg == "spacing" or node.arg == "padding" or node.arg.startswith("padding_"):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                    assert node.value.value in ALLOWED_SPACING, f"{filename}:{node.lineno} {node.arg}={node.value.value}"
