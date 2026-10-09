"""Application entry points for normal-stock fundamentals: refresh and the shared universe evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
from etf_cockpit.data import instrument_lookup
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


def add_stock_note(instrument_id: str, text: str, *, root: Path | None = None) -> dict[str, Any]:
    from etf_cockpit.data import stock_notes

    return stock_notes.add_note(instrument_id, text, root=root)


def retract_stock_note(instrument_id: str, note_id: str, *, root: Path | None = None) -> None:
    from etf_cockpit.data import stock_notes

    stock_notes.retract_note(instrument_id, note_id, root=root)


def set_stock_peers(instrument_id: str, raw: str, config: Any, *, root: Path | None = None) -> tuple[list[str], list[str]]:
    """Save user-picked peers from free text (universe ids or Yahoo tickers); returns (saved ids, messages).

    A ticker outside the universe is fetched once (read-only, free source) so its numbers can be compared;
    a ticker Yahoo does not know is rejected with the reason instead of being stored.
    """

    import re

    from etf_cockpit.data.stock_peer_picks import set_user_peers

    known = {record.instrument_id.casefold(): record.instrument_id for record in stock_universe_records(config)}
    saved: list[str] = []
    messages: list[str] = []
    for token in [t for t in re.split(r"[,;\s]+", raw or "") if t]:
        if token.casefold() in known:
            saved.append(known[token.casefold()])
            continue
        report = refresh_user_peer(token, root=root)
        failure = report.failures.get(f"peer:{token}")
        if failure:
            messages.append(f"{token}: not added — {failure}")
        else:
            saved.append(token)
    try:
        stored = set_user_peers(instrument_id, saved, root=root)
    except ValueError as exc:
        return [], [*messages, str(exc)]
    return stored, messages


def lookup_instrument(identifier: str, **sources: Any) -> instrument_lookup.Resolution:
    """Resolve an ISIN or ticker to listings (read-only, free sources); nothing is stored."""

    return instrument_lookup.resolve(identifier, **sources)


def pick_listing(resolution: instrument_lookup.Resolution, symbol: str) -> instrument_lookup.Resolution:
    return instrument_lookup.choose(resolution, symbol)


def universe_values(resolution: instrument_lookup.Resolution, existing_ids: Sequence[str]) -> dict[str, object]:
    """UniverseRecord fields for a resolved listing; refuses when a field would have to be guessed.

    Currency is never defaulted: a listing without a Yahoo currency must be added by hand. The ISIN stays
    ``needs_verification`` unless OpenFIGI confirmed it.
    """

    chosen = resolution.chosen
    if resolution.status != "ok" or chosen is None:
        raise ValueError(resolution.reason or "the identifier is not resolved to one listing")
    if not chosen.currency:
        raise ValueError(f"{chosen.symbol}: Yahoo returned no currency; use Add record and enter it by hand")
    verified = resolution.isin_status == "verified"
    return {
        "instrument_id": instrument_lookup.suggest_instrument_id(chosen.symbol, existing_ids),
        "name": chosen.name,
        "isin": resolution.isin if verified else "needs_verification",
        "isin_status": "verified" if verified else "needs_verification",
        "ticker": chosen.symbol,
        "asset_type": instrument_lookup.SUPPORTED_QUOTE_TYPES.get(chosen.quote_type, "stock"),
        "tier": "secondary",
        "data_policy": "yfinance_only",
        "currency": chosen.currency,
        "region": chosen.country,
        "sector": chosen.sector,
        "notes": f"added by {resolution.kind} lookup ({', '.join(resolution.sources)}); {resolution.isin_note}".strip("; "),
    }


def lifecycle_of(config: Any, instrument_id: str) -> str:
    """"" for a trading instrument, "delisted" or "merged" when the universe flags it (history is kept)."""

    for row in getattr(getattr(config, "universe", None), "etfs", ()) or ():
        if str(getattr(row, "id", "")).casefold() == str(instrument_id).casefold():
            return str(getattr(row, "lifecycle", "") or "")
    return ""
