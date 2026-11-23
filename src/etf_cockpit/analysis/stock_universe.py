"""Stock evidence for the whole stock universe, built once and shared by the score, the pages and Stock Research.

Loads the local fundamentals store, rebuilds decision-time market inputs from the stored prices,
runs ``stock_evidence`` for every stock (first without, then with its peers) and returns one object.
The caller supplies the decision time; ``live_decision_time`` is the single rule for "now".
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import AnalystInputs, MarketInputs, StockEvidence, build_stock_evidence, metric_freshness_reason
from etf_cockpit.analysis.stock_peers import COHORT_LEVELS, PeerIndex, PeerPick, PeerProfile, auto_peers, effective_peers
from etf_cockpit.core.frame_signature import columns_key
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data.stock_peer_picks import load_user_peers

LIVE_GRACE_DAYS = 5
SECTOR_ROUTE_MISSING = "sector_route_missing"
# Insurers, exchanges and diversified financials have no dedicated fundamentals route yet. Banks are excluded from the
# generic route by ``scope.excluded_sectors`` (the Sparebank scorecard owns them) and never match here.
_NON_BANK_FINANCIAL_TOKENS = ("financ", "insur", "assurance")
_BANK_TOKENS = ("bank", "savings")


def is_non_bank_financial_sector(sector: object) -> bool:
    """True for a Financials / Insurance / Financial exchanges classification (never for banks or blank labels)."""

    text = "" if _blank(sector) else str(sector).strip().casefold()
    if not text or any(token in text for token in _BANK_TOKENS):
        return False
    return any(token in text for token in _NON_BANK_FINANCIAL_TOKENS)

PEER_METRIC_KEYS = ("pe", "ev_ebit", "ev_sales", "pb", "roe", "ebit_margin", "fcf_yield", "dividend_yield", "revenue_cagr")
COHORT_METRIC_KEYS = ("pe", "earnings_yield", "fcf_yield", "ebit_ev_yield", "roe", "roic", "ebit_margin", "net_debt_to_ebitda", "fcf_conversion", "revenue_cagr")


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
    invalid_lifecycle: bool = False  # a cutoff was given but cannot be parsed: no evidence, with a reason


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
    excluded: dict[str, str] = field(default_factory=dict)  # instrument_id -> reason it has no evidence


def _blank(value: object) -> bool:
    if value is None:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and value.strip().casefold() in {"", "nan", "nat", "none"}


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
        raw_cutoff = row.get("lifecycle_date")
        cutoff = None if _blank(raw_cutoff) else sm.as_utc(raw_cutoff)  # a blank cell (None/NaN/NaT/"") means no cutoff
        invalid = not _blank(raw_cutoff) and cutoff is None  # an unparseable cutoff cannot prove the stock is active: fail closed
        records.append(
            StockRecord(
                instrument_id,
                str(row.get("name") or instrument_id),
                str(row.get("provider_symbol") or row.get("ticker") or "").strip(),
                str(row.get("currency") or ""),
                str(row.get("region") or ""),
                str(row.get("sector") or ""),
                cutoff.date() if cutoff is not None else None,
                invalid,
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


def _evidenced(values: pd.Series) -> np.ndarray:
    """Per-row action evidence: only a real boolean True counts."""

    return values.map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value)).to_numpy(dtype=bool)


def with_as_traded_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Carry split-only adjustment evidence across a caller's decision-time cut.

    Compute from the full stored series, before truncation. Existing factors came
    from an upstream full-series call and must survive subsequent truncations.
    No price or other future observation contributes to these factors. A bar
    with an unevidenced later row gets no factor: that row's split is unknown.
    """

    if "as_traded_split_factor" in prices or prices.empty:
        return prices
    result = prices.copy()
    factors = np.full(len(prices), np.nan)
    groups = prices.groupby("etf_id", dropna=False).indices.values() if "etf_id" in prices else [np.arange(len(prices))]
    for positions in groups:
        frame = prices.iloc[positions]
        if not {"date", "stock_splits", "actions_evidenced"} <= set(frame.columns):
            continue
        dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        splits = pd.to_numeric(frame["stock_splits"], errors="coerce")
        if dates.isna().any() or dates.dt.date.duplicated().any():
            continue
        if splits.isna().any() or not np.isfinite(splits).all() or (splits < 0).any():
            continue
        order = np.argsort(dates.to_numpy())
        ratios = splits.to_numpy(dtype=float)[order]
        ratios[ratios == 0] = 1.0
        # The split on the bar date is already reflected in its traded price.
        unevidenced = ~_evidenced(frame["actions_evidenced"])[order]
        later_unevidenced = np.r_[np.cumsum(unevidenced[:0:-1])[::-1], 0] > 0
        with np.errstate(over="ignore", under="ignore"):
            restored = np.r_[np.cumprod(ratios[:0:-1])[::-1], 1.0]
        factors[np.asarray(positions)[order]] = np.where(later_unevidenced, np.nan, restored)
    result["as_traded_split_factor"] = factors
    return result


def as_traded_close(frame: pd.DataFrame, when: date) -> tuple[float | None, str | None]:
    """Restore a stored split-adjusted close to its traded units on ``when``.

    ``frame`` contains either the full stored split history or per-bar factors
    prepared by ``with_as_traded_factors`` before decision-time truncation.
    Later splits only undo the provider's retrospective price adjustment, so
    every row after ``when`` needs action evidence; earlier rows do not.
    Missing or ambiguous action evidence fails closed, including legacy rows.
    """

    return _as_traded_closes(frame)(when)


def _as_traded_closes(frame: pd.DataFrame) -> Callable[[date], tuple[float | None, str | None]]:
    """``as_traded_close`` for one frame: the checks that do not depend on the date run once, in the same order."""

    def fails(reason: str) -> Callable[[date], tuple[float | None, str | None]]:
        return lambda _when: (None, reason)

    if frame.empty or not {"date", "close"} <= set(frame.columns):
        return fails("no stored close for the valuation date")
    if "etf_id" in frame and frame["etf_id"].nunique(dropna=False) != 1:
        return fails("ambiguous instrument in valuation price history")
    if "actions_evidenced" not in frame:
        return fails("actions_evidence_missing: as-traded valuation price is unavailable")
    if "stock_splits" not in frame:
        return fails("split_history_missing: as-traded valuation price is unavailable")
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.date
    if dates.isna().any() or dates.duplicated().any():
        return fails("ambiguous dates in valuation split history")
    position = {day: index for index, day in enumerate(dates)}
    unevidenced = dates[~_evidenced(frame["actions_evidenced"])]
    last_unevidenced = unevidenced.max() if len(unevidenced) else None  # splits on later rows are reversed
    splits = pd.to_numeric(frame["stock_splits"], errors="coerce")
    splits_invalid = bool(splits.isna().any() or not np.isfinite(splits).all() or (splits < 0).any())

    def close_on(when: date) -> tuple[float | None, str | None]:
        index = position.get(when)
        if index is None:
            return None, "no stored close for the valuation date"
        if last_unevidenced is not None and last_unevidenced > when:
            return None, "actions_evidence_missing: as-traded valuation price is unavailable"
        row = frame.iloc[index]
        close = sm._finite(row["close"])
        if close is None or close <= 0:
            return None, "stored valuation close is missing or non-positive"
        if splits_invalid:
            return None, "split_history_invalid: as-traded valuation price is unavailable"
        # Zero is the provider's explicit no-event marker. A split on d is already
        # reflected in d's traded price, so only strictly later events are reversed.
        if "as_traded_split_factor" in frame:
            factor = sm._finite(row["as_traded_split_factor"])
            if factor is None or factor <= 0:
                return None, "split_history_invalid: full-series split factor is unavailable"
        else:
            factor = math.prod(float(ratio) for ratio in splits[(dates > when) & (splits != 0)])
        value = sm._finite(close * factor)
        if value is None or value <= 0:
            return None, "split_history_invalid: restored valuation price is non-finite or non-positive"
        return value, None

    return close_on


def market_inputs(
    frame: pd.DataFrame,
    snapshot: Mapping[str, Any] | None,
    reporting_currency: str | None,
    decision_time: datetime,
    fx: pd.DataFrame,
    config: Mapping[str, Any],
) -> MarketInputs:
    """Decision-time valuation inputs; later splits only reverse stored price adjustments."""

    minor = (config.get("reporting", {}) or {}).get("minor_currency_units", {}) or {}
    if frame.empty:
        return MarketInputs(unavailable_reason="no stored price rows for this instrument")
    days = frame["date"].dt.tz_localize(None) if frame["date"].dt.tz is not None else frame["date"]  # the stored day, as d.date()
    # a stored day is known from the next midnight UTC
    known = frame[days.dt.normalize() + pd.Timedelta(days=1) <= pd.Timestamp(decision_time).tz_convert("UTC").tz_localize(None)]
    if known.empty:
        return MarketInputs(unavailable_reason="no stored price is known at the decision time")
    last = known.iloc[-1]
    price_date = last["date"].date()
    close_on = _as_traded_closes(frame)
    close, price_reason = close_on(price_date)
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
            # Provider dividends share the stored close's split-adjusted units.
            # Express both legs in the traded share units at the valuation date.
            if close is None:
                dividend_reason = price_reason
            elif not _evidenced(window["actions_evidenced"]).all():
                dividend_reason = "actions_evidence_missing: trailing-year dividend rows are not evidenced"
            else:
                dividends = float(values.sum()) * close / float(last["close"])
        else:
            dividend_reason = "incomplete_dividend_year: stored dividend rows do not cover the full trailing year"
    else:
        dividend_reason = "incomplete_dividend_year: no complete trailing-year dividend observations are stored"
    closes = known.set_index("date")["close"].dropna()
    # the month-end reading is dated by the last stored price, not the calendar label, so filings known between the two never leak in
    month_ends = closes.groupby(closes.index.to_period("M")).tail(1)
    running_month = pd.Period(decision_time.date(), "M")
    month_ends = month_ends[month_ends.index.to_period("M") < running_month]  # the decision month is still running, every earlier month is complete
    series = tuple(
        (index.date(), value)
        for index in month_ends.index
        if (value := close_on(index.date())[0]) is not None
    )
    shares = sm._finite((snapshot or {}).get("shares_outstanding"))
    snap_time = sm.as_utc((snapshot or {}).get("known_at"))
    provider_cap = sm._finite((snapshot or {}).get("market_cap_provider"))
    if provider_cap is not None and (snap_time is None or snap_time > decision_time):
        provider_cap = None  # a snapshot not known at the decision time is not independent evidence
    if provider_cap is not None and reporting_currency and quote:
        reporting_major, _ = sm.minor_unit(reporting_currency, minor)
        if reporting_major != quote_major:
            provider_cap = None if fx_rate is None else provider_cap * fx_rate  # same-date FX, else no comparison
    elif provider_cap is not None:
        provider_cap = None
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
        market_cap_provider=provider_cap,
        unavailable_reason=price_reason,
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
    quote = str((snapshot or {}).get("quote_currency") or "").strip()  # never the instrument's listing currency: the cap's own currency is unknown otherwise
    if cap is not None and quote:
        quote_major, _ = sm.minor_unit(quote, minor)
        if quote_major == "EUR":
            cap_eur = cap / 1e9
        else:
            cap_time = sm.as_utc((snapshot or {}).get("known_at"))
            cap_date = cap_time.date() if cap_time is not None else None
            # the provider cap is dated by its snapshot: convert with the FX of that date, never a later or older vintage
            rate, _day = (None, None) if cap_date is None else store.fx_rate(f"{quote_major}EUR", cap_date, fx, decision_time=decision_time)
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
    excluded = {r.instrument_id: "invalid_lifecycle_date: the lifecycle cutoff cannot be parsed, so the stock is not shown as active" for r in records if r.invalid_lifecycle}
    records = [record for record in records if not record.invalid_lifecycle and (record.lifecycle_date is None or decision_time.date() <= record.lifecycle_date)]
    cfg = dict(config) if config is not None else store.load_stock_config(root)
    chain = list((cfg.get("sources", {}) or {}).get("chain", ["sec_edgar", "esef", "yfinance"]))
    periods_frame, built = _read_fundamentals(root, chain)
    snapshots = store.read_snapshots(root)
    fx = store.read_fx(root)
    # each frame is grouped by id once (the same rows as a per-id filter of the whole frame)
    periods_rows, snapshot_rows = store.group_rows(periods_frame), store.group_rows(snapshots)
    price_rows = store.group_rows(prices, "etf_id") if prices is not None and not prices.empty and "etf_id" in prices else lambda _iid: prices
    result = UniverseEvidence(decision_time, config=cfg, excluded=excluded)
    user_picks = load_user_peers(root)
    result.user_peers = user_picks
    ids = [r.instrument_id for r in records]
    extra_ids = sorted({p for picks in user_picks.values() for p in picks} - set(ids))
    all_records = list(records) + [StockRecord(f"peer:{p}", p, p, "", "", "") for p in extra_ids]
    first: dict[str, StockEvidence] = {}
    analysts: dict[str, Mapping[str, Any] | None] = {}
    for record in all_records:
        iid = record.instrument_id
        periods = built.get(iid)
        if periods is None:
            periods = built[iid] = store.periods_for(iid, periods_rows(iid), chain)
        snapshot = store.latest_snapshot(iid, snapshot_rows(iid), decision_time)
        analyst = store.latest_analyst(iid, periods_rows(iid), decision_time)
        analysts[iid] = analyst
        reporting = None
        known = sm.known_periods(periods, decision_time)
        if known:
            reporting = known[-1].currency
        if iid.startswith("peer:"):
            frame = pd.DataFrame()
            market = _market_from_snapshot(snapshot, decision_time)
        else:
            frame = _price_frame(price_rows(iid), iid)
            market = market_inputs(frame, snapshot, reporting, decision_time, fx, cfg)
        reason = store.no_data_reason(iid, snapshot_rows(iid), decision_time, bool(known))
        result.snapshots[iid] = snapshot or {}
        result.periods[iid] = known
        result.prices[iid] = market
        result.names[iid] = (snapshot or {}).get("long_name") if iid.startswith("peer:") and snapshot else record.name
        first[iid] = build_stock_evidence(iid, periods, decision_time, market, analyst_inputs(analyst), cfg, no_data_reason=reason)
        result.profiles[iid] = _profile(record, snapshot, fx, cfg, decision_time)
    stale_days = int((cfg.get("reporting", {}) or {}).get("max_balance_staleness_days", 400))
    peer_values = {
        key: {
            iid: ev.metrics[key].value
            for iid, ev in first.items()
            if key in ev.metrics and ev.metrics[key].available and metric_freshness_reason(ev.metrics[key], decision_time, stale_days) is None
        }
        for key in PEER_METRIC_KEYS
    }
    cohort_metrics = {
        key: {
            iid: ev.metrics[key].value
            for iid, ev in first.items()
            if key in ev.metrics and ev.metrics[key].available and metric_freshness_reason(ev.metrics[key], decision_time, stale_days) is None
        }
        for key in COHORT_METRIC_KEYS
    }
    # Non-bank financials are not scored by the industrial ratios, so they must not shape industrial peer cohorts either.
    candidates = [profile for profile in (result.profiles[r.instrument_id] for r in records) if not is_non_bank_financial_sector(getattr(profile, "sector", None))]
    index = PeerIndex(candidates)
    # One cohort per bucket, shared by its members; the stock's own value is in it, and the evidence build skips it.
    cohort_buckets: dict[tuple[str, str] | None, dict[str, dict[str, float]]] = {}
    names = dict(result.names)
    first_order = {pid: position for position, pid in enumerate(first)}
    for record in records:
        iid = record.instrument_id
        profile = result.profiles[iid]
        automatic = auto_peers(profile, index.classified(profile), cfg)
        result.auto_peers[iid] = automatic
        picks = [p if (p in first or p in ids) else f"peer:{p}" for p in user_picks.get(iid, [])]
        chosen = effective_peers(automatic, picks, names, iid)
        result.peers[iid] = chosen
        members = sorted({p.instrument_id for p in chosen} & first_order.keys(), key=first_order.__getitem__)  # peer values are in this order
        scoped = {key: {pid: values[pid] for pid in members if pid in values} for key, values in peer_values.items()}
        periods = built[iid]
        cohorts = {}
        for level in COHORT_LEVELS:
            bucket = index.bucket(level, profile)
            if bucket not in cohort_buckets:
                bucket_ids = [item.instrument_id for item in index.members(level, profile)]
                cohort_buckets[bucket] = {key: {pid: cohort_metrics[key][pid] for pid in bucket_ids if pid in cohort_metrics[key]} for key in COHORT_METRIC_KEYS}
            cohorts[level] = cohort_buckets[bucket]
        result.evidence[iid] = with_sector_route(build_stock_evidence(
            iid, periods, decision_time, result.prices[iid], analyst_inputs(analysts[iid]), cfg,
            peer_values=scoped, cohort_values=cohorts, no_data_reason=store.no_data_reason(iid, snapshot_rows(iid), decision_time, bool(sm.known_periods(periods, decision_time))),
        ), getattr(result.profiles[iid], "sector", None))
    for pid, evidence in first.items():
        if pid.startswith("peer:"):
            result.evidence[pid] = evidence
    return result


def with_sector_route(evidence: StockEvidence, sector: object) -> StockEvidence:
    """Non-bank financials have no fundamentals route: value and quality are unavailable (analyst revision is sector-neutral)."""

    if not is_non_bank_financial_sector(sector):
        return evidence
    unavailable = {}
    for key in ("stock_value", "stock_quality"):
        part = evidence.components[key]
        unavailable[key] = replace(
            part,
            score_10=None,
            inputs=(),
            freshness="unavailable",
            why=f"{part.label}: {SECTOR_ROUTE_MISSING}: non-bank financials have no dedicated fundamentals route yet, "
            "and the generic industrial ratios (ROE, ROIC, net debt/EBITDA, EBIT margin) do not apply to them.",
            band_low=None,
            band_high=None,
            label_stable=None,
            band_basis=None,
        )
    return replace(evidence, components={**evidence.components, **unavailable})


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
_PERIODS: dict[str, Any] = {}  # periods_for per id for one fundamentals file state and chain (in memory only)


def _file_stamp(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return str(path), stat.st_mtime_ns, stat.st_size


def _read_fundamentals(root: Path | None, chain: Sequence[str]) -> tuple[pd.DataFrame, dict[str, list[sm.Period]]]:
    """The fundamentals rows, and the ``periods_for`` results already built from this file state.

    ``periods_for`` has no decision-time input, so later sessions of a run reuse them. They are shared only when the
    file did not change during the read; a new file state starts empty.
    """

    path = store.store_paths(root)["periods"]
    stamp = _file_stamp(path)
    frame = store.read_fundamentals(root)
    if stamp is None or stamp != _file_stamp(path):
        return frame, {}
    key = (stamp, tuple(chain))
    with _LOCK:
        if _PERIODS.get("key") != key:
            _PERIODS.clear()
            _PERIODS.update(key=key, periods={})
        return frame, _PERIODS["periods"]


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
    price_columns = tuple(str(column) for column in prices.columns) if isinstance(prices, pd.DataFrame) else ()
    price_key = columns_key(prices, price_columns) if price_columns and all(isinstance(column, str) for column in prices.columns) else None
    if price_key is None:
        return build_universe_evidence(records, prices, decision_time, root=root)
    key = repr((str(root or ROOT), stamps, config_stamp, repr(records), price_key, decision_time.isoformat()))
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
