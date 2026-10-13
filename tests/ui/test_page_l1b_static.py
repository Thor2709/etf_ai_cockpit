from __future__ import annotations

import ast
import re
from pathlib import Path


PAGES = {
    "errors_recovery.py": {"errors_recovery_page"},
    "trust_evidence.py": {"evidence_ledger_page"},
    "chatgpt_audit.py": {"chatgpt_audit_page"},
    "system_map.py": {"system_map_page"},
    "release_readiness.py": {"release_readiness_page"},
    "programme_map.py": {"programme_map_page"},
}
ALLOWED_SPACING = {0, 4, 8, 12, 16, 20, 24, 28}
STYLE_KEYS = {"color", "size", "width", "height", "radius", "shadow", "spacing", "padding", "gap", "run_spacing"}


def test_no_literals() -> None:
    root = Path(__file__).parents[2] / "src" / "etf_cockpit" / "app" / "pages"
    for filename, names in PAGES.items():
        source = (root / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        assert {node.name for node in functions} == names
        for function in functions:
            page_source = ast.get_source_segment(source, function) or ""
            assert re.search(r"#[0-9a-fA-F]{6}\b", page_source) is None
            assert "rgba(" not in page_source.casefold()
            assert "ft.Colors." not in page_source or "ft.Colors.TRANSPARENT" in page_source
            assert "border_only" not in page_source
            assert "ft.Border(" not in page_source
            for node in ast.walk(function):
                if isinstance(node, ast.Call):
                    for keyword in node.keywords:
                        if keyword.arg in STYLE_KEYS and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, (int, float)):
                            value = keyword.value.value
                            assert value in ALLOWED_SPACING, f"{filename}:{keyword.arg}={value}"
