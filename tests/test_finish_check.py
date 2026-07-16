from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import smoke_app


def test_smoke_declares_all_required_modes() -> None:
    parser = smoke_app.build_parser()
    mode_action = next(action for action in parser._actions if action.dest == "mode")

    assert set(mode_action.choices) == {"source", "native", "portable-native", "launcher", "first-run", "offline"}
    assert smoke_app.parse_args(["--mode", "offline"]).mode == "offline"


def test_smoke_validates_the_configured_flet_title(tmp_path, monkeypatch) -> None:
    title_source = tmp_path / "src" / "etf_cockpit" / "app" / "flet_app.py"
    title_source.parent.mkdir(parents=True)
    title_source.write_text('page.title = "ETF AI Evidence Cockpit"\n', encoding="utf-8")
    monkeypatch.setattr(smoke_app, "ROOT", tmp_path)

    smoke_app.verify_expected_title()


def test_smoke_rejects_a_process_from_an_unexpected_path(tmp_path) -> None:
    expected = tmp_path / "expected.exe"
    unexpected = tmp_path / "unexpected.exe"
    process = SimpleNamespace(args=[str(unexpected)])

    with pytest.raises(RuntimeError, match="unexpected executable"):
        smoke_app.verify_process_path(process, expected)
