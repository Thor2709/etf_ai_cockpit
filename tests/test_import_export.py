from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import inspect

import pandas as pd
import pytest

from etf_cockpit.data import export_tables, import_export
from etf_cockpit.data.export_tables import export_table
from etf_cockpit.data.import_export import ImportService, validate_import


def test_import_requires_preview_before_commit_and_exports_table(tmp_path: Path) -> None:
    source = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2026-07-10"], "etf_id": ["A"], "adjusted_close": [100.0]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    assert preview.valid is True
    service = ImportService(tmp_path)
    service.register(preview)
    result = service.commit(preview.preview_id)
    assert result.rows == 1
    destination = tmp_path / "export.csv"
    export_table("prices", result.frame, destination)
    assert destination.exists()


def test_invalid_import_does_not_commit(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    pd.DataFrame({"bad": [1]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    assert preview.valid is False
    with pytest.raises(ValueError):
        ImportService(tmp_path).commit(preview.preview_id)


def test_import_commit_preserves_previous_parquet_on_locked_replace(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2026-07-10"], "etf_id": ["A"], "adjusted_close": [100.0]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    service = ImportService(tmp_path)
    service.register(preview)
    destination = tmp_path / "data" / "clean" / "prices.parquet"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    real_replace = Path.replace

    def fail_replace(self: Path, target: Path):
        if Path(target) == destination:
            raise PermissionError("destination locked")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError, match="destination locked"):
        service.commit(preview.preview_id)
    assert destination.read_bytes() == b"old"


@pytest.mark.parametrize(
    ("import_type", "columns"),
    [
        ("broker", {"as_of_date": ["2026-07-10"], "etf_id": ["A"], "units": [1], "market_price": [10], "market_value_eur": [10], "current_weight": [1]}),
        ("candidate", {"instrument_id": ["A"], "ticker": ["AAA"], "name": ["Example"]}),
        ("manual_notes", {"as_of_date": ["2026-07-10"], "note": ["review"]}),
        ("etf_holdings", {"as_of_date": ["2026-07-10"], "etf_id": ["A"], "holding_name": ["Issuer"], "weight": [0.5]}),
        ("news", {"published_at": ["2026-07-10T12:00:00Z"], "headline": ["Headline"], "url": ["https://example.test"]}),
    ],
)
def test_approved_import_shapes_validate_and_commit_only_after_preview(tmp_path: Path, import_type: str, columns: dict[str, list[object]]) -> None:
    source = tmp_path / f"{import_type}.csv"
    pd.DataFrame(columns).to_csv(source, index=False)
    preview = validate_import(import_type, source)
    assert preview.valid is True, preview.errors
    assert preview.preview_id
    assert callable(getattr(import_export, "commit_import", None))
    with pytest.raises(ValueError):
        import_export.commit_import("preview-not-registered")
    service = ImportService(tmp_path)
    service.register(preview)
    result = service.commit(preview.preview_id)
    assert result.status == "committed"
    assert result.destination.exists()
    assert result.execution_allowed is False


def test_etf_holdings_import_retains_existing_instruments(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "clean" / "fund_holdings.parquet"
    destination.parent.mkdir(parents=True)
    pd.DataFrame({"instrument_id": ["OTHER"], "security": ["Issuer B"], "weight": [1.0]}).to_parquet(destination, index=False)
    source = tmp_path / "holdings.csv"
    pd.DataFrame({"as_of_date": ["2026-07-10"], "etf_id": ["VWCE"], "holding_name": ["Issuer A"], "ticker": ["A"], "weight": [1.0]}).to_csv(source, index=False)
    preview = validate_import("etf_holdings", source)
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert set(saved["instrument_id"].astype(str)) == {"OTHER", "VWCE"}


def test_etf_holdings_preview_rejects_mixed_parent_instruments(tmp_path: Path) -> None:
    source = tmp_path / "mixed-holdings.csv"
    pd.DataFrame(
        {
            "as_of_date": ["2026-07-10", "2026-07-10"],
            "etf_id": ["VWCE", "EUNL"],
            "holding_name": ["Issuer A", "Issuer B"],
            "weight": [0.5, 0.5],
        }
    ).to_csv(source, index=False)
    preview = validate_import("etf_holdings", source)
    assert preview.valid is False
    assert any("instrument" in error or "single" in error for error in preview.errors)


def test_news_preview_rejects_headline_source_url_without_publication_date(tmp_path: Path) -> None:
    source = tmp_path / "undated-news.csv"
    pd.DataFrame({"headline": ["Headline"], "source_url": ["https://example.test/news"]}).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is False
    assert any("published" in error or "date" in error for error in preview.errors)


def test_export_result_reports_path_and_controlled_failure(tmp_path: Path) -> None:
    destination = tmp_path / "scoreboard.csv"
    result = export_table("scoreboard", pd.DataFrame({"score": [1]}), destination)
    assert isinstance(result, export_tables.ExportResult)
    assert result.ok is True
    assert result.destination == destination
    failed = export_table("scoreboard", None, destination)
    assert failed.ok is False
    assert "unavailable" in failed.error


def test_broker_import_uses_canonical_current_holdings_csv(tmp_path: Path) -> None:
    source = tmp_path / "broker.csv"
    pd.DataFrame(
        {
            "as_of_date": ["2026-07-10"],
            "etf_id": ["VWCE"],
            "units": [2.0],
            "market_price": [100.0],
            "market_value_eur": [200.0],
            "current_weight": [1.0],
        }
    ).to_csv(source, index=False)
    preview = validate_import("broker", source)
    result = ImportService(tmp_path).commit(preview.preview_id)
    assert result.destination == tmp_path / "data" / "portfolios" / "current_holdings.csv"
    assert result.destination.exists()
    assert not (tmp_path / "data" / "portfolios" / "current_holdings.parquet").exists()


def test_broker_commit_uses_checksum_bound_preview_frame_not_mutated_source(tmp_path: Path) -> None:
    source = tmp_path / "broker.csv"
    original = {"as_of_date": ["2026-07-10"], "etf_id": ["VWCE"], "units": [2.0], "market_price": [100.0], "market_value_eur": [200.0], "current_weight": [1.0]}
    pd.DataFrame(original).to_csv(source, index=False)
    preview = validate_import("broker", source)
    pd.DataFrame({**original, "units": [99.0]}).to_csv(source, index=False)
    result = ImportService(tmp_path).commit(preview.preview_id)
    assert float(pd.read_csv(result.destination).loc[0, "units"]) == 2.0


def test_candidate_import_preserves_runtime_yahoo_csv_contract(tmp_path: Path) -> None:
    source = tmp_path / "candidates.csv"
    pd.DataFrame({"instrument_id": ["AAA"], "yahoo_symbol": ["AAA.DE"], "name": ["Example"]}).to_csv(source, index=False)
    preview = validate_import("candidate", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)
    assert result.destination.parent == tmp_path / "data" / "raw" / "trade_candidates"
    assert result.destination.name.startswith("yahoo_trade_candidates_")
    saved = pd.read_csv(result.destination)
    assert {"instrument_id", "yahoo_symbol"}.issubset(saved.columns)


def test_manual_notes_import_keeps_normaliser_provenance_and_authority(tmp_path: Path) -> None:
    source = tmp_path / "notes.csv"
    pd.DataFrame({"as_of_date": ["2026-07-10"], "note": ["dated thesis"], "etf_id": ["VWCE"], "source_url": ["https://example.test/note"]}).to_csv(source, index=False)
    preview = validate_import("manual_notes", source)
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert result.destination == tmp_path / "data" / "clean" / "manual_news.parquet"
    assert bool(saved.loc[0, "executable_authority"]) is False
    assert {"source_credibility", "evidence_grade", "authority_note"}.issubset(saved.columns)


def test_mutated_preview_is_rejected_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2026-07-10"], "etf_id": ["A"], "adjusted_close": [100.0]}).to_csv(source, index=False)
    preview = validate_import("prices", source)
    preview.frame.loc[0, "adjusted_close"] = 999.0
    with pytest.raises(ValueError, match="stale|checksum|mutated"):
        ImportService(tmp_path).commit(preview.preview_id)
    assert not (tmp_path / "data" / "clean" / "prices.parquet").exists()


@pytest.mark.parametrize(
    "columns",
    [
        {"as_of_date": ["2026-07-10"], "note": [None]},
        {"as_of_date": ["2026-07-10"], "note": ["   "]},
        {"published_at": ["2026-07-10T12:00:00Z"], "headline": [None], "url": ["https://example.test"]},
        {"published_at": ["2026-07-10T12:00:00Z"], "headline": ["   "], "url": ["https://example.test"]},
    ],
)
def test_manual_text_and_news_headline_nan_or_blank_are_rejected(tmp_path: Path, columns: dict[str, list[object]]) -> None:
    source = tmp_path / "invalid.csv"
    pd.DataFrame(columns).to_csv(source, index=False)
    import_type = "manual_notes" if "note" in columns else "news"
    preview = validate_import(import_type, source)
    assert preview.valid is False


@pytest.mark.parametrize("feed_url", ["", "not-a-url"])
def test_rss_list_import_requires_valid_feed_url(tmp_path: Path, feed_url: str) -> None:
    source = tmp_path / "feeds.csv"
    pd.DataFrame({"feed_url": [feed_url]}).to_csv(source, index=False)
    preview = validate_import("rss_list", source)
    assert preview.valid is False


def test_rss_feed_url_list_commits_safe_feed_evidence_without_network(tmp_path: Path) -> None:
    source = tmp_path / "feeds.csv"
    pd.DataFrame({"feed_url": ["https://example.test/feed.xml"], "provider": ["rss"]}).to_csv(source, index=False)
    preview = validate_import("rss_list", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert result.rows == 1
    assert result.execution_allowed is False
    assert saved.loc[0, "source_url"] == "https://example.test/feed.xml"
    assert saved.loc[0, "feed_url"] == "https://example.test/feed.xml"
    assert bool(saved.loc[0, "context_only"]) is True
    assert bool(saved.loc[0, "executable_authority"]) is False


def test_rss_feed_list_index_cannot_escape_raw_directory(tmp_path: Path) -> None:
    source = tmp_path / "feeds-index.parquet"
    frame = pd.DataFrame(
        {"feed_url": ["https://example.test/one.xml", "https://example.test/two.xml"]},
        index=["../outside", "nested\\..\\escape"],
    )
    frame.to_parquet(source)

    preview = validate_import("rss_list", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)

    raw_dir = tmp_path / "data" / "raw" / "news_context"
    raw_paths = [Path(path) for path in pd.read_parquet(result.destination)["raw_path"]]
    assert all(path.parent == raw_dir for path in raw_paths)
    assert {path.name.split("-")[0] for path in raw_paths} == {"feed"}
    assert any(path.name.startswith("feed-0-") for path in raw_paths)
    assert any(path.name.startswith("feed-1-") for path in raw_paths)
    assert not (tmp_path / "data" / "raw" / "outside").exists()
    assert not (tmp_path / "data" / "raw" / "news_context" / "nested").exists()


def test_news_commit_fails_closed_when_existing_ledger_is_corrupt(tmp_path: Path) -> None:
    clean_path = tmp_path / "data" / "clean" / "news.parquet"
    clean_path.parent.mkdir(parents=True)
    corrupt_bytes = b"not a parquet ledger"
    clean_path.write_bytes(corrupt_bytes)
    source = tmp_path / "news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
        }
    ).to_csv(source, index=False)

    preview = validate_import("news", source)
    assert preview.valid is True, preview.errors
    with pytest.raises((ValueError, RuntimeError), match="ledger|parquet|read|corrupt"):
        ImportService(tmp_path).commit(preview.preview_id)

    assert clean_path.read_bytes() == corrupt_bytes
    assert not clean_path.with_suffix(".csv").exists()


def test_rss_feed_commit_fails_closed_when_existing_ledger_is_corrupt(tmp_path: Path) -> None:
    clean_path = tmp_path / "data" / "clean" / "news.parquet"
    clean_path.parent.mkdir(parents=True)
    corrupt_bytes = b"not a parquet ledger"
    clean_path.write_bytes(corrupt_bytes)
    source = tmp_path / "feeds.csv"
    pd.DataFrame({"feed_url": ["https://example.test/feed.xml"]}).to_csv(source, index=False)

    preview = validate_import("rss_list", source)
    assert preview.valid is True, preview.errors
    with pytest.raises((ValueError, RuntimeError), match="ledger|parquet|read|corrupt"):
        ImportService(tmp_path).commit(preview.preview_id)

    assert clean_path.read_bytes() == corrupt_bytes
    assert not (tmp_path / "data" / "raw" / "news_context").exists()


def test_news_import_rejects_ambiguous_availability_boolean(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous-news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
            "available_at_decision_time": ["sometimes"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is False
    assert any("boolean" in error for error in preview.errors)


def test_news_import_rejects_ambiguous_revised_boolean(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous-revised-news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
            "revised": ["unclear"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is False
    assert any("boolean" in error for error in preview.errors)


def test_news_import_rejects_naive_publication_timestamp(tmp_path: Path) -> None:
    source = tmp_path / "naive-news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is False
    assert any("timezone" in error or "published" in error for error in preview.errors)


def test_news_import_persists_canonical_context_provenance(tmp_path: Path) -> None:
    source = tmp_path / "news.csv"
    pd.DataFrame(
        {
            "news_id": ["n1"],
            "instrument_id": ["VWCE"],
            "source": ["rss"],
            "provider": ["feed"],
            "headline": ["Markets rise"],
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "ingested_at": ["2026-07-10T12:01:00+00:00"],
            "url": ["https://example.test/n1"],
            "instrument_mapping_method": ["manual"],
            "available_at_decision_time": [True],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert {"news_id", "context_only", "executable_authority", "item_checksum"}.issubset(saved.columns)
    assert bool(saved.loc[0, "context_only"]) is True
    assert bool(saved.loc[0, "executable_authority"]) is False


def test_news_import_parses_string_false_without_fabricating_availability(tmp_path: Path) -> None:
    source = tmp_path / "false-news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
            "available_at_decision_time": ["false"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert bool(saved.loc[0, "available_at_decision_time"]) is False
    assert bool(saved.loc[0, "backtest_eligible"]) is False


def test_news_import_without_ingestion_or_availability_is_context_only(tmp_path: Path) -> None:
    source = tmp_path / "context-only-news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert saved.loc[0, "ingested_at"] in {"", None}
    assert bool(saved.loc[0, "available_at_decision_time"]) is False
    assert bool(saved.loc[0, "backtest_eligible"]) is False


def test_news_import_explicit_true_without_ingestion_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "ineligible-news.csv"
    pd.DataFrame(
        {
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "headline": ["Headline"],
            "url": ["https://example.test/news"],
            "available_at_decision_time": ["true"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is False
    assert any("ingest" in error for error in preview.errors)


@pytest.mark.parametrize(
    ("metadata", "expected_timezone", "expected_confidence"),
    [
        ({"timestamp_confidence": "ambiguous"}, "UTC", "ambiguous"),
        ({"timestamp_confidence": "exact", "timezone_name": "unknown"}, "unknown", "exact"),
    ],
)
def test_parsed_news_preserves_explicit_timestamp_metadata_and_fails_closed(
    tmp_path: Path,
    metadata: dict[str, str],
    expected_timezone: str,
    expected_confidence: str,
) -> None:
    from etf_cockpit.data.import_export import _news_items
    from etf_cockpit.data.news_context import validate_news_item

    row = {
        "news_id": "metadata-news",
        "instrument_id": "VWCE",
        "source": "rss",
        "provider": "feed",
        "headline": "Headline",
        "published_at": "2026-07-10T12:00:00+00:00",
        "ingested_at": "2026-07-10T12:01:00+00:00",
        "url": "https://example.test/news",
        "instrument_mapping_method": "manual",
        "available_at_decision_time": True,
        **metadata,
    }
    item = _news_items(pd.DataFrame([row]))[0]
    assert item.timezone_name == expected_timezone
    assert item.timestamp_confidence == expected_confidence
    validation = validate_news_item(item, datetime(2026, 7, 10, 13, tzinfo=timezone.utc))
    assert validation.backtest_eligible is False
    assert validation.status == "ambiguous_timestamp"


def test_parsed_news_explicit_availability_with_ambiguous_metadata_is_ineligible(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous-news.csv"
    pd.DataFrame(
        {
            "news_id": ["ambiguous-available"],
            "instrument_id": ["VWCE"],
            "source": ["rss"],
            "provider": ["feed"],
            "headline": ["Headline"],
            "published_at": ["2026-07-10T12:00:00+00:00"],
            "ingested_at": ["2026-07-10T12:01:00+00:00"],
            "url": ["https://example.test/news"],
            "instrument_mapping_method": ["manual"],
            "available_at_decision_time": [True],
            "timestamp_confidence": ["ambiguous"],
        }
    ).to_csv(source, index=False)
    preview = validate_import("news", source)
    assert preview.valid is True, preview.errors
    result = ImportService(tmp_path).commit(preview.preview_id)
    saved = pd.read_parquet(result.destination)
    assert bool(saved.loc[0, "available_at_decision_time"]) is False
    assert bool(saved.loc[0, "backtest_eligible"]) is False
    assert saved.loc[0, "timestamp_confidence"] != "exact"


@pytest.mark.parametrize("import_type", ["news", "rss_list"])
def test_news_commits_reject_readable_malformed_canonical_ledger_before_writes(tmp_path: Path, import_type: str) -> None:
    clean_path = tmp_path / "data" / "clean" / "news.parquet"
    clean_path.parent.mkdir(parents=True)
    malformed = pd.DataFrame({"news_id": ["old"], "item_checksum": ["checksum"]})
    malformed.to_parquet(clean_path, index=False)
    before = clean_path.read_bytes()
    if import_type == "rss_list":
        source = tmp_path / "feeds.csv"
        pd.DataFrame({"feed_url": ["https://example.test/feed.xml"]}).to_csv(source, index=False)
    else:
        source = tmp_path / "news.csv"
        pd.DataFrame(
            {
                "published_at": ["2026-07-10T12:00:00+00:00"],
                "headline": ["Headline"],
                "url": ["https://example.test/news"],
            }
        ).to_csv(source, index=False)
    preview = validate_import(import_type, source)
    assert preview.valid is True, preview.errors
    with pytest.raises(ValueError, match="schema|ledger"):
        ImportService(tmp_path).commit(preview.preview_id)
    assert clean_path.read_bytes() == before
    assert not (tmp_path / "data" / "raw" / "news_context").exists()


def test_export_sources_use_live_data_journal_and_canonical_watchlist_store() -> None:
    from etf_cockpit.app.pages.import_export import import_export_page

    source = inspect.getsource(import_export_page)
    assert "root=DATA_DIR" in source
    assert "scoreboard.parquet" in source
    assert "pyproject.toml" in source
    assert ".ai_worklog" in source


def test_settings_references_actual_version_and_changelog_files() -> None:
    from etf_cockpit.app.pages.settings import settings_page

    source = inspect.getsource(settings_page)
    assert "pyproject.toml" in source
    assert ".ai_worklog" in source
    assert "CHANGELOG.md" not in source
