"""Stock evidence for the whole stock universe, built once and shared by the score, the pages and Stock Research.

Loads the local fundamentals store, rebuilds decision-time market inputs from the stored prices,
runs ``stock_evidence`` for every stock (first without, then with its peers) and returns one object.
The caller supplies the decision time; ``live_decision_time`` is the single rule for "now".
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import AnalystInputs, MarketInputs, StockEvidence, build_stock_evidence
from etf_cockpit.analysis.stock_peers import PeerPick, PeerProfile, auto_peers, effective_peers
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data.stock_peer_picks import load_user_peers

LIVE_GRACE_DAYS = 5
PEER_METRIC_KEYS = ("pe", "ev_ebit", "ev_sales", "pb", "roe", "ebit_margin", "fcf_yield", "dividend_yield", "revenue_cagr")


def live_decision_time(as_of: date | None, now: datetime | None = None) -> datetime:
    """The decision time for a score: *now* when the price data is current, else the end of its date.

    A replay on older data only sees facts learned by that date; a live view sees everything fetched so far.
    """

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if as_of is None or as_of >= (current - timedelta(days=LIVE_GRACE_DAYS)).date():
        return current
    return datetime.combine(as_of, time(23, 59, 59), tzinfo=timezone.utc)


@dataclass(frozen=True)
class StockRecord:
    instrument_id: str
    name: str
    symbol: str
    currency: str
    region: str
    sector: str
    lifecycle_date: date | None = None


@dataclass
class UniverseEvidence:
    decision_time: datetime
    evidence: dict[str, StockEvidence] = field(default_factory=dict)
    profiles: dict[str, PeerProfile] = field(default_factory=dict)
    peers: dict[str, list[PeerPick]] = field(default_factory=dict)
    auto_peers: dict[str, list[PeerPick]] = field(default_factory=dict)
    user_peers: dict[str, list[str]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    prices: dict[str, MarketInputs] = field(default_factory=dict)
    periods: dict[str, list[sm.Period]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


def stock_records(universe_rows: Iterable[Mapping[str, Any]], config: Mapping[str, Any]) -> list[StockRecord]:
    """Analysis membership retains historical stocks; only the refresh path applies current flags."""

    excluded = (config.get("scope", {}) or {}).get("excluded_sectors", [])
    blocked = {str(item).casefold() for item in excluded}
    records = []
    for row in universe_rows:
        kind = str(row.get("instrument_type") or row.get("asset_type") or "").casefold()
        if kind != "stock" or str(row.get("sector") or "").casefold() in blocked:
            continue
        instrument_id = str(row.get("id") or "")
        if not instrument_id:
            continue
        records.append(
            StockRecord(
                instrument_id,
                str(row.get("name") or instrument_id),
                str(row.get("provider_symbol") or row.get("ticker") or "").strip(),
                str(row.get("currency") or ""),
                str(row.get("region") or ""),
                str(row.get("sector") or ""),
                (sm.as_utc(row.get("lifecycle_date")) or datetime.max.replace(tzinfo=timezone.utc)).date()
                if row.get("lifecycle_date")
                else None,
            )
        )
    return records


def _price_frame(prices: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    if prices is None or prices.empty or "etf_id" not in prices:
        return pd.DataFrame()
    frame = prices[prices["etf_id"].astype(str) == instrument_id]
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame.dropna(subset=["date"]).sort_values("date")


def market_inputs(
    frame: pd.DataFrame,
    snapshot: Mapping[str, Any] | None,
    reporting_currency: str | None,
    decision_time: datetime,
    fx: pd.DataFrame,
    config: Mapping[str, Any],
) -> MarketInputs:
    """Decision-time price, FX, trailing dividends and month-end history; every field known at the decision time."""

    minor = (config.get("reporting", {}) or {}).get("minor_currency_units", {}) or {}
    if frame.empty:
        return MarketInputs(unavailable_reason="no stored price rows for this instrument")
    known = frame[frame["date"].map(lambda d: datetime.combine(d.date() + timedelta(days=1), time(0), tzinfo=timezone.utc) <= decision_time)]
    if known.empty:
        return MarketInputs(unavailable_reason="no stored price is known at the decision time")
    last = known.iloc[-1]
    price_date = last["date"].date()
    close = sm._finite(last.get("close"))
    quote = (snapshot or {}).get("quote_currency") or (str(last.get("currency")) if pd.notna(last.get("currency")) else "")
    quote_major, _factor = sm.minor_unit(str(quote), minor)
    fx_rate = None
    if reporting_currency and quote:
        reporting_major, _ = sm.minor_unit(reporting_currency, minor)
        if reporting_major != quote_major:
            fx_rate, _day = store.fx_rate(f"{quote_major}{reporting_major}", price_date, fx, decision_time=decision_time)
    dividends = None
    dividend_reason = "no dividend history is stored for this instrument"
    if "dividends" in known.columns:
        start = pd.Timestamp(price_date) - pd.Timedelta(days=365)
        window = known[(known["date"] > start) & (known["date"].dt.date <= price_date)]
        history_complete = bool(not known.empty and known["date"].iloc[0] <= start and not window.empty)
        values = pd.to_numeric(window["dividends"], errors="coerce")
        if history_complete and values.notna().all():
            dividends = float(values.sum())
        else:
            dividend_reason = "incomplete_dividend_year: stored dividend rows do not cover the full trailing year"
    else:
        dividend_reason = "incomplete_dividend_year: no complete trailing-year dividend observations are stored"
    month_ends = known.set_index("date")["close"].resample("ME").last().dropna()
    series = tuple((index.date(), float(value)) for index, value in month_ends.items())
    shares = sm._finite((snapshot or {}).get("shares_outstanding"))
    snap_time = sm.as_utc((snapshot or {}).get("known_at"))
    return MarketInputs(
        price=close,
        price_currency=quote_major or None,
        price_date=price_date,
        fx_to_reporting=fx_rate,
        dividends_per_share_12m=dividends,
        dividend_reason=dividend_reason,
        price_series=series,
        shares_fallback=shares,
        shares_fallback_known_at=snap_time,
    )


def analyst_inputs(row: Mapping[str, Any] | None) -> AnalystInputs | None:
    if not row:
        return None
    return AnalystInputs(
        eps_current=sm._finite(row.get("eps_current")),
        eps_90d_ago=sm._finite(row.get("eps_90d_ago")),
        revisions_up_30d=sm._finite(row.get("revisions_up_30d")),
        revisions_down_30d=sm._finite(row.get("revisions_down_30d")),
        known_at=sm.as_utc(row.get("known_at")),
        source=str(row.get("source") or "yfinance"),
    )


def _profile(record: StockRecord, snapshot: Mapping[str, Any] | None, fx: pd.DataFrame, config: Mapping[str, Any], decision_time: datetime) -> PeerProfile:
    minor = (config.get("reporting", {}) or {}).get("minor_currency_units", {}) or {}
    cap = sm._finite((snapshot or {}).get("market_cap_provider"))
    cap_eur = None
    if cap is not None:
        quote_major, _ = sm.minor_unit(str((snapshot or {}).get("quote_currency") or record.currency), minor)
        if quote_major == "EUR":
            cap_eur = cap / 1e9
        else:
            rate, _day = store.fx_rate(f"{quote_major}EUR", decision_time.date(), fx, decision_time=decision_time, max_age_days=30)
            cap_eur = None if rate is None else cap * rate / 1e9
    return PeerProfile(
        record.instrument_id,
        record.name,
        str((snapshot or {}).get("sector") or record.sector or ""),
        str((snapshot or {}).get("industry") or ""),
        record.region,
        cap_eur,
    )


def build_universe_evidence(
    records: Sequence[StockRecord],
    prices: pd.DataFrame,
    decision_time: datetime,
    *,
    root: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> UniverseEvidence:
    records = [record for record in records if record.lifecycle_date is None or decision_time.date() <= record.lifecycle_date]
    cfg = dict(config) if config is not None else store.load_stock_config(root)
    chain = list((cfg.get("sources", {}) or {}).get("chain", ["sec_edgar", "yfinance"]))
    periods_frame = store.read_fundamentals(root)
    snapshots = store.read_snapshots(root)
    fx = store.read_fx(root)
    result = UniverseEvidence(decision_time, config=cfg)
    user_picks = load_user_peers(root)
    result.user_peers = user_picks
    ids = [r.instrument_id for r in records]
    extra_ids = sorted({p for picks in user_picks.values() for p in picks} - set(ids))
    all_records = list(records) + [StockRecord(f"peer:{p}", p, p, "", "", "") for p in extra_ids]
    first: dict[str, StockEvidence] = {}
    for record in all_records:
        iid = record.instrument_id
        periods = store.periods_for(iid, periods_frame, chain)
        snapshot = store.latest_snapshot(iid, snapshots, decision_time)
        analyst = store.latest_analyst(iid, periods_frame, decision_time)
        reporting = None
        known = sm.known_periods(periods, decision_time)
        if known:
            reporting = known[-1].currency
        if iid.startswith("peer:"):
            frame = pd.DataFrame()
            market = _market_from_snapshot(snapshot, decision_time)
        else:
            frame = _price_frame(prices, iid)
            market = market_inputs(frame, snapshot, reporting, decision_time, fx, cfg)
        reason = store.no_data_reason(iid, snapshots, decision_time, bool(known))
        result.snapshots[iid] = snapshot or {}
        result.periods[iid] = sm.known_periods(periods, decision_time)
        result.prices[iid] = market
        result.names[iid] = (snapshot or {}).get("long_name") if iid.startswith("peer:") and snapshot else record.name
        first[iid] = build_stock_evidence(iid, periods, decision_time, market, analyst_inputs(analyst), cfg, no_data_reason=reason)
        result.profiles[iid] = _profile(record, snapshot, fx, cfg, decision_time)
    peer_values = {key: {iid: ev.metrics[key].value for iid, ev in first.items() if key in ev.metrics and ev.metrics[key].available} for key in PEER_METRIC_KEYS}
    candidates = [result.profiles[r.instrument_id] for r in records]
    for record in records:
        iid = record.instrument_id
        automatic = auto_peers(result.profiles[iid], candidates, cfg)
        result.auto_peers[iid] = automatic
        picks = [p if (p in first or p in ids) else f"peer:{p}" for p in user_picks.get(iid, [])]
        names = {k: v for k, v in result.names.items()}
        chosen = effective_peers(automatic, picks, names, iid)
        result.peers[iid] = chosen
        members = {p.instrument_id for p in chosen}
        scoped = {key: {pid: value for pid, value in values.items() if pid in members} for key, values in peer_values.items()}
        periods = store.periods_for(iid, periods_frame, chain)
        snapshot = store.latest_snapshot(iid, snapshots, decision_time)
        result.evidence[iid] = build_stock_evidence(
            iid, periods, decision_time, result.prices[iid], analyst_inputs(analyst), cfg,
            peer_values=scoped, no_data_reason=store.no_data_reason(iid, snapshots, decision_time, bool(sm.known_periods(periods, decision_time))),
        )
    for pid, evidence in first.items():
        if pid.startswith("peer:"):
            result.evidence[pid] = evidence
    return result


def _market_from_snapshot(snapshot: Mapping[str, Any] | None, decision_time: datetime) -> MarketInputs:
    """Market inputs for a user-picked external peer: provider market cap / shares (no price file exists)."""

    if not snapshot:
        return MarketInputs(unavailable_reason="peer fundamentals were never fetched")
    cap = sm._finite(snapshot.get("market_cap_provider"))
    shares = sm._finite(snapshot.get("shares_outstanding"))
    known = sm.as_utc(snapshot.get("known_at"))
    if cap is None or shares is None or shares <= 0 or known is None or known > decision_time:
        return MarketInputs(unavailable_reason="provider market cap is not available for this peer")
    return MarketInputs(price=cap / shares, price_currency=str(snapshot.get("quote_currency") or "") or None, price_date=known.date(), shares_fallback=shares, shares_fallback_known_at=known)


_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def get_universe_evidence(
    records: Sequence[StockRecord],
    prices: pd.DataFrame,
    decision_time: datetime,
    *,
    root: Path | None = None,
) -> UniverseEvidence:
    """Cached build: same stores, prices and decision day reuse the previous result."""

    paths = store.store_paths(root)
    stamps = tuple(p.stat().st_mtime_ns if p.is_file() else 0 for p in paths.values())
    picks_path = Path(root or ROOT) / "data" / "stock_peers" / "user_peers.json"
    stamps += (picks_path.stat().st_mtime_ns if picks_path.is_file() else 0,)
    config_stamp = store.config_path(root).stat().st_mtime_ns
    last_price = str(prices["date"].max()) if prices is not None and not prices.empty and "date" in prices else ""
    key = repr((str(root or ROOT), stamps, config_stamp, tuple((r.instrument_id, r.lifecycle_date) for r in records), last_price, len(prices) if prices is not None else 0, decision_time.isoformat()))
    with _LOCK:
        if _CACHE.get("key") == key:
            return _CACHE["value"]
    value = build_universe_evidence(records, prices, decision_time, root=root)
    with _LOCK:
        _CACHE.update(key=key, value=value)
    return value


def rows_from_config(config: Any) -> list[dict[str, Any]]:
    """Universe entries as plain dicts (extra YAML keys such as ``cik`` included)."""

    rows = []
    for item in getattr(getattr(config, "universe", None), "etfs", ()) or ():
        rows.append(item.model_dump() if hasattr(item, "model_dump") else dict(item))
    return rows


def records_from_config(config: Any, root: Path | None = None) -> list[StockRecord]:
    return stock_records(rows_from_config(config), store.load_stock_config(root))
