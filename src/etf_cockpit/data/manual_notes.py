from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR, SNAPSHOTS_DIR
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.provenance import metadata_from_frame, sha256_dataframe
from etf_cockpit.data.providers import ProviderResult

MANUAL_NEWS_CLEAN_PATH = CLEAN_DIR / "manual_news.parquet"

DATE_COLUMNS = ("as_of_date", "date", "published_at", "published_date", "note_date")
TEXT_COLUMNS = ("note", "text", "summary", "content", "thesis", "body")


@dataclass(frozen=True)
class ManualNewsValidation:
    frame: pd.DataFrame
    errors: list[str]
    warnings: list[str]
    metadata: DatasetMetadata | None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ManualNewsImportCommit:
    raw_path: Path
    clean_path: Path
    previous_snapshot_path: Path | None
    metadata_path: Path
    rows: int
    checksum: str
    warnings: list[str]
    metadata: DatasetMetadata


def validate_manual_news(
    frame: pd.DataFrame,
    *,
    source_name: str = "manual_news",
    provider_or_manual_source: str = "manual",
    known_etfs: Iterable[str] | None = None,
) -> ManualNewsValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if frame.empty:
        return ManualNewsValidation(
            frame=_empty_manual_news_frame(),
            errors=["Manual news/thesis import contains no rows."],
            warnings=[],
            metadata=None,
        )

    date_column = _first_present(frame, DATE_COLUMNS)
    text_column = _first_present(frame, TEXT_COLUMNS)
    if date_column is None:
        errors.append(f"Manual notes require one dated column: {', '.join(DATE_COLUMNS)}.")
    if text_column is None:
        errors.append(f"Manual notes require one text column: {', '.join(TEXT_COLUMNS)}.")
    if errors:
        return ManualNewsValidation(_empty_manual_news_frame(), errors, warnings, None)

    normalised = pd.DataFrame()
    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=False)
    if parsed_dates.isna().any():
        errors.append("Manual notes contain invalid or missing as_of_date values.")
    normalised["as_of_date"] = parsed_dates.dt.date

    text_values = frame[text_column].astype(str).str.strip()
    if text_values.eq("").any() or frame[text_column].isna().any():
        errors.append("Manual notes contain empty note/text values.")
    normalised["note"] = text_values

    normalised["title"] = _column_or_default(frame, "title", text_values.str.slice(0, 80))
    normalised["etf_id"] = _column_or_default(frame, "etf_id", "")
    normalised["source"] = _first_available_series(frame, ("source", "provider", "source_name"), "manual_import")
    normalised["source_url"] = _first_available_series(frame, ("source_url", "url", "link"), "")
    normalised["confidence"] = _column_or_default(frame, "confidence", "")
    normalised["imported_at"] = datetime.now(timezone.utc).isoformat()
    normalised["executable_authority"] = False
    normalised["staleness_status"] = "dated_only"
    normalised["authority_note"] = "Manual news/thesis notes are dated audit evidence only and cannot authorise trades."
    credibility = [_source_credibility(row) for _, row in normalised.iterrows()]
    normalised["source_type_category"] = [item["source_type_category"] for item in credibility]
    normalised["evidence_grade"] = [item["evidence_grade"] for item in credibility]
    normalised["source_credibility"] = [item["source_credibility"] for item in credibility]
    normalised["promotional_risk"] = [item["promotional_risk"] for item in credibility]
    normalised["reproducibility"] = [item["reproducibility"] for item in credibility]
    normalised["claim_quality"] = [item["claim_quality"] for item in credibility]

    if "executable_authority" in frame.columns and frame["executable_authority"].fillna(False).astype(str).str.lower().isin({"true", "1", "yes"}).any():
        warnings.append("Imported executable_authority values were ignored and forced to false.")

    known = {str(etf_id) for etf_id in known_etfs or []}
    if known:
        unknown_etfs = sorted(
            {
                str(value)
                for value in normalised["etf_id"].dropna().unique()
                if str(value).strip() and str(value) not in known
            }
        )
        if unknown_etfs:
            warnings.append(f"Notes reference ETFs outside the configured universe: {', '.join(unknown_etfs)}.")

    if errors:
        return ManualNewsValidation(_empty_manual_news_frame(), errors, warnings, None)

    metadata = metadata_from_frame(
        normalised,
        source_name=source_name,
        source_type="manual_news",
        as_of_date=max(normalised["as_of_date"]),
        currency=None,
        provider_or_manual_source=provider_or_manual_source,
        staleness_status="dated_only",
        notes="Manual news/thesis notes are dated only and never executable trade authority.",
    )
    return ManualNewsValidation(normalised, errors, warnings, metadata)


def commit_manual_news_import(
    result: ProviderResult,
    *,
    known_etfs: Iterable[str] | None = None,
    clean_path: Path = MANUAL_NEWS_CLEAN_PATH,
    raw_dir: Path = RAW_DIR / "manual_news",
    snapshots_dir: Path = SNAPSHOTS_DIR / "manual_news",
) -> ManualNewsImportCommit:
    if not result.ok or result.data is None:
        raise ValueError("Cannot commit a provider result that did not load manual notes.")

    validation = validate_manual_news(
        result.data,
        source_name=result.metadata.source_name if result.metadata else "manual_news",
        provider_or_manual_source=result.metadata.provider_or_manual_source if result.metadata else "manual",
        known_etfs=known_etfs,
    )
    if not validation.ok or validation.metadata is None:
        raise ValueError("; ".join(validation.errors))

    frame = validation.frame
    checksum = sha256_dataframe(frame)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    raw_path = _store_raw_manual_import(result, frame, raw_dir, timestamp, checksum)
    previous_snapshot_path = _snapshot_existing_clean(clean_path, snapshots_dir, timestamp)

    metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_manual_news_metadata.json"
    metadata_payload = json.dumps(
        {
            "dataset_type": "manual_news",
            "provider_name": result.provider_name,
            "message": result.message,
            "rows": len(frame),
            "checksum": checksum,
            "raw_path": str(raw_path),
            "clean_path": str(clean_path),
            "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else None,
            "warnings": validation.warnings,
            "metadata": _metadata_to_json(validation.metadata),
        },
        indent=2,
    ).encode("utf-8")
    atomic_write_group(
        (
            AtomicWriteRequest(clean_path, parquet_payload(frame), validate_parquet_file),
            AtomicWriteRequest(metadata_path, metadata_payload, lambda path: json.loads(path.read_text(encoding="utf-8"))),
        )
    )
    return ManualNewsImportCommit(
        raw_path=raw_path,
        clean_path=clean_path,
        previous_snapshot_path=previous_snapshot_path,
        metadata_path=metadata_path,
        rows=len(frame),
        checksum=checksum,
        warnings=validation.warnings,
        metadata=validation.metadata,
    )


def load_manual_news(path: Path = MANUAL_NEWS_CLEAN_PATH) -> pd.DataFrame:
    if not path.exists():
        return _empty_manual_news_frame()
    frame = pd.read_parquet(path)
    for column in _empty_manual_news_frame().columns:
        if column not in frame.columns:
            frame[column] = "" if column != "executable_authority" else False
    frame["executable_authority"] = False
    if {"source", "source_url", "title", "note"}.issubset(frame.columns):
        needs_credibility = frame["source_credibility"].astype(str).str.strip().eq("").any() if "source_credibility" in frame else True
        if needs_credibility:
            credibility = [_source_credibility(row) for _, row in frame.iterrows()]
            for column in ("source_type_category", "evidence_grade", "source_credibility", "promotional_risk", "reproducibility", "claim_quality"):
                frame[column] = [item[column] for item in credibility]
    return frame


def manual_news_markdown(frame: pd.DataFrame, *, max_rows: int = 20) -> str:
    if frame.empty:
        return "No manual thesis/news notes have been imported.\n"
    rows = frame.copy()
    rows["as_of_date"] = pd.to_datetime(rows["as_of_date"], errors="coerce").dt.date
    rows = rows.sort_values("as_of_date", ascending=False).head(max_rows)
    lines = [
        "# Recent Manual Thesis/News Notes",
        "",
        "These notes are dated audit evidence only. executable_authority=false for every row.",
        "",
    ]
    for _, row in rows.iterrows():
        etf_id = str(row.get("etf_id") or "portfolio")
        title = str(row.get("title") or "Untitled note")
        source = str(row.get("source") or "manual_import")
        grade = str(row.get("evidence_grade") or "low")
        credibility = str(row.get("source_credibility") or "unverified")
        promotional = str(row.get("promotional_risk") or "unknown")
        reproducibility = str(row.get("reproducibility") or "unknown")
        note = str(row.get("note") or "").replace("\r", " ").replace("\n", " ").strip()
        lines.append(
            f"- {row.get('as_of_date')} | {etf_id} | {title} | source={source} | "
            f"evidence_grade={grade} | credibility={credibility} | promotional_risk={promotional} | "
            f"reproducibility={reproducibility} | executable_authority=false"
        )
        lines.append(f"  {note}")
    return "\n".join(lines).rstrip() + "\n"


def _first_present(frame: pd.DataFrame, columns: Iterable[str]) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


def _column_or_default(frame: pd.DataFrame, column: str, default: object) -> pd.Series:
    if column in frame.columns:
        return frame[column].fillna("").astype(str).str.strip()
    if isinstance(default, pd.Series):
        return default.fillna("").astype(str).str.strip()
    return pd.Series([default] * len(frame), index=frame.index).astype(str)


def _first_available_series(frame: pd.DataFrame, columns: Iterable[str], default: str) -> pd.Series:
    column = _first_present(frame, columns)
    if column is None:
        return pd.Series([default] * len(frame), index=frame.index)
    return frame[column].fillna(default).astype(str).str.strip().replace("", default)


def _empty_manual_news_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "as_of_date",
            "etf_id",
            "title",
            "note",
            "source",
            "source_url",
            "confidence",
            "imported_at",
            "executable_authority",
            "staleness_status",
            "authority_note",
            "source_type_category",
            "evidence_grade",
            "source_credibility",
            "promotional_risk",
            "reproducibility",
            "claim_quality",
        ]
    )


def _source_credibility(row: pd.Series) -> dict[str, str]:
    source = str(row.get("source") or "").lower()
    url = str(row.get("source_url") or "").lower()
    title = str(row.get("title") or "").lower()
    note = str(row.get("note") or "").lower()
    combined = " ".join([source, url, title, note])
    promotional_tokens = ("guaranteed", "paid group", "course", "telegram", "discord", "signal service", "subscribe", "dm me")
    performance_tokens = ("screenshot", "return in", "% return", "profit", "win rate", "best year")

    promotional_risk = "high" if any(token in combined for token in promotional_tokens) else "low"
    if "reddit" in combined or "r/" in combined:
        return {
            "source_type_category": "community_anecdote",
            "evidence_grade": "low",
            "source_credibility": "anecdotal",
            "promotional_risk": "high" if promotional_risk == "high" else "medium",
            "reproducibility": "low",
            "claim_quality": "performance_screenshot_or_claim" if any(token in combined for token in performance_tokens) else "community_context_only",
        }
    if any(token in combined for token in performance_tokens):
        return {
            "source_type_category": "performance_claim",
            "evidence_grade": "low",
            "source_credibility": "anecdotal",
            "promotional_risk": promotional_risk,
            "reproducibility": "low",
            "claim_quality": "performance_screenshot_or_claim",
        }
    if any(token in combined for token in ("sec.gov", "fred", "stooq", "yahoo", "official", "factsheet", "issuer")):
        return {
            "source_type_category": "official_or_provider",
            "evidence_grade": "moderate",
            "source_credibility": "provider_documentation",
            "promotional_risk": promotional_risk,
            "reproducibility": "medium",
            "claim_quality": "source_dated_context",
        }
    if any(token in combined for token in ("doi", "arxiv", "paper", "journal", "ssrn", "huggingface.co/docs")):
        return {
            "source_type_category": "research_or_documentation",
            "evidence_grade": "moderate",
            "source_credibility": "research_or_documentation",
            "promotional_risk": promotional_risk,
            "reproducibility": "medium",
            "claim_quality": "method_context",
        }
    return {
        "source_type_category": "manual_unverified",
        "evidence_grade": "low",
        "source_credibility": "unverified_manual_note",
        "promotional_risk": promotional_risk,
        "reproducibility": "unknown",
        "claim_quality": "context_only",
    }


def _store_raw_manual_import(result: ProviderResult, frame: pd.DataFrame, raw_dir: Path, timestamp: str, checksum: str) -> Path:
    source_path = _source_path(result.metadata)
    if source_path and source_path.exists() and source_path.is_file():
        raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_{source_path.name}"
        shutil.copy2(source_path, raw_path)
        return raw_path
    raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_manual_news.parquet"
    frame.to_parquet(raw_path, index=False)
    return raw_path


def _snapshot_existing_clean(clean_path: Path, snapshots_dir: Path, timestamp: str) -> Path | None:
    if not clean_path.exists():
        return None
    snapshot_path = snapshots_dir / f"{timestamp}_previous_{clean_path.name}"
    shutil.copy2(clean_path, snapshot_path)
    return snapshot_path


def _source_path(metadata: DatasetMetadata | None) -> Path | None:
    if metadata is None:
        return None
    try:
        return Path(metadata.provider_or_manual_source)
    except Exception:
        return None


def _metadata_to_json(metadata: DatasetMetadata) -> dict[str, object]:
    return {
        "source_name": metadata.source_name,
        "source_type": metadata.source_type,
        "as_of_date": metadata.as_of_date.isoformat() if metadata.as_of_date else None,
        "ingested_at": metadata.ingested_at.isoformat() if metadata.ingested_at else None,
        "currency": metadata.currency,
        "timezone": metadata.timezone,
        "provider_or_manual_source": metadata.provider_or_manual_source,
        "checksum": metadata.checksum,
        "staleness_status": metadata.staleness_status,
        "age_days": metadata.age_days,
        "notes": metadata.notes,
    }
