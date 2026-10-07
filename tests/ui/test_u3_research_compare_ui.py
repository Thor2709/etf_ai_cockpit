from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.pages import comparison, strategy_builder
from etf_cockpit.app.components.shell.page_view import PageView


def _walk(control):
    yield control
    for attr in ("content", "controls"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        for item in child if isinstance(child, (list, tuple)) else [child]:
            if hasattr(item, "__dict__"):
                yield from _walk(item)


def _score(display_id: str, price):
    return SimpleNamespace(
        display_id=display_id, name=f"Name {display_id}", latest_price=price, final_score_10=None,
        evidence_quality_10=None, risk_friction_10=None, instrument_period_return=None, latest_date=None,
    )


def test_comparison_frame_keeps_missing_values_explicit() -> None:
    frame = comparison.comparison_frame(_score("AAA", None), _score("BBB", 10.0))
    assert list(frame.columns) == ["Measure", "A: AAA", "B: BBB"]
    row = frame[frame["Measure"] == "Final score"].iloc[0]
    assert row["A: AAA"] == "Unavailable" and row["B: BBB"] == "Unavailable"
    assert frame[frame["Measure"] == "Coverage"].iloc[0]["A: AAA"] == "partial/unavailable"


def test_comparison_frame_handles_identical_ids() -> None:
    frame = comparison.comparison_frame(_score("AAA", 1.0), _score("AAA", 1.0))
    assert len(set(frame.columns)) == 3


def test_comparison_table_uses_kit_glass_and_plate() -> None:
    panel = comparison._comparison_table(_score("AAA", None), _score("BBB", 2.0))
    keys = {getattr(c, "key", None) for c in _walk(panel)}
    assert {"comparison.evidence", "comparison.table"} <= keys


def test_comparison_export_writes_local_csv(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages import comparison as module

    monkeypatch.setattr(module, "EXPORTS_DIR", tmp_path)
    result = module.export_table("comparison_aligned_evidence", module.comparison_frame(_score("AAA", None), _score("BBB", 1.0)), tmp_path / "c.csv")
    assert result.ok and (tmp_path / "c.csv").read_text(encoding="utf-8").startswith("Measure,A: AAA,B: BBB")


def test_strategy_builder_cards_have_stable_keys_and_status_tags(tmp_path, monkeypatch) -> None:
    page = SimpleNamespace(update=lambda: None)
    state = SimpleNamespace(snapshot=SimpleNamespace(signals=()))
    content = strategy_builder.strategy_builder_page(page, state)
    assert isinstance(content, PageView)
    keys = {getattr(c, "key", None) for c in _walk(content.body)}
    assert any(str(k).startswith("strategy-builder.card.") for k in keys)
    assert any(str(k).startswith("strategy-builder.status.") for k in keys)
    assert "strategy-builder.template.*" in keys
    assert isinstance(content.body, ft.Column)
