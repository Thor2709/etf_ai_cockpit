from __future__ import annotations

import ast
from pathlib import Path

from etf_cockpit.application.scope_facade import capability_scope_view
from etf_cockpit.governance.static_checks import run_static_execution_boundary_check
from etf_cockpit.governance.product_scope import load_strategy_scope


ROOT = Path(__file__).resolve().parents[1]


def _research_doc(name: str) -> str:
    return (ROOT / "docs" / "research" / name).read_text(encoding="utf-8").casefold()


def test_pair_trading_is_research_only_and_cannot_authorise_anything() -> None:
    loaded = load_strategy_scope()
    assert loaded.policy is not None
    entry = next(item for item in loaded.policy.entries if item.strategy_id == "pair_trading")
    assert (entry.lifecycle, entry.authority) == ("research_only", "none")
    assert not entry.score_authority
    assert not entry.research_promotion_allowed
    assert not entry.portfolio_review_allowed
    assert not entry.paper_authority
    assert not entry.execution_allowed

    view = capability_scope_view()
    row = next(item for item in view.strategies if item.strategy_id == "pair_trading")
    assert row.lifecycle == "research_only"
    assert row.authority == "none"
    assert not row.score_authority and not row.paper_authority and not row.live_authority
    assert not view.execution_allowed


def test_pair_research_spec_covers_point_in_time_risk_and_cost_controls() -> None:
    text = _research_doc("pair-trading.md")
    for term in (
        "point-in-time",
        "cointegration",
        "stationarity",
        "stationarity break",
        "regime",
        "borrow availability",
        "borrow cost",
        "execution costs",
        "multiple testing",
        "default score",
        "trade signal",
    ):
        assert term in text


def test_triple_barrier_is_research_only_and_cannot_authorise_anything() -> None:
    loaded = load_strategy_scope()
    assert loaded.policy is not None
    entry = next(item for item in loaded.policy.entries if item.strategy_id == "triple_barrier_research")
    assert (entry.lifecycle, entry.authority) == ("research_only", "none")
    assert not entry.score_authority
    assert not entry.research_promotion_allowed
    assert not entry.portfolio_review_allowed
    assert not entry.paper_authority
    assert not entry.execution_allowed


def test_triple_barrier_spec_covers_labels_purging_and_leakage_controls() -> None:
    text = _research_doc("triple-barrier-validation.md")
    for term in (
        "upper horizontal barrier",
        "lower horizontal barrier",
        "vertical barrier",
        "minimum",
        "stability",
        "transparent",
        "purge",
        "embargo",
        "leakage",
        "classifier",
        "issue-0120",
    ):
        assert term in text


def test_research_specs_do_not_add_runtime_modules_or_authority() -> None:
    """Research identifiers may exist only in the governed scope/presentation declarations."""

    allowed_declaration_files = {
        ROOT / "src" / "etf_cockpit" / "governance" / "product_scope.py",
        ROOT / "src" / "etf_cockpit" / "app" / "pages" / "system_map.py",
    }
    identifiers = ("pair_trading", "triple_barrier", "pair-research", "label-research")
    forbidden_modules = {"pair_research", "label_research", "triple_barrier_validation"}
    violations: list[str] = []

    for path in sorted((ROOT / "src" / "etf_cockpit").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [
                    alias.name
                    for alias in node.names
                ] if isinstance(node, ast.Import) else [node.module or ""]
                if any(module.rsplit(".", 1)[-1].casefold() in forbidden_modules for module in modules):
                    violations.append(f"{path}:{node.lineno}: research runtime import")

            values: list[str] = []
            if isinstance(node, ast.Name):
                values.append(node.id)
            elif isinstance(node, ast.Attribute):
                values.append(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                values.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                values.append(node.value)
            if path not in allowed_declaration_files and any(
                identifier in value.casefold() for value in values for identifier in identifiers
            ):
                violations.append(f"{path}:{getattr(node, 'lineno', 0)}: research runtime reference")

    assert not violations
    report = run_static_execution_boundary_check(ROOT)
    assert report.result == "pass"
    assert report.execution_allowed is False
    assert report.executable_authority is False
    assert not report.violations
