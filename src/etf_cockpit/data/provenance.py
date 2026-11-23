from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd

from etf_cockpit.core.atomic_io import sha256_file as sha256_file
from etf_cockpit.core.types import DatasetMetadata, StalenessStatus

DatasetKind = Literal["prices", "etf_factsheet", "etf_holdings", "manual_news", "fx", "unknown"]


_DIGEST_CHUNK_ROWS = 500_000
_CSV_SPECIAL = (",", '"', "\n", "\r")


def sha256_dataframe(frame: pd.DataFrame) -> str:
    """SHA-256 of ``astype(str)`` per column as CSV (columns sorted, no index): the digest of every stored checksum.

    The same bytes, made in row chunks. Datetime-like and integer columns run ``str`` once per distinct value over
    the whole column (a datetime's text depends on all its values, e.g. dates only). Rows are joined directly unless
    a value is empty or needs CSV quoting; then that chunk is written by ``to_csv``.
    """
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    if not (frame.columns.is_unique and all(isinstance(name, str) for name in frame.columns)):
        stable = frame.copy()
        for column in stable.columns:
            stable[column] = stable[column].astype(str)
        return hashlib.sha256(stable.sort_index(axis=1).to_csv(index=False).encode("utf-8")).hexdigest()
    columns = sorted(frame.columns)
    digest = hashlib.sha256(frame.iloc[0:0][columns].to_csv(index=False).encode("utf-8"))
    whole = {name: _distinct_text(frame[name]) for name in columns if frame[name].dtype.kind in "iubMm"}
    for start in range(0, len(frame), _DIGEST_CHUNK_ROWS):
        stop = start + _DIGEST_CHUNK_ROWS
        texts = [
            whole[name][1][whole[name][0][start:stop]] if name in whole
            else frame[name].iloc[start:stop].astype(str).to_numpy(object)
            for name in columns
        ]
        if any(text == "" or any(char in text for char in _CSV_SPECIAL) for values in texts for text in pd.unique(values)):
            chunk = pd.DataFrame(dict(zip(columns, texts))).to_csv(index=False, header=False)
        else:
            chunk = os.linesep.join(map(",".join, zip(*texts))) + os.linesep
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def _distinct_text(values: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Codes per row and ``astype(str)`` of the distinct values, run on the original typed values."""
    codes, uniques = pd.factorize(values, use_na_sentinel=False)
    first = np.empty(len(uniques), dtype=np.intp)
    first[codes[::-1]] = np.arange(len(codes) - 1, -1, -1)  # the first row of each distinct value
    return codes, values.iloc[first].astype(str).to_numpy(object)


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
