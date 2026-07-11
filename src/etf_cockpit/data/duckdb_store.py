from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from etf_cockpit.core.atomic_io import wait_for_atomic_group
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.paths import FEATURES_DIR, PORTFOLIOS_DIR, VALIDATED_DIR, ensure_project_dirs
from etf_cockpit.data.sample_data import ensure_sample_files
from etf_cockpit.data.validation import validate_prices

PRICE_PARQUET = VALIDATED_DIR / "prices" / "prices_daily.parquet"
FEATURE_PARQUET = FEATURES_DIR / "features_daily.parquet"
HOLDINGS_CSV = PORTFOLIOS_DIR / "current_holdings.csv"


def read_price_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def initialise_store(config: AppConfig | None = None, force_sample: bool = False) -> None:
    ensure_project_dirs()
    cfg = config or load_config()
    price_csv, _ = ensure_sample_files(cfg, force=force_sample)
    if force_sample or not PRICE_PARQUET.exists():
        prices = read_price_csv(price_csv)
        report = validate_prices(prices)
        if report.status == "Blocked":
            blocked = ", ".join(sorted(report.blocked_etfs))
            raise ValueError(f"Sample data unexpectedly blocked for: {blocked}")
        write_prices(prices)


def write_prices(prices: pd.DataFrame, path: Path = PRICE_PARQUET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame.to_parquet(path, index=False)


def load_prices(path: Path = PRICE_PARQUET) -> pd.DataFrame:
    if not path.exists():
        initialise_store()
    wait_for_atomic_group(path)
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def load_holdings(path: Path = HOLDINGS_CSV) -> pd.DataFrame:
    if not path.exists():
        initialise_store()
    frame = pd.read_csv(path)
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    return frame


def write_features(features: pd.DataFrame, path: Path = FEATURE_PARQUET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame.to_parquet(path, index=False)


def load_features(path: Path = FEATURE_PARQUET) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def query_parquet(sql: str) -> pd.DataFrame:
    with duckdb.connect(database=":memory:") as con:
        con.execute("SET enable_progress_bar=false")
        return con.execute(sql).df()
