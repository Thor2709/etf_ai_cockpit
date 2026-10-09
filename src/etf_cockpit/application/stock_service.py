"""Application entry points for normal-stock fundamentals: refresh and the shared universe evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from etf_cockpit.analysis.stock_universe import (
    StockRecord,
    UniverseEvidence,
    get_universe_evidence,
    live_decision_time,
    records_from_config,
    rows_from_config,
)
from etf_cockpit.data import stock_fundamentals as store


def universe_rows(config: Any) -> list[dict[str, Any]]:
    return rows_from_config(config)


def stock_universe_records(config: Any) -> list[StockRecord]:
    return records_from_config(config)


def refresh_universe_stock_fundamentals(
    config: Any,
    *,
    root: Path | None = None,
    only_ids: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> store.RefreshReport:
    """Fetch fundamentals for every normal stock (filings first, then yfinance); read-only free sources."""

    cfg = store.load_stock_config(root)
    targets = store.targets_from_universe(universe_rows(config), excluded_sectors=(cfg.get("scope", {}) or {}).get("excluded_sectors", []))
    if only_ids:
        targets = [t for t in targets if t.instrument_id in only_ids]
    return store.refresh_stock_fundamentals(targets, root=root, now=now, config=cfg, progress=progress)


def refresh_user_peer(ticker: str, *, root: Path | None = None, now: datetime | None = None) -> store.RefreshReport:
    """Fetch an externally picked peer (any Yahoo ticker) into the store under the id ``peer:<ticker>``."""

    cfg = store.load_stock_config(root)
    target = store.StockTarget(f"peer:{ticker}", ticker, ticker)
    return store.refresh_stock_fundamentals([target], root=root, now=now, config=cfg)


def snapshot_stock_evidence(snapshot: Any, *, decision_time: datetime | None = None) -> UniverseEvidence:
    """Universe evidence for the stocks of a cockpit snapshot (prices and universe come from the snapshot)."""

    prices = getattr(snapshot, "prices", pd.DataFrame())
    as_of = None
    if prices is not None and not prices.empty and "date" in prices:
        as_of = pd.to_datetime(prices["date"], errors="coerce").max()
        as_of = None if pd.isna(as_of) else as_of.date()
    when = decision_time or live_decision_time(as_of)
    return get_universe_evidence(stock_universe_records(snapshot.config), prices, when)
