"""Application commands and local persistence for portfolio valuation history."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload
from etf_cockpit.portfolio.valuation import (
    SNAPSHOT_COLUMNS,
    PortfolioValuationError,
    build_daily_portfolio_snapshots,
    calculate_money_weighted_return,
    link_time_weighted_return,
    summarise_portfolio_valuation_history,
)


def build_portfolio_valuation_history(
    holdings: pd.DataFrame | None,
    prices: pd.DataFrame | None,
    cash_balances: pd.DataFrame | None,
    events: pd.DataFrame | None,
    *,
    decision_time: object = None,
) -> dict[str, object]:
    """Build daily values and expose period/inception performance evidence."""
    try:
        snapshots = build_daily_portfolio_snapshots(
            holdings,
            prices,
            cash_balances,
            events,
            decision_time=decision_time,  # type: ignore[arg-type]
        )
    except PortfolioValuationError as exc:
        report = summarise_portfolio_valuation_history(pd.DataFrame(columns=SNAPSHOT_COLUMNS))
        report["reason"] = str(exc)
        return report
    return summarise_portfolio_valuation_history(snapshots)


def save_portfolio_valuation_history(
    snapshots: pd.DataFrame,
    *,
    storage_root: Path | None = None,
) -> Path:
    """Atomically persist daily snapshots to ``data/analytics`` as Parquet."""
    from etf_cockpit.core.paths import ROOT

    _validate_snapshots(snapshots)
    destination = Path(storage_root or ROOT).resolve() / "data" / "analytics" / "portfolio_valuations.parquet"
    atomic_write_bytes(destination, parquet_payload(snapshots), _validate_parquet_snapshots)
    return destination


def load_portfolio_valuation_history(*, storage_root: Path | None = None) -> dict[str, object]:
    """Load saved daily snapshots and reproduce inception TWR/MWR locally."""
    from etf_cockpit.core.paths import ROOT

    source = Path(storage_root or ROOT).resolve() / "data" / "analytics" / "portfolio_valuations.parquet"
    if not source.is_file():
        report = summarise_portfolio_valuation_history(pd.DataFrame(columns=SNAPSHOT_COLUMNS))
        report["reason"] = "Saved daily portfolio valuation history is unavailable."
        return report
    try:
        snapshots = pd.read_parquet(source)
        _validate_snapshots(snapshots)
    except (OSError, ValueError, TypeError, ImportError) as exc:
        report = summarise_portfolio_valuation_history(pd.DataFrame(columns=SNAPSHOT_COLUMNS))
        report["reason"] = f"Saved daily portfolio valuation history is invalid: {exc}"
        return report
    return summarise_portfolio_valuation_history(snapshots)


def _validate_snapshots(snapshots: pd.DataFrame) -> None:
    if not isinstance(snapshots, pd.DataFrame) or snapshots.columns.duplicated().any():
        raise PortfolioValuationError("Portfolio valuation snapshots are malformed.")
    if not set(SNAPSHOT_COLUMNS).issubset(snapshots.columns):
        raise PortfolioValuationError("Portfolio valuation snapshot fields are incomplete.")
    parsed_dates = pd.to_datetime(snapshots["date"], errors="coerce", utc=True)
    if parsed_dates.isna().any():
        raise PortfolioValuationError("Portfolio valuation dates are invalid.")
    dates = parsed_dates.dt.tz_convert(None).dt.normalize()
    if dates.duplicated().any():
        raise PortfolioValuationError("Portfolio valuation dates must be unique.")
    if not snapshots["execution_allowed"].eq(False).all():
        raise PortfolioValuationError("Portfolio valuation history cannot grant execution authority.")
    valued = snapshots["valuation_status"].eq("available")
    for column in ("cash_value", "securities_value", "total_value"):
        values = pd.to_numeric(snapshots[column], errors="coerce")
        if valued.any() and any(pd.isna(value) or not math.isfinite(float(value)) for value in values.loc[valued]):
            raise PortfolioValuationError(f"Available portfolio valuations must contain finite {column} values.")
    flowing = snapshots["flow_status"].eq("available")
    external_flows = pd.to_numeric(snapshots["external_flow"], errors="coerce")
    if flowing.any() and any(pd.isna(value) or not math.isfinite(float(value)) for value in external_flows.loc[flowing]):
        raise PortfolioValuationError("Available portfolio flow classifications must contain finite flows.")


def _validate_parquet_snapshots(path: Path) -> None:
    frame = pd.read_parquet(path)
    _validate_snapshots(frame)


__all__ = [
    "build_portfolio_valuation_history",
    "calculate_money_weighted_return",
    "link_time_weighted_return",
    "load_portfolio_valuation_history",
    "save_portfolio_valuation_history",
]
