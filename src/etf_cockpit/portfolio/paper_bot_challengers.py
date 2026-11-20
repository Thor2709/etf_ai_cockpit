"""Challenger inputs for the forward paper run (SDD C6): the B2-o weight engine and the B1-r ranker scores.

Both read only rows known at or before the cut-off. Missing optional packages leave the input unavailable: without
skfolio the ``sk_min_cvar`` key is absent; ``gbdt_rank_63`` is always present, as scores or ``{}``.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.core.pandas_values import bool_like_or_none
from etf_cockpit.data.fx_data import load_fx_rates
from etf_cockpit.features.feature_observations import FX_FILE_RELATIVE, VINTAGE_DIR_RELATIVE, known_prices
from etf_cockpit.features.feature_pipeline import eur_basis_prices
from etf_cockpit.features.feature_store import BUILTIN_FEATURES, FeatureStoreError, LocalFeatureStore
from etf_cockpit.features.panel import PanelContractError, PITPanelInputs, build_pit_panel
from etf_cockpit.models import cross_sectional_ranker as ranker
from etf_cockpit.portfolio import paper_bots as bots
from etf_cockpit.validation.protocol import ValidationSpec

_SCOPE = "listing:sp500:all"
_HORIZON = 63
# The builtin price features, registered under vintage ids: the store does not materialise builtin ids by name.
_FEATURES = tuple(
    replace(item, feature_id=f"vintage.{item.feature_id}", source_dataset="feature_vintages") for item in BUILTIN_FEATURES
)
_FEATURE_IDS = tuple(item.feature_id for item in _FEATURES)
# Folds count decision dates (one per forward run); the purge covers the 63-session label.
_RANKER_SPEC = ValidationSpec(horizon=_HORIZON)


def build_challenger_engines(root: Path, cutoff: datetime) -> tuple[dict[str, object], dict[str, object]]:
    """(engines, report): the ``challenger_engines`` mapping for ``run_paper_bots`` and its state for the run JSON."""

    root = Path(root)
    prices = _eur_adjusted_prices(root, cutoff)
    engines: dict[str, object] = {}
    report: dict[str, object] = {}
    if find_spec("skfolio") is None:
        report[bots._OPTIMISER_ENGINE_NAME] = {"status": "unavailable", "reason": "skfolio is not installed"}
    else:
        engines[bots._OPTIMISER_ENGINE_NAME] = bots.optimiser_challenger_engine(prices)
        report[bots._OPTIMISER_ENGINE_NAME] = {"status": "available"}
    engines[bots._RANKER_SELECTOR], report[bots._RANKER_SELECTOR] = _ranker_scores(root, cutoff, prices)
    return engines, report


def _eur_adjusted_prices(root: Path, cutoff: datetime) -> pd.DataFrame:
    """Adjusted rows known by the cut-off, in EUR; a session without an FX rate drops out (never zero-filled)."""

    frame = known_prices(root, cutoff)
    if frame.empty or "is_adjusted" not in frame.columns:
        return frame.iloc[0:0]
    frame = frame.loc[frame["is_adjusted"].map(bool_like_or_none).eq(True)]
    configured = {item.id: item.currency for item in load_config(root / "configs").universe.etfs}
    eur = eur_basis_prices(frame, load_fx_rates(root / FX_FILE_RELATIVE), configured_currency=configured, known_by=cutoff).frame
    return eur.dropna(subset=["adjusted_close"]).assign(currency="EUR")


def _ranker_scores(root: Path, cutoff: datetime, prices: pd.DataFrame) -> tuple[dict[str, float], dict[str, object]]:
    """B1-r: fit on the PIT panel of all feature vintages known by the cut-off, score the latest decision."""

    if not ranker.is_available():
        return {}, {"status": "unavailable", "preflight": ["lightgbm is not installed"]}
    vintages = _vintages(root, cutoff)
    if vintages.empty:
        return {}, {"status": "insufficient_evidence", "preflight": ["no feature vintage is known by the cut-off"]}
    panel_prices = prices.rename(columns={"etf_id": "instrument_id"})
    benchmark = panel_prices if panel_prices.empty else panel_prices.loc[panel_prices["instrument_id"].astype(str).eq("VWCE")]
    store = LocalFeatureStore(root)
    try:
        for definition in _FEATURES:
            store.register_feature(definition)
        panel = build_pit_panel(
            sorted(set(vintages["known_at"])), _SCOPE, _FEATURE_IDS, horizons=(_HORIZON,),
            inputs=PITPanelInputs(store, vintages, panel_prices, benchmark),
        )
    except FeatureStoreError as error:
        return {}, {"status": "unavailable", "preflight": [f"feature store: {error}"]}
    except PanelContractError as error:
        return {}, {"status": "insufficient_evidence", "preflight": [str(error)]}
    decisions = pd.to_datetime(panel["decision_time"], format="mixed", utc=True)
    # The store takes the latest row at or before each decision; a row from an older vintage (an instrument missing
    # from that night's vintage) is not that decision's observation, so it neither trains nor scores.
    stamps = pd.to_datetime(panel["feature_vintages_available_at"], format="mixed", utc=True, errors="coerce")
    panel.loc[~stamps.eq(decisions), list(_FEATURE_IDS)] = None
    latest = decisions.max()
    report: dict[str, object] = {"decision_time": latest.isoformat()}
    # Tonight's decision only: a failed capture or vintage write on this night must not send older ranks out.
    day = cutoff.astimezone(timezone.utc).date()
    if latest.date() != day:
        return {}, {**report, "status": "unavailable", "preflight": [f"latest decision {latest.date()} is not on the cut-off day {day}"]}
    outcome = ranker.fit(panel, _RANKER_SPEC, horizon=_HORIZON, feature_ids=_FEATURE_IDS)
    if outcome.artefact is None:
        return {}, {**report, "status": outcome.status, "preflight": outcome.reason.split("; ")}
    rows = panel.loc[decisions.eq(latest)]
    scores = {
        str(instrument): float(value)
        for instrument, value in zip(rows["instrument_id"], ranker.score(outcome.artefact, rows))
        if math.isfinite(value)
    }
    return scores, {**report, "status": outcome.status, "preflight": [], "scored": len(scores)}


def _vintages(root: Path, cutoff: datetime) -> pd.DataFrame:
    """Feature vintage rows known at or before the cut-off."""

    files = sorted((root / VINTAGE_DIR_RELATIVE).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=["known_at"])
    frame = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    known = frame["known_at"].map(bots._parse_timestamp)
    return frame.loc[known.map(lambda value: value is not None and value <= cutoff)].reset_index(drop=True)
