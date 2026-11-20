"""Feature vintages of the forward score run (SDD C9): one append-only file per session for the B1-r panel."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.application.reference_context import _benchmark_reference_snapshot_inputs, _reference_context_from_inputs
from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.core.config import load_config
from etf_cockpit.data.fx_data import load_fx_rates
from etf_cockpit.portfolio.paper_bot_challengers import FX_FILE_RELATIVE, VINTAGE_DIR_RELATIVE, known_prices


def record_feature_observations(
    root: Path, session: date, known_at: datetime, *, run_id: str | None = None, snapshot_hash: str | None = None,
) -> Path | None:
    """Write the features of ``session`` once, stamped ``known_at`` (t_S); None when the file exists or has no rows.

    The features come from the canonical path the score run uses (``FeatureService.compute_features``, publish=False,
    EUR basis, the score run's reference window), fed only with prices and FX rates known by ``known_at``.
    A read or write failure raises; the caller logs it and the run continues (SDD C9).
    """

    root = Path(root)
    path = root / VINTAGE_DIR_RELATIVE / f"{session.isoformat()}.parquet"
    if path.exists():
        return None
    config = load_config(root / "configs")
    context = _reference_context_from_inputs(
        _benchmark_reference_snapshot_inputs(config, session, None), purpose="comparison", analysis_id=f"backfill:{session.isoformat()}",
    )
    prices = known_prices(root, known_at)
    prices = prices.loc[prices["date"] <= session] if not prices.empty else prices
    if prices.empty:
        return None
    # The feature path cuts FX at the session end (S 23:59:59); a rate ingested after t_S is not known at t_S.
    fx = load_fx_rates(root / FX_FILE_RELATIVE)
    if "ingested_at" in fx.columns:
        fx = fx.loc[pd.to_datetime(fx["ingested_at"], utc=True, errors="coerce") <= known_at]
    features = FeatureService(config, reference_context=context, fx_rates=fx).compute_features(
        session, prices, publish=False,
    )
    rows = features.loc[pd.to_datetime(features["date"]).dt.date.eq(session)].copy()
    if rows.empty:
        return None
    stamp = known_at.astimezone(timezone.utc).isoformat()
    rows["instrument_id"] = rows["etf_id"].astype(str)
    rows["date"] = session
    rows["known_at"] = stamp
    rows["available_at"] = stamp
    rows["pit_grade"] = "observed"
    rows["run_id"] = run_id
    rows["snapshot_hash"] = snapshot_hash
    rows.attrs = {}
    atomic_write_bytes(path, parquet_payload(rows.reset_index(drop=True)), validate_parquet_file)
    return path
