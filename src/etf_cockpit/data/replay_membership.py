"""Read-only, knowledge-time-aware listing membership for historical scoring.

The configured watchlist is not listing history. Only listing scopes from the
existing append-only membership store establish eligibility. Intervals are
half-open; prices are never used to invent a delisting date.

Optional, explicit and OFF by default (``survivorship_mode``): a listing may be
derived from an instrument's first available price date (evidence type
``listing_from_price_history``, usable only from the end of that day) so that
instruments with a verified listing but an unverified delisting can be admitted.
Such admissions are always labelled ``survivorship_unverified``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping

import pandas as pd


MEMBERSHIP_POLICY = "replay_listing_membership.v1"
STRICT_MODE = "strict"
UNVERIFIED_DELISTINGS_MODE = "unverified-delistings"
SURVIVORSHIP_MODES = (STRICT_MODE, UNVERIFIED_DELISTINGS_MODE)
PRICE_LISTING_EVIDENCE = "listing_from_price_history"
DELISTING_UNVERIFIED_STATUS = "listed_delisting_unverified"
SURVIVORSHIP_UNVERIFIED_BANNER = (
    "SURVIVORSHIP UNVERIFIED: survivorship-mode unverified-delistings is on; the instruments below have a listing date derived from "
    "their first price but no verified delisting history, so delisted or merged names may be missing and results are biased upward. "
    "Conditional simulation, never forward evidence."
)


@dataclass(frozen=True)
class MembershipSnapshot:
    eligible_ids: tuple[str, ...]
    unverified_ids: tuple[str, ...]
    reasons: dict[str, str]
    fingerprint: str
    delisting_unverified_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListingHistory:
    # Plain records can be sent unchanged to the existing spawn process pool.
    revisions: tuple[dict[str, object], ...] = ()
    captures: tuple[dict[str, object], ...] = ()
    # Listing evidence derived from first price dates; consulted only in survivorship mode "unverified-delistings".
    price_listings: tuple[dict[str, object], ...] = ()
    survivorship_mode: str = STRICT_MODE

    def with_price_history(self, first_dates: Mapping[str, date], survivorship_mode: str = UNVERIFIED_DELISTINGS_MODE) -> ListingHistory:
        """Attach ``listing_from_price_history`` evidence: listed from the first price date, known at the end of that day.

        A delisting is never inferred from a price gap or last price: such instruments stay delisting-unverified.
        """
        if survivorship_mode not in SURVIVORSHIP_MODES:
            raise ValueError(f"Unknown survivorship mode {survivorship_mode!r}")
        records = tuple({
            "evidence_type": PRICE_LISTING_EVIDENCE, "instrument_id": str(key), "valid_from": first.isoformat(), "valid_to": None,
            "known_at": datetime.combine(first, time.max, tzinfo=timezone.utc).isoformat(), "delisting_verified": False,
        } for key, first in sorted(first_dates.items(), key=lambda item: str(item[0])))
        return replace(self, price_listings=records, survivorship_mode=survivorship_mode)

    def _price_listed(self, known_ids: set[str], when: date | datetime) -> set[str]:
        if self.survivorship_mode != UNVERIFIED_DELISTINGS_MODE:
            return set()
        cutoff = _timestamp(when)
        day = cutoff.date().isoformat()
        return {str(row["instrument_id"]) for row in self.price_listings
                if str(row["instrument_id"]) not in known_ids and str(row["valid_from"]) <= day and _timestamp(row["known_at"]) <= cutoff}

    @classmethod
    def from_root(cls, root: Path) -> ListingHistory:
        path = Path(root) / "data/derived/universe_membership/membership.sqlite"
        if not path.is_file():
            return cls()
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported listing membership schema")
            rows = [dict(row) for row in connection.execute(
                "SELECT r.*, c.snapshot_date FROM interval_revisions r "
                "JOIN capture_log c ON c.capture_id=r.capture_id "
                "WHERE r.scope LIKE 'listing:%' AND r.source_kind='self' "
                "ORDER BY r.revision_id"
            )]
            rows.extend({**dict(row), "source_kind": "licensed"} for row in connection.execute(
                "SELECT * FROM licensed_history WHERE scope LIKE 'listing:%' ORDER BY history_id"
            ))
            captures = tuple(dict(row) for row in connection.execute(
                "SELECT scope, snapshot_date, known_at FROM capture_log "
                "WHERE scope LIKE 'listing:%' AND source_kind='self' ORDER BY capture_id"
            ))
            return cls(tuple(rows), captures)
        finally:
            connection.close()

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return tuple(sorted({str(row["instrument_id"]) for row in self.revisions}))

    def intervals_as_of(self, when: date | datetime) -> tuple[dict[str, object], ...]:
        cutoff = _timestamp(when)
        visible = [row for row in self.revisions if _timestamp(row["known_at"]) <= cutoff]
        self_days = {(row["scope"], row["snapshot_date"]) for row in (*self.captures, *visible)
                     if row.get("source_kind", "self") == "self" and _timestamp(row["known_at"]) <= cutoff}
        latest: dict[tuple[str, ...], dict[str, object]] = {}
        for row in sorted(visible, key=lambda item: (
            _timestamp(item["known_at"]), int(item.get("revision_id", item.get("history_id", 0)))
        )):
            if row["source_kind"] == "self":
                key = (str(row["scope"]), "self", str(row["interval_id"]))
            else:
                if (row["scope"], row["snapshot_date"]) in self_days:
                    continue
                # Later licensed revisions of an interval replace its old open
                # end; retaining both would make a delisted name eligible forever.
                key = (str(row["scope"]), "licensed", str(row["instrument_id"]), str(row["valid_from"]))
            latest[key] = row
        return tuple(latest[key] for key in sorted(latest))

    def snapshot(self, when: date | datetime, instrument_ids) -> MembershipSnapshot:
        day = _timestamp(when).date().isoformat()
        intervals = self.intervals_as_of(when)
        known_ids = {str(row["instrument_id"]) for row in intervals}
        closed_through: dict[tuple[str, str], str] = {}
        for row in intervals:
            if row["valid_to"] is not None and str(row["valid_to"]) <= day:
                key = (str(row["scope"]), str(row["instrument_id"]))
                closed_through[key] = max(closed_through.get(key, ""), str(row["valid_to"]))
        active = {str(row["instrument_id"]) for row in intervals if (
            str(row["valid_from"]) <= day and (row["valid_to"] is None or day < str(row["valid_to"]))
            # An old licensed open interval must not resurrect a later captured
            # closure in the same listing scope. A real relisting starts a new interval.
            and str(row["valid_from"]) >= closed_through.get((str(row["scope"]), str(row["instrument_id"])), "")
        )}
        price_listed = self._price_listed(known_ids, when)
        active |= price_listed
        ids = sorted(set(map(str, instrument_ids)))
        unverified = tuple(key for key in ids if key not in known_ids and key not in price_listed)
        delisting_unverified = tuple(key for key in ids if key in price_listed)
        reasons = {key: "survivorship_unverified: no listing history known as of this date" if key in unverified
                   else "outside_listing_interval" for key in ids if key not in active}
        material = {
            "policy": MEMBERSHIP_POLICY, "as_of": _timestamp(when).isoformat(),
            "instruments": ids,
            "intervals": sorted((str(row["scope"]), str(row["instrument_id"]), str(row["valid_from"]),
                                 str(row["valid_to"]), str(row["known_at"])) for row in intervals),
        }
        if self.survivorship_mode == UNVERIFIED_DELISTINGS_MODE:  # strict fingerprints stay byte-identical
            material["survivorship_mode"] = self.survivorship_mode
            material["price_listed"] = sorted(price_listed.intersection(ids))
        fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        return MembershipSnapshot(
            tuple(key for key in ids if key in active), unverified, reasons, fingerprint, delisting_unverified,
        )

    def fingerprint(self) -> str:
        """Invalidate resumable backfills when any membership input changes."""
        extra = (self.survivorship_mode, *self.price_listings) if self.survivorship_mode == UNVERIFIED_DELISTINGS_MODE else ()
        records = [json.dumps(row, sort_keys=True, default=str) for row in (*self.revisions, *self.captures, *extra)]
        return hashlib.sha256(json.dumps(sorted(records)).encode()).hexdigest()

    def delistings(self, cutoff: datetime) -> tuple[tuple[datetime, str, date], ...]:
        """Closure events become actionable only once their revision is known.

        A late capture uses the last pre-delisting price but never backdates cash.
        A closure in one venue does not liquidate a still-listed instrument.
        """
        events = set()
        for row in self.intervals_as_of(cutoff):
            if row["valid_to"] is None:
                continue
            day = date.fromisoformat(str(row["valid_to"]))
            when = max(datetime.combine(day, time.min, tzinfo=timezone.utc), _timestamp(row["known_at"]))
            instrument = str(row["instrument_id"])
            if when <= cutoff and instrument not in self.snapshot(when, [instrument]).eligible_ids:
                events.add((when, instrument, day))
        return tuple(sorted(events))


def unverified_instruments(eligibility: pd.DataFrame) -> list[str]:
    if eligibility.empty or "membership_status" not in eligibility:
        return []
    return sorted(set(eligibility.loc[
        eligibility["membership_status"].eq("survivorship_unverified"), "instrument_id"
    ].astype(str)))


def delisting_unverified_instruments(eligibility: pd.DataFrame) -> list[str]:
    if eligibility.empty or "membership_status" not in eligibility:
        return []
    return sorted(set(eligibility.loc[
        eligibility["membership_status"].eq(DELISTING_UNVERIFIED_STATUS), "instrument_id"
    ].astype(str)))


def delisting_unverified_in_history(history: pd.DataFrame, membership: ListingHistory, cutoff: datetime) -> list[str]:
    """Instruments actually scored on a day where their only listing evidence was the first price date."""
    if membership.survivorship_mode != UNVERIFIED_DELISTINGS_MODE or history.empty:
        return []
    found: set[str] = set()
    known_times = history["run_completed_at"].map(_timestamp)
    for known, rows in history.loc[known_times.le(cutoff)].groupby("run_completed_at", sort=True):
        found.update(membership.snapshot(_timestamp(known), rows["instrument_id"]).delisting_unverified_ids)
    return sorted(found)


def replay_preflight(history: pd.DataFrame, membership: ListingHistory, book, cutoff: datetime) -> str | None:
    """Reject legacy or ineligible scores before writing any replay state."""
    if history.empty:
        return "No backfill history to replay."
    if "run_completed_at" not in history:
        return "Stored scores lack point-in-time knowledge times."
    history = history.loc[history["run_completed_at"].map(_timestamp).le(cutoff)]
    if history.empty:
        return "No backfill history is known at the replay cutoff."
    if "membership_policy" not in history or not history["membership_policy"].eq(MEMBERSHIP_POLICY).all():
        return "Backfill lacks point-in-time listing membership; recompute it before replay."
    if not {"as_of_date", "instrument_id", "run_completed_at"}.issubset(history.columns):
        return "Stored scores lack point-in-time dates or instrument identities."
    for (day, known), rows in history.groupby(["as_of_date", "run_completed_at"], sort=True):
        when = _timestamp(known)
        if when > cutoff:
            continue
        if when.date().isoformat() != str(day):
            return f"Stored score time does not match its replay date on {day}."
        snapshot = membership.snapshot(when, rows["instrument_id"])
        if snapshot.reasons:
            return f"Stored scores violate listing membership on {day}; recompute the backfill."
    first = date.fromisoformat(str(history["as_of_date"].min()))
    for day in book.sessions:
        if first <= day < cutoff.date() and book.benchmark_id not in membership.snapshot(day, [book.benchmark_id]).eligible_ids:
            return f"Benchmark listing membership is unverified or ineligible on {day}."
    return None


class MembershipPriceBook:
    """Apply the listing gate again on the execution session, after score time."""

    def __init__(self, book, membership: ListingHistory):
        self._book = book
        self._membership = membership
        self.membership_fingerprint = membership.fingerprint()

    def __getattr__(self, name):
        return getattr(self._book, name)

    def bar(self, instrument_id: str, day: date):
        # Conservative at session start: a later knowledge time cannot authorise
        # an opening fill. last_bar remains the underlying decision-time source.
        when = datetime.combine(day, time.min, tzinfo=timezone.utc)
        if instrument_id not in self._membership.snapshot(when, [instrument_id]).eligible_ids:
            return None
        return self._book.bar(instrument_id, day)

    def delistings(self, cutoff: datetime):
        return self._membership.delistings(cutoff)

    def liquidation_bar(self, instrument_id: str, delisting_day: date):
        from datetime import timedelta

        return self._book.last_bar(instrument_id, delisting_day - timedelta(days=1))


def _timestamp(value) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("Listing knowledge time must have a timezone")
    return stamp.to_pydatetime().astimezone(timezone.utc)
