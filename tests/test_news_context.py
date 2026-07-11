from __future__ import annotations

from datetime import datetime, timezone

from etf_cockpit.data.news_context import NewsItem, validate_news_item


def test_news_after_decision_time_is_rejected_from_backtest() -> None:
    item = NewsItem("n1", "MSFT", "source", "vendor", "Headline", "2026-07-10T12:00:00+00:00", "2026-07-10T12:01:00+00:00", "https://example.invalid", "medium")
    validation = validate_news_item(item, datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc))
    assert validation.backtest_eligible is False
    assert validation.status == "after_decision_time"


def test_ambiguous_timestamp_is_unavailable() -> None:
    item = NewsItem("n2", "MSFT", "source", "vendor", "Headline", "2026-07-10", "", "https://example.invalid", "medium")
    validation = validate_news_item(item, datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc))
    assert validation.backtest_eligible is False
    assert validation.status == "ambiguous_timestamp"
