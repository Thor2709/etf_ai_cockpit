"""Strict UK iShares latest CSV parser; no historical endpoint is inferred.

Only the recon's equity schema is enabled by default. Bond schemas/classes must
be supplied explicitly after verification. Unknown columns, classes and missing
numbers reject the file. ISINs come only from exact configured ticker/exchange
pairs. The next certified business day at 00:00 UTC is the declared publication
lag; collected snapshot reads additionally enforce receipt time. Licensed/manual
history uses its explicitly documented publication time instead of this lag.
Calendar evidence and an explicit instrument master identity are mandatory.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
import math
import re
from typing import Mapping

import pandas as pd

from etf_cockpit.data.fund_holdings import normalise_holdings
from etf_cockpit.data.market_calendar import (
    BusinessDayConvention, ListingCalendarEvidence, MarketCalendarService,
)

COLUMNS = (
    "Ticker", "Name", "Sector", "Asset Class", "Market Value", "Weight (%)",
    "Notional Value", "Shares", "Price", "Location", "Exchange", "Market Currency",
)
OTHER_CLASSES = {"Cash", "FX", "Futures", "Money Market", "Cash Collateral and Margins"}
UTC = timezone.utc


def utc_timestamp(value: object) -> datetime:
    if not isinstance(value, (str, datetime)) or not str(value).strip():
        raise ValueError("timezone-aware timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed.astimezone(UTC)


def next_known_at(as_of: date, listing: ListingCalendarEvidence,
                  calendar: MarketCalendarService | None = None) -> datetime:
    service = calendar or MarketCalendarService()
    # Freeze calendar knowledge at the as-of date rather than use future corrections.
    cutoff = datetime.combine(as_of, time.max, UTC)
    day = service.adjust_business_day(listing, as_of + timedelta(days=1),
                                     BusinessDayConvention.FOLLOWING, knowledge_cutoff=cutoff)
    return datetime.combine(day, time.min, UTC)


def _number(text: str) -> float:
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
        raise ValueError("missing or malformed numeric holding")
    try:
        value = Decimal(text.replace(",", ""))
        result = float(value)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("invalid numeric holding") from exc
    if not value.is_finite() or not math.isfinite(result):
        raise ValueError("nonfinite numeric holding")
    return result


def parse_ishares_csv(payload: bytes, *, instrument_id: str, source_url: str,
                      listing: ListingCalendarEvidence,
                      isin_mapping: Mapping[tuple[str, str], str] | None = None,
                      expected_columns: tuple[str, ...] = COLUMNS,
                      bond_asset_classes: tuple[str, ...] = (),
                      known_at: str | datetime | None = None,
                      calendar: MarketCalendarService | None = None) -> dict:
    if not instrument_id.strip() or listing.instrument_id != instrument_id or not source_url.strip():
        raise ValueError("explicit matching instrument identity and source required")
    if not set(COLUMNS).issubset(expected_columns) or len(set(expected_columns)) != len(expected_columns):
        raise ValueError("invalid configured CSV schema")
    mapping = dict(isin_mapping or {})
    if any(not isinstance(key, tuple) or len(key) != 2 or not all(key)
           or not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value)
           for key, value in mapping.items()):
        raise ValueError("invalid configured ticker/exchange ISIN mapping")
    rows = csv.reader(StringIO(payload.decode("utf-8-sig")), strict=True)
    first = next(rows, [])
    if len(first) != 2 or first[0] != "Fund Holdings as of":
        raise ValueError("not an iShares holdings CSV (HTML/non-CSV rejected)")
    # Explicit English month table avoids dependence on the host's locale.
    match = re.fullmatch(r"(\d{1,2})/([A-Z][a-z]{2})/(\d{4})", first[1])
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    if match is None or match[2] not in months:
        raise ValueError("missing or invalid holdings as-of")
    as_of = date(int(match[3]), months.index(match[2]) + 1, int(match[1]))
    publication = next_known_at(as_of, listing, calendar) if known_at is None else utc_timestamp(known_at)
    if publication < datetime.combine(as_of, time.min, UTC):
        raise ValueError("known_at precedes as_of")
    header = next((row for row in rows if any(cell.strip() for cell in row)), [])
    if tuple(header) != tuple(expected_columns):
        raise ValueError("unverified holdings CSV schema")
    holdings, other = [], []
    for values in rows:
        if not any(cell.strip() for cell in values):
            continue
        if len(values) != len(header):
            raise ValueError("malformed holdings row or unsupported footer")
        raw = dict(zip(header, (cell.strip() for cell in values)))
        asset = raw["Asset Class"]
        if asset not in {"Equity", *bond_asset_classes, *OTHER_CLASSES} or not raw["Name"]:
            raise ValueError("unverified asset class or missing security")
        numbers = {key: _number(raw[key]) for key in COLUMNS[4:9]}
        weight = numbers["Weight (%)"] / 100
        if asset not in OTHER_CLASSES and not 0 <= weight <= 1:
            raise ValueError("invalid security weight")
        isin = mapping.get((raw["Ticker"], raw["Exchange"]))
        row = dict(security=raw["Name"], ticker=raw["Ticker"], exchange=raw["Exchange"],
                   isin=isin, isin_unavailable=isin is None, weight=weight,
                   sector=raw["Sector"], country=raw["Location"], currency=raw["Market Currency"],
                   asset_class=asset, market_value=numbers["Market Value"],
                   notional_value=numbers["Notional Value"], shares=numbers["Shares"], price=numbers["Price"],
                   instrument_id=instrument_id, as_of=as_of.isoformat(), known_at=publication.isoformat(),
                   source="issuer_csv", source_id=source_url, authority="issuer",
                   score_eligible=False, execution_allowed=False)
        (other if asset in OTHER_CLASSES else holdings).append(row)
    if not holdings:
        raise ValueError("no equity or configured bond holdings")
    # Reuse canonical normalisation to determine completeness, without promoting
    # unmapped positions into score inputs or dropping their diagnostic fields.
    equity_weight_total = sum(float(row["weight"]) for row in holdings)
    disclosed_nav_weight = sum(float(row["weight"]) for row in (*holdings, *other))
    validation_holdings = pd.DataFrame(holdings).copy()
    if equity_weight_total > 0 and math.isfinite(disclosed_nav_weight) and disclosed_nav_weight >= 0:
        # Completeness is measured against the full NAV, including cash and
        # derivative positions; keep the published security weights unchanged.
        validation_holdings["weight"] = (
            validation_holdings["weight"] * disclosed_nav_weight / equity_weight_total
        )
    normalised = normalise_holdings(validation_holdings, instrument_id, as_of, "issuer_csv", today=as_of)
    if normalised.completeness == "invalid" or len(normalised.frame) != len(holdings):
        raise ValueError("invalid or duplicate canonical holdings")
    for row in holdings:
        row["completeness"] = normalised.completeness
    return dict(instrument_id=instrument_id, as_of=as_of.isoformat(), known_at=publication.isoformat(),
                holdings=holdings, other_positions=other, execution_allowed=False)
