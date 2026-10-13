"""OHLCV schema normalisation, discrepancy reporting and candle quality cap.

This module provides canonical OHLCV normalization across heterogeneous
providers (yfinance, Stooq, Twelve Data, Tiingo, manual CSV/Parquet),
detects cross-provider discrepancies on a per-symbol and per-date basis,
and exposes a candle quality cap function for downstream evidence gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any

import numpy as np
import pandas as pd

from etf_cockpit.data.contracts import redact_text

CANONICAL_OHLCV_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "split_factor",
    "dividend",
    "currency",
    "provider_symbol",
    "source",
    "is_adjusted",
)

# Per-field tolerances for discrepancy detection (module constants)
TOLERANCE_CLOSE_PCT: float = 0.005  # 0.5% tolerance on unadjusted close
TOLERANCE_ADJUSTED_CLOSE_PCT: float = 0.005  # 0.5% tolerance on adjusted close
TOLERANCE_VOLUME_PCT: float = 0.05  # 5.0% tolerance on trading volume
TOLERANCE_SPLIT_FACTOR: float = 0.001  # Absolute tolerance on split ratio
TOLERANCE_DIVIDEND: float = 0.01  # Absolute tolerance on dividend amount

DEFAULT_FIELD_TOLERANCES: dict[str, float] = {
    "close": TOLERANCE_CLOSE_PCT,
    "adjusted_close": TOLERANCE_ADJUSTED_CLOSE_PCT,
    "volume": TOLERANCE_VOLUME_PCT,
    "split_factor": TOLERANCE_SPLIT_FACTOR,
    "dividend": TOLERANCE_DIVIDEND,
}


class OhlcvNormalisationError(ValueError):
    """Raised when provider rows cannot be normalised without inventing or merging facts."""


_TRUE_FLAGS = frozenset({"true", "t", "yes", "y", "1", "1.0"})
_FALSE_FLAGS = frozenset({"false", "f", "no", "n", "0", "0.0"})

_COLUMN_ALIASES: dict[str, str] = {
    "Date": "date",
    "datetime": "date",
    "timestamp": "date",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Adj Close": "adjusted_close",
    "adjClose": "adjusted_close",
    "adj_close": "adjusted_close",
    "splitFactor": "split_factor",
    "Stock Splits": "split_factor",
    "stock_splits": "split_factor",
    "splits": "split_factor",
    "divCash": "dividend",
    "Dividends": "dividend",
    "dividends": "dividend",
    "Currency": "currency",
    "provider_symbol": "provider_symbol",
    "ticker": "provider_symbol",
    "etf_id": "provider_symbol",
}


def _to_date(value: object) -> date | pd.Timestamp | None:
    """Return a calendar date for daily stamps; keep the time (UTC) when one is present."""

    if value is None:
        return None
    try:
        if pd.isna(value):  # type: ignore[call-overload]
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        ts = pd.to_datetime(value)
    except Exception:
        return None
    if not isinstance(ts, pd.Timestamp) or pd.isna(ts):
        return None
    if ts == ts.normalize():
        return ts.date()
    return ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")


def _parse_flag(value: object) -> bool | None:
    """Parse a provider boolean flag; anything unrecognised or missing is unknown (None)."""

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        return True if text in _TRUE_FLAGS else False if text in _FALSE_FLAGS else None
    try:
        if pd.isna(value):  # type: ignore[call-overload]
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, (int, float, np.number)):
        return True if value == 1 else False if value == 0 else None
    return None


def _identity_column(frame: pd.DataFrame, column: str, explicit: str, label: str) -> pd.Series:
    """Per-row identity; mixed values block instead of being broadcast from the first row."""

    given = explicit.strip()
    if column not in frame.columns:
        return pd.Series(given, index=frame.index, dtype=object)
    cleaned = frame[column].map(lambda v: "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip())
    distinct = {item.upper() for item in cleaned if item}
    if given and label == "currency":
        distinct.add(given.upper())
    if len(distinct) > 1:
        raise OhlcvNormalisationError(f"mixed {label} values in one series: {sorted(distinct)}")
    if label == "provider_symbol" and given:
        return pd.Series(given, index=frame.index, dtype=object)
    return cleaned.where(cleaned != "", given).astype(object)


def normalise_ohlcv(
    frame: pd.DataFrame,
    *,
    source: str = "",
    symbol: str = "",
    currency: str = "",
) -> pd.DataFrame:
    """Normalise arbitrary provider OHLCV rows to the canonical cockpit schema.

    Preserves missing values without zero-filling financial prices. A missing
    adjusted close stays missing (raw close is never substituted); intraday
    timestamps are kept; mixed currency/instrument identities, alias collisions
    and conflicting same-date rows raise :class:`OhlcvNormalisationError`.
    """
    if frame is None or frame.empty:
        empty_df = pd.DataFrame(columns=list(CANONICAL_OHLCV_COLUMNS))
        return empty_df

    df = frame.copy()

    # Rename provider columns; several source columns for one target must agree.
    targets = [_COLUMN_ALIASES.get(str(c), c) for c in df.columns]
    first_position: dict[object, int] = {}
    keep: list[int] = []
    for position, target in enumerate(targets):
        if target in first_position:
            left = df.iloc[:, first_position[target]].reset_index(drop=True)
            right = df.iloc[:, position].reset_index(drop=True)
            if not left.equals(right):
                raise OhlcvNormalisationError(f"conflicting source columns map to '{target}'")
            continue
        first_position[target] = position
        keep.append(position)
    df = df.iloc[:, keep].copy()
    df.columns = [targets[position] for position in keep]

    # Date normalization (intraday time of day is kept)
    if "date" in df.columns:
        df["date"] = df["date"].apply(_to_date)
    else:
        # Check index if date is not in columns
        if isinstance(df.index, (pd.DatetimeIndex, pd.Index)):
            df["date"] = [ _to_date(i) for i in df.index ]
        else:
            df["date"] = None

    # Filter out rows with invalid dates
    df = df.dropna(subset=["date"])
    if any(isinstance(item, pd.Timestamp) for item in df["date"]):
        # Mixed daily/intraday stamps stay comparable as UTC timestamps.
        df["date"] = df["date"].apply(lambda item: item if isinstance(item, pd.Timestamp) else pd.Timestamp(item).tz_localize("UTC"))

    # Numeric conversions (preserving NaN without zero-filling prices)
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = float("nan")

    # Adjusted close: absent stays missing; raw close is never substituted.
    if "adjusted_close" in df.columns:
        df["adjusted_close"] = pd.to_numeric(df["adjusted_close"], errors="coerce")
    else:
        df["adjusted_close"] = float("nan")

    # Volume (numeric, uncoerced NaN preserved)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    else:
        df["volume"] = float("nan")

    # Source
    inferred_source = str(source or "").strip()
    if not inferred_source and "source" in df.columns:
        src_series = df["source"].dropna().astype(str).str.strip()
        if not src_series.empty:
            inferred_source = src_series.iloc[0]
    df["source"] = inferred_source

    # Split factor: preserve missing values (NaN) without zero-filling.
    # Translate only explicit provider 'no event' encodings under provider-specific rules.
    if "split_factor" in df.columns:
        raw_splits = pd.to_numeric(df["split_factor"], errors="coerce")
        is_yfinance = (
            "yfinance" in inferred_source.lower()
            or "Stock Splits" in frame.columns
            or "stock_splits" in frame.columns
        )
        if is_yfinance:
            # yfinance encodes 'no split event' explicitly as 0.0, corresponding to ratio 1.0
            raw_splits = raw_splits.apply(
                lambda x: 1.0 if pd.notna(x) and float(x) == 0.0 else (float(x) if pd.notna(x) else float("nan"))
            )
        df["split_factor"] = raw_splits
    else:
        df["split_factor"] = float("nan")

    # Dividend: preserve missing values (NaN) without zero-filling.
    # Explicit provider reported dividends (including 0.0) are preserved; missing values remain NaN.
    if "dividend" in df.columns:
        df["dividend"] = pd.to_numeric(df["dividend"], errors="coerce")
    else:
        df["dividend"] = float("nan")

    # Identity: per row, never broadcast from the first row.
    df["provider_symbol"] = _identity_column(df, "provider_symbol", str(symbol or ""), "provider_symbol")
    df["currency"] = _identity_column(df, "currency", str(currency or ""), "currency")

    # is_adjusted flag: strings such as 'False' parse as False; missing/unrecognised flags are unknown.
    if "is_adjusted" in df.columns:
        flags = [_parse_flag(item) for item in df["is_adjusted"]]
        if any(item is None for item in flags):
            df["is_adjusted"] = pd.array(flags, dtype="boolean")
        else:
            df["is_adjusted"] = pd.Series(flags, index=df.index, dtype=bool)
    else:
        has_adj = (
            "Adj Close" in frame.columns
            or "adjClose" in frame.columns
            or bool(((df["adjusted_close"] != df["close"]) & df["adjusted_close"].notna() & df["close"].notna()).any())
        )
        df["is_adjusted"] = bool(has_adj)

    # Same-date rows: identical rows collapse, conflicting rows block (never overwritten).
    canonical = df[list(CANONICAL_OHLCV_COLUMNS)].copy()
    canonical = canonical.drop_duplicates()
    if canonical["date"].duplicated().any():
        clash = sorted({str(item) for item in canonical.loc[canonical["date"].duplicated(keep=False), "date"]})
        raise OhlcvNormalisationError(f"conflicting rows for the same timestamp: {clash[:3]}")

    # Sort by date ascending
    return canonical.sort_values("date").reset_index(drop=True)


@dataclass(frozen=True)
class DiscrepancyRow:
    """Detailed record of a discrepancy between two providers for a symbol and date."""

    symbol: str
    date: date
    field: str  # "close", "adjusted_close", "volume", "split_factor", "currency", "missing_bar"
    provider_a: str
    value_a: Any
    provider_b: str
    value_b: Any
    diff_pct: float | None = None
    tolerance: float | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "date": self.date.isoformat(),
            "field": self.field,
            "provider_a": self.provider_a,
            "value_a": self.value_a,
            "provider_b": self.provider_b,
            "value_b": self.value_b,
            "diff_pct": self.diff_pct,
            "tolerance": self.tolerance,
            "message": redact_text(self.message),
        }


def compute_candle_quality_cap(
    discrepancies: Sequence[DiscrepancyRow],
    total_dates: int = 1,
) -> float:
    """Compute a numeric candle quality cap (0.0 to 1.0) from discrepancies.

    Returns 1.0 when there are zero discrepancies. Disagreements, missing bars,
    or split mismatches reduce the cap proportionally.
    """
    if not discrepancies:
        return 1.0

    safe_total = max(1, total_dates)
    unique_dates = {d.date for d in discrepancies}
    date_ratio = min(1.0, len(unique_dates) / safe_total)

    penalty = 0.0
    for disc in discrepancies:
        if disc.field == "split_factor":
            penalty += 0.30
        elif disc.field in {"close", "adjusted_close"}:
            penalty += 0.15
        elif disc.field == "missing_bar":
            penalty += 0.10
        elif disc.field == "currency":
            penalty += 0.15
        elif disc.field == "volume":
            penalty += 0.05
        else:
            penalty += 0.05

    # Scale with fraction of affected dates
    reduction = min(1.0, max(0.05, penalty * max(0.5, date_ratio)))
    cap = round(max(0.0, 1.0 - reduction), 4)

    # Invariant: any detected discrepancy strictly lowers cap below 1.0
    if cap >= 1.0:
        cap = 0.95
    return cap


@dataclass(frozen=True)
class DiscrepancyReport:
    """Structured report comparing two OHLCV provider series."""

    symbol: str
    primary_provider: str
    secondary_provider: str
    discrepancies: tuple[DiscrepancyRow, ...]
    quality_cap: float
    total_dates_compared: int
    missing_bars_primary: int
    missing_bars_secondary: int
    primary_series: pd.DataFrame
    secondary_series: pd.DataFrame

    @property
    def has_discrepancies(self) -> bool:
        return len(self.discrepancies) > 0

    @property
    def candle_quality_cap(self) -> float:
        return self.quality_cap

    @property
    def discrepancy_rows(self) -> tuple[DiscrepancyRow, ...]:
        return self.discrepancies

    def to_dataframe(self) -> pd.DataFrame:
        if not self.discrepancies:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "date",
                    "field",
                    "provider_a",
                    "value_a",
                    "provider_b",
                    "value_b",
                    "diff_pct",
                    "tolerance",
                    "message",
                ]
            )
        return pd.DataFrame([d.to_dict() for d in self.discrepancies])


_RELATIVE_FIELDS: frozenset[str] = frozenset({"close", "adjusted_close", "volume"})
_COUNTERPART_FIELDS: tuple[str, ...] = ("close", "adjusted_close", "volume")


def _validated_tolerances(tolerances: Mapping[str, float] | None) -> dict[str, float]:
    """Merge custom tolerances over the defaults, rejecting values that would silence or break checks."""

    tol_map = dict(DEFAULT_FIELD_TOLERANCES)
    for name, value in (tolerances or {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"tolerance for '{name}' must be a finite non-negative number, got {value!r}")
        if name in _RELATIVE_FIELDS and value >= 1.0:
            raise ValueError(f"relative tolerance for '{name}' must be below 1.0 (100%), got {value!r}")
        tol_map[name] = float(value)
    return tol_map


def _is_missing(value: object) -> bool:
    return value is None or bool(pd.isna(value))  # type: ignore[call-overload]


def _align_keys(frames: Sequence[pd.DataFrame]) -> list[pd.DataFrame]:
    """Make daily dates and intraday timestamps comparable when a series mixes both."""

    if not any(isinstance(item, pd.Timestamp) for frame in frames for item in frame["date"]):
        return list(frames)
    aligned = []
    for frame in frames:
        copy = frame.copy()
        copy["date"] = copy["date"].apply(lambda item: item if isinstance(item, pd.Timestamp) else pd.Timestamp(item).tz_localize("UTC"))
        aligned.append(copy)
    return aligned


def build_discrepancy_report(
    primary: pd.DataFrame,
    secondary: pd.DataFrame,
    *,
    symbol: str = "",
    primary_name: str = "",
    secondary_name: str = "",
    tolerances: Mapping[str, float] | None = None,
) -> DiscrepancyReport:
    """Compare two provider series per symbol and date.

    Missing bars and missing field counterparts are reported and never filled.
    Relative differences are symmetric in the two providers, non-finite values
    always count as discrepancies, and unsafe custom tolerances are rejected.
    Higher-confidence series is never overwritten or mutated.
    """
    tol_map = _validated_tolerances(tolerances)

    norm_primary = normalise_ohlcv(primary, source=primary_name, symbol=symbol)
    norm_secondary = normalise_ohlcv(secondary, source=secondary_name, symbol=symbol)

    p_source = (
        primary_name
        or (str(norm_primary["source"].iloc[0]) if not norm_primary.empty and norm_primary["source"].iloc[0] else "primary")
    )
    s_source = (
        secondary_name
        or (str(norm_secondary["source"].iloc[0]) if not norm_secondary.empty and norm_secondary["source"].iloc[0] else "secondary")
    )

    sym = (
        symbol
        or (str(norm_primary["provider_symbol"].iloc[0]) if not norm_primary.empty and norm_primary["provider_symbol"].iloc[0] else "")
        or (str(norm_secondary["provider_symbol"].iloc[0]) if not norm_secondary.empty and norm_secondary["provider_symbol"].iloc[0] else "unknown")
    )

    keyed_primary, keyed_secondary = (
        _align_keys((norm_primary, norm_secondary)) if not norm_primary.empty and not norm_secondary.empty else (norm_primary, norm_secondary)
    )
    p_by_date = {row["date"]: row for _, row in keyed_primary.iterrows() if row["date"] is not None}
    s_by_date = {row["date"]: row for _, row in keyed_secondary.iterrows() if row["date"] is not None}

    all_dates = sorted(set(p_by_date.keys()) | set(s_by_date.keys()))
    discrepancies: list[DiscrepancyRow] = []
    missing_primary = 0
    missing_secondary = 0

    # A field one provider never supplies is reported once, not once per bar.
    absent_fields: dict[str, str] = {}
    for name in _COUNTERPART_FIELDS:
        p_absent = bool(norm_primary.empty or norm_primary[name].isna().all())
        s_absent = bool(norm_secondary.empty or norm_secondary[name].isna().all())
        if p_absent != s_absent and all_dates:
            absent_fields[name] = p_source if p_absent else s_source
            discrepancies.append(
                DiscrepancyRow(
                    symbol=sym,
                    date=all_dates[0],
                    field="missing_field",
                    provider_a=p_source,
                    value_a=None if p_absent else name,
                    provider_b=s_source,
                    value_b=None if s_absent else name,
                    message=f"Field {name} is not provided by {absent_fields[name]}; it cannot be compared.",
                )
            )

    for d in all_dates:
        row_p = p_by_date.get(d)
        row_s = s_by_date.get(d)

        # Missing bar checks (reported, never filled)
        if row_p is None:
            missing_primary += 1
            discrepancies.append(
                DiscrepancyRow(
                    symbol=sym,
                    date=d,
                    field="missing_bar",
                    provider_a=p_source,
                    value_a=None,
                    provider_b=s_source,
                    value_b=f"present (close={row_s['close']})",
                    message=f"Date {d} present in {s_source} but missing in primary {p_source}.",
                )
            )
            continue

        if row_s is None:
            missing_secondary += 1
            discrepancies.append(
                DiscrepancyRow(
                    symbol=sym,
                    date=d,
                    field="missing_bar",
                    provider_a=p_source,
                    value_a=f"present (close={row_p['close']})",
                    provider_b=s_source,
                    value_b=None,
                    message=f"Date {d} present in primary {p_source} but missing in {s_source}.",
                )
            )
            continue

        # Both rows present: compare fields against tolerances

        # 1-3. Close, adjusted close, volume (symmetric relative difference)
        for name, label, floor in (("close", "Close", 1e-9), ("adjusted_close", "Adjusted close", 1e-9), ("volume", "Volume", 1.0)):
            v_p = row_p.get(name)
            v_s = row_s.get(name)
            p_missing = _is_missing(v_p)
            s_missing = _is_missing(v_s)
            tol = tol_map.get(name, DEFAULT_FIELD_TOLERANCES[name])
            if p_missing and s_missing:
                continue
            if p_missing or s_missing:
                if name not in absent_fields:
                    discrepancies.append(
                        DiscrepancyRow(
                            symbol=sym,
                            date=d,
                            field="missing_field",
                            provider_a=p_source,
                            value_a=None if p_missing else v_p,
                            provider_b=s_source,
                            value_b=None if s_missing else v_s,
                            message=f"{label} reported by only one provider on {d} ({p_source}={v_p}, {s_source}={v_s}).",
                        )
                    )
                continue
            if not (math.isfinite(v_p) and math.isfinite(v_s)):
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field=name,
                        provider_a=p_source,
                        value_a=v_p,
                        provider_b=s_source,
                        value_b=v_s,
                        tolerance=tol,
                        message=f"{label} is non-finite on {d} ({p_source}={v_p}, {s_source}={v_s}).",
                    )
                )
                continue
            diff_pct = abs(v_p - v_s) / max(abs(v_p), abs(v_s), floor)
            if diff_pct > tol:
                suffix = f" ({p_source}={v_p}, {s_source}={v_s})" if name == "close" else ""
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field=name,
                        provider_a=p_source,
                        value_a=v_p,
                        provider_b=s_source,
                        value_b=v_s,
                        diff_pct=round(diff_pct, 6),
                        tolerance=tol,
                        message=f"{label} diff {diff_pct:.4%} exceeds tolerance {tol:.4%} on {d}{suffix}.",
                    )
                )

        # 4. Split factor (compared when both providers report observations)
        sf_p = row_p.get("split_factor")
        sf_s = row_s.get("split_factor")
        if sf_p is not None and sf_s is not None and pd.notna(sf_p) and pd.notna(sf_s):
            sf_p_val = float(sf_p)
            sf_s_val = float(sf_s)
            tol_split = tol_map.get("split_factor", TOLERANCE_SPLIT_FACTOR)
            if not (math.isfinite(sf_p_val) and math.isfinite(sf_s_val)) or abs(sf_p_val - sf_s_val) > tol_split:
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field="split_factor",
                        provider_a=p_source,
                        value_a=sf_p_val,
                        provider_b=s_source,
                        value_b=sf_s_val,
                        tolerance=tol_split,
                        message=f"Split factor mismatch on {d}: {p_source}={sf_p_val} vs {s_source}={sf_s_val}.",
                    )
                )

        # 5. Dividend (compared when both providers report observations)
        div_p = row_p.get("dividend")
        div_s = row_s.get("dividend")
        if div_p is not None and div_s is not None and pd.notna(div_p) and pd.notna(div_s):
            div_p_val = float(div_p)
            div_s_val = float(div_s)
            tol_div = tol_map.get("dividend", TOLERANCE_DIVIDEND)
            if not (math.isfinite(div_p_val) and math.isfinite(div_s_val)) or abs(div_p_val - div_s_val) > tol_div:
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field="dividend",
                        provider_a=p_source,
                        value_a=div_p_val,
                        provider_b=s_source,
                        value_b=div_s_val,
                        tolerance=tol_div,
                        message=f"Dividend mismatch on {d}: {p_source}={div_p_val} vs {s_source}={div_s_val}.",
                    )
                )

        # 6. Currency
        curr_p = str(row_p.get("currency") or "").strip().upper()
        curr_s = str(row_s.get("currency") or "").strip().upper()
        if curr_p and curr_s and curr_p != curr_s:
            discrepancies.append(
                DiscrepancyRow(
                    symbol=sym,
                    date=d,
                    field="currency",
                    provider_a=p_source,
                    value_a=curr_p,
                    provider_b=s_source,
                    value_b=curr_s,
                    message=f"Currency mismatch on {d}: {p_source}={curr_p} vs {s_source}={curr_s}.",
                )
            )

    cap = compute_candle_quality_cap(discrepancies, total_dates=len(all_dates))

    return DiscrepancyReport(
        symbol=sym,
        primary_provider=p_source,
        secondary_provider=s_source,
        discrepancies=tuple(discrepancies),
        quality_cap=cap,
        total_dates_compared=len(all_dates),
        missing_bars_primary=missing_primary,
        missing_bars_secondary=missing_secondary,
        primary_series=norm_primary.copy(),
        secondary_series=norm_secondary.copy(),
    )
