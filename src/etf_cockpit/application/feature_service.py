"""Feature computation and bound feature artefacts (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    ensure_run_manifest,
    price_bound_run_label,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import (
    load_prices,
    write_features,
)
from etf_cockpit.features.feature_store import LocalFeatureStore as LocalFeatureStore
from etf_cockpit.data.fx_data import fx_rates_for_prices
from etf_cockpit.features.feature_pipeline import (
    RELATIVE_STRENGTH_FALLBACK_ANCHOR,
    attach_eur_basis,
    compute_features,
    eur_basis_prices,
    fx_basis_binding,
)
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
    unavailable_reference_projection,
)
from etf_cockpit.application.derived_cache import (
    _calculation_window,
    _current_universe_revision,
    _feature_cache_binding,
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
    def __init__(
        self,
        config: AppConfig,
        *,
        reference_context: CanonicalReferenceContext | None = None,
        fx_rates: pd.DataFrame | None = None,
    ):
        self.config = config
        self._fx_rates = fx_rates
        self.reference_context = reference_context or CanonicalReferenceContext(
            CanonicalBenchmarkRegistry(),
            None,
            unavailable_reference_projection(),
        )

    def _fx_frame(self, prices: pd.DataFrame | None = None) -> pd.DataFrame:
        if self._fx_rates is not None:
            return self._fx_rates
        try:
            return fx_rates_for_prices(prices)
        except Exception:
            return pd.DataFrame()

    def _configured_currency(self) -> dict[str, str]:
        return {etf.id: etf.currency for etf in self.config.universe.etfs}

    def fx_binding(self, prices: pd.DataFrame, calculation_window: Mapping[str, str]) -> dict[str, object]:
        """Currency basis and FX series identity the features of ``prices`` are bound to."""

        window = {key: str(calculation_window[key]) for key in ("start_date", "end_date", "decision_time")}
        return fx_basis_binding(
            clip_to_decision_window(prices, **window),
            self._fx_frame(prices),
            configured_currency=self._configured_currency(),
            known_by=window["decision_time"],
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
        # Score price features are computed on an EUR total-return basis; a session without a
        # usable FX rate has no EUR price and so no feature (reason ``fx_unavailable``).
        eur_basis = eur_basis_prices(
            frame,
            self._fx_frame(frame),
            configured_currency=self._configured_currency(),
            known_by=calculation_window["decision_time"],
        )
        features = compute_features(eur_basis.frame, benchmark_etf_id=benchmark)
        attach_eur_basis(features, eur_basis)
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
        # One run identity: date + exact price snapshot + settings revision. A corrected price
        # state gets a new immutable manifest instead of reusing the old one.
        run_id = settings_bound_run_id(
            price_bound_run_label(f"features_{effective_as_of.isoformat()}", price_binding, eur_basis.binding),
            settings_identity=settings_identity,
        )
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                ("schema:local-storage", "dataset:prices", "dataset:universe"),
                settings_identity=settings_identity,
                dataset_bindings={"dataset:prices": dict(price_binding), "dataset:fx": dict(eur_basis.binding)},
            )
        with publication_scope(publish_guard):
            write_features(
                features,
                cache_metadata={
                    "universe_revision": _current_universe_revision(),
                    "settings_revision": str(settings_identity["settings_revision"]),
                    "reference_identity": context.identity,
                    **price_binding,
                    **_feature_cache_binding(frame, calculation_window=calculation_window, fx_binding=eur_basis.binding),
                },
            )
        return features
