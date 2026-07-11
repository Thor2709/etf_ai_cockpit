from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.provenance import metadata_from_frame, sha256_file

ProviderStatus = Literal["ok", "unavailable", "error"]


@dataclass(frozen=True)
class ProviderResult:
    provider_name: str
    dataset_type: str
    status: ProviderStatus
    message: str
    data: pd.DataFrame | None = None
    metadata: DatasetMetadata | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.data is not None


class PriceProvider(ABC):
    """Legacy one-symbol price provider interface kept for existing adapters."""

    name: str

    @abstractmethod
    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return daily OHLCV rows mapped to the cockpit schema."""

    @abstractmethod
    def validate_symbol(self, symbol: str) -> bool:
        """Return whether the provider recognises a symbol."""


class DataProvider(ABC):
    name: str

    @abstractmethod
    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        """Fetch daily price data for multiple provider symbols."""

    @abstractmethod
    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        """Fetch explicit dated FX data."""

    @abstractmethod
    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        """Fetch ETF identity/factsheet metadata."""

    @abstractmethod
    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        """Fetch ETF underlying holdings where available."""


class ManualLocalFileProvider(DataProvider):
    name = "manual_local_file"

    def import_file(self, path: Path, dataset_type: str) -> ProviderResult:
        try:
            frame = _read_local_table(path)
        except Exception as exc:
            return ProviderResult(self.name, dataset_type, "error", f"Could not read {path.name}: {exc}")
        if frame.empty:
            return ProviderResult(self.name, dataset_type, "error", f"{path.name} contains no rows.", frame)
        as_of_date = _infer_as_of_date(frame)
        currency = _infer_single_value(frame, "currency")
        metadata = metadata_from_frame(
            frame,
            source_name=path.name,
            source_type=dataset_type,
            as_of_date=as_of_date,
            currency=currency,
            provider_or_manual_source=str(path),
            staleness_status="unknown",
            notes=f"file_sha256={sha256_file(path)}",
        )
        return ProviderResult(self.name, dataset_type, "ok", f"Loaded {len(frame)} rows from {path.name}.", frame, metadata)

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        return ProviderResult(self.name, "prices", "unavailable", "Manual provider requires a local file import.")

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        return ProviderResult(self.name, "fx", "unavailable", "Manual provider requires a local file import.")

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        return ProviderResult(self.name, "etf_metadata", "unavailable", "Manual provider requires a local file import.")

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        return ProviderResult(self.name, "etf_holdings", "unavailable", "Manual provider requires a local file import.")


class GenericHTTPProvider(DataProvider):
    name = "generic_http"

    def __init__(self, section: ProviderSection | None = None, *, dataset_type: str = "prices"):
        self.section = section or ProviderSection()
        self.dataset_type = dataset_type

    def _unavailable(self, dataset_type: str) -> ProviderResult:
        if self.section.active_provider in {"", "none"}:
            return ProviderResult(self.name, dataset_type, "unavailable", "No API provider configured. Add provider details in Settings or import local files.")
        if not self.section.base_url or not self.section.api_key:
            return ProviderResult(self.name, dataset_type, "unavailable", "API provider is incomplete. Add base URL and API key in Settings or import local files.")
        return ProviderResult(self.name, dataset_type, "unavailable", "Generic HTTP provider is configured for a later fetch-mapping step; no network call was made.")

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        return self._unavailable("prices")

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        return self._unavailable("fx")

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        return self._unavailable("etf_metadata")

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        return self._unavailable("etf_holdings")


def _read_local_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file type {suffix}. Use CSV, XLSX, JSON or Parquet.")


def _infer_as_of_date(frame: pd.DataFrame) -> date | None:
    for column in ("as_of_date", "date"):
        if column in frame.columns and frame[column].notna().any():
            return pd.to_datetime(frame[column]).max().date()
    return None


def _infer_single_value(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame.columns:
        return None
    values = sorted({str(value) for value in frame[column].dropna().unique()})
    if len(values) == 1:
        return values[0]
    if len(values) > 1:
        return "mixed"
    return None
