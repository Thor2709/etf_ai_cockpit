from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
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
    "broker": (("as_of_date", "date"), ("etf_id", "instrument_id", "ticker"), ("units",), ("market_price", "price"), ("market_value_eur", "market_value", "value"), ("current_weight", "weight")),
    "candidate": (("instrument_id", "etf_id", "ticker"), ("ticker", "symbol", "yfinance_ticker")),
    "manual_notes": (("as_of_date", "date", "published_at", "published_date"), ("note", "text", "summary", "content", "thesis", "body")),
    "manual_news": (("as_of_date", "date", "published_at", "published_date"), ("note", "text", "summary", "content", "thesis", "body")),
    "etf_metadata": (("as_of_date", "date", "factsheet_date", "holdings_date", "report_date"), ("etf_id", "fund_id", "isin", "fund_isin", "ticker", "fund_ticker")),
    "etf_holdings": (("as_of_date", "date", "holdings_date", "report_date"), ("etf_id", "parent_etf_id", "isin", "fund_isin", "ticker"), ("holding_name", "security_name", "name", "constituent_name"), ("weight", "weight_decimal", "weight_percent", "weight_pct")),
    "news": (("published_at", "published_date", "date", "as_of_date", "timestamp"), ("headline", "title", "summary", "text", "note")),
}

_DESTINATION_NAMES = {
    "broker": Path("data/portfolios/current_holdings.parquet"),
    "candidate": Path("data/raw/trade_candidates/candidates.parquet"),
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
        destination = self.root / _DESTINATION_NAMES[preview.import_type]
        payload = parquet_payload(preview.frame)
        atomic_write_bytes(destination, payload, validate_parquet_file)
        return ImportCommitResult(preview.import_type, len(preview.frame), preview.frame.copy(), destination)


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
    if import_type == "news" and not rss_list and frame.get("headline", frame.get("title", pd.Series(dtype=object))).astype(str).str.strip().eq("").any():
        errors.append("empty_headline")
    if import_type in {"manual_news", "manual_notes"} and frame.astype(str).apply(lambda column: column.str.strip().eq("")).all(axis=None):
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
