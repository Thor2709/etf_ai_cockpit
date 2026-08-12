from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.digest import MAX_DIGEST_ITEMS, DashboardDigest, build_digest, filter_news_contradiction_inputs
from etf_cockpit.app.pages import dashboard
from etf_cockpit.data.alerts import AlertType
from etf_cockpit.data.news_context import NEWS_SCHEMA_VERSION


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
    monkeypatch.setattr(dashboard, "_latest_run_change_report", lambda _cutoff: None)
    monkeypatch.setattr(dashboard, "_read_alerts", lambda **_kwargs: SimpleNamespace(status="available", records=()))
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


def test_dashboard_uses_one_cutoff_and_complete_alert_population(monkeypatch) -> None:
    captured: dict[str, object] = {}
    alerts = SimpleNamespace(
        status="available",
        records=(
            SimpleNamespace(alert=SimpleNamespace(alert_type=AlertType.MODEL_FORECAST_FAILURE, severity=SimpleNamespace(value="warning"), subject_id="OLD-MODEL")),
            SimpleNamespace(alert=SimpleNamespace(alert_type=AlertType.STALE_DATA, severity=SimpleNamespace(value="warning"), subject_id="OLD-STALE")),
        ),
    )

    def capture_report(cutoff):
        captured["score_cutoff"] = cutoff
        return None

    def capture_alerts(**kwargs):
        captured.update(kwargs)
        return alerts

    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            data_report=SimpleNamespace(status="Clean", as_of_date="2026-08-12"),
            prices=pd.DataFrame(),
        ),
        last_export_path=None,
        recent_activity=[],
    )
    monkeypatch.setattr(dashboard, "_latest_run_change_report", capture_report)
    monkeypatch.setattr(dashboard, "_read_alerts", capture_alerts)
    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(dashboard, "load_calendar_events", lambda _path: pd.DataFrame())
    monkeypatch.setattr(dashboard, "MacroWarehouse", lambda: SimpleNamespace(summary=lambda **_kwargs: {"status": "unavailable"}))

    digest = dashboard._dashboard_digest(state, scores=[])

    assert captured["limit"] is None
    assert pd.Timestamp(captured["as_of"]) == captured["score_cutoff"]
    by_source = {item.source: item for item in digest.items}
    assert "OLD-MODEL" in by_source["model_failures"].detail
    assert "OLD-STALE" in by_source["stale_data"].detail


def _news_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": NEWS_SCHEMA_VERSION,
        "news_id": "news-vwce-1",
        "instrument_id": "VWCE",
        "published_at": "2026-08-10T08:00:00+00:00",
        "ingested_at": "2026-08-10T08:05:00+00:00",
        "available_at_decision_time": True,
        "headline": "VWCE rises",
        "timestamp_status": "valid_context",
        "backtest_eligible": True,
        "timestamp_confidence": "exact",
        "source_url": "https://example.invalid/news/vwce",
        "provider_name": "Local provider",
        "source_authority": "manual-import",
        "instrument_mapping_method": "canonical_id",
        "context_only": True,
        "executable_authority": False,
    }
    row.update(changes)
    return row


def _price_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {"instrument_id": "VWCE", "date": "2026-08-09", "adjusted_close": 100.0}
    row.update(changes)
    return row


def test_dashboard_contradiction_keeps_macro_comparison_manual_review(monkeypatch) -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(prices=pd.DataFrame([_price_row(), _price_row(date="2026-08-11", adjusted_close=101.0)])))
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
    news = pd.DataFrame([
        _news_row(),
        _news_row(news_id="future-news", published_at="2026-08-13T08:00:00+00:00", ingested_at="2026-08-13T08:05:00+00:00"),
    ])
    prices = pd.DataFrame([
        _price_row(),
        _price_row(date="2026-08-11", adjusted_close=101.0),
        _price_row(date="2026-08-13", adjusted_close=90.0),
    ])

    filtered = filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00")

    assert filtered is not None
    filtered_news, filtered_prices = filtered
    assert filtered_news["published_at"].tolist() == ["2026-08-10T08:00:00+00:00"]
    assert filtered_prices["date"].tolist() == ["2026-08-09", "2026-08-11"]


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp_status": "ambiguous_timestamp"},
        {"backtest_eligible": False},
        {"timestamp_confidence": "unknown"},
        {"provider_name": ""},
        {"source_url": ""},
        {"context_only": False},
        {"executable_authority": True},
        {"provider": "Contradictory provider"},
        {"ingested_at": "2026-08-10T07:59:00+00:00"},
    ],
)
def test_contradiction_inputs_reject_noncanonical_news_truth(changes) -> None:
    news = pd.DataFrame([_news_row(**changes)])
    prices = pd.DataFrame([_price_row(), _price_row(date="2026-08-11", adjusted_close=101.0)])

    assert filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00") is None


def test_contradiction_inputs_support_etf_id_and_reject_conflicting_identity() -> None:
    news = pd.DataFrame([_news_row()])
    prices = pd.DataFrame([
        {"etf_id": "VWCE", "date": "2026-08-09", "adjusted_close": 100.0},
        {"etf_id": "VWCE", "date": "2026-08-11", "adjusted_close": 101.0},
    ])

    filtered = filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00")

    assert filtered is not None
    assert filtered[1]["instrument_id"].tolist() == ["VWCE", "VWCE"]
    missing_alias = prices.assign(instrument_id=[None, None])
    assert filter_news_contradiction_inputs(news, missing_alias, "2026-08-12T23:59:59+00:00") is not None
    conflicting = prices.assign(instrument_id=["OTHER", "OTHER"])
    assert filter_news_contradiction_inputs(news, conflicting, "2026-08-12T23:59:59+00:00") is None


@pytest.mark.parametrize("bad_price", [0.0, -1.0, float("inf"), float("nan")])
def test_contradiction_inputs_require_finite_positive_scoped_price_evidence(bad_price) -> None:
    news = pd.DataFrame([_news_row()])
    prices = pd.DataFrame([
        _price_row(adjusted_close=bad_price),
        _price_row(date="2026-08-11", adjusted_close=101.0),
        _price_row(instrument_id="SPY", date="2026-08-09", adjusted_close=500.0),
        _price_row(instrument_id="SPY", date="2026-08-11", adjusted_close=501.0),
    ])

    assert filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00") is None


def test_contradiction_inputs_reject_conflicting_duplicate_prices_independent_of_row_order() -> None:
    news = pd.DataFrame([_news_row()])
    prices = pd.DataFrame([
        _price_row(),
        _price_row(adjusted_close=99.0),
        _price_row(date="2026-08-11", adjusted_close=101.0),
    ])

    assert filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00") is None
    assert filter_news_contradiction_inputs(news, prices.iloc[::-1], "2026-08-12T23:59:59+00:00") is None


def test_contradiction_inputs_deterministically_collapse_exact_duplicate_prices() -> None:
    news = pd.DataFrame([_news_row()])
    prices = pd.DataFrame([
        _price_row(),
        _price_row(),
        _price_row(date="2026-08-11", adjusted_close=101.0),
    ])

    first = filter_news_contradiction_inputs(news, prices, "2026-08-12T23:59:59+00:00")
    reversed_rows = filter_news_contradiction_inputs(news, prices.iloc[::-1], "2026-08-12T23:59:59+00:00")

    assert first is not None
    assert reversed_rows is not None
    pd.testing.assert_frame_equal(first[1], reversed_rows[1])
    assert first[1]["date"].tolist() == ["2026-08-09", "2026-08-11"]


def test_score_history_uses_attributable_runs_at_or_before_cutoff(monkeypatch) -> None:
    history = pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-08-09T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": 4.0, "rank": 3},
        {"run_id": "current", "run_completed_at": "2026-08-10T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": 5.0, "rank": 2},
        {"run_id": "future", "run_completed_at": "2026-08-13T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": 9.0, "rank": 1},
        {"run_id": "unattributed", "run_completed_at": "2026-08-11 10:00:00", "instrument_id": "VWCE", "final_combined_score_10": 7.0, "rank": 1},
    ])
    monkeypatch.setattr(dashboard, "score_history_frame", lambda: history)

    report = dashboard._latest_run_change_report(pd.Timestamp("2026-08-12T23:59:59+00:00"))

    assert report is not None
    assert report.current_run_id == "current"
    assert report.previous_run_id == "old"


def test_score_history_with_fewer_than_two_cutoff_eligible_runs_is_unavailable(monkeypatch) -> None:
    history = pd.DataFrame([
        {"run_id": "old", "run_completed_at": "2026-08-09T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": 4.0},
        {"run_id": "future", "run_completed_at": "2026-08-13T10:00:00+00:00", "instrument_id": "VWCE", "final_combined_score_10": 9.0},
    ])
    monkeypatch.setattr(dashboard, "score_history_frame", lambda: history)

    assert dashboard._latest_run_change_report(pd.Timestamp("2026-08-12T23:59:59+00:00")) is None


def test_score_rank_summary_shows_both_and_distinguishes_unavailable_from_zero() -> None:
    history = pd.DataFrame([
        {"run_id": "old", "instrument_id": "VWCE", "final_combined_score_10": 4.0, "rank": 4},
        {"run_id": "new", "instrument_id": "VWCE", "final_combined_score_10": 6.0, "rank": 2},
    ])
    report = dashboard.compare_runs(history, "new", "old")
    detail = str(dashboard._score_change_record(report, as_of="2026-08-12")[0]["detail"])
    assert "scores: VWCE +2.0" in detail
    assert "ranks: VWCE -2" in detail

    unavailable = dashboard.compare_runs(
        pd.DataFrame([
            {"run_id": "old", "instrument_id": "VWCE"},
            {"run_id": "new", "instrument_id": "VWCE"},
        ]),
        "new",
        "old",
    )
    unavailable_record = dashboard._score_change_record(unavailable, as_of="2026-08-12")[0]
    assert unavailable_record["status"] == "unavailable"
    assert "scores: unavailable" in str(unavailable_record["detail"])
    assert "ranks: unavailable" in str(unavailable_record["detail"])

    zero = dashboard.compare_runs(
        pd.DataFrame([
            {"run_id": "old", "instrument_id": "VWCE", "final_combined_score_10": 4.0, "rank": 2},
            {"run_id": "new", "instrument_id": "VWCE", "final_combined_score_10": 4.0, "rank": 2},
        ]),
        "new",
        "old",
    )
    zero_record = dashboard._score_change_record(zero, as_of="2026-08-12")[0]
    assert zero_record["status"] == "available"
    assert "scores: no change" in str(zero_record["detail"])
    assert "ranks: no change" in str(zero_record["detail"])


@pytest.mark.parametrize("missing_run", ["old", "new"])
def test_warning_summary_is_unavailable_when_either_run_lacks_warning_evidence(missing_run) -> None:
    history = pd.DataFrame([
        {
            "run_id": "old",
            "instrument_id": "VWCE",
            "warnings": None if missing_run == "old" else "stale_data_warning",
        },
        {
            "run_id": "new",
            "instrument_id": "VWCE",
            "warnings": None if missing_run == "new" else "stale_data_warning",
        },
    ])
    report = dashboard.compare_runs(history, "new", "old")

    record = dashboard._warning_change_record(report, as_of="2026-08-12")[0]

    assert record["status"] == "unavailable"
    assert "manual review" in str(record["detail"])
    assert record["title"] != "No new or removed score warnings"


def test_warning_summary_preserves_proven_zero_change() -> None:
    history = pd.DataFrame([
        {"run_id": "old", "instrument_id": "VWCE", "warnings": "stale_data_warning"},
        {"run_id": "new", "instrument_id": "VWCE", "warnings": "stale_data_warning"},
    ])
    report = dashboard.compare_runs(history, "new", "old")

    record = dashboard._warning_change_record(report, as_of="2026-08-12")[0]

    assert record["status"] == "available"
    assert record["title"] == "No new or removed score warnings"


def test_manual_review_includes_final_action() -> None:
    scores = [SimpleNamespace(display_id="VWCE", decision="Hold", final_action="manual_review")]

    record = dashboard._manual_review_record(None, scores, as_of="2026-08-12")

    assert record is not None
    assert "VWCE" in str(record[0]["detail"])


@pytest.mark.parametrize("status", ["cancelled", "interrupted"])
def test_cancelled_or_interrupted_export_requires_manual_review(status) -> None:
    state = SimpleNamespace(
        last_export_path=None,
        recent_activity=[SimpleNamespace(label="Export audit packet", status=status, message=f"Export {status}")],
    )

    record = dashboard._audit_export_record(state, as_of="2026-08-12")

    assert record[0]["status"] == "manual_review"
    assert "failed" in str(record[0]["title"]).casefold()
