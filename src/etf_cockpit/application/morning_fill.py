"""Session-opens job of the forward paper path (SDD C7): observe the opens that forward fills can need.

The job writes only ``data/validated/prices/session_opens.parquet``: append-only, as an atomic replace of the whole
file (old rows + new rows). It does not wait on the data-jobs mutex. It never fills, orders or touches a ledger; the
nightly execution books each fill from these observations. Paper disabled or the kill switch on means no fetch.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.application.paper_manual_order import load_paper_controls_status
from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.core.config import load_config
from etf_cockpit.core.settings_bundle import load_settings_bundle
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.portfolio.paper_bots_execution import (
    EXECUTION_CONFIG_PATH,
    SESSION_OPENS_RELATIVE,
    _config_file,
    _fill_datetime,
    load_execution_config,
    pending_fill_instruments,
)
from etf_cockpit.portfolio.valuation import expected_session_dates

BENCHMARK_CALENDAR = "XETR"  # the VWCE listing defines the sessions


def _provider(root: Path) -> YFinanceProvider:
    return YFinanceProvider.from_config(load_config(root / "configs"))


def run_morning_fill(root: Path, *, now: datetime | None = None) -> dict[str, object]:
    """Observe today's opens of the pending fill instruments; status ``available``, ``skipped`` or ``failed``."""

    root = Path(root)
    clock = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    session = clock.date()
    result: dict[str, object] = {
        "status": "skipped", "reason": None, "session_date": session.isoformat(), "requested": [], "observed": [],
        "missing": [], "known_at": None, "execution_allowed": False,
    }
    if not load_settings_bundle(root).controls.paper.enabled:
        return {**result, "reason": "paper_disabled"}
    controls = load_paper_controls_status(root, "local-paper")
    if controls.get("status") != "available":
        return {**result, "reason": "paper_controls_unavailable"}
    if controls.get("kill_switch_active") is True:
        return {**result, "reason": "paper_kill_switch_active"}
    _, config = load_execution_config(_config_file(root, "paper_bots_execution_v1.yaml", EXECUTION_CONFIG_PATH))
    if expected_session_dates(session, session, BENCHMARK_CALENDAR).empty:
        return {**result, "reason": "not_a_session"}
    if clock >= _fill_datetime(config, session):
        return {**result, "reason": "fill_time_passed"}
    try:
        ids = pending_fill_instruments(root, clock)
        if not ids:
            return {**result, "reason": "no_pending_instruments"}
        fetched = _provider(root).fetch_prices(ids, session, session + timedelta(days=1))
        known_at = datetime.now(timezone.utc) if now is None else clock  # the values are in hand from here on
        frame = _observations(fetched.data, session, known_at, fetched.provider_name)
        result.update(requested=ids, observed=sorted(frame["instrument_id"]), known_at=known_at.isoformat())
        result["missing"] = sorted(set(ids) - set(frame["instrument_id"]))
        if frame.empty:
            return {**result, "status": "failed", "reason": f"no session bar returned: {str(fetched.message)[:200]}"}
        path = root / SESSION_OPENS_RELATIVE
        combined = pd.concat([pd.read_parquet(path), frame], ignore_index=True) if path.is_file() else frame
        atomic_write_bytes(path, parquet_payload(combined), validate_parquet_file)
    except Exception as exc:  # job boundary: any failure means no observation, reported in the run JSON
        return {**result, "status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {**result, "status": "available", "reason": None if not result["missing"] else str(fetched.message)[:200]}


def _observations(data: pd.DataFrame | None, session: date, known_at: datetime, provider: str) -> pd.DataFrame:
    """One row per instrument bar dated ``session``; bars of any other date are dropped."""

    columns = ["instrument_id", "session_date", "open", "volume", "currency", "dividends", "stock_splits",
               "actions_evidenced", "provider_symbol", "source", "provider", "known_at"]
    if data is None or data.empty:
        return pd.DataFrame(columns=columns)
    bars = data.loc[pd.to_datetime(data["date"]).dt.date == session]
    return pd.DataFrame({
        "instrument_id": bars["etf_id"].astype(str), "session_date": session, "open": bars["open"],
        "volume": bars["volume"], "currency": bars["currency"], "dividends": bars["dividends"],
        "stock_splits": bars["stock_splits"],
        # False when the provider returned no action values for the row.
        "actions_evidenced": bars["dividends"].notna() & bars["stock_splits"].notna(),
        "provider_symbol": bars["provider_symbol"], "source": bars["source"], "provider": provider,
        "known_at": pd.Timestamp(known_at),
    }, columns=columns).reset_index(drop=True)


__all__ = ["run_morning_fill"]
