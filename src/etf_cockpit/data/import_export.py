from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
import uuid

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group, parquet_payload, validate_parquet_file


@dataclass(frozen=True)
class ImportPreview:
    preview_id: str
    import_type: str
    path: Path
    valid: bool
    rows: int
    columns: tuple[str, ...]
    errors: tuple[str, ...]
    frame: pd.DataFrame
    warnings: tuple[str, ...] = ()
    checksum: str = ""


@dataclass(frozen=True)
class ImportCommitResult:
    import_type: str
    rows: int
    frame: pd.DataFrame
    destination: Path
    status: str = "committed"
    errors: tuple[str, ...] = ()
    execution_allowed: bool = False


_PREVIEWS: dict[str, ImportPreview] = {}

_ALIASES = {
    "broker": "broker",
    "broker_csv": "broker",
    "holdings": "broker",
    "candidate": "candidate",
    "candidates": "candidate",
    "candidate_csv": "candidate",
    "notes": "manual_notes",
    "manual_notes": "manual_notes",
    "manual_news": "manual_news",
    "news": "news",
    "news_csv": "news",
    "rss": "news",
    "rss_list": "news",
    "prices": "prices",
    "fx": "fx",
    "etf_metadata": "etf_metadata",
    "etf_factsheet": "etf_metadata",
    "etf_factsheets": "etf_metadata",
    "etf_holdings": "etf_holdings",
}

_REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    "prices": (("date",), ("etf_id", "instrument_id"), ("adjusted_close", "adj_close", "close")),
    "fx": (("date",), ("rate", "fx_rate", "value")),
    "broker": (("as_of_date",), ("etf_id",), ("units",), ("market_price",), ("market_value_eur",), ("current_weight",)),
    "candidate": (("instrument_id", "etf_id", "ticker"), ("yahoo_symbol", "ticker", "symbol", "yfinance_ticker")),
    "manual_notes": (("as_of_date", "date", "published_at", "published_date"), ("note", "text", "summary", "content", "thesis", "body")),
    "manual_news": (("as_of_date", "date", "published_at", "published_date"), ("note", "text", "summary", "content", "thesis", "body")),
    "etf_metadata": (("as_of_date", "date", "factsheet_date", "holdings_date", "report_date"), ("etf_id", "fund_id", "isin", "fund_isin", "ticker", "fund_ticker")),
    "etf_holdings": (("as_of_date", "date", "holdings_date", "report_date"), ("etf_id", "parent_etf_id", "isin", "fund_isin", "ticker"), ("holding_name", "security_name", "name", "constituent_name"), ("weight", "weight_decimal", "weight_percent", "weight_pct")),
    "news": (("published_at", "published_date", "date", "as_of_date", "timestamp"), ("headline", "title", "summary", "text", "note")),
}

_DESTINATION_NAMES = {
    "broker": Path("data/portfolios/current_holdings.csv"),
    "candidate": Path("data/raw/trade_candidates"),
    "manual_notes": Path("data/clean/manual_news.parquet"),
    "manual_news": Path("data/clean/manual_news.parquet"),
    "news": Path("data/clean/news.parquet"),
    "etf_metadata": Path("data/clean/etf_metadata.parquet"),
    "etf_holdings": Path("data/clean/etf_holdings.parquet"),
    "prices": Path("data/clean/prices.parquet"),
    "fx": Path("data/clean/fx.parquet"),
}


def validate_import(import_type: str, path: Path) -> ImportPreview:
    resolved_type = _normalise_type(import_type)
    source = Path(path)
    preview_id = f"preview_{uuid.uuid4().hex[:12]}"
    try:
        frame = _read(source)
    except Exception as exc:
        preview = ImportPreview(preview_id, resolved_type, source, False, 0, (), (f"read_failed:{type(exc).__name__}:{exc}",), pd.DataFrame())
        _PREVIEWS[preview_id] = preview
        return preview
    # Import semantics depend on row order, not a caller-controlled index.
    # Reset it before binding the preview checksum so an index can never become
    # a filesystem path component during commit.
    frame = frame.reset_index(drop=True)
    errors, warnings = _validate_frame(resolved_type, frame)
    checksum = _frame_checksum(frame)
    preview = ImportPreview(preview_id, resolved_type, source, not errors, len(frame), tuple(map(str, frame.columns)), tuple(errors), frame.copy(), tuple(warnings), checksum)
    _PREVIEWS[preview_id] = preview
    return preview


def commit_import(preview_id: str, *, root: Path | None = None) -> ImportCommitResult:
    preview = _PREVIEWS.get(str(preview_id))
    if preview is None or not preview.valid:
        raise ValueError("A valid import preview is required before commit")
    return ImportService(root or Path.cwd()).commit(preview.preview_id)


class ImportService:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._previews: dict[str, ImportPreview] = {}

    def register(self, preview: ImportPreview) -> None:
        self._previews[preview.preview_id] = preview
        _PREVIEWS[preview.preview_id] = preview

    def commit(self, preview_id: str) -> ImportCommitResult:
        preview = self._previews.get(preview_id) or _PREVIEWS.get(preview_id)
        if preview is None or not preview.valid:
            raise ValueError("A valid import preview is required before commit")
        if _frame_checksum(preview.frame) != preview.checksum:
            raise ValueError("Import preview is stale or mutated; checksum verification failed")
        # Re-run the safety contract on the checksum-bound frame.  Callers can
        # construct ImportPreview values directly, so commit must not trust a
        # stale/under-validated preview and accidentally misattribute holdings
        # or point-in-time news.
        validation_errors, _ = _validate_frame(preview.import_type, preview.frame)
        if validation_errors:
            raise ValueError("Import preview failed validation: " + "; ".join(validation_errors))
        destination = self._destination(preview)
        frame = preview.frame.copy(deep=True)
        if preview.import_type == "broker":
            from etf_cockpit.data.ingest_broker import import_holdings_frame

            import_holdings_frame(frame, destination=destination)
            committed = pd.read_csv(destination)
        elif preview.import_type == "candidate":
            committed = _normalise_candidate_frame(frame)
            _write_csv(destination, committed)
        elif preview.import_type in {"manual_notes", "manual_news"}:
            from etf_cockpit.data.manual_notes import commit_manual_news_import
            from etf_cockpit.data.providers import ProviderResult

            commit = commit_manual_news_import(
                ProviderResult("manual_local_file", "manual_news", "ok", f"Loaded {len(frame)} rows from import.", frame),
                clean_path=destination,
                raw_dir=self.root / "data" / "raw" / "manual_news",
                snapshots_dir=self.root / "data" / "snapshots" / "manual_news",
            )
            destination = commit.clean_path
            committed = pd.read_parquet(destination)
        elif preview.import_type == "news":
            from etf_cockpit.data.news_context import persist_news_items

            if _is_feed_list(frame):
                _persist_feed_list(
                    frame,
                    raw_dir=self.root / "data" / "raw" / "news_context",
                    clean_path=destination,
                    audit_path=destination.with_name("news_context_audit.json"),
                )
            else:
                persist_news_items(
                    _news_items(frame),
                    raw_dir=self.root / "data" / "raw" / "news_context",
                    clean_path=destination,
                    audit_path=destination.with_name("news_context_audit.json"),
                )
            committed = pd.read_parquet(destination)
        elif preview.import_type == "etf_holdings":
            from etf_cockpit.data.fund_holdings import _merge_holdings_frame, _read_existing_holdings, _write_holdings_frame, normalise_holdings

            date_column = _first_column(frame, ("as_of", "as_of_date", "date", "holdings_date", "report_date"))
            instrument_column = _first_column(frame, ("instrument_id", "etf_id", "parent_etf_id", "isin", "fund_isin", "ticker"))
            if date_column is None or instrument_column is None:
                raise ValueError("ETF holdings import requires as_of date and instrument identity")
            instrument_id = str(frame[instrument_column].dropna().iloc[0]).strip()
            source_column = _first_column(frame, ("source", "provider", "source_name"))
            source_name = str(frame[source_column].dropna().iloc[0]).strip() if source_column and not frame[source_column].dropna().empty else "issuer"
            result = normalise_holdings(frame, instrument_id, frame[date_column].dropna().iloc[0], source_name)
            if result.frame.empty:
                raise ValueError("ETF holdings import is invalid; no data changed")
            destination = self.root / "data" / "clean" / "fund_holdings.parquet"
            destination.parent.mkdir(parents=True, exist_ok=True)
            holdings_frame = result.frame.copy()
            if "schema_version" not in holdings_frame.columns:
                holdings_frame.insert(0, "schema_version", 1)
            merged = _merge_holdings_frame(_read_existing_holdings(destination), holdings_frame, instrument_id)
            _write_holdings_frame(merged, destination=destination)
            committed = pd.read_parquet(destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(destination, parquet_payload(frame), validate_parquet_file)
            committed = frame
        return ImportCommitResult(preview.import_type, len(committed), committed.copy(), destination)

    def _destination(self, preview: ImportPreview) -> Path:
        if preview.import_type == "candidate":
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            return self.root / "data" / "raw" / "trade_candidates" / f"yahoo_trade_candidates_{timestamp}.csv"
        return self.root / _DESTINATION_NAMES[preview.import_type]


def _normalise_type(import_type: str) -> str:
    key = str(import_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported import type: {import_type}") from exc


def _validate_frame(import_type: str, frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if frame.empty:
        return ["empty_file"], warnings
    columns = {str(column).strip().lower() for column in frame.columns}
    # A source_url belongs to an already parsed news item.  Only feed_url/rss_url
    # represent an RSS list; treating source_url as a feed would let URL-only
    # rows bypass the headline/publication contract.
    rss_list = import_type == "news" and _first_column(frame, ("feed_url", "rss_url")) is not None
    required_groups = () if rss_list else _REQUIRED.get(import_type, ())
    for group in required_groups:
        if not columns.intersection(group):
            errors.append("missing_column:" + "/".join(group))
    if errors:
        return errors, warnings
    date_columns = ("date", "as_of_date", "published_at", "published_date", "factsheet_date", "holdings_date", "report_date", "timestamp")
    for name in date_columns:
        if name in columns:
            # News publication fields must be checked without ``utc=True``;
            # that option silently localises naive values and fabricates
            # provenance.  The news-specific branch below enforces offsets.
            if import_type == "news" and name in {"published_at", "published_date", "date", "as_of_date", "timestamp"}:
                continue
            actual = next(column for column in frame.columns if str(column).strip().lower() == name)
            if pd.to_datetime(frame[actual], errors="coerce", utc=True).isna().any():
                errors.append(f"invalid_date:{actual}")
                break
    for name in ("adjusted_close", "adj_close", "close", "market_price", "price", "weight", "weight_decimal", "weight_percent", "weight_pct", "units", "market_value_eur", "market_value", "value", "rate", "fx_rate"):
        if name in columns:
            actual = next(column for column in frame.columns if str(column).strip().lower() == name)
            if pd.to_numeric(frame[actual], errors="coerce").isna().any():
                errors.append(f"invalid_number:{actual}")
                break
    if import_type == "prices":
        price_column = _first_column(frame, ("adjusted_close", "adj_close", "close"))
        if price_column is not None and (pd.to_numeric(frame[price_column], errors="coerce") <= 0).any():
            errors.append(f"invalid_price:{price_column}")
    if import_type == "broker":
        for name in ("units", "market_value_eur", "market_value", "value", "current_weight", "weight"):
            column = _first_column(frame, (name,))
            if column is not None and (pd.to_numeric(frame[column], errors="coerce") < 0).any():
                errors.append(f"negative_value:{column}")
        weight = _first_column(frame, ("current_weight", "weight"))
        if weight is not None and (pd.to_numeric(frame[weight], errors="coerce") > 1).any():
            errors.append(f"invalid_weight:{weight}")
    if import_type == "etf_holdings":
        instrument_column = _first_column(frame, ("instrument_id", "etf_id", "parent_etf_id", "isin", "fund_isin", "ticker"))
        if instrument_column is not None:
            instrument_values = frame[instrument_column].astype("string").str.strip()
            distinct_instruments = instrument_values[instrument_values.notna() & instrument_values.ne("")].unique()
            if len(distinct_instruments) == 0:
                errors.append(f"empty_instrument_id:{instrument_column}")
            elif len(distinct_instruments) > 1:
                errors.append(f"multiple_instruments_not_allowed:{instrument_column}")
        weight = _first_column(frame, ("weight", "weight_decimal", "weight_percent", "weight_pct"))
        if weight is not None:
            values = pd.to_numeric(frame[weight], errors="coerce")
            if "percent" in weight or "pct" in weight:
                invalid = (values < 0) | (values > 100)
            else:
                invalid = (values < 0) | (values > 1)
            if invalid.any():
                errors.append(f"invalid_weight:{weight}")
    if import_type == "news":
        availability_column = _first_column(frame, ("available_at_decision_time", "available_at_decision", "available"))
        for boolean_names in (
            ("available_at_decision_time", "available_at_decision", "available"),
            ("current_only",),
            ("revised",),
            ("context_only",),
            ("executable_authority",),
        ):
            boolean_column = _first_column(frame, boolean_names)
            if boolean_column is not None and any(_parse_boolean(value) is None for value in frame[boolean_column]):
                errors.append(f"invalid_boolean:{boolean_column}")
        if rss_list:
            feed_column = _first_column(frame, ("feed_url", "rss_url", "source_url"))
            if feed_column is None or _blank_values(frame[feed_column]).any() or not _valid_urls(frame[feed_column]):
                errors.append("invalid_feed_url")
        headline_column = _first_column(frame, ("headline", "title"))
        publication_column = _first_column(frame, ("published_at", "published_date", "date", "as_of_date", "timestamp"))
        if publication_column is not None and any(not _timezone_aware(value) for value in frame[publication_column]):
            errors.append(f"naive_publication_timezone:{publication_column}")
        ingested_column = _first_column(frame, ("ingested_at", "ingested_date"))
        if ingested_column is not None and any(not _timezone_aware(value) for value in frame[ingested_column]):
            errors.append(f"naive_ingested_timezone:{ingested_column}")
        # An explicit positive availability claim is an intent to use the
        # item at decision time.  It must be backed by an explicit,
        # timezone-aware ingestion timestamp; otherwise fail closed rather
        # than manufacturing provenance from the publication timestamp.
        if availability_column is not None:
            explicit_available = frame[availability_column].map(_parse_boolean)
            if explicit_available.eq(True).any() and ingested_column is None:
                errors.append("missing_ingested_timestamp_for_eligibility")
        # Parsed news rows are only useful for point-in-time context when their
        # headline/source URL is paired with a non-blank publication timestamp.
        if headline_column is not None and _first_column(frame, ("source_url", "url", "link")) is not None:
            if publication_column is None:
                errors.append("missing_publication_timestamp")
            elif _blank_values(frame[publication_column]).any():
                errors.append(f"blank_publication_timestamp:{publication_column}")
        if headline_column is not None and publication_column is not None and _blank_values(frame[publication_column]).any():
            errors.append(f"blank_publication_timestamp:{publication_column}")
        if headline_column is not None and (not rss_list or _first_column(frame, ("url", "source_url", "link")) is not None) and _blank_values(frame[headline_column]).any():
            errors.append("empty_headline")
        if not rss_list or headline_column is not None:
            url_column = _first_column(frame, ("url", "source_url", "link"))
            if url_column is None or _blank_values(frame[url_column]).any() or not _valid_urls(frame[url_column]):
                errors.append("invalid_news_url")
        if rss_list and frame.empty:
            errors.append("empty_feed")
    if import_type in {"manual_news", "manual_notes"}:
        text_column = _first_column(frame, ("note", "text", "summary", "content", "thesis", "body"))
        if text_column is None or _blank_values(frame[text_column]).any():
            errors.append("empty_note")
    return errors, warnings


def _read(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    if suffix in {".rss", ".xml"}:
        return _read_rss(path)
    raise ValueError("Unsupported import file type")


def _read_rss(path: Path) -> pd.DataFrame:
    try:
        import feedparser  # type: ignore[import-not-found]

        feed = feedparser.parse(path.read_bytes())
        return pd.DataFrame(
            [{"published_at": item.get("published", item.get("updated", "")), "headline": item.get("title", ""), "url": item.get("link", ""), "summary": item.get("summary", "")} for item in feed.entries]
        )
    except ImportError:
        import xml.etree.ElementTree as element_tree

        root = element_tree.fromstring(path.read_bytes())
        rows = []
        for item in root.findall(".//item"):
            rows.append({"published_at": item.findtext("pubDate", ""), "headline": item.findtext("title", ""), "url": item.findtext("link", ""), "summary": item.findtext("description", "")})
        return pd.DataFrame(rows)


def _frame_checksum(frame: pd.DataFrame) -> str:
    # Index labels are transport metadata rather than import content.  Ignore
    # them explicitly while preserving the validated row ordering in records.
    payload = frame.reset_index(drop=True).sort_index(axis=1).to_json(orient="records", date_format="iso", date_unit="ns")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _first_column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    lookup = {str(column).strip().lower(): str(column) for column in frame.columns}
    return next((lookup[name] for name in names if name in lookup), None)


def _normalise_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "yahoo_symbol" not in result.columns:
        source = _first_column(result, ("ticker", "symbol", "yfinance_ticker"))
        if source is not None:
            result["yahoo_symbol"] = result[source]
    if "instrument_id" not in result.columns:
        source = _first_column(result, ("etf_id", "ticker"))
        if source is not None:
            result["instrument_id"] = result[source]
    return result


def _news_items(frame: pd.DataFrame):
    from etf_cockpit.data.news_context import NewsItem

    items = []
    for index, row in frame.iterrows():
        published = _timestamp_text(row.get("published_at", row.get("published_date", row.get("date", ""))))
        url = str(row.get("url", row.get("source_url", row.get("link", ""))) or "").strip()
        instrument = str(row.get("instrument_id", row.get("etf_id", "portfolio")) or "portfolio").strip() or "portfolio"
        items.append(
            NewsItem(
                news_id=str(row.get("news_id", f"import-{index}")),
                instrument_id=instrument,
                source=str(row.get("source", "manual")),
                provider=str(row.get("provider", row.get("provider_name", "manual_local_file"))),
                headline=str(row.get("headline", row.get("title", "")) or "").strip(),
                published_at=published,
                # Do not infer ingestion from publication.  A missing
                # ingestion timestamp is retained as unavailable, allowing
                # the canonical news validator to keep the item
                # context-only and backtest-ineligible.
                ingested_at=_timestamp_text(row.get("ingested_at", row.get("ingested_date", ""))),
                url=url,
                instrument_mapping_method=str(row.get("instrument_mapping_method", "manual")),
                available_at_decision_time=(
                    _parse_boolean(
                        row.get(
                            "available_at_decision_time",
                            row.get("available_at_decision", row.get("available", False)),
                        )
                    )
                    is True
                ),
                credibility=str(row.get("credibility", "unverified")),
                current_only=bool(_parse_boolean(row.get("current_only", False))),
                revised=bool(_parse_boolean(row.get("revised", False))),
                # Preserve explicit timestamp metadata from parsed providers.
                # Missing values retain the NewsItem compatibility defaults,
                # while explicit ambiguous/unknown values remain visible to
                # validate_news_item and therefore fail closed.
                timezone_name=_metadata_text(row.get("timezone_name"), "UTC"),
                timezone=_metadata_optional_text(row.get("timezone")),
                timestamp_confidence=_metadata_text(row.get("timestamp_confidence"), "exact"),
            )
        )
    return items


def _timestamp_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.isoformat()


def _metadata_text(value: object, default: str) -> str:
    if value is None or pd.isna(value):
        return default
    text = str(value).strip()
    return text if text else default


def _metadata_optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    normalised = str(value).strip().casefold()
    if normalised in {"true", "t", "yes", "y", "on", "1"}:
        return True
    if normalised in {"false", "f", "no", "n", "off", "0"}:
        return False
    return None


def _timezone_aware(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _is_feed_list(frame: pd.DataFrame) -> bool:
    return _first_column(frame, ("feed_url", "rss_url")) is not None and _first_column(frame, ("headline", "title")) is None


def _persist_feed_list(frame: pd.DataFrame, *, raw_dir: Path, clean_path: Path, audit_path: Path) -> None:
    """Persist local RSS feed URLs as context-only evidence, without fetching."""

    from etf_cockpit.data.news_context import NEWS_SCHEMA_VERSION, _read_clean_strict

    feed_column = _first_column(frame, ("feed_url", "rss_url"))
    if feed_column is None:
        raise ValueError("RSS feed list requires a feed_url column")
    existing = _read_clean_strict(clean_path)
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    raw_requests: list[AtomicWriteRequest] = []
    raw_paths: list[str] = []
    for ordinal, (_, row) in enumerate(frame.iterrows()):
        feed_url = str(row[feed_column]).strip()
        provider = str(row.get("provider", row.get("provider_name", "rss_local_list")) or "rss_local_list").strip() or "rss_local_list"
        payload = {
            "schema_version": NEWS_SCHEMA_VERSION,
            "dataset_type": "rss_feed_list",
            "feed_url": feed_url,
            "provider_name": provider,
            "context_only": True,
            "executable_authority": False,
        }
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        raw_path = raw_dir / f"feed-{ordinal}-{checksum}.json"
        raw_paths.append(str(raw_path))
        if not raw_path.exists():
            raw_requests.append(AtomicWriteRequest(raw_path, (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))))
        rows.append(
            {
                "schema_version": NEWS_SCHEMA_VERSION,
                "news_id": f"feed-{ordinal}-{checksum[:12]}",
                "instrument_id": "portfolio",
                "headline": "",
                "feed_url": feed_url,
                "source_url": feed_url,
                "source": "rss",
                "provider": provider,
                "provider_name": provider,
                "published_at": "",
                "ingested_at": "",
                "instrument_mapping_method": "unavailable",
                "available_at_decision_time": False,
                "timestamp_confidence": "unknown",
                "timestamp_status": "feed_list",
                "backtest_eligible": False,
                "credibility": "unverified",
                "source_authority": "community",
                "context_only": True,
                "executable_authority": False,
                "raw_path": str(raw_path),
                "item_checksum": checksum,
            }
        )
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if not combined.empty:
        subset = [column for column in ("news_id", "item_checksum") if column in combined.columns]
        if subset:
            combined = combined.drop_duplicates(subset=subset, keep="last")
    audit = {
        "schema_version": NEWS_SCHEMA_VERSION,
        "dataset_type": "rss_feed_list",
        "raw_paths": raw_paths,
        "clean_path": str(clean_path),
        "rows": len(combined),
        "context_only": True,
        "executable_authority": False,
    }
    csv_path = clean_path.with_suffix(".csv")
    atomic_write_group(
        (
            AtomicWriteRequest(clean_path, parquet_payload(combined), validate_parquet_file),
            AtomicWriteRequest(csv_path, combined.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
            AtomicWriteRequest(audit_path, (json.dumps(audit, sort_keys=True, indent=2) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))),
            *raw_requests,
        )
    )


def _blank_values(values: pd.Series) -> pd.Series:
    return values.isna() | values.astype("string").str.strip().eq("")


def _valid_urls(values: pd.Series) -> bool:
    return all(
        (parsed := urlparse(str(value).strip())).scheme in {"http", "https"} and bool(parsed.netloc)
        for value in values
        if not pd.isna(value) and str(value).strip()
    )


def _write_csv(destination: Path, frame: pd.DataFrame) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(destination, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path))
