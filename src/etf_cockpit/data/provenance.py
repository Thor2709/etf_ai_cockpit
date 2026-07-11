from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd

from etf_cockpit.core.types import DatasetMetadata, StalenessStatus

DatasetKind = Literal["prices", "etf_factsheet", "etf_holdings", "manual_news", "fx", "unknown"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_dataframe(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    stable = frame.copy()
    for column in stable.columns:
        stable[column] = stable[column].astype(str)
    payload = stable.sort_index(axis=1).to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def price_staleness_status(age_trading_days: int) -> StalenessStatus:
    if age_trading_days <= 3:
        return "ok"
    if age_trading_days <= 10:
        return "warning"
    return "block"


def calendar_staleness_status(kind: DatasetKind, age_days: int) -> StalenessStatus:
    if kind == "etf_factsheet":
        if age_days <= 45:
            return "ok"
        if age_days <= 120:
            return "warning"
        return "block"
    if kind == "etf_holdings":
        if age_days <= 60:
            return "ok"
        if age_days <= 180:
            return "warning"
        return "block"
    if kind == "manual_news":
        return "dated_only"
    return "unknown"


def metadata_from_frame(
    frame: pd.DataFrame,
    *,
    source_name: str,
    source_type: str,
    as_of_date: date | None,
    currency: str | None = None,
    timezone_name: str = "UTC",
    provider_or_manual_source: str = "manual",
    staleness_status: StalenessStatus = "unknown",
    age_days: int | None = None,
    notes: str | None = None,
) -> DatasetMetadata:
    return DatasetMetadata(
        source_name=source_name,
        source_type=source_type,
        as_of_date=as_of_date,
        ingested_at=datetime.now(timezone.utc),
        currency=currency,
        timezone=timezone_name,
        provider_or_manual_source=provider_or_manual_source,
        checksum=sha256_dataframe(frame),
        staleness_status=staleness_status,
        age_days=age_days,
        notes=notes,
    )
