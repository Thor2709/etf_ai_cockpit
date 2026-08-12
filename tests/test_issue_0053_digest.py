from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application.digest import MAX_DIGEST_ITEMS, DashboardDigest, build_digest, filter_news_contradiction_inputs
from etf_cockpit.app.pages import dashboard


def _text_values(node: object) -> list[str]:
    values: list[str] = []
    value = getattr(node, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(node, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(node, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    return values


def test_digest_is_deterministic_bounded_and_context_only() -> None:
    records = {
        "model_failures": [
            {
                "title": "Model failure requires review",
                "detail": "Baseline forecast failed locally.",
                "status": "available",
                "severity": "critical",
                "provenance": "local_alerts",
            }
        ],
        "score_changes": [
            {
                "title": f"change-{index}",
                "detail": "Score changed.",
                "status": "available",
                "severity": "info",
                "provenance": "score_history",
            }
            for index in range(20)
        ],
    }

    first = build_digest(records, as_of="2026-08-12")
    second = build_digest(records, as_of="2026-08-12")

    assert first == second
    assert len(first.items) == MAX_DIGEST_ITEMS
    assert first.items[0].source == "model_failures"
    assert all(item.execution_allowed is False for item in first.items)
    assert first.execution_allowed is False


def test_digest_exposes_unavailable_sources_and_incomplete_records() -> None:
    digest = build_digest(
        {
            "alerts": [
                {
                    "title": "Alerts need review",
                    "detail": "The alert source omitted provenance.",
                    "status": "manual_review",
                }
            ]
        }
    )

    source_status = dict(digest.source_status)
    assert source_status["alerts"] == "manual_review"
    assert source_status["upcoming_events"] == "unavailable"
    assert digest.items[0].status == "manual_review"
    assert digest.items[0].provenance == "unavailable"


def test_dashboard_digest_is_visible_with_stable_acceptance_key(monkeypatch) -> None:
    expected = build_digest(
        {
            "score_changes": [
                {
                    "title": "Biggest score/rank changes",
                    "detail": "VWCE score +1.2.",
                    "status": "available",
                    "severity": "warning",
                    "provenance": "score_history",
                }
            ]
        },
        as_of="2026-08-12",
    )
    monkeypatch.setattr(dashboard, "_dashboard_digest", lambda _state, scores=None: expected)

    control = dashboard._what_matters_today(SimpleNamespace(), scores=[])
    rendered = "\n".join(_text_values(control))

    assert control.key == "dashboard.what-matters-today"
    assert "What matters today" in rendered
    assert "Biggest score/rank changes" in rendered
    assert "execution_allowed=false" in rendered
    assert "upcoming_events" in rendered


def test_dashboard_digest_failure_is_readable_and_fail_closed(monkeypatch) -> None:
    def fail(_state, scores=None) -> DashboardDigest:
        raise RuntimeError("local digest failure")

    monkeypatch.setattr(dashboard, "_dashboard_digest", fail)

    rendered = "\n".join(_text_values(dashboard._what_matters_today(SimpleNamespace(), scores=[])))

    assert "Digest unavailable" in rendered
    assert "manual review required" in rendered
    assert "execution_allowed=false" in rendered


def test_dashboard_generation_keeps_each_accepted_category_visible(monkeypatch) -> None:
    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            data_report=SimpleNamespace(status="Clean", as_of_date="2026-08-12"),
            prices=pd.DataFrame(),
        ),
        last_export_path=None,
        recent_activity=[],
    )
    monkeypatch.setattr(dashboard, "_latest_run_change_report", lambda: None)
    monkeypatch.setattr(dashboard, "_read_alerts", lambda: SimpleNamespace(status="available", records=()))
    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(dashboard, "load_calendar_events", lambda _path: pd.DataFrame())
    monkeypatch.setattr(dashboard, "MacroWarehouse", lambda: SimpleNamespace(summary=lambda **_kwargs: {"status": "unavailable"}))

    digest = dashboard._dashboard_digest(state, scores=[])

    assert {source for source, _status in digest.source_status} == {
        "score_changes",
        "warning_changes",
        "alerts",
        "model_failures",
        "contradictions",
        "manual_review",
        "upcoming_events",
        "stale_data",
        "audit_export",
    }
    assert all(item.execution_allowed is False for item in digest.items)


def _news_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_id": "VWCE",
        "published_at": "2026-08-10T08:00:00+00:00",
        "ingested_at": "2026-08-10T08:05:00+00:00",
        "available_at_decision_time": True,
        "headline": "VWCE rises",
    }
    row.update(changes)
    return row


def _price_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {"instrument_id": "VWCE", "date": "2026-08-09", "adjusted_close": 100.0}
    row.update(changes)
    return row


def test_dashboard_contradiction_keeps_macro_comparison_manual_review(monkeypatch) -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame([_price_row()])))
    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: pd.DataFrame([_news_row()]))
    monkeypatch.setattr(dashboard, "MacroWarehouse", lambda: SimpleNamespace(summary=lambda **_kwargs: {"status": "available"}))

    record = dashboard._contradiction_record(state, as_of="2026-08-12")

    assert record[0]["status"] == "manual_review"
    assert "macro contradiction comparison is unavailable" in str(record[0]["detail"])


def test_dashboard_contradiction_is_unavailable_without_prices(monkeypatch) -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame()))
    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: pd.DataFrame([_news_row()]))
    monkeypatch.setattr(dashboard, "MacroWarehouse", lambda: SimpleNamespace(summary=lambda **_kwargs: {"status": "available"}))

    record = dashboard._contradiction_record(state, as_of="2026-08-12")

    assert record[0]["status"] == "unavailable"
    assert "price" in str(record[0]["detail"])


def test_contradiction_inputs_exclude_future_news_and_prices() -> None:
    news = pd.DataFrame([_news_row(), _news_row(published_at="2026-08-13T08:00:00+00:00", ingested_at="2026-08-13T08:05:00+00:00")])
    prices = pd.DataFrame([_price_row(), _price_row(date="2026-08-13", adjusted_close=90.0)])

    filtered = filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00")

    assert filtered is not None
    filtered_news, filtered_prices = filtered
    assert filtered_news["published_at"].tolist() == ["2026-08-10T08:00:00+00:00"]
    assert filtered_prices["date"].tolist() == ["2026-08-09"]
