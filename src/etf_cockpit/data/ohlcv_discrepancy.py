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


def _to_date(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        ts = pd.to_datetime(value)
        return ts.date()
    except Exception:
        return None


def normalise_ohlcv(
    frame: pd.DataFrame,
    *,
    source: str = "",
    symbol: str = "",
    currency: str = "",
) -> pd.DataFrame:
    """Normalise arbitrary provider OHLCV rows to the canonical cockpit schema.

    Preserves missing values without zero-filling financial prices.
    """
    if frame is None or frame.empty:
        empty_df = pd.DataFrame(columns=list(CANONICAL_OHLCV_COLUMNS))
        return empty_df

    df = frame.copy()

    # Column name mappings across providers
    col_map: dict[str, str] = {
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

    # Rename existing columns
    rename_targets = {c: col_map[c] for c in df.columns if c in col_map}
    df = df.rename(columns=rename_targets)

    # Date normalization
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

    # Numeric conversions (preserving NaN without zero-filling prices)
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = float("nan")

    # Adjusted close
    if "adjusted_close" in df.columns:
        df["adjusted_close"] = pd.to_numeric(df["adjusted_close"], errors="coerce")
    else:
        df["adjusted_close"] = df["close"]

    # Volume (numeric, uncoerced NaN preserved)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    else:
        df["volume"] = float("nan")

    # Split factor (standard default is 1.0 = no split)
    if "split_factor" in df.columns:
        splits = pd.to_numeric(df["split_factor"], errors="coerce").fillna(1.0)
        # In providers like yfinance, 0.0 indicates no split; standard factor is 1.0
        splits = splits.apply(lambda x: 1.0 if x == 0.0 or pd.isna(x) else float(x))
        df["split_factor"] = splits
    else:
        df["split_factor"] = 1.0

    # Dividend (default 0.0 if not reported)
    if "dividend" in df.columns:
        df["dividend"] = pd.to_numeric(df["dividend"], errors="coerce").fillna(0.0)
    else:
        df["dividend"] = 0.0

    # Provider symbol
    inferred_symbol = str(symbol or "").strip()
    if not inferred_symbol and "provider_symbol" in df.columns:
        non_empty = df["provider_symbol"].dropna().astype(str).str.strip()
        if not non_empty.empty:
            inferred_symbol = non_empty.iloc[0]
    df["provider_symbol"] = inferred_symbol

    # Source
    inferred_source = str(source or "").strip()
    if not inferred_source and "source" in df.columns:
        src_series = df["source"].dropna().astype(str).str.strip()
        if not src_series.empty:
            inferred_source = src_series.iloc[0]
    df["source"] = inferred_source

    # Currency
    inferred_currency = str(currency or "").strip()
    if not inferred_currency and "currency" in df.columns:
        curr_series = df["currency"].dropna().astype(str).str.strip()
        if not curr_series.empty:
            inferred_currency = curr_series.iloc[0]
    df["currency"] = inferred_currency

    # is_adjusted flag
    if "is_adjusted" in df.columns:
        df["is_adjusted"] = df["is_adjusted"].astype(bool)
    else:
        # If adjusted_close is explicitly present and diverges or is from adjusted provider
        has_adj = (
            "Adj Close" in frame.columns
            or "adjClose" in frame.columns
            or (df["adjusted_close"] != df["close"]).any()
        )
        df["is_adjusted"] = bool(has_adj)

    # Sort by date ascending
    df = df.sort_values("date").reset_index(drop=True)

    # Select and order canonical columns
    return df[list(CANONICAL_OHLCV_COLUMNS)]


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

    Missing bars are reported and never filled. Higher-confidence series is
    never overwritten or mutated.
    """
    tol_map = dict(DEFAULT_FIELD_TOLERANCES)
    if tolerances:
        tol_map.update(tolerances)

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

    p_by_date = {row["date"]: row for _, row in norm_primary.iterrows() if row["date"] is not None}
    s_by_date = {row["date"]: row for _, row in norm_secondary.iterrows() if row["date"] is not None}

    all_dates = sorted(set(p_by_date.keys()) | set(s_by_date.keys()))
    discrepancies: list[DiscrepancyRow] = []
    missing_primary = 0
    missing_secondary = 0

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

        # 1. Close price
        c_p = row_p.get("close")
        c_s = row_s.get("close")
        if c_p is not None and c_s is not None and not (math.isnan(c_p) or math.isnan(c_s)):
            denom = max(abs(c_p), 1e-9)
            diff_pct = abs(c_p - c_s) / denom
            tol = tol_map.get("close", TOLERANCE_CLOSE_PCT)
            if diff_pct > tol:
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field="close",
                        provider_a=p_source,
                        value_a=c_p,
                        provider_b=s_source,
                        value_b=c_s,
                        diff_pct=round(diff_pct, 6),
                        tolerance=tol,
                        message=f"Close diff {diff_pct:.4%} exceeds tolerance {tol:.4%} on {d} ({p_source}={c_p}, {s_source}={c_s}).",
                    )
                )

        # 2. Adjusted close price
        ac_p = row_p.get("adjusted_close")
        ac_s = row_s.get("adjusted_close")
        if ac_p is not None and ac_s is not None and not (math.isnan(ac_p) or math.isnan(ac_s)):
            denom = max(abs(ac_p), 1e-9)
            diff_pct = abs(ac_p - ac_s) / denom
            tol = tol_map.get("adjusted_close", TOLERANCE_ADJUSTED_CLOSE_PCT)
            if diff_pct > tol:
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field="adjusted_close",
                        provider_a=p_source,
                        value_a=ac_p,
                        provider_b=s_source,
                        value_b=ac_s,
                        diff_pct=round(diff_pct, 6),
                        tolerance=tol,
                        message=f"Adjusted close diff {diff_pct:.4%} exceeds tolerance {tol:.4%} on {d}.",
                    )
                )

        # 3. Volume
        v_p = row_p.get("volume")
        v_s = row_s.get("volume")
        if v_p is not None and v_s is not None and not (math.isnan(v_p) or math.isnan(v_s)):
            denom = max(abs(v_p), 1.0)
            diff_pct = abs(v_p - v_s) / denom
            tol = tol_map.get("volume", TOLERANCE_VOLUME_PCT)
            if diff_pct > tol:
                discrepancies.append(
                    DiscrepancyRow(
                        symbol=sym,
                        date=d,
                        field="volume",
                        provider_a=p_source,
                        value_a=v_p,
                        provider_b=s_source,
                        value_b=v_s,
                        diff_pct=round(diff_pct, 6),
                        tolerance=tol,
                        message=f"Volume diff {diff_pct:.4%} exceeds tolerance {tol:.4%} on {d}.",
                    )
                )

        # 4. Split factor
        sf_p = float(row_p.get("split_factor") or 1.0)
        sf_s = float(row_s.get("split_factor") or 1.0)
        tol_split = tol_map.get("split_factor", TOLERANCE_SPLIT_FACTOR)
        if abs(sf_p - sf_s) > tol_split:
            discrepancies.append(
                DiscrepancyRow(
                    symbol=sym,
                    date=d,
                    field="split_factor",
                    provider_a=p_source,
                    value_a=sf_p,
                    provider_b=s_source,
                    value_b=sf_s,
                    tolerance=tol_split,
                    message=f"Split factor mismatch on {d}: {p_source}={sf_p} vs {s_source}={sf_s}.",
                )
            )

        # 5. Currency
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
