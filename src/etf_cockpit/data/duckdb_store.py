from __future__ import annotations

from pathlib import Path
import hashlib
import json

import duckdb
import pandas as pd

from etf_cockpit.core.atomic_io import wait_for_atomic_group
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.paths import FEATURES_DIR, PORTFOLIOS_DIR, VALIDATED_DIR
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.data.sample_data import ensure_sample_files
from etf_cockpit.data.validation import validate_prices

PRICE_PARQUET = VALIDATED_DIR / "prices" / "prices_daily.parquet"
FEATURE_PARQUET = FEATURES_DIR / "features_daily.parquet"
HOLDINGS_CSV = PORTFOLIOS_DIR / "current_holdings.csv"


def read_price_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def initialise_store(
    config: AppConfig | None = None,
    force_sample: bool = False,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> None:
    cfg = config or load_config()
    price_csv, _ = ensure_sample_files(cfg, force=force_sample, publish_guard=publish_guard)
    if force_sample or not PRICE_PARQUET.exists():
        prices = read_price_csv(price_csv)
        report = validate_prices(prices)
        if report.status == "Blocked":
            blocked = ", ".join(sorted(report.blocked_etfs))
            raise ValueError(f"Sample data unexpectedly blocked for: {blocked}")
        with publication_scope(publish_guard):
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


def load_features(
    path: Path = FEATURE_PARQUET,
    *,
    reference_identity: dict[str, object] | None = None,
) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if reference_identity is not None:
        metadata_path = Path(f"{path}.meta.json")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            encoded = json.dumps(reference_identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
            identity_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        except (OSError, TypeError, ValueError):
            return pd.DataFrame()
        if (
            not isinstance(metadata, dict)
            or metadata.get("reference_identity") != reference_identity
            or metadata.get("reference_identity_hash") != identity_hash
        ):
            return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def query_parquet(sql: str) -> pd.DataFrame:
    with duckdb.connect(database=":memory:") as con:
        con.execute("SET enable_progress_bar=false")
        return con.execute(sql).df()
