from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.application.screening import ScreenFilter, ScreenQuery, ScreenSort, run_screen


ROWS = pd.DataFrame(
    [
        {"instrument_id": "A", "region": " Europe ", "score": 7.0, "quality": 8.0},
        {"instrument_id": "B", "region": "US", "score": 7.0, "quality": None},
        {"instrument_id": "C", "region": "europe", "score": "bad", "quality": 9.0},
        {"instrument_id": "D", "region": "Europe", "score": 5.0, "quality": 9.0},
    ]
)


def test_screen_filters_casefolded_categories_and_inclusive_numeric_bounds() -> None:
    query = ScreenQuery(filters=(ScreenFilter("region", "eq", " EUROPE "), ScreenFilter("score", "min", 5), ScreenFilter("score", "max", 7)))
    result = run_screen(ROWS, query)
    assert [row["instrument_id"] for row in result.rows] == ["A", "D"]
    assert result.total_input == 4
    assert result.total_matched == 2
    assert result.execution_allowed is False


def test_screen_rejects_missing_and_non_numeric_values_for_numeric_filters() -> None:
    result = run_screen(ROWS, ScreenQuery(filters=(ScreenFilter("score", "min", 0),)))
    assert [row["instrument_id"] for row in result.rows] == ["A", "B", "D"]


def test_screen_reports_unavailable_fields_and_fails_closed() -> None:
    result = run_screen(ROWS, ScreenQuery(filters=(ScreenFilter("news_conflict", "eq", "none"),), requested_fields=("backtest_trust",)))
    assert result.rows == ()
    assert result.unavailable_fields == ("backtest_trust", "news_conflict")
    assert result.warnings == ("unavailable_field:backtest_trust", "unavailable_field:news_conflict")


def test_screen_multi_sort_is_stable_and_always_places_missing_last() -> None:
    result = run_screen(ROWS, ScreenQuery(sort=(ScreenSort("score", descending=True), ScreenSort("quality", descending=True))))
    assert [row["instrument_id"] for row in result.rows] == ["A", "B", "D", "C"]
    ascending = run_screen(ROWS, ScreenQuery(sort=(ScreenSort("quality"),)))
    assert [row["instrument_id"] for row in ascending.rows] == ["A", "C", "D", "B"]


def test_screen_checksum_is_semantic_and_round_trips() -> None:
    first = ScreenQuery(filters=(ScreenFilter("region", "eq", " Europe "),), dataset_checksums=(("scores", "abc"), ("fundamentals", "def")))
    second = ScreenQuery(filters=(ScreenFilter("region", "eq", "EUROPE"),), dataset_checksums=(("fundamentals", "def"), ("scores", "abc")))
    restored = ScreenQuery.from_dict(first.as_dict())
    assert first.checksum == second.checksum == restored.checksum


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ScreenFilter("", "eq", "x"), "field"),
        (lambda: ScreenFilter("score", "unknown", "x"), "operator"),
        (lambda: ScreenFilter("score", "min", "bad"), "finite"),
        (lambda: ScreenSort(""), "field"),
    ],
)
def test_screen_query_contract_rejects_invalid_values(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_empty_screen_is_deterministic() -> None:
    query = ScreenQuery(requested_fields=("score",))
    first = run_screen(pd.DataFrame(), query)
    second = run_screen([], query)
    assert first == second
    assert first.unavailable_fields == ("score",)


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "999", "filters": [], "sort": [], "requested_fields": [], "dataset_checksums": {}},
        {"schema_version": "1.0", "filters": {}, "sort": [], "requested_fields": [], "dataset_checksums": {}},
        {"schema_version": "1.0", "filters": [], "sort": [{"field": "score", "descending": "false"}], "requested_fields": [], "dataset_checksums": {}},
        {"schema_version": "1.0", "filters": [], "sort": [], "requested_fields": [], "dataset_checksums": {}, "unknown": True},
    ],
)
def test_screen_query_from_dict_rejects_future_or_malformed_contracts(payload) -> None:
    with pytest.raises(ValueError):
        ScreenQuery.from_dict(payload)
