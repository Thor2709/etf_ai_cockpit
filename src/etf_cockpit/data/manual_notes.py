from __future__ import annotations

import json
import re
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
CREDIBILITY_SCHEMA_VERSION = "manual_news.credibility.v2"
CREDIBILITY_FLAG_CODES = (
    "performance_screenshot_without_methodology",
    "dm_or_funnel_language",
    "closed_source_claim",
    "missing_benchmark",
    "missing_drawdown",
    "missing_cost_slippage",
    "missing_sample_size",
    "missing_reproducible_method",
    "too_good_to_be_true_return_claim",
)
CREDIBILITY_FLAG_COLUMNS = tuple(f"credibility_flag_{code}" for code in CREDIBILITY_FLAG_CODES)


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
    evidence = [classify_manual_note_credibility(row) for _, row in normalised.iterrows()]
    normalised["credibility_schema_version"] = CREDIBILITY_SCHEMA_VERSION
    normalised["credibility_flag_status"] = "available"
    normalised["credibility_flags"] = [
        "|".join(code for code in CREDIBILITY_FLAG_CODES if item[code] == "detected") or "none"
        for item in evidence
    ]
    normalised["credibility_reason_codes"] = normalised["credibility_flags"]
    normalised["credibility_evidence"] = [
        json.dumps({code: item[code] for code in CREDIBILITY_FLAG_CODES}, sort_keys=True)
        for item in evidence
    ]
    for code, column in zip(CREDIBILITY_FLAG_CODES, CREDIBILITY_FLAG_COLUMNS):
        normalised[column] = [item[code] for item in evidence]

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
    expected_columns = {
        "credibility_schema_version",
        "credibility_flag_status",
        "credibility_flags",
        "credibility_reason_codes",
        "credibility_evidence",
        *CREDIBILITY_FLAG_COLUMNS,
    }
    structured_schema_present = expected_columns.issubset(frame.columns)
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
    if not structured_schema_present:
        # Older parquet frames cannot be reclassified on load: retain their
        # legacy credibility fields but make the new evidence state explicit.
        frame["credibility_schema_version"] = "unknown"
        frame["credibility_flag_status"] = "unavailable"
        frame["credibility_flags"] = "unknown"
        frame["credibility_reason_codes"] = "unknown"
        frame["credibility_evidence"] = "unknown"
        for column in CREDIBILITY_FLAG_COLUMNS:
            frame[column] = "unknown"
    else:
        invalid_rows = [index for index, row in frame.iterrows() if not _structured_credibility_valid(row)]
        if invalid_rows:
            frame.loc[invalid_rows, "credibility_schema_version"] = "unknown"
            frame.loc[invalid_rows, "credibility_flag_status"] = "unavailable"
            frame.loc[invalid_rows, "credibility_flags"] = "unknown"
            frame.loc[invalid_rows, "credibility_reason_codes"] = "unknown"
            frame.loc[invalid_rows, "credibility_evidence"] = "unknown"
            for column in CREDIBILITY_FLAG_COLUMNS:
                frame.loc[invalid_rows, column] = "unknown"
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
        flags = str(row.get("credibility_flags") or "unknown")
        flag_status = str(row.get("credibility_flag_status") or "unavailable")
        evidence = str(row.get("credibility_evidence") or "unknown")
        note = str(row.get("note") or "").replace("\r", " ").replace("\n", " ").strip()
        lines.append(
            f"- {row.get('as_of_date')} | {etf_id} | {title} | source={source} | "
            f"evidence_grade={grade} | credibility={credibility} | promotional_risk={promotional} | "
            f"reproducibility={reproducibility} | credibility_flags={flags} | "
            f"credibility_flag_status={flag_status} | credibility_evidence={evidence} | executable_authority=false"
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
            "credibility_schema_version",
            "credibility_flag_status",
            "credibility_flags",
            "credibility_reason_codes",
            "credibility_evidence",
            *CREDIBILITY_FLAG_COLUMNS,
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


_NEGATION_RE = re.compile(
    r"\b(?:no|not|without|never|none|missing|unavailable|absent|omitted|lack(?:s|ing)?)\b"
)


def _contains_claim(text: str, pattern: str) -> bool:
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        prefix = text[max(0, match.start() - 45) : match.start()]
        if _NEGATION_RE.search(re.split(r"[.,;:!?]", prefix)[-1]):
            continue
        return True
    return False


def _contains_absence(text: str, pattern: str) -> bool:
    absence = r"\b(?:no|without|missing|unavailable|absent|omitted|not\s+(?:provided|shown|disclosed|reported))\b"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        sentence = re.split(r"[.!?]", text[max(0, match.start() - 140) : match.start()])[-1]
        absence_match = list(re.finditer(absence, sentence, flags=re.IGNORECASE))
        if absence_match and not re.search(r"\bbut\b", sentence[absence_match[-1].end() :], flags=re.IGNORECASE):
            return True
    return bool(
        re.search(
            rf"{pattern}\W{{0,140}}(?:is\s+)?(?:missing|unavailable|absent|omitted|not\s+(?:provided|shown|disclosed|reported))\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _credibility_evidence(row: pd.Series) -> dict[str, str]:
    text = " ".join(str(row.get(field) or "") for field in ("source", "source_url", "title", "note")).casefold()
    performance_screenshot = _contains_claim(text, r"\bscreenshot\b") and _contains_claim(text, r"(?:\breturns?\b|\bprofit(?:s|able)?\b|\bwin\s*rate\b|\bsharpe\b|\bperformance\b)")
    performance_claim = performance_screenshot or _contains_claim(text, r"(?:\breturns?\b|\bprofit(?:s|able)?\b|\bwin\s*rate\b|\bsharpe\b|\bannuali[sz]ed\b)")
    methodology_present = _contains_claim(text, r"(?:\bmethodolog(?:y|ies)\b|\bmethod\b|\brules?\b|\bbacktest(?:ed|ing)?\b|\breproduc(?:ible|e|ed)\b|\breplicat(?:e|ed|able)\b|\bsource\s+code\b|\bgithub\b|\bentry\s+and\s+exit\b)")
    benchmark_present = _contains_claim(text, r"(?:\bbenchmark\b|\bcompar(?:e|ed|ison)\b|\bvs\.?\b|\brelative\s+to\b|\boutperform(?:ed|s)?\b)")
    drawdown_present = _contains_claim(text, r"\bdrawdown\b")
    cost_present = _contains_claim(text, r"(?:\bcosts?\b|\bslippage\b|\bspread\b|\bexpense\s+ratio\b|\bcommission\b|\bfriction\b|\bfees?\b)")
    sample_present = _contains_claim(text, r"(?:\bsample\s+size\b|\bobservations?\b|\btrades?\b|\btransactions?\b|\bn\s*[=:]\s*\d+)" )
    too_good = _contains_claim(text, r"(?:too\s+good\s+to\s+be\s+true|\b\+?\d{3,}(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*x\b|\b(?:double|tripled?)\b|\bguaranteed\b.{0,24}\b(?:returns?|profits?)\b)")
    missing_benchmark = _contains_absence(text, r"\bbenchmark\b") or (performance_claim and not benchmark_present)
    missing_drawdown = _contains_absence(text, r"\bdrawdown\b") or (performance_claim and not drawdown_present)
    missing_cost = _contains_absence(text, r"(?:\bcosts?\b|\bslippage\b|\bfees?\b)") or (performance_claim and not cost_present)
    missing_sample = _contains_absence(text, r"(?:\bsample\s+size\b|\bobservations?\b|\btrades?\b)") or (performance_claim and not sample_present)
    missing_method = _contains_absence(text, r"(?:\bmethodolog(?:y|ies)\b|\bmethod\b|\breproduc(?:ible|e|ed)\b|\breplicat(?:e|ed|able)\b)") or (performance_claim and not methodology_present)
    return {
        "performance_screenshot_without_methodology": "detected" if performance_screenshot and (not methodology_present or _contains_absence(text, r"(?:\bmethodolog(?:y|ies)\b|\bmethod\b|\breproduc(?:ible|e|ed)\b|\breplicat(?:e|ed|able)\b)")) else "not_detected",
        "dm_or_funnel_language": "detected" if _contains_claim(text, r"(?:\bdm\s+me\b|\bsend\s+(?:me\s+)?a?\s*dm\b|\bmessage\s+me\b|\bdirect\s+message\b|\bfunnel\b|\bpaid\s+group\b|\bsubscribe\b|\blink\s+in\s+bio\b|\bjoin\s+(?:my|the)\s+group\b)") else "not_detected",
        "closed_source_claim": "detected" if _contains_claim(text, r"(?:\bclosed[-\s]?source\b|\bblack[-\s]?box\b|\bproprietary\s+(?:algorithm|system|model)\b|\bsecret\s+(?:algorithm|strategy)\b)") else "not_detected",
        "missing_benchmark": "detected" if missing_benchmark else "not_detected",
        "missing_drawdown": "detected" if missing_drawdown else "not_detected",
        "missing_cost_slippage": "detected" if missing_cost else "not_detected",
        "missing_sample_size": "detected" if missing_sample else "not_detected",
        "missing_reproducible_method": "detected" if missing_method else "not_detected",
        "too_good_to_be_true_return_claim": "detected" if too_good else "not_detected",
    }


def classify_manual_note_credibility(row: pd.Series) -> dict[str, str]:
    """Classify local note claims into stable evidence flags without score authority."""

    return _credibility_evidence(row)


def _structured_credibility_valid(row: pd.Series) -> bool:
    if str(row.get("credibility_schema_version") or "") != CREDIBILITY_SCHEMA_VERSION:
        return False
    if str(row.get("credibility_flag_status") or "") != "available":
        return False
    states = {code: str(row.get(column) or "") for code, column in zip(CREDIBILITY_FLAG_CODES, CREDIBILITY_FLAG_COLUMNS)}
    if any(value not in {"detected", "not_detected"} for value in states.values()):
        return False
    detected = "|".join(code for code in CREDIBILITY_FLAG_CODES if states[code] == "detected") or "none"
    if str(row.get("credibility_flags") or "") != detected:
        return False
    if str(row.get("credibility_reason_codes") or "") != detected:
        return False
    try:
        evidence = json.loads(str(row.get("credibility_evidence") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return evidence == states


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
