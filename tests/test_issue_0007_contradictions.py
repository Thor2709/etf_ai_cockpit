from __future__ import annotations

from types import SimpleNamespace
from datetime import date

import pandas as pd

from etf_cockpit.app.pages.dashboard import _news_digest
from etf_cockpit.app.pages.instrument_detail import render_news_contradiction_panel
from etf_cockpit.app.pages.trust_evidence import _news_context_extra
from etf_cockpit.application.digest import contradiction_digest_records
from etf_cockpit.chatgpt_bridge import export_pack
from etf_cockpit.data.news_context import build_news_macro_contradictions


CUTOFF = "2026-08-12T23:59:59+00:00"


def _news(*, instrument_id="VWCE", headline="VWCE rises", published="2026-08-10T08:00:00+00:00", provider="provider-a", news_id="n1"):
    return {
        "news_id": news_id,
        "instrument_id": instrument_id,
        "headline": headline,
        "published_at": published,
        "ingested_at": published,
        "provider_name": provider,
    }


def _history(previous=6.0, current=5.0):
    return pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-08-10T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": previous},
        {"run_id": "new", "run_completed_at": "2026-08-11T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": current},
    ])


def _result(results, rule):
    return next(row for row in results if row["rule"] == rule)


def _text_values(node):
    values = []
    value = getattr(node, "value", None)
    if isinstance(value, str):
        values.append(value)
    text = getattr(node, "text", None)
    if isinstance(text, str):
        values.append(text)
    for child in getattr(node, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(node, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    return values


def test_positive_news_weak_fundamentals_flagged_clear_and_unavailable():
    news = pd.DataFrame([_news()])
    weak = pd.DataFrame([{"instrument_id": "VWCE", "as_of_date": "2026-08-10", "quality_score": 0.2}])
    strong = weak.assign(quality_score=0.8)
    assert _result(build_news_macro_contradictions(news, fundamentals=weak, cutoff=CUTOFF), "positive_news_weak_fundamentals")["status"] == "flagged"
    assert _result(build_news_macro_contradictions(news, fundamentals=strong, cutoff=CUTOFF), "positive_news_weak_fundamentals")["status"] == "clear"
    assert _result(build_news_macro_contradictions(news, cutoff=CUTOFF), "positive_news_weak_fundamentals")["status"] == "unavailable"


def test_macro_risk_against_exposure_flagged_clear_and_unavailable():
    macro = {"status": "available", "regime": {"label": "stressed", "score_10": 3.0}}
    exposures = {"VWCE": "equity"}
    assert _result(build_news_macro_contradictions(pd.DataFrame(), macro_context=macro, exposures=exposures, cutoff=CUTOFF), "macro_risk_against_exposure")["status"] == "flagged"
    assert _result(build_news_macro_contradictions(pd.DataFrame(), macro_context={"status": "available", "regime": {"label": "risk-on", "score_10": 8.0}}, exposures=exposures, cutoff=CUTOFF), "macro_risk_against_exposure")["status"] == "clear"
    assert _result(build_news_macro_contradictions(pd.DataFrame(), exposures=exposures, cutoff=CUTOFF), "macro_risk_against_exposure")["status"] == "unavailable"


def test_missing_macro_classification_is_unavailable():
    macro = {"status": "available", "regime": {"label": "risk-on", "score_10": 8.0}}
    result = _result(build_news_macro_contradictions(pd.DataFrame(), macro_context=macro, exposures={"VWCE": ""}, cutoff=CUTOFF), "macro_risk_against_exposure")
    assert result["status"] == "unavailable"
    assert "classification" in result["reason"]


def test_missing_ingestion_timestamp_is_not_eligible():
    news = pd.DataFrame([_news()]).drop(columns=["ingested_at"])
    result = _result(build_news_macro_contradictions(news, cutoff=CUTOFF), "source_disagreement")
    assert result["status"] == "unavailable"
    assert "news items" in result["reason"]


def test_source_disagreement_flagged_clear_and_unavailable():
    opposite = pd.DataFrame([_news(provider="a", news_id="a1"), _news(headline="VWCE falls", provider="b", news_id="b1", published="2026-08-11T08:00:00+00:00")])
    clear = pd.DataFrame([_news(provider="a"), _news(provider="b", news_id="b1", published="2026-08-11T08:00:00+00:00")])
    assert _result(build_news_macro_contradictions(opposite, cutoff=CUTOFF), "source_disagreement")["status"] == "flagged"
    assert _result(build_news_macro_contradictions(clear, cutoff=CUTOFF), "source_disagreement")["status"] == "clear"
    assert _result(build_news_macro_contradictions(pd.DataFrame(), cutoff=CUTOFF), "source_disagreement")["status"] == "unavailable"


def test_source_disagreement_without_comparable_provider_evidence_is_unavailable():
    result = _result(build_news_macro_contradictions(pd.DataFrame([_news(provider="a")]), cutoff=CUTOFF), "source_disagreement")
    assert result["status"] == "unavailable"
    assert "comparable" in result["reason"]


def test_bullish_sentiment_deteriorating_score_flagged_clear_and_unavailable():
    news = pd.DataFrame([_news()])
    assert _result(build_news_macro_contradictions(news, score_history=_history(), cutoff=CUTOFF), "bullish_sentiment_deteriorating_score")["status"] == "flagged"
    assert _result(build_news_macro_contradictions(news, score_history=_history(5.0, 6.0), cutoff=CUTOFF), "bullish_sentiment_deteriorating_score")["status"] == "clear"
    assert _result(build_news_macro_contradictions(news, score_history=pd.DataFrame(), cutoff=CUTOFF), "bullish_sentiment_deteriorating_score")["status"] == "unavailable"


def test_strong_score_missing_stale_news_flagged_clear_and_unavailable():
    history = _history(6.0, 8.0)
    stale = pd.DataFrame([_news(published="2026-07-01T08:00:00+00:00")])
    fresh = pd.DataFrame([_news()])
    assert _result(build_news_macro_contradictions(stale, score_history=history, cutoff=CUTOFF), "strong_score_missing_stale_news")["status"] == "flagged"
    assert _result(build_news_macro_contradictions(fresh, score_history=history, cutoff=CUTOFF), "strong_score_missing_stale_news")["status"] == "clear"
    assert _result(build_news_macro_contradictions(fresh, cutoff=CUTOFF), "strong_score_missing_stale_news")["status"] == "unavailable"


def test_point_in_time_future_news_is_ignored():
    results = build_news_macro_contradictions(pd.DataFrame([_news(headline="VWCE falls", published="2026-08-13T08:00:00+00:00")]), cutoff=CUTOFF)
    assert _result(results, "source_disagreement")["status"] == "unavailable"


def test_news_changes_do_not_change_score_or_action_inputs():
    score = {"instrument_id": "VWCE", "final_combined_score_10": 7.25, "action": "hold"}
    history = pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-08-10T10:00:00+00:00", **score},
        {"run_id": "new", "run_completed_at": "2026-08-11T10:00:00+00:00", **score},
    ])
    before = history.copy(deep=True)
    build_news_macro_contradictions(pd.DataFrame([_news(headline="VWCE rises")]), score_history=history, cutoff=CUTOFF)
    build_news_macro_contradictions(pd.DataFrame([_news(headline="VWCE falls")]), score_history=history, cutoff=CUTOFF)
    pd.testing.assert_frame_equal(history, before)
    assert score["final_combined_score_10"] == 7.25
    assert score["action"] == "hold"


def test_existing_positive_trend_rule_is_flagged_clear_and_unavailable():
    prices = pd.DataFrame([
        {"instrument_id": "VWCE", "date": "2026-08-09", "adjusted_close": 100.0},
        {"instrument_id": "VWCE", "date": "2026-08-11", "adjusted_close": 95.0},
    ])
    news = pd.DataFrame([_news()])
    assert _result(build_news_macro_contradictions(news, prices=prices, cutoff=CUTOFF), "positive_trend_negative_news")["status"] == "flagged"
    prices.loc[1, "adjusted_close"] = 105.0
    assert _result(build_news_macro_contradictions(news, prices=prices, cutoff=CUTOFF), "positive_trend_negative_news")["status"] == "clear"
    assert _result(build_news_macro_contradictions(news, cutoff=CUTOFF), "positive_trend_negative_news")["status"] == "unavailable"


def test_conflicting_price_identities_are_unavailable():
    prices = pd.DataFrame([
        {"instrument_id": "VWCE", "etf_id": "OTHER", "date": "2026-08-09", "adjusted_close": 100.0},
        {"instrument_id": "VWCE", "etf_id": "OTHER", "date": "2026-08-11", "adjusted_close": 95.0},
    ])
    result = _result(build_news_macro_contradictions(pd.DataFrame([_news()]), prices=prices, cutoff=CUTOFF), "positive_trend_negative_news")
    assert result["status"] == "unavailable"
    assert "Conflicting" in result["reason"]


def test_no_strong_score_rows_are_unavailable():
    result = _result(build_news_macro_contradictions(pd.DataFrame([_news()]), score_history=_history(6.0, 6.5), cutoff=CUTOFF), "strong_score_missing_stale_news")
    assert result["status"] == "unavailable"


def test_audit_contradiction_export_preserves_unreadable_state(monkeypatch):
    monkeypatch.setattr(export_pack, "load_news_items", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("broken ledger")))
    payload = export_pack._contradiction_export_payload(as_of_date=date(2026, 8, 12))
    assert payload["status"] == "unavailable"
    assert payload["as_of"] == "2026-08-12T23:59:59+00:00"
    assert "ValueError" in payload["reason"]


def test_dashboard_macro_context_uses_cutoff_filtered_prices(monkeypatch):
    import etf_cockpit.app.pages.dashboard as dashboard

    news = pd.DataFrame([_news()])
    prices = pd.DataFrame([
        {"instrument_id": "VWCE", "date": "2026-08-11", "adjusted_close": 100.0},
        {"instrument_id": "VWCE", "date": "2026-08-20", "adjusted_close": 50.0},
    ])
    seen: list[pd.DataFrame] = []
    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: news)
    monkeypatch.setattr(dashboard, "filter_news_contradiction_inputs", lambda *_args: (news, prices))
    monkeypatch.setattr(dashboard, "build_macro_context", lambda frame, _rows: seen.append(frame.copy()) or {"status": "available", "regime": {"label": "risk-on"}})
    monkeypatch.setattr(dashboard, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    monkeypatch.setattr(dashboard, "score_history_frame", lambda: pd.DataFrame())
    state = SimpleNamespace(snapshot=SimpleNamespace(prices=prices, config=SimpleNamespace(universe=SimpleNamespace(etfs=()))))
    dashboard._contradiction_record(state, as_of="2026-08-12", cutoff=pd.Timestamp(CUTOFF))
    assert len(seen) == 1
    assert set(seen[0]["date"]) == {"2026-08-11"}


def test_instrument_panel_does_not_recompute_missing_supplied_records(monkeypatch):
    import etf_cockpit.app.pages.instrument_detail as instrument_detail

    monkeypatch.setattr(instrument_detail, "contradiction_digest_records", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("UI fallback recomputed contradictions")))
    model = SimpleNamespace(sections={"news": {"status": "available", "items": []}}, instrument_id="VWCE")
    panel = render_news_contradiction_panel(model)
    assert "News/macro contradictions" in " ".join(_text_values(panel))


def test_digest_and_ui_panels_render_all_results_without_execution_authority(monkeypatch):
    news = pd.DataFrame([_news()])
    records = contradiction_digest_records(news, cutoff=CUTOFF)
    assert len(records) >= 7
    assert all(record.get("status") in {"available", "manual_review", "unavailable"} for record in records)
    assert all(record.get("contradiction", {}).get("execution_allowed", False) is False for record in records[1:])

    import etf_cockpit.app.pages.dashboard as dashboard
    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: news)
    assert "News/macro contradictions" in " ".join(_text_values(_news_digest(None, SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame())))))

    import etf_cockpit.app.pages.trust_evidence as trust
    monkeypatch.setattr(trust, "load_news_items", lambda _path: news)
    extra = _news_context_extra(SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame(), data_report=SimpleNamespace(as_of_date="2026-08-12"))))
    assert "News contradictions" in " ".join(_text_values(extra))

    model = SimpleNamespace(sections={"news": {"status": "available", "items": list(news.to_dict(orient="records"))}}, instrument_id="VWCE")
    assert "News/macro contradictions" in " ".join(_text_values(render_news_contradiction_panel(model)))
