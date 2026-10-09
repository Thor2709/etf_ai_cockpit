from __future__ import annotations

import os
from types import SimpleNamespace

import flet as ft

from etf_cockpit.app import flet_app
from etf_cockpit.app.pages import comparison, dashboard, signals, stock_research
from etf_cockpit.application.ui_views.home import score_rows
from etf_cockpit.application.ui_views.stock_research import StockView


_SCORECARD_REASON = "Underwriting is determined by the Sparebank scorecard; tactical evidence is presented separately."


def _scorecard() -> SimpleNamespace:
    return SimpleNamespace(
        display_id="SPAR1",
        name="Sparebank 1 SR-Bank",
        instrument_key="SPAR1",
        source_group="Sparebanken",
        final_score_10=None,
        final_label="scorecard_owned",
        final_action="manual_review",
        one_line_reason=_SCORECARD_REASON,
        risk_friction_10=None,
        evidence_quality_10=None,
        components=[],
        warnings=[],
    )


def test_sparebank_scorecard_cells_keep_reason_and_open_sparebanken_scores(monkeypatch) -> None:
    score = _scorecard()
    row = score_rows([score], {})[0]
    assert row.scorecard_reason == _SCORECARD_REASON

    navigations: list[str] = []
    monkeypatch.setattr(dashboard, "_go_to", lambda _page, _state, route: navigations.append(route))
    home_cell = dashboard._score_cell(SimpleNamespace(), SimpleNamespace(), row, 80)
    assert home_cell.data["kit"] == "Tag" and home_cell.data["text"] == "Scorecard"
    assert home_cell.tooltip == _SCORECARD_REASON
    home_cell.on_click(None)
    assert navigations == ["/signals?tier=Sparebanken"]

    signal_navigations: list[str] = []
    signal_cell = signals._score_rows(
        [score], lambda _event: signal_navigations.append("/signals?tier=Sparebanken")
    )[0]["score"]
    assert signal_cell.data["kit"] == "Tag" and signal_cell.data["text"] == "Scorecard"
    assert signal_cell.tooltip == _SCORECARD_REASON
    signal_cell.on_click(None)
    assert signal_navigations == ["/signals?tier=Sparebanken"]
    assert signals._requested_tier(SimpleNamespace(route=signal_navigations[0])) == "Sparebanken"

    comparison_navigations: list[str] = []
    comparison_cell = comparison._row_values(
        "Final score",
        score,
        "",
        "—",
        on_scorecard_click=lambda _event: comparison_navigations.append("/signals?tier=Sparebanken"),
    )
    assert comparison_cell.data["kit"] == "Tag" and comparison_cell.data["text"] == "Scorecard"
    assert comparison_cell.tooltip == _SCORECARD_REASON
    comparison_cell.on_click(None)
    assert comparison_navigations == ["/signals?tier=Sparebanken"]


def test_stock_research_explains_missing_forecast_run() -> None:
    view = StockView("SPAR1", "1Y", unavailable_price="No stored price rows for this instrument.")
    card = stock_research._hero_card(600, 420, view, {"currency": "NOK"}, None)

    assert card.data["title"] == "Price, forecast & drawdown"
    assert card.data["note_control"].value == "NOK · close · Forecast unavailable — no forecast run yet"


def test_desktop_and_web_launch_use_the_same_main_and_assets(monkeypatch) -> None:
    calls: list[tuple[dict[str, object], str | None, str | None]] = []

    def fake_flet_app(**kwargs) -> None:
        calls.append((kwargs, os.getenv("FLET_PLATFORM"), os.getenv("FLET_FORCE_WEB_SERVER")))

    monkeypatch.setattr(flet_app, "_patch_flet_static_temp_dir", lambda: None)
    monkeypatch.setattr(flet_app, "_attach_windowed_stdio", lambda: None)
    monkeypatch.setattr(flet_app, "_reuse_existing_web_server", lambda *_args: False)
    monkeypatch.setattr(flet_app, "_fallback_port_if_busy", lambda port: port)
    monkeypatch.setattr(flet_app, "_startup_log", lambda _message: None)
    monkeypatch.setattr(flet_app, "init_session_log", lambda **_kwargs: None)
    monkeypatch.setattr(flet_app, "_resolve_flet_app", lambda: fake_flet_app)
    monkeypatch.setenv("ETF_COCKPIT_PORT", "9855")
    monkeypatch.setenv("ETF_COCKPIT_OPEN_BROWSER", "0")
    monkeypatch.setenv("FLET_PLATFORM", "web")
    monkeypatch.setenv("FLET_FORCE_WEB_SERVER", "true")

    monkeypatch.setenv("ETF_COCKPIT_VIEW", "desktop")
    flet_app.run()
    assert calls[0][0]["view"] == ft.AppView.FLET_APP
    assert calls[0][1:] == (None, None)

    monkeypatch.setenv("FLET_PLATFORM", "web")
    monkeypatch.setenv("ETF_COCKPIT_VIEW", "web")
    flet_app.run()

    desktop, web = calls[0][0], calls[1][0]
    assert desktop["target"] is web["target"] is flet_app.main
    assert desktop["assets_dir"] == web["assets_dir"] == str(flet_app.theme.ASSETS_DIR)


def test_sparebank_native_score_shows_bar_not_pending_tag() -> None:
    score = _scorecard()
    score.final_score_10 = 5.65
    row = score_rows([score], {})[0]
    assert row.scorecard_reason is None and row.rank == 1
    assert dashboard._score_cell(None, SimpleNamespace(), row, 80).data["kit"] != "Tag"
    assert signals._score_rows([score])[0]["score"].data["kit"] != "Tag"
    assert comparison._row_values("Final score", score, "", "—").data["kit"] != "Tag"


def test_score_ring_and_headline_use_list_scale() -> None:
    ring = signals._score_ring(5.65)
    assert ring.data["score"] == 56.5
    assert "5.7" in str(ring.controls) or any("5.7" in str(c) for c in ring.controls)
    scored, pending = _scorecard(), _scorecard()
    scored.final_score_10 = 5.65
    assert signals._scored_headline([scored, pending]) == "1 of 2 instruments scored"


def test_detail_headline_uses_canonical_list_score(monkeypatch) -> None:
    from etf_cockpit.app.pages import instrument_detail
    from etf_cockpit.application.instrument_detail_view import InstrumentDetailViewModel

    model = InstrumentDetailViewModel("NONG", "Bank", "available", {"instrument_id": "NONG"}, {"scores": {"evidence_score": None}})
    listed = _scorecard()
    listed.final_score_10 = 7.08
    listed.one_line_reason = "Sparebank scorecard 7.1/10 from 30% of axis evidence."
    monkeypatch.setattr(instrument_detail, "_listed_score", lambda _state, _iid: listed)
    card = instrument_detail._score_card(model, None, SimpleNamespace())
    ring = next(c for c in _walk(card) if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == "VerdictRing")
    assert ring.data["score"] == 70.8
    assert any("Generic components do not apply" in str(getattr(c, "value", "")) for c in _walk(card))


def _walk(node):
    yield node
    for child in getattr(node, "controls", None) or []:
        yield from _walk(child)
    content = getattr(node, "content", None)
    if content is not None:
        yield from _walk(content)
