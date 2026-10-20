"""Issue #978 (UV1): score and research view-models must not show wrong or stale numbers.

One native test per bughunt entry (or shared parametrised test); every test fails on the pre-fix base.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app import formatting
from etf_cockpit.app.pages import dashboard, macro_factors, screener
from etf_cockpit.application import instrument_detail_view as detail_view
from etf_cockpit.application import score_views
from etf_cockpit.application.alerts import AlertReadback
from etf_cockpit.application.ui_views import comparison as compare_view
from etf_cockpit.application.ui_views import home as home_view
from etf_cockpit.application.ui_views import sectors as sectors_view
from etf_cockpit.application.ui_views import stock_research as research_view


def _walk(control: object) -> Iterator[ft.Control]:
    if not isinstance(control, ft.Control):
        content = getattr(control, "body", None)
        if content is not None:
            yield from _walk(content)
        return
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _texts(control: object) -> list[str]:
    return [str(v) for item in _walk(control) if (v := getattr(item, "value", None)) is not None]


def _prices(rows: dict[str, list[tuple[str, float]]]) -> pd.DataFrame:
    records = [
        {"etf_id": instrument, "date": day, "close": value, "adjusted_close": value}
        for instrument, series in rows.items()
        for day, value in series
    ]
    return pd.DataFrame(records)


# --- E002-N001 / E009 rolling window: a missing month is a gap, never removed before the change is taken ---------


def test_e002_n001_monthly_gap_keeps_missing_months_as_unavailable() -> None:
    prices = _prices(
        {
            "A": [("2026-01-30", 100.0), ("2026-02-27", 100.0), ("2026-04-30", 120.0)],  # March missing
            "B": [("2026-01-30", 100.0), ("2026-02-27", 100.0), ("2026-03-31", 110.0), ("2026-04-30", 120.0)],
        }
    )
    gap = compare_view.monthly_gap(prices, "A", "B", "1Y")
    assert gap.labels == ["Feb 26", "Mar 26", "Apr 26"]
    assert gap.values == [0.0, None, None]  # April would span two months for A: not a one-month return


def test_e009_rolling_12_month_return_does_not_span_missing_months() -> None:
    days = pd.date_range("2025-01-31", periods=16, freq="ME")
    frame = pd.DataFrame({"date": days, "adjusted_close": [100.0 + i for i in range(16)]})
    assert len(research_view.month_end_returns(frame)) == 4  # months 13..16 of a complete history
    holed = frame.drop(index=2).reset_index(drop=True)  # March 2025 has no stored price
    returns = research_view.month_end_returns(holed)
    series = pd.Series(holed["adjusted_close"].to_numpy(), index=pd.DatetimeIndex(holed["date"]))
    assert len(returns) == 3  # the month whose 12-month partner is the hole has no return
    for stamp, value in returns.items():
        earlier = stamp - pd.offsets.MonthEnd(12)
        assert earlier in series.index
        assert value == pytest.approx(series.loc[stamp] / series.loc[earlier] - 1.0)


# --- E002-N002: price formatted in the instrument currency ---------------------------------------------------


def _score(currency: str | None, **extra: object) -> SimpleNamespace:
    base = dict(
        display_id="AAPL", name="Apple", latest_price=123.45, instrument_currency=currency, final_score_10=6.0,
        evidence_quality_10=5.0, risk_friction_10=4.0, instrument_period_return=0.1, latest_date="2026-01-05",
    )
    base.update(extra)
    return SimpleNamespace(**base)


def test_e002_n002_usd_instrument_price_formatted_in_usd() -> None:
    from etf_cockpit.app.pages.comparison import comparison_frame

    frame = comparison_frame(_score("USD"), _score(None, display_id="XYZ"))
    row = frame[frame["Measure"] == "Latest price"].iloc[0]
    assert row["A: AAPL"] == "USD 123.45"
    assert "EUR" not in row["B: XYZ"]  # unknown currency is stated, never assumed
    assert "currency unavailable" in row["B: XYZ"]


def test_format_quote_price_states_unknown_currency() -> None:
    assert formatting.format_quote_price(None, "USD") == "N/A"
    assert formatting.format_quote_price(5, "usd ") == "USD 5.00"
    assert formatting.format_quote_price(5, None) == "5.00 (currency unavailable)"


# --- E003-N001: no substitution of the 1-year return for another window --------------------------------------


@pytest.mark.parametrize("window", ["1M", "3M", "5Y"])
def test_e003_n001_missing_window_return_is_not_replaced_by_1y(window: str) -> None:
    frame = pd.DataFrame(
        [{"security": "ACME", "pe_ratio": 12.0, "roe": 0.2, "sector": "Technology", "market_cap": 1e9, "return_1y": 28.0}]
    )
    points, _reason = sectors_view.bubbles_from_holdings(frame, window)
    assert points and points[0].ret is None
    points_1y, _ = sectors_view.bubbles_from_holdings(frame, "1Y")
    assert points_1y[0].ret == 28.0


# --- E107-N003 / E114-N001: an unavailable regime is never green / OK ----------------------------------------


@pytest.mark.parametrize("label", ["Regime unavailable", "Regime unavailable until refreshed", "unknown", "", None])
def test_e107_n003_unavailable_regime_is_not_ok(label: str | None) -> None:
    assert home_view.regime_available(label) is False
    rows = home_view.build_checks({}, regime_label=label, regime_detail="d", final_mode="Normal", data_status="Clean")
    regime = next(row for row in rows if row.title.startswith("Market regime"))
    assert regime.dot != "ok"
    assert regime.title.endswith("Unavailable")


def test_e107_n003_available_regime_still_ok() -> None:
    rows = home_view.build_checks({}, regime_label="Risk-on", regime_detail="d", final_mode="Normal", data_status="Clean")
    regime = next(row for row in rows if row.title.startswith("Market regime"))
    assert regime.dot == "ok" and regime.title == "Market regime: Risk-on"


@pytest.mark.parametrize("label", ["Regime unavailable", "unknown", None, ""])
def test_e114_n001_macro_page_regime_badge_not_available_when_unavailable(label: str | None) -> None:
    tag = macro_factors._regime_tag(label)
    assert tag.data["text"] == "Unavailable" and tag.data["kind"] != "ok"
    assert macro_factors._regime_tag("Risk-on").data["text"] == "Available"


# --- E108-N003: Top-N winners follow utility_rank, not the alphabetical candidate table ----------------------


def test_e108_n003_top_n_winners_sorted_by_utility_rank() -> None:
    from etf_cockpit.application.selection_views import ordered_winners

    candidates = [
        {"instrument_id": "AAA", "utility_rank": 3, "utility_score": 0.2},
        {"instrument_id": "BBB", "utility_rank": 1, "utility_score": 0.9},
        {"instrument_id": "CCC", "utility_rank": 2, "utility_score": 0.5},
        {"instrument_id": "DDD", "utility_rank": None, "utility_score": None},
    ]
    winners = ordered_winners(candidates, {"AAA", "BBB", "CCC", "DDD"})
    assert [item["instrument_id"] for item in winners] == ["BBB", "CCC", "AAA", "DDD"]
    assert [item["instrument_id"] for item in ordered_winners(candidates, {"AAA", "CCC"})] == ["CCC", "AAA"]


def test_e108_n003_screener_winners_table_order(monkeypatch) -> None:
    result = {
        "status": "available",
        "mode": "cross_asset",
        "selected_ids": ["AAA", "BBB"],
        "candidate_table": [
            {"instrument_id": "AAA", "utility_rank": 2, "utility_score": 0.2},
            {"instrument_id": "BBB", "utility_rank": 1, "utility_score": 0.9},
        ],
        "slices": [],
    }
    monkeypatch.setattr(screener, "load_top_n_selection", lambda **_k: result)
    control = screener._selection_view(None, "2026-01-05T00:00:00+00:00", None)
    text = [value for value in _texts(control)]
    assert text.index("BBB") < text.index("AAA")


# --- E108-N001: chart quality is the canonical evidence_quality of the table ---------------------------------


def test_e108_n001_quality_chart_uses_canonical_evidence_quality() -> None:
    result = SimpleNamespace(
        rows=(
            {"instrument_id": "X", "risk_friction": 4.0, "evidence_quality": 7.5, "quality": 2.0},
            {"instrument_id": "Y", "risk_friction": 5.0, "evidence_quality": None, "quality": 9.0},
        )
    )
    points = screener.quality_risk_points(result)
    assert [(p.name, p.x, p.y) for p in points] == [("X", 4.0, 7.5)]  # Y has no canonical quality: not plotted


# --- E108-N002: a loaded saved screen shows its saved lineage or warns ---------------------------------------


def test_e108_n002_saved_screen_load_warns_when_lineage_differs(monkeypatch) -> None:
    from etf_cockpit.analysis.screening import ScreenQuery
    from etf_cockpit.application.screening_data import saved_lineage_notice

    saved = ScreenQuery(as_of="2025-12-01", universe_revision="rev-old", input_checksum="aaa")
    current = ScreenQuery(as_of="2026-01-05", universe_revision="rev-new", input_checksum="bbb")
    notice = saved_lineage_notice(saved, current)
    assert notice and "2025-12-01" in notice and "rev-old" in notice and "2026-01-05" in notice
    assert saved_lineage_notice(saved, saved) is None
    lineage = screener._lineage(current, saved)
    assert "saved_screen" in lineage and "2025-12-01" in lineage and "rev-old" in lineage


def test_e108_n002_loading_a_saved_screen_shows_the_warning_on_the_page(monkeypatch) -> None:
    from etf_cockpit.analysis.screening import ScreenQuery
    from etf_cockpit.app.state import AppState
    from etf_cockpit.application.snapshot_builder import build_snapshot

    monkeypatch.setattr(screener, "load_top_n_selection", lambda **_k: {"status": "unavailable", "reason": "x", "rows": []})
    monkeypatch.setattr(screener, "load_fixed_income_screener", lambda **_k: {"status": "unavailable", "reason_codes": [], "rows": []})
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    monkeypatch.setattr(screener, "load_screen", lambda _name: ScreenQuery(as_of="1999-01-01", universe_revision="rev-old", input_checksum="old"))
    snapshot = build_snapshot()
    view = screener.screener_page(None, AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf))
    load = next(c for c in _walk(view) if getattr(c, "key", None) == "screener.saved.load")
    load.on_click(None)
    text = "\n".join(_texts(view))
    assert "created on different evidence" in text and "1999-01-01" in text


# --- E108-N004: histogram title follows the sort field -------------------------------------------------------


def test_e108_n004_distribution_title_follows_sort_field(monkeypatch) -> None:
    from etf_cockpit.application.snapshot_builder import build_snapshot
    from etf_cockpit.app.state import AppState

    monkeypatch.setattr(screener, "load_top_n_selection", lambda **_k: {"status": "unavailable", "reason": "x", "rows": []})
    monkeypatch.setattr(screener, "load_fixed_income_screener", lambda **_k: {"status": "unavailable", "reason_codes": [], "rows": []})
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    snapshot = build_snapshot()
    view = screener.screener_page(None, AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf))
    sort = next(c for c in _walk(view) if getattr(c, "key", None) == "screener.sort.field")
    other = next(o.key for o in sort.options if o.key != sort.value and o.key in {"risk_friction", "evidence_quality"})
    sort.value = other
    sort.on_change(None)
    titles = [c.data.get("title") for c in _walk(view) if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == "GlassCard"]
    assert f"Distribution of {screener._human(other)}" in titles


# --- E07-C2-N001 (HIGH): home data-health follows the snapshot, never only the re-read disk health ----------------


def _home_state(status: str, forecasts: pd.DataFrame | None = None) -> SimpleNamespace:
    report = SimpleNamespace(as_of_date="2026-01-05", status=status, blocked_etfs=(), warning_etfs=())
    snapshot = SimpleNamespace(
        data_report=report,
        config=SimpleNamespace(),
        forecasts=forecasts if forecasts is not None else pd.DataFrame(),
        universe_revision="rev",
        prices=pd.DataFrame(),
    )
    return SimpleNamespace(snapshot=snapshot, universe_cache_revision="", last_export_path=None, recent_activity=())


def _score_row(display_id: str, score: float | None, regime: str) -> SimpleNamespace:
    return SimpleNamespace(
        display_id=display_id, name=display_id, final_score_10=score, final_label="watchlist", final_action="",
        one_line_reason="", source_group="Primary", risk_friction_10=6.0, market_regime_label=regime,
    )


@pytest.fixture
def _home_stubs(monkeypatch):
    monkeypatch.setattr(dashboard, "build_data_health", lambda *_a, **_k: SimpleNamespace(rows=[SimpleNamespace(status="healthy")]))
    monkeypatch.setattr(dashboard, "_digest_parts", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no evidence")))
    monkeypatch.setattr(dashboard, "_canonical_forecasts", lambda state: state.snapshot.forecasts, raising=False)
    return monkeypatch


@pytest.mark.parametrize("status, expected", [("Blocked", "Manual review"), ("Warning", "Caution"), ("Clean", "Normal")])
def test_e07_c2_n001_home_mode_follows_snapshot_data_report(_home_stubs, monkeypatch, status, expected) -> None:
    monkeypatch.setattr(score_views, "snapshot_scores", lambda *_a, **_k: [])
    view, _scores = dashboard._home_view(_home_state(status))
    mode = next(row for row in view.checks if row.title.startswith("Final mode"))
    assert mode.title == f"Final mode: {expected}"
    if status != "Clean":
        assert view.data_status != "Clean"


# --- E07-C2-N003: market regime comes from the visible top row, not the first list row ------------------------


def test_e07_c2_n003_regime_taken_from_visible_top_score(_home_stubs, monkeypatch) -> None:
    scores = [_score_row("LOW", 4.0, "Calm"), _score_row("TOP", 9.0, "Stress")]
    monkeypatch.setattr(score_views, "snapshot_scores", lambda *_a, **_k: list(scores))
    view, _ = dashboard._home_view(_home_state("Clean"))
    assert any(row.title == "Market regime: Stress" for row in view.checks)
    assert score_views.visible_top_score(scores).display_id == "TOP"
    assert score_views.visible_top_score([]) is None


# --- E107-N001: the forecast badge lists canonical eligible models only ----------------------------------------


def test_e107_n001_forecast_badge_uses_eligible_models_only(_home_stubs, monkeypatch) -> None:
    monkeypatch.setattr(score_views, "snapshot_scores", lambda *_a, **_k: [])
    forecasts = pd.DataFrame(
        [
            {"etf_id": "A", "model_name": "ModelOk", "status": "ok", "model_allowed_in_score": True},
            {"etf_id": "A", "model_name": "ModelNotAllowed", "status": "ok", "model_allowed_in_score": False},
            {"etf_id": "A", "model_name": "baseline_x", "status": "ok", "model_allowed_in_score": True},
        ]
    )
    view, _ = dashboard._home_view(_home_state("Clean", forecasts))
    assert view.extra_models == ("ModelOk",)


# --- E107-N004: the session audit/export record is never served from the digest cache ---------------------------


def test_e107_n004_audit_digest_follows_session_state(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "_score_history_for_snapshot", lambda _s: pd.DataFrame())
    monkeypatch.setattr(dashboard, "_latest_run_change_report", lambda *_a, **_k: None)
    monkeypatch.setattr(dashboard, "_read_alerts", lambda **_k: AlertReadback("unavailable"))
    monkeypatch.setattr(dashboard, "_contradiction_record", lambda *_a, **_k: [])
    monkeypatch.setattr(dashboard, "_event_record", lambda **_k: None)
    state = _home_state("Clean")
    first = dashboard._digest_parts(state, [])[1]["audit_export"][0]["title"]
    state.last_export_path = "C:/exports/packet.zip"
    second = dashboard._digest_parts(state, [])[1]["audit_export"][0]["title"]
    assert first != second and "available" in second.casefold()


# --- E007-N001: the dashboard news list is cut at the snapshot decision date ----------------------------------


def test_e007_n001_news_digest_hides_news_after_the_decision_date(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "_digest_parts", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")))
    state = _home_state("Clean")
    frame = pd.DataFrame(
        [
            {"published_at": "2026-01-02T10:00:00+00:00", "ingested_at": "2026-01-02T10:05:00+00:00", "headline": "Past headline", "provider_name": "P", "timestamp_status": "valid"},
            {"published_at": "2026-02-10T10:00:00+00:00", "ingested_at": "2026-02-10T10:05:00+00:00", "headline": "Future headline", "provider_name": "P", "timestamp_status": "valid"},
        ]
    )
    dashboard._dashboard_render_cache(state)["news_frame"] = frame
    text = "\n".join(_texts(dashboard._news_digest(None, state)))
    assert "Past headline" in text and "Future headline" not in text


# --- E07-C2-N002: below-fold alerts are read as of the decision date and not capped ---------------------------


def test_e07_c2_n002_alert_digest_uses_decision_date_and_no_cap(monkeypatch) -> None:
    seen: dict[str, object] = {}
    records = tuple(SimpleNamespace(index=i) for i in range(10))

    def read(**kwargs):
        seen.update(kwargs)
        return AlertReadback("available", records)

    monkeypatch.setattr(dashboard, "_read_alerts", read)
    monkeypatch.setattr(dashboard, "_alert_row", lambda _p, _s, record, **_k: ft.Text(f"row-{record.index}"))
    texts = _texts(dashboard._alerts_digest(None, _home_state("Clean")))
    assert seen.get("as_of") is not None and seen.get("limit") is None
    assert sum(1 for value in texts if value.startswith("row-")) == 10


# --- E114-N002: the news page contradiction digest carries every binding ---------------------------------------


def test_e114_n002_news_page_contradictions_receive_all_bindings(monkeypatch) -> None:
    from etf_cockpit.app.pages import news_context

    captured: dict[str, object] = {}

    def fake(news, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(news_context, "contradiction_digest_records", fake)
    state = _home_state("Clean")
    state.snapshot.config = SimpleNamespace(universe=SimpleNamespace(etfs=()))
    monkeypatch.setattr(dashboard, "_score_history_for_snapshot", lambda _s: pd.DataFrame({"run_id": ["r"]}))
    monkeypatch.setattr(dashboard, "load_fundamental_evidence", lambda _p: pd.DataFrame({"instrument_id": ["Z"]}))
    news_context.news_context_page(SimpleNamespace(), state)
    for name in ("macro_context", "fundamentals", "exposures", "score_history"):
        assert name in captured, name
    assert captured["score_history"] is not None and not captured["score_history"].empty


# --- E114-N003: future manual notes are hidden in a historical context -----------------------------------------


def test_e114_n003_future_manual_note_hidden_as_of_an_earlier_date(monkeypatch) -> None:
    manual = pd.DataFrame(
        [
            {"etf_id": "TEST", "as_of_date": "2026-01-02", "title": "Old note", "source": "m"},
            {"etf_id": "TEST", "as_of_date": "2026-03-02", "title": "Future note", "source": "m"},
        ]
    )
    monkeypatch.setattr(detail_view, "load_news_items", lambda _p: pd.DataFrame())
    monkeypatch.setattr(detail_view, "load_manual_news", lambda _p: manual)
    panel = detail_view._news_panel("TEST", pd.DataFrame(), decision_time="2026-01-05")
    headlines = [item["headline"] for item in panel["items"]]
    assert headlines == ["Old note"]
    unfiltered = detail_view._news_panel("TEST", pd.DataFrame())
    assert len(unfiltered["items"]) == 2  # no decision time given: the legacy contract is unchanged


# --- V8 C.C4.S15.N001: a valid 0.0 canonical axis is not replaced by the secondary value -------------------------


def test_v8_n001_zero_canonical_axis_is_kept() -> None:
    signal = SimpleNamespace(
        canonical_score=SimpleNamespace(as_dict=lambda: {"attractiveness_10": 7.0, "expected_return_10": 6.0, "risk_implementation_10": 5.0, "coverage": 0.9}),
        blocked_by=(), total_score=None, supporting_metrics={},
    )
    scoreboard = {
        "final_label": "watchlist", "one_line_reason": "r", "evidence_score_10": 5.0, "latest_price_date": "2026-01-01",
        "canonical_attractiveness_10": 0.0, "canonical_expected_return_10": 0.0, "canonical_risk_implementation_10": 0.0,
        "canonical_coverage": 0.0,
    }
    panel = detail_view._score_panel(signal, scoreboard, {"crowding": {}}, {})
    assert panel["canonical_attractiveness_10"] == 0.0
    assert panel["canonical_expected_return_10"] == 0.0
    assert panel["canonical_risk_implementation_10"] == 0.0
    assert panel["canonical_coverage"] == 0.0


# --- V8 C.C4.S15.N002: same-length replacement of the signals is not served from the score cache ----------------


def test_v8_n002_snapshot_score_cache_follows_signal_content(monkeypatch) -> None:
    monkeypatch.setattr(score_views, "_CACHE", {})
    monkeypatch.setattr(score_views, "context_from_snapshot", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("no ref")))

    def build(config, signals, *_a, **_k):
        return [SimpleNamespace(instrument_key=s.etf_id, display_id=s.etf_id, yahoo_symbol="", final_score_10=s.total_score) for s in signals]

    monkeypatch.setattr(score_views, "build_simple_instrument_scores", build)
    first = SimpleNamespace(etf_id="AAA", total_score=1.0)
    second = SimpleNamespace(etf_id="AAA", total_score=9.0)
    snapshot = SimpleNamespace(signals=[first], forecasts=pd.DataFrame(), prices=pd.DataFrame(), config=None, universe_revision="r")
    assert score_views.snapshot_scores(snapshot, penalise_missing=False)[0].final_score_10 == 1.0
    snapshot.signals = [second]  # same length, same snapshot object
    assert score_views.snapshot_scores(snapshot, penalise_missing=False)[0].final_score_10 == 9.0
    snapshot.signals[0] = first
    assert score_views.snapshot_scores(snapshot, penalise_missing=False)[0].final_score_10 == 1.0
