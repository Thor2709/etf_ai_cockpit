"""Feature computation and bound feature artefacts (application; ADR-0002)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import (
    load_prices,
    write_features,
)
from etf_cockpit.features.feature_store import LocalFeatureStore as LocalFeatureStore
from etf_cockpit.features.feature_pipeline import RELATIVE_STRENGTH_FALLBACK_ANCHOR, compute_features
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
    unavailable_reference_projection,
)
from etf_cockpit.application.derived_cache import (
    _calculation_window,
    _current_universe_revision,
    _price_snapshot_binding,
    _reference_identity_hash,
)



# Relative strength is a momentum signal against the broad market, not a benchmark-performance
# claim; without canonical benchmark evidence it is measured against RELATIVE_STRENGTH_FALLBACK_ANCHOR.

def relative_strength_anchor(context: object, available_ids: set[str]) -> str | None:
    canonical = getattr(context, "benchmark_data_id", None) if context is not None else None
    if canonical is not None and canonical in available_ids:
        return str(canonical)
    return RELATIVE_STRENGTH_FALLBACK_ANCHOR if RELATIVE_STRENGTH_FALLBACK_ANCHOR in available_ids else None

class FeatureService:
    def __init__(self, config: AppConfig, *, reference_context: CanonicalReferenceContext | None = None):
        self.config = config
        self.reference_context = reference_context or CanonicalReferenceContext(
            CanonicalBenchmarkRegistry(),
            None,
            unavailable_reference_projection(),
        )

    def compute_features(
        self,
        as_of_date: date | None = None,
        prices: pd.DataFrame | None = None,
        *,
        publish_guard: PublicationScopeFactory | None = None,
        reference_context: CanonicalReferenceContext | None = None,
    ) -> pd.DataFrame:
        settings_identity = current_settings_identity()
        frame = (prices if prices is not None else load_prices()).copy()
        if "volume" not in frame.columns:
            frame["volume"] = float("nan")
        context = reference_context if reference_context is not None else self.reference_context
        effective_as_of = as_of_date
        if effective_as_of is None:
            if "date" not in frame.columns:
                raise ValueError("canonical feature calculation window is unavailable")
            valid_dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dropna()
            if valid_dates.empty:
                raise ValueError("canonical feature calculation window is unavailable")
            effective_as_of = valid_dates.max().date()
        calculation_window = _calculation_window(context, effective_as_of, frame)
        if calculation_window is None:
            raise ValueError("canonical feature calculation window is unavailable")
        frame = clip_to_decision_window(frame, **calculation_window)
        price_binding = _price_snapshot_binding(frame, calculation_window=calculation_window)
        if price_binding is None:
            raise ValueError("adjusted-price snapshot identity is unavailable")
        available_ids = set(frame["etf_id"].astype(str)) if "etf_id" in frame.columns else set()
        benchmark = relative_strength_anchor(context, available_ids)
        features = compute_features(frame, benchmark_etf_id=benchmark)
        features.attrs["relative_strength_anchor"] = benchmark
        if benchmark is None:
            for column in ("relative_strength_60d", "relative_strength_120d"):
                if column in features.columns:
                    features[column] = float("nan")
        features.attrs["benchmark_reference"] = (
            unavailable_reference_projection()
            if context is None
            else context.projection
        )
        features.attrs["reference_identity"] = context.identity
        features.attrs["reference_identity_hash"] = _reference_identity_hash(context.identity)
        features.attrs["price_binding"] = dict(price_binding)
        run_id = settings_bound_run_id(
            f"features_{effective_as_of.isoformat()}",
            settings_identity=settings_identity,
        )
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                ("schema:local-storage", "dataset:prices", "dataset:universe"),
                settings_identity=settings_identity,
            )
        with publication_scope(publish_guard):
            write_features(
                features,
                cache_metadata={
                    "universe_revision": _current_universe_revision(),
                    "settings_revision": str(settings_identity["settings_revision"]),
                    "reference_identity": context.identity,
                    **price_binding,
                },
            )
        return features
