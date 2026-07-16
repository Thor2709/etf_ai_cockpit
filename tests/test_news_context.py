from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pandas as pd

from etf_cockpit.data.news_context import NewsItem, build_news_contradiction_rows, validate_news_item


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


def test_news_atomic_failure_preserves_existing_generation_without_orphan_raw(tmp_path, monkeypatch) -> None:
    import etf_cockpit.data.news_context as module

    item = NewsItem(
        "n6", "MSFT", "source", "vendor", "Headline", "2026-07-10T10:00:00+00:00",
        "2026-07-10T10:05:00+00:00", "https://example.invalid/news/6", "medium",
        instrument_mapping_method="ticker", available_at_decision_time=True,
    )
    clean_path = tmp_path / "clean.parquet"
    module.persist_news_items([item], raw_dir=tmp_path / "raw", clean_path=clean_path)
    before = clean_path.read_bytes()
    audit_path = clean_path.with_name("clean_audit.json")
    audit_before = audit_path.read_bytes()
    raw_before = {path.name: path.read_bytes() for path in (tmp_path / "raw").glob("*.json")}
    real_atomic_write_group = module.atomic_write_group

    def fail_before_commit(requests):
        def inject_failure(state, _journal):
            if state == "committing":
                raise RuntimeError("injected failure")

        return real_atomic_write_group(requests, lifecycle_hook=inject_failure)

    monkeypatch.setattr(module, "atomic_write_group", fail_before_commit)
    changed_item = NewsItem(
        "n7", "MSFT", "source", "vendor", "Changed headline", "2026-07-10T10:00:00+00:00",
        "2026-07-10T10:06:00+00:00", "https://example.invalid/news/7", "medium",
        instrument_mapping_method="ticker", available_at_decision_time=True,
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        module.persist_news_items([changed_item], raw_dir=tmp_path / "raw", clean_path=clean_path)

    assert clean_path.read_bytes() == before
    assert audit_path.read_bytes() == audit_before
    assert {path.name: path.read_bytes() for path in (tmp_path / "raw").glob("*.json")} == raw_before


def test_news_persistence_orders_generations_by_published_then_ingested_time(tmp_path) -> None:
    from etf_cockpit.data.news_context import load_news_items, persist_news_items

    clean_path = tmp_path / "clean.parquet"
    newer = NewsItem(
        "newer", "MSFT", "source", "vendor", "Newer", "2026-07-12T10:00:00+00:00",
        "2026-07-12T10:05:00+00:00", "https://example.invalid/newer", "medium",
        instrument_mapping_method="ticker", available_at_decision_time=True,
    )
    older = NewsItem(
        "older", "MSFT", "source", "vendor", "Older", "2026-07-11T10:00:00+00:00",
        "2026-07-11T10:05:00+00:00", "https://example.invalid/older", "medium",
        instrument_mapping_method="ticker", available_at_decision_time=True,
    )
    persist_news_items([newer], raw_dir=tmp_path / "raw", clean_path=clean_path)
    persist_news_items([older], raw_dir=tmp_path / "raw", clean_path=clean_path)

    assert list(load_news_items(clean_path)["news_id"]) == ["older", "newer"]


def test_news_contradictions_compare_explicit_headline_direction_with_next_close() -> None:
    news = pd.DataFrame([
        {"news_id": "n7", "instrument_id": "MSFT", "headline": "MSFT shares rise after results", "published_at": "2026-07-10T10:00:00+00:00"},
    ])
    prices = pd.DataFrame([
        {"instrument_id": "MSFT", "date": "2026-07-10", "adjusted_close": 100.0},
        {"instrument_id": "MSFT", "date": "2026-07-11", "adjusted_close": 95.0},
    ])
    contradictions = build_news_contradiction_rows(news, prices)
    assert len(contradictions) == 1
    assert contradictions.iloc[0]["headline_direction"] == "up"
    assert contradictions.iloc[0]["price_direction"] == "down"


def test_mixed_direction_headline_is_unavailable_for_contradiction_checks() -> None:
    news = pd.DataFrame([{
        "news_id": "mixed",
        "instrument_id": "MSFT",
        "headline": "MSFT shares rise despite a loss outlook",
        "published_at": "2026-07-10T10:00:00+00:00",
    }])
    prices = pd.DataFrame([
        {"instrument_id": "MSFT", "date": "2026-07-10", "adjusted_close": 100.0},
        {"instrument_id": "MSFT", "date": "2026-07-11", "adjusted_close": 95.0},
    ])

    contradictions = build_news_contradiction_rows(news, prices)

    assert contradictions.empty


def test_news_contradictions_match_direction_words_at_token_boundaries() -> None:
    news = pd.DataFrame([
        {"news_id": "group", "instrument_id": "MSFT", "headline": "Group reports results", "published_at": "2026-07-10T10:00:00+00:00"},
        {"news_id": "rise", "instrument_id": "MSFT", "headline": "MSFT shares rise after results", "published_at": "2026-07-10T10:00:00+00:00"},
    ])
    prices = pd.DataFrame([
        {"instrument_id": "MSFT", "date": "2026-07-10", "adjusted_close": 100.0},
        {"instrument_id": "MSFT", "date": "2026-07-11", "adjusted_close": 95.0},
    ])

    contradictions = build_news_contradiction_rows(news, prices)

    assert "group" not in set(contradictions["news_id"])
    assert "rise" in set(contradictions["news_id"])
