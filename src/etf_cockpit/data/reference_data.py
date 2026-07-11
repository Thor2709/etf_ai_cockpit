from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR, SNAPSHOTS_DIR
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.provenance import calendar_staleness_status, metadata_from_frame, sha256_dataframe
from etf_cockpit.data.providers import ProviderResult

ETF_METADATA_CLEAN_PATH = CLEAN_DIR / "etf_metadata.parquet"
ETF_HOLDINGS_CLEAN_PATH = CLEAN_DIR / "etf_holdings.parquet"

DATE_COLUMNS = ("as_of_date", "date", "factsheet_date", "holdings_date", "report_date")
ETF_ID_COLUMNS = ("etf_id", "fund_id", "parent_etf_id")
ISIN_COLUMNS = ("isin", "fund_isin", "parent_isin")
TICKER_COLUMNS = ("ticker", "fund_ticker")


@dataclass(frozen=True)
class ReferenceValidation:
    frame: pd.DataFrame
    errors: list[str]
    warnings: list[str]
    metadata: DatasetMetadata | None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ReferenceImportCommit:
    raw_path: Path
    clean_path: Path
    previous_snapshot_path: Path | None
    metadata_path: Path
    rows: int
    checksum: str
    warnings: list[str]
    metadata: DatasetMetadata


def normalise_reference_dataset_type(dataset_type: str) -> str:
    if dataset_type in {"etf_metadata", "etf_factsheet", "etf_factsheets"}:
        return "etf_metadata"
    if dataset_type == "etf_holdings":
        return "etf_holdings"
    raise ValueError(f"Unsupported reference dataset type: {dataset_type}")


def validate_reference_dataset(
    frame: pd.DataFrame,
    dataset_type: str,
    *,
    known_etfs: Iterable[str] | None = None,
    isin_to_etf_id: dict[str, str] | None = None,
    ticker_to_etf_id: dict[str, str] | None = None,
    source_name: str = "reference_import",
    provider_or_manual_source: str = "manual",
    today: date | None = None,
) -> ReferenceValidation:
    resolved_type = normalise_reference_dataset_type(dataset_type)
    if resolved_type == "etf_metadata":
        return validate_etf_metadata(
            frame,
            known_etfs=known_etfs,
            isin_to_etf_id=isin_to_etf_id,
            ticker_to_etf_id=ticker_to_etf_id,
            source_name=source_name,
            provider_or_manual_source=provider_or_manual_source,
            today=today,
        )
    return validate_etf_holdings(
        frame,
        known_etfs=known_etfs,
        isin_to_etf_id=isin_to_etf_id,
        ticker_to_etf_id=ticker_to_etf_id,
        source_name=source_name,
        provider_or_manual_source=provider_or_manual_source,
        today=today,
    )


def validate_etf_metadata(
    frame: pd.DataFrame,
    *,
    known_etfs: Iterable[str] | None = None,
    isin_to_etf_id: dict[str, str] | None = None,
    ticker_to_etf_id: dict[str, str] | None = None,
    source_name: str = "etf_metadata",
    provider_or_manual_source: str = "manual",
    today: date | None = None,
) -> ReferenceValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if frame.empty:
        return ReferenceValidation(_empty_etf_metadata_frame(), ["ETF factsheet import contains no rows."], [], None)

    date_column = _first_present(frame, DATE_COLUMNS)
    if date_column is None:
        errors.append(f"ETF factsheets require one dated column: {', '.join(DATE_COLUMNS)}.")

    id_resolution = _resolve_etf_ids(frame, known_etfs=known_etfs, isin_to_etf_id=isin_to_etf_id, ticker_to_etf_id=ticker_to_etf_id)
    errors.extend(id_resolution.errors)
    warnings.extend(id_resolution.warnings)
    if errors:
        return ReferenceValidation(_empty_etf_metadata_frame(), errors, warnings, None)

    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=False)
    if parsed_dates.isna().any():
        errors.append("ETF factsheets contain invalid or missing as_of_date values.")
    if errors:
        return ReferenceValidation(_empty_etf_metadata_frame(), errors, warnings, None)

    normalised = pd.DataFrame()
    normalised["as_of_date"] = parsed_dates.dt.date
    normalised["etf_id"] = id_resolution.etf_ids
    normalised["isin"] = _first_available_series(frame, ISIN_COLUMNS, "")
    normalised["ticker"] = _first_available_series(frame, TICKER_COLUMNS, "")
    normalised["name"] = _first_available_series(frame, ("name", "fund_name", "etf_name"), "")
    normalised["currency"] = _first_available_series(frame, ("currency", "base_currency", "fund_currency"), "")
    normalised["ter"] = pd.to_numeric(_first_available_series(frame, ("ter", "total_expense_ratio"), ""), errors="coerce")
    normalised["provider"] = _first_available_series(frame, ("provider", "issuer", "source"), "manual_import")
    normalised["factsheet_url"] = _first_available_series(frame, ("factsheet_url", "url"), "")
    normalised["staleness_status"] = _staleness_for_frame(normalised, "etf_factsheet", today=today)

    metadata = _metadata_for_reference_frame(
        normalised,
        source_name=source_name,
        source_type="etf_metadata",
        provider_or_manual_source=provider_or_manual_source,
        today=today,
        staleness_kind="etf_factsheet",
        notes="ETF factsheets: OK <= 45 days, warning 46-120, block > 120.",
    )
    return ReferenceValidation(normalised, errors, warnings, metadata)


def validate_etf_holdings(
    frame: pd.DataFrame,
    *,
    known_etfs: Iterable[str] | None = None,
    isin_to_etf_id: dict[str, str] | None = None,
    ticker_to_etf_id: dict[str, str] | None = None,
    source_name: str = "etf_holdings",
    provider_or_manual_source: str = "manual",
    today: date | None = None,
) -> ReferenceValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if frame.empty:
        return ReferenceValidation(_empty_etf_holdings_frame(), ["ETF holdings import contains no rows."], [], None)

    date_column = _first_present(frame, DATE_COLUMNS)
    if date_column is None:
        errors.append(f"ETF holdings require one dated column: {', '.join(DATE_COLUMNS)}.")

    id_resolution = _resolve_etf_ids(frame, known_etfs=known_etfs, isin_to_etf_id=isin_to_etf_id, ticker_to_etf_id=ticker_to_etf_id)
    errors.extend(id_resolution.errors)
    warnings.extend(id_resolution.warnings)

    name_column = _first_present(frame, ("holding_name", "security_name", "name", "constituent_name"))
    if name_column is None:
        errors.append("ETF holdings require a holding/security name column.")
    weight_column = _first_present(frame, ("weight", "weight_decimal", "weight_percent", "weight_pct"))
    if weight_column is None:
        errors.append("ETF holdings require a weight, weight_decimal, weight_percent or weight_pct column.")
    if errors:
        return ReferenceValidation(_empty_etf_holdings_frame(), errors, warnings, None)

    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=False)
    if parsed_dates.isna().any():
        errors.append("ETF holdings contain invalid or missing as_of_date values.")

    raw_weights = pd.to_numeric(frame[weight_column], errors="coerce")
    if raw_weights.isna().any():
        errors.append("ETF holdings contain non-numeric weights.")
    if weight_column in {"weight_percent", "weight_pct"}:
        weights = raw_weights / 100.0
    else:
        weights = raw_weights
        if (weights > 1.0).any():
            errors.append("ETF holdings weight values must be decimals in [0, 1]; use weight_percent for percentage values.")
    if (weights < 0).any():
        errors.append("ETF holdings contain negative weights.")
    if errors:
        return ReferenceValidation(_empty_etf_holdings_frame(), errors, warnings, None)

    normalised = pd.DataFrame()
    normalised["as_of_date"] = parsed_dates.dt.date
    normalised["etf_id"] = id_resolution.etf_ids
    normalised["holding_name"] = frame[name_column].fillna("").astype(str).str.strip()
    if normalised["holding_name"].eq("").any():
        errors.append("ETF holdings contain empty holding/security names.")
    normalised["holding_id"] = _first_available_series(frame, ("holding_id", "security_id", "security_isin", "constituent_isin", "isin"), "")
    normalised["weight"] = weights.astype(float)
    normalised["currency"] = _first_available_series(frame, ("currency", "holding_currency"), "")
    normalised["region"] = _first_available_series(frame, ("region", "country"), "")
    normalised["sector"] = _first_available_series(frame, ("sector", "industry"), "")
    normalised["source"] = _first_available_series(frame, ("source", "provider"), "manual_import")
    normalised["staleness_status"] = _staleness_for_frame(normalised, "etf_holdings", today=today)
    if errors:
        return ReferenceValidation(_empty_etf_holdings_frame(), errors, warnings, None)

    totals = normalised.groupby("etf_id")["weight"].sum()
    too_high = totals[totals > 1.02]
    if not too_high.empty:
        errors.append("ETF holdings weights sum above 102% for: " + ", ".join(f"{idx}={value:.1%}" for idx, value in too_high.items()))
    partial = totals[totals < 0.50]
    if not partial.empty:
        warnings.append("ETF holdings look partial for: " + ", ".join(f"{idx}={value:.1%}" for idx, value in partial.items()))
    if errors:
        return ReferenceValidation(_empty_etf_holdings_frame(), errors, warnings, None)

    metadata = _metadata_for_reference_frame(
        normalised,
        source_name=source_name,
        source_type="etf_holdings",
        provider_or_manual_source=provider_or_manual_source,
        today=today,
        staleness_kind="etf_holdings",
        notes="ETF holdings: OK <= 60 days, warning 61-180, block > 180.",
    )
    return ReferenceValidation(normalised, errors, warnings, metadata)


def commit_reference_import(
    result: ProviderResult,
    dataset_type: str,
    *,
    known_etfs: Iterable[str] | None = None,
    isin_to_etf_id: dict[str, str] | None = None,
    ticker_to_etf_id: dict[str, str] | None = None,
    clean_path: Path | None = None,
    raw_dir: Path | None = None,
    snapshots_dir: Path | None = None,
) -> ReferenceImportCommit:
    if not result.ok or result.data is None:
        raise ValueError("Cannot commit a provider result that did not load reference data.")
    resolved_type = normalise_reference_dataset_type(dataset_type)
    clean_path = clean_path or _clean_path_for(resolved_type)
    raw_dir = raw_dir or _raw_dir_for(resolved_type)
    snapshots_dir = snapshots_dir or (SNAPSHOTS_DIR / resolved_type)
    validation = validate_reference_dataset(
        result.data,
        resolved_type,
        known_etfs=known_etfs,
        isin_to_etf_id=isin_to_etf_id,
        ticker_to_etf_id=ticker_to_etf_id,
        source_name=result.metadata.source_name if result.metadata else resolved_type,
        provider_or_manual_source=result.metadata.provider_or_manual_source if result.metadata else "manual",
    )
    if not validation.ok or validation.metadata is None:
        raise ValueError("; ".join(validation.errors))

    frame = validation.frame
    checksum = sha256_dataframe(frame)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    raw_path = _store_raw_reference_import(result, frame, raw_dir, timestamp, checksum, resolved_type)
    previous_snapshot_path = _snapshot_existing_clean(clean_path, snapshots_dir, timestamp)
    metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_{resolved_type}_metadata.json"
    metadata_payload = json.dumps(
        {
            "dataset_type": resolved_type,
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
    return ReferenceImportCommit(raw_path, clean_path, previous_snapshot_path, metadata_path, len(frame), checksum, validation.warnings, validation.metadata)


def load_reference_dataset(dataset_type: str, path: Path | None = None) -> pd.DataFrame:
    resolved_type = normalise_reference_dataset_type(dataset_type)
    clean_path = path or _clean_path_for(resolved_type)
    if not clean_path.exists():
        return _empty_etf_metadata_frame() if resolved_type == "etf_metadata" else _empty_etf_holdings_frame()
    return pd.read_parquet(clean_path)


def reference_data_inventory() -> list[dict[str, object]]:
    inventory = []
    for dataset_type in ("etf_metadata", "etf_holdings"):
        path = _clean_path_for(dataset_type)
        frame = load_reference_dataset(dataset_type, path)
        if frame.empty:
            inventory.append({"dataset_type": dataset_type, "present": False, "path": str(path)})
            continue
        latest = pd.to_datetime(frame["as_of_date"], errors="coerce").max()
        staleness = str(frame["staleness_status"].dropna().iloc[0]) if "staleness_status" in frame.columns and frame["staleness_status"].notna().any() else "unknown"
        inventory.append(
            {
                "dataset_type": dataset_type,
                "present": True,
                "path": str(path),
                "rows": len(frame),
                "as_of_date": latest.date().isoformat() if pd.notna(latest) else None,
                "staleness_status": staleness,
                "checksum": sha256_dataframe(frame),
            }
        )
    return inventory


def _clean_path_for(dataset_type: str) -> Path:
    return ETF_METADATA_CLEAN_PATH if dataset_type == "etf_metadata" else ETF_HOLDINGS_CLEAN_PATH


def _raw_dir_for(dataset_type: str) -> Path:
    return RAW_DIR / ("etf_factsheets" if dataset_type == "etf_metadata" else "etf_holdings")


@dataclass(frozen=True)
class _EtfIdResolution:
    etf_ids: pd.Series
    errors: list[str]
    warnings: list[str]


def _resolve_etf_ids(
    frame: pd.DataFrame,
    *,
    known_etfs: Iterable[str] | None,
    isin_to_etf_id: dict[str, str] | None,
    ticker_to_etf_id: dict[str, str] | None,
) -> _EtfIdResolution:
    errors: list[str] = []
    warnings: list[str] = []
    known = {str(etf_id) for etf_id in known_etfs or []}
    etf_id_column = _first_present(frame, ETF_ID_COLUMNS)
    isin_column = _first_present(frame, ISIN_COLUMNS)
    ticker_column = _first_present(frame, TICKER_COLUMNS)
    if etf_id_column is None and isin_column is None and ticker_column is None:
        return _EtfIdResolution(pd.Series([""] * len(frame), index=frame.index), ["Reference import requires etf_id, fund_isin/isin or ticker."], warnings)

    if etf_id_column is not None:
        etf_ids = frame[etf_id_column].fillna("").astype(str).str.strip()
    elif isin_column is not None:
        mapping = {str(key): str(value) for key, value in (isin_to_etf_id or {}).items()}
        etf_ids = frame[isin_column].fillna("").astype(str).str.strip().map(mapping).fillna("")
    else:
        mapping = {str(key): str(value) for key, value in (ticker_to_etf_id or {}).items()}
        etf_ids = frame[ticker_column].fillna("").astype(str).str.strip().map(mapping).fillna("")

    if etf_ids.eq("").any():
        errors.append("Reference import contains rows that cannot be mapped to an ETF in the configured universe.")
    if known:
        unknown = sorted({value for value in etf_ids.unique() if value and value not in known})
        if unknown:
            warnings.append("Reference import contains ETFs outside the enabled universe: " + ", ".join(unknown))
    return _EtfIdResolution(etf_ids, errors, warnings)


def _metadata_for_reference_frame(
    frame: pd.DataFrame,
    *,
    source_name: str,
    source_type: str,
    provider_or_manual_source: str,
    today: date | None,
    staleness_kind: str,
    notes: str,
) -> DatasetMetadata:
    latest = max(frame["as_of_date"])
    age_days = max(((today or date.today()) - latest).days, 0)
    staleness = calendar_staleness_status(staleness_kind, age_days)
    currency = None
    if "currency" in frame.columns and frame["currency"].notna().any():
        values = sorted({str(value) for value in frame["currency"].dropna().unique() if str(value)})
        currency = values[0] if len(values) == 1 else "mixed" if len(values) > 1 else None
    return metadata_from_frame(
        frame,
        source_name=source_name,
        source_type=source_type,
        as_of_date=latest,
        currency=currency,
        provider_or_manual_source=provider_or_manual_source,
        staleness_status=staleness,
        age_days=age_days,
        notes=notes,
    )


def _staleness_for_frame(frame: pd.DataFrame, kind: str, *, today: date | None = None) -> str:
    latest = max(frame["as_of_date"])
    age_days = max(((today or date.today()) - latest).days, 0)
    return calendar_staleness_status(kind, age_days)


def _first_present(frame: pd.DataFrame, columns: Iterable[str]) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


def _first_available_series(frame: pd.DataFrame, columns: Iterable[str], default: str) -> pd.Series:
    column = _first_present(frame, columns)
    if column is None:
        return pd.Series([default] * len(frame), index=frame.index)
    return frame[column].fillna(default).astype(str).str.strip().replace("", default)


def _empty_etf_metadata_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["as_of_date", "etf_id", "isin", "ticker", "name", "currency", "ter", "provider", "factsheet_url", "staleness_status"])


def _empty_etf_holdings_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["as_of_date", "etf_id", "holding_name", "holding_id", "weight", "currency", "region", "sector", "source", "staleness_status"])


def _store_raw_reference_import(result: ProviderResult, frame: pd.DataFrame, raw_dir: Path, timestamp: str, checksum: str, dataset_type: str) -> Path:
    source_path = _source_path(result.metadata)
    if source_path and source_path.exists() and source_path.is_file():
        raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_{source_path.name}"
        shutil.copy2(source_path, raw_path)
        return raw_path
    raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_{dataset_type}.parquet"
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
