from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
import uuid

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file


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

            if _first_column(frame, ("feed_url", "rss_url")) is not None and _first_column(frame, ("headline", "title")) is None:
                raise ValueError("RSS feed URL lists require parsed headline/date/url items before commit")
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
    rss_list = import_type == "news" and _first_column(frame, ("feed_url", "rss_url", "source_url")) is not None
    required_groups = () if rss_list else _REQUIRED.get(import_type, ())
    for group in required_groups:
        if not columns.intersection(group):
            errors.append("missing_column:" + "/".join(group))
    if errors:
        return errors, warnings
    date_columns = ("date", "as_of_date", "published_at", "published_date", "factsheet_date", "holdings_date", "report_date", "timestamp")
    for name in date_columns:
        if name in columns:
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
        if rss_list:
            feed_column = _first_column(frame, ("feed_url", "rss_url", "source_url"))
            if feed_column is None or _blank_values(frame[feed_column]).any() or not _valid_urls(frame[feed_column]):
                errors.append("invalid_feed_url")
            elif _first_column(frame, ("headline", "title")) is None:
                errors.append("rss_feed_list_requires_parsed_items")
        headline_column = _first_column(frame, ("headline", "title"))
        if not rss_list and (headline_column is None or _blank_values(frame[headline_column]).any()):
            errors.append("empty_headline")
        if not rss_list:
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
    payload = frame.sort_index(axis=1).to_json(orient="records", date_format="iso", date_unit="ns")
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
                ingested_at=_timestamp_text(row.get("ingested_at", published)),
                url=url,
                instrument_mapping_method=str(row.get("instrument_mapping_method", "manual")),
                available_at_decision_time=bool(row.get("available_at_decision_time", True)),
                credibility=str(row.get("credibility", "unverified")),
            )
        )
    return items


def _timestamp_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return ""
    return parsed.isoformat()


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
