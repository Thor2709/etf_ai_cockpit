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


def test_news_requires_point_in_time_provenance_and_is_never_executable() -> None:
    item = NewsItem(
        "n3",
        "MSFT",
        "source",
        "vendor",
        "Headline",
        "2026-07-10T10:00:00+00:00",
        "2026-07-10T10:05:00+00:00",
        "https://example.invalid/news/3",
        "medium",
        instrument_mapping_method="isin_exact",
        available_at_decision_time=True,
    )
    validation = validate_news_item(item, datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc))
    assert validation.status == "valid_context"
    assert validation.backtest_eligible is True
    assert validation.context_only is True
    assert validation.executable_authority is False


def test_current_only_revised_news_is_rejected() -> None:
    item = NewsItem(
        "n4",
        "MSFT",
        "source",
        "vendor",
        "Revised headline",
        "2026-07-10T10:00:00+00:00",
        "2026-07-10T10:05:00+00:00",
        "https://example.invalid/news/4",
        "medium",
        instrument_mapping_method="ticker",
        available_at_decision_time=None,
        current_only=True,
        revised=True,
    )
    validation = validate_news_item(item, datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc))
    assert validation.status == "current_only_revised"
    assert validation.backtest_eligible is False


def test_news_raw_clean_persistence_is_idempotent(tmp_path) -> None:
    from etf_cockpit.data.news_context import persist_news_items

    item = NewsItem(
        "n5", "MSFT", "source", "vendor", "Headline", "2026-07-10T10:00:00+00:00",
        "2026-07-10T10:05:00+00:00", "https://example.invalid/news/5", "medium",
        instrument_mapping_method="ticker", available_at_decision_time=True,
    )
    first = persist_news_items([item], raw_dir=tmp_path / "raw", clean_path=tmp_path / "clean.parquet")
    second = persist_news_items([item], raw_dir=tmp_path / "raw", clean_path=tmp_path / "clean.parquet")
    assert first.clean_path == second.clean_path
    assert len(list((tmp_path / "raw").glob("*.json"))) == 1
    assert second.rows == 1
