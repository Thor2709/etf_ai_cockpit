"""Point-in-time quality-momentum reference strategy evidence.

This module produces ranking evidence only.  It never creates authority or an
order.  Fundamental rows must be complete, point-in-time, official and
sector-labelled; missing or vendor-only inputs remain unavailable.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Literal, Mapping

import pandas as pd

from etf_cockpit.data.fundamentals import assess_fundamental_row, latest_fundamental_rows
from etf_cockpit.features.momentum import momentum


QUALITY_MOMENTUM_VERSION = "quality_momentum.v1"
QUALITY_FIELDS = ("profitability", "leverage", "growth", "shareholder_return")
OFFICIAL_SOURCE_AUTHORITIES = frozenset(
    {"official", "official_filing", "official_regulator", "sec", "sec_edgar", "esef", "issuer", "issuer_document"}
)
FRAME_COLUMNS = (
    "instrument_id",
    "signal_date",
    "fundamental_as_of",
    "fundamental_available_at",
    "sector",
    *QUALITY_FIELDS,
    "quality_score",
    "momentum_score",
    "composite_score",
    "momentum_raw",
    "status",
    "reason",
    "source_id",
    "source_authority",
    "strategy_version",
    "execution_allowed",
)


def build_quality_momentum_frame(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    *,
    as_of_date: date,
    sector_by_instrument: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Build deterministic, sector-neutral scores using only known evidence."""

    signal_date = pd.Timestamp(as_of_date).date()
    sectors = {str(key): str(value).strip() for key, value in (sector_by_instrument or {}).items() if str(value).strip()}
    price_frame = _normalise_prices(prices, signal_date)
    ids = sorted(price_frame["instrument_id"].unique()) if not price_frame.empty else []
    if not ids:
        return _empty_frame(signal_date, "unavailable_missing_adjusted_prices")
    fundamental_rows = _latest_rows(fundamentals, signal_date)
    records: list[dict[str, object]] = []
    for instrument_id in ids:
        history = price_frame.loc[price_frame["instrument_id"] == instrument_id].sort_values("date")
        momentum_raw = _latest_momentum(history)
        row = fundamental_rows.get(instrument_id)
        record: dict[str, object] = {
            "instrument_id": instrument_id,
            "signal_date": signal_date,
            "fundamental_as_of": None,
            "fundamental_available_at": None,
            "sector": sectors.get(instrument_id),
            "quality_score": None,
            "momentum_score": None,
            "composite_score": None,
            "momentum_raw": momentum_raw,
            "status": "unavailable",
            "reason": "unavailable_missing_official_point_in_time_fundamentals",
            "source_id": "unavailable",
            "source_authority": "unavailable",
            "strategy_version": QUALITY_MOMENTUM_VERSION,
            "execution_allowed": False,
        }
        if row is None:
            records.append(record)
            continue
        record["fundamental_as_of"] = str(row.get("as_of_date", row.get("as_of", ""))) or None
        record["fundamental_available_at"] = _text(_availability_value(row))
        record["source_id"] = str(row.get("source_id", "unavailable"))
        record["source_authority"] = str(row.get("source_authority", row.get("source", "unavailable"))).casefold()
        record["sector"] = sectors.get(instrument_id) or _text(row.get("sector")) or _text(row.get("sector_id"))
        execution_allowed = bool(row.get("execution_allowed", row.get("executable_authority", False)))
        record["execution_allowed"] = execution_allowed
        assessment = assess_fundamental_row(row, today=signal_date)
        if row.get("__availability_missing"):
            record["reason"] = "unavailable_missing_official_availability_timestamp"
        elif execution_allowed:
            record["reason"] = "rejected_execution_authority_metadata"
        elif record["source_authority"] not in OFFICIAL_SOURCE_AUTHORITIES:
            record["reason"] = "unavailable_non_official_fundamentals"
        elif not assessment.score_eligible:
            record["reason"] = "unavailable_invalid_or_stale_fundamentals:" + ",".join(assessment.reasons)
        elif not record["sector"]:
            record["reason"] = "unavailable_missing_sector_for_neutralisation"
        elif momentum_raw is None:
            record["reason"] = "unavailable_insufficient_adjusted_price_history"
        else:
            record["reason"] = "pending_sector_neutralisation"
            for field_name in QUALITY_FIELDS:
                record[field_name] = assessment.values.get(field_name)
        records.append(record)

    frame = pd.DataFrame(records)
    if frame.empty:
        return _empty_frame(signal_date, "unavailable_no_instruments")
    pending = frame["reason"] == "pending_sector_neutralisation"
    sector_counts = frame.loc[pending].groupby("sector")["instrument_id"].transform("count")
    singleton_ids = frame.loc[pending].loc[sector_counts < 2, "instrument_id"]
    frame.loc[frame["instrument_id"].isin(singleton_ids), "reason"] = "unavailable_insufficient_sector_peers"
    valid = frame[frame["reason"] == "pending_sector_neutralisation"].copy()
    if not valid.empty:
        for field_name in QUALITY_FIELDS:
            ranks = valid.groupby("sector", sort=True)[field_name].rank(method="average", pct=True)
            if field_name == "leverage":
                ranks = 1.0 - ranks
            valid[f"_{field_name}_rank"] = ranks
        valid["quality_score"] = valid[[f"_{field_name}_rank" for field_name in QUALITY_FIELDS]].mean(axis=1)
        valid["momentum_score"] = valid["momentum_raw"].rank(method="average", pct=True)
        valid["composite_score"] = (valid["quality_score"] + valid["momentum_score"]) / 2.0
        valid["status"] = "available"
        valid["reason"] = "official_point_in_time_sector_neutral_quality_and_canonical_momentum"
        frame = frame.set_index("instrument_id")
        frame.update(valid.set_index("instrument_id"))
        frame = frame.reset_index()
    return frame.reindex(columns=FRAME_COLUMNS).sort_values("instrument_id").reset_index(drop=True)


def quality_momentum_weights(
    evidence: pd.DataFrame,
    instrument_ids: list[str],
    *,
    mode: Literal["quality", "momentum", "quality_momentum"] = "quality_momentum",
) -> pd.Series:
    """Return normalised long-only weights, or all zeroes when evidence fails closed."""

    weights = pd.Series(0.0, index=instrument_ids, dtype=float)
    if evidence.empty:
        return weights
    score_column = {"quality": "quality_score", "momentum": "momentum_score", "quality_momentum": "composite_score"}[mode]
    usable = evidence.loc[evidence["status"] == "available", ["instrument_id", score_column]].copy()
    usable[score_column] = pd.to_numeric(usable[score_column], errors="coerce")
    usable = usable[usable[score_column].notna() & usable[score_column].map(math.isfinite)]
    if usable.empty or float(usable[score_column].sum()) <= 0:
        return weights
    normalised = usable.set_index("instrument_id")[score_column] / float(usable[score_column].sum())
    weights.update(normalised.reindex(weights.index).fillna(0.0))
    return weights


def _normalise_prices(prices: pd.DataFrame, signal_date: date) -> pd.DataFrame:
    required = {"date", "adjusted_close"}
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.DataFrame(columns=["date", "instrument_id", "adjusted_close"])
    id_column = "instrument_id" if "instrument_id" in prices.columns else "etf_id"
    if not required.issubset(prices.columns) or id_column not in prices.columns:
        return pd.DataFrame(columns=["date", "instrument_id", "adjusted_close"])
    frame = prices[["date", id_column, "adjusted_close"]].copy()
    frame = frame.rename(columns={id_column: "instrument_id"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    finite_prices = frame["adjusted_close"].map(
        lambda value: pd.notna(value) and math.isfinite(float(value))
    )
    frame = frame[frame["date"].notna() & (frame["date"] <= signal_date) & finite_prices]
    return frame.sort_values(["instrument_id", "date"]).drop_duplicates(["instrument_id", "date"], keep="last")


def _latest_rows(fundamentals: pd.DataFrame, signal_date: date) -> dict[str, dict[str, object]]:
    if not isinstance(fundamentals, pd.DataFrame) or fundamentals.empty:
        return {}
    frame = fundamentals.copy()
    if "instrument_id" not in frame.columns:
        return {}
    date_column = "as_of_date" if "as_of_date" in frame.columns else "as_of"
    if date_column not in frame.columns:
        return {}
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce").dt.date
    frame = frame[frame[date_column].notna() & (frame[date_column] <= signal_date)].copy()
    if frame.empty:
        return {}
    frame["instrument_id"] = frame["instrument_id"].astype(str)
    availability_column = next(
        (
            column
            for column in ("available_at", "availability_date", "published_at", "publication_date", "filing_date")
            if column in frame.columns
        ),
        None,
    )
    if availability_column is None:
        frame["__availability_date"] = pd.NaT
    else:
        frame["__availability_date"] = pd.to_datetime(
            frame[availability_column], errors="coerce", utc=True
        ).dt.date
    frame["__availability_known"] = frame["__availability_date"].notna() & (
        frame["__availability_date"] <= signal_date
    )
    known = frame.loc[frame["__availability_known"]].copy()
    rows: dict[str, dict[str, object]] = {}
    if not known.empty:
        latest_known = latest_fundamental_rows(known)
        rows.update({str(row["instrument_id"]): row.to_dict() for _, row in latest_known.iterrows()})
    for instrument_id, candidates in frame.groupby("instrument_id", sort=True):
        if str(instrument_id) in rows:
            continue
        latest_any = latest_fundamental_rows(candidates)
        if latest_any.empty:
            continue
        row = latest_any.iloc[-1].to_dict()
        row["__availability_missing"] = True
        rows[str(instrument_id)] = row
    return rows


def _latest_momentum(history: pd.DataFrame) -> float | None:
    if history.empty:
        return None
    price = history.set_index("date")["adjusted_close"].astype(float)
    values = pd.DataFrame({f"momentum_{horizon}d": momentum(price, horizon) for horizon in (20, 60, 120, 180)})
    if values.empty or values.iloc[-1].isna().any():
        return None
    return float((0.15 * values.iloc[-1]["momentum_20d"] + 0.35 * values.iloc[-1]["momentum_60d"] + 0.35 * values.iloc[-1]["momentum_120d"] + 0.15 * values.iloc[-1]["momentum_180d"]))


def _empty_frame(signal_date: date, reason: str) -> pd.DataFrame:
    frame = pd.DataFrame(columns=FRAME_COLUMNS)
    frame.attrs["status"] = reason
    frame.attrs["strategy_version"] = QUALITY_MOMENTUM_VERSION
    frame.attrs["signal_date"] = signal_date.isoformat()
    return frame


def _text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    return text or None


def _availability_value(row: Mapping[str, object]) -> object:
    for column in ("available_at", "availability_date", "published_at", "publication_date", "filing_date"):
        value = row.get(column)
        if _text(value):
            return value
    return row.get("__availability_date")


__all__ = [
    "FRAME_COLUMNS",
    "OFFICIAL_SOURCE_AUTHORITIES",
    "QUALITY_FIELDS",
    "QUALITY_MOMENTUM_VERSION",
    "build_quality_momentum_frame",
    "quality_momentum_weights",
]
