"""Point-in-time news/context contracts and local-first persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR


NEWS_SCHEMA_VERSION = "news_context.v2"
NEWS_CLEAN_PATH = CLEAN_DIR / "news_context.parquet"
NEWS_RAW_DIR = RAW_DIR / "news_context"


@dataclass(frozen=True)
class NewsItem:
    # The first nine fields preserve the original positional API.
    news_id: str = ""
    instrument_id: str = ""
    source: str = ""
    provider: str = ""
    headline: str = ""
    published_at: str = ""
    ingested_at: str = ""
    url: str = ""
    credibility: str = "unverified"
    instrument_mapping_method: str = ""
    available_at_decision_time: bool | None = None
    timezone_name: str = "UTC"
    timestamp_confidence: str = "exact"
    current_only: bool = False
    revised: bool = False
    context_only: bool = True
    executable_authority: bool = False
    source_url: str | None = None
    provider_name: str | None = None
    timezone: str | None = None

    def __post_init__(self) -> None:
        if self.source_url is None:
            object.__setattr__(self, "source_url", self.url)
        if self.provider_name is None:
            object.__setattr__(self, "provider_name", self.provider)
        if self.timezone:
            object.__setattr__(self, "timezone_name", self.timezone)

    @property
    def source_url_value(self) -> str:
        return str(self.source_url or self.url or "").strip()

    @property
    def provider_name_value(self) -> str:
        return str(self.provider_name or self.provider or "").strip()


@dataclass(frozen=True)
class NewsValidation:
    status: str
    backtest_eligible: bool
    reason: str
    context_only: bool = True
    executable_authority: bool = False
    available_at_decision_time: bool = False
    timestamp_confidence: str = "unknown"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewsPersistenceResult:
    raw_paths: tuple[Path, ...]
    clean_path: Path
    audit_path: Path
    rows: int
    checksum: str
    idempotent: bool = False


def validate_news_item(item: NewsItem, decision_time: datetime) -> NewsValidation:
    """Validate metadata required to use an item in a point-in-time backtest."""

    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        return _invalid("ambiguous_timestamp", "Decision timestamp must include an explicit timezone.")
    published, _ = _parse_timestamp(item.published_at)
    ingested, _ = _parse_timestamp(item.ingested_at)
    if published is None or ingested is None:
        return _invalid("ambiguous_timestamp", "Published/ingested timestamp must be ISO-8601 with timezone.")
    if str(item.timestamp_confidence or "").strip().lower() in {"ambiguous", "local", "unknown"} or str(item.timezone_name or "").strip().lower() in {"local", "unknown", "ambiguous"}:
        return _invalid("ambiguous_timestamp", "News timestamp timezone/confidence is ambiguous.")
    if item.current_only or item.revised:
        return _invalid("current_only_revised", "Current-only or revised news cannot be used for point-in-time backtests.")
    if published > decision_time or ingested > decision_time:
        return _invalid("after_decision_time", "News was not available at the decision time.")
    if not item.source_url_value or not item.provider_name_value or not str(item.instrument_id).strip() or not str(item.instrument_mapping_method).strip():
        return _invalid("missing_provenance", "News source URL, provider, instrument mapping and timestamps are required.")
    if item.available_at_decision_time is not True:
        return _invalid("not_available_at_decision", "Provider did not prove that the item was available at the decision time.")
    return NewsValidation(
        "valid_context",
        True,
        "Timestamp and provenance are valid; news remains context-only.",
        context_only=True,
        executable_authority=False,
        available_at_decision_time=True,
        timestamp_confidence="exact",
    )


def persist_news_items(
    items: Iterable[NewsItem],
    *,
    raw_dir: Path = NEWS_RAW_DIR,
    clean_path: Path = NEWS_CLEAN_PATH,
    audit_path: Path | None = None,
    decision_time: datetime | None = None,
) -> NewsPersistenceResult:
    """Persist immutable raw news and an idempotent canonical clean ledger."""

    raw_dir = Path(raw_dir)
    clean_path = Path(clean_path)
    audit_path = Path(audit_path or clean_path.with_name(clean_path.stem + "_audit.json"))
    item_tuple = tuple(items)
    if not item_tuple:
        raise ValueError("At least one news item is required.")
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    raw_requests: list[AtomicWriteRequest] = []
    rows: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    for item in item_tuple:
        payload = _item_payload(item)
        checksum = _payload_checksum(payload)
        raw_path = raw_dir / f"{_safe_id(item.news_id)}-{checksum}.json"
        if not raw_path.exists():
            raw_requests.append(
                AtomicWriteRequest(
                    raw_path,
                    (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8"),
                    lambda path: json.loads(path.read_text(encoding="utf-8")),
                )
            )
        raw_paths.append(raw_path)
        validation = validate_news_item(item, decision_time or _default_decision_time(item))
        rows.append(_clean_row(item, validation, checksum, raw_path))
        validations.append({"news_id": item.news_id, **asdict(validation), "executable_authority": False})

    existing = _read_clean(clean_path)
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["news_id", "item_checksum"], keep="last")
        combined = sort_news_items(combined)
    audit_payload = {
        "schema_version": NEWS_SCHEMA_VERSION,
        "dataset_type": "news_context",
        "raw_paths": [str(path) for path in raw_paths],
        "clean_path": str(clean_path),
        "checksum": _frame_checksum(combined),
        "rows": len(combined),
        "validations": validations,
        "context_only": True,
        "executable_authority": False,
    }
    csv_path = clean_path.with_suffix(".csv")
    requests = [
        AtomicWriteRequest(clean_path, parquet_payload(combined), validate_parquet_file),
        AtomicWriteRequest(csv_path, combined.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
        AtomicWriteRequest(audit_path, (json.dumps(audit_payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8"), lambda path: json.loads(path.read_text(encoding="utf-8"))),
        *raw_requests,
    ]
    # Raw provider payloads are immutable and part of the same generation as
    # clean/audit mirrors. Existing raw bytes are intentionally not rewritten.
    atomic_write_group(tuple(requests))
    checksum = _payload_checksum(_item_payload(item_tuple[0]))
    return NewsPersistenceResult(tuple(raw_paths), clean_path, audit_path, len(combined), checksum, len(existing) == len(combined))


def load_news_items(path: Path = NEWS_CLEAN_PATH) -> pd.DataFrame:
    return sort_news_items(_read_clean(Path(path)))


def sort_news_items(frame: pd.DataFrame) -> pd.DataFrame:
    """Return news ordered by publication/ingestion time and stable identity."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    result = frame.copy()
    result["_published_sort"] = pd.to_datetime(result.get("published_at", pd.Series(index=result.index)), errors="coerce", utc=True)
    result["_ingested_sort"] = pd.to_datetime(result.get("ingested_at", pd.Series(index=result.index)), errors="coerce", utc=True)
    result["_news_id_sort"] = result.get("news_id", pd.Series(index=result.index)).astype(str)
    result["_checksum_sort"] = result.get("item_checksum", pd.Series(index=result.index)).astype(str)
    result = result.sort_values(
        ["_published_sort", "_ingested_sort", "_news_id_sort", "_checksum_sort"],
        kind="stable",
        na_position="first",
    )
    return result.drop(columns=["_published_sort", "_ingested_sort", "_news_id_sort", "_checksum_sort"]).reset_index(drop=True)


def build_news_contradiction_rows(news: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Compare explicit headline direction with the next deterministic close.

    Only unambiguous direction words and dated price rows are compared.  No
    sentiment is inferred from free text; unsupported rows remain absent from
    the contradiction set and are shown as unavailable by the UI.
    """

    columns = ["news_id", "instrument_id", "headline", "headline_direction", "price_direction", "reason"]
    if news.empty or prices.empty:
        return pd.DataFrame(columns=columns)
    required = {"instrument_id", "published_at", "headline"}
    if not required <= set(news.columns) or not {"instrument_id", "date", "adjusted_close"} <= set(prices.columns):
        return pd.DataFrame(columns=columns)
    price_frame = prices.copy()
    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce").dt.date
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["date", "adjusted_close"])
    rows: list[dict[str, object]] = []
    positive = ("up", "rise", "gain", "higher", "surge", "rally")
    negative = ("down", "fall", "loss", "lower", "drop", "selloff")
    for _, item in news.iterrows():
        headline = str(item.get("headline", ""))
        lowered = headline.casefold()
        has_positive = re.search(r"(?<!\w)(?:" + "|".join(map(re.escape, positive)) + r")(?!\w)", lowered) is not None
        has_negative = re.search(r"(?<!\w)(?:" + "|".join(map(re.escape, negative)) + r")(?!\w)", lowered) is not None
        headline_direction = "up" if has_positive else "down" if has_negative else "unknown"
        if headline_direction == "unknown":
            continue
        published = pd.to_datetime(item.get("published_at"), errors="coerce")
        if pd.isna(published):
            continue
        instrument = str(item.get("instrument_id", "")).strip()
        scoped = price_frame[price_frame["instrument_id"].astype(str).eq(instrument)].sort_values("date")
        prior = scoped[scoped["date"] <= published.date()]
        following = scoped[scoped["date"] > published.date()]
        if prior.empty or following.empty:
            continue
        change = float(following.iloc[0]["adjusted_close"]) - float(prior.iloc[-1]["adjusted_close"])
        price_direction = "up" if change > 0 else "down" if change < 0 else "flat"
        if price_direction in {"flat", headline_direction}:
            continue
        rows.append({
            "news_id": str(item.get("news_id", "")),
            "instrument_id": instrument,
            "headline": headline,
            "headline_direction": headline_direction,
            "price_direction": price_direction,
            "reason": "Explicit headline direction disagrees with the next dated deterministic close.",
        })
    return pd.DataFrame(rows, columns=columns)


def _invalid(status: str, reason: str) -> NewsValidation:
    return NewsValidation(status, False, reason, context_only=True, executable_authority=False, available_at_decision_time=False, timestamp_confidence="invalid")


def _parse_timestamp(value: object) -> tuple[datetime | None, str]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None, "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "ambiguous"
    return parsed, "exact"


def _default_decision_time(item: NewsItem) -> datetime:
    parsed, _ = _parse_timestamp(item.ingested_at)
    return parsed or datetime.now(timezone.utc)


def _item_payload(item: NewsItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["source_url"] = item.source_url_value
    payload["provider_name"] = item.provider_name_value
    payload["context_only"] = True
    payload["executable_authority"] = False
    payload["schema_version"] = NEWS_SCHEMA_VERSION
    return payload


def _clean_row(item: NewsItem, validation: NewsValidation, checksum: str, raw_path: Path) -> dict[str, Any]:
    return {
        "schema_version": NEWS_SCHEMA_VERSION,
        "news_id": item.news_id,
        "instrument_id": item.instrument_id,
        "headline": item.headline,
        "source_url": item.source_url_value,
        "provider_name": item.provider_name_value,
        "published_at": item.published_at,
        "ingested_at": item.ingested_at,
        "instrument_mapping_method": item.instrument_mapping_method,
        "available_at_decision_time": validation.available_at_decision_time,
        "timestamp_confidence": validation.timestamp_confidence,
        "timestamp_status": validation.status,
        "backtest_eligible": validation.backtest_eligible,
        "credibility": item.credibility,
        "source_authority": item.source,
        "context_only": True,
        "executable_authority": False,
        "raw_path": str(raw_path),
        "item_checksum": checksum,
    }


def _read_clean(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
        for column, default in (("context_only", True), ("executable_authority", False)):
            if column not in frame.columns:
                frame[column] = default
        frame["context_only"] = True
        frame["executable_authority"] = False
        return frame
    except Exception:
        return pd.DataFrame()


def _frame_checksum(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    stable = frame.sort_index(axis=1).astype(str).sort_values(list(frame.columns), kind="stable")
    return hashlib.sha256(stable.to_csv(index=False).encode("utf-8")).hexdigest()


def _payload_checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value)) or "unknown"


persist_news = persist_news_items
write_news_items = persist_news_items


__all__ = [
    "NEWS_CLEAN_PATH",
    "NEWS_RAW_DIR",
    "NEWS_SCHEMA_VERSION",
    "NewsItem",
    "NewsPersistenceResult",
    "NewsValidation",
    "build_news_contradiction_rows",
    "load_news_items",
    "persist_news_items",
    "persist_news",
    "sort_news_items",
    "write_news_items",
    "validate_news_item",
]
