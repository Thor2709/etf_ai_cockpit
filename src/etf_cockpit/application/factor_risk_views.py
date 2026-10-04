"""Point-in-time bound factor-risk panel for Instrument Detail (application; ADR-0002)."""

from collections.abc import Mapping

from etf_cockpit.portfolio.factor_risk import build_factor_risk_report


def load_bound_factor_risk_panel(snapshot: object, instrument_id: str) -> dict[str, object]:
    """Project canonical factor risk only from replayed snapshot input bindings."""
    import math as numeric_math
    from numbers import Real
    import pandas as pandas
    from etf_cockpit.application.benchmark_reference import adjusted_price_snapshot_binding, clip_to_decision_window
    from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry, ReferencePortfolioDefinition
    from etf_cockpit.portfolio.sandbox import holdings_checksum

    def source_knowledge(frame, effective_times, decision, *, price_rows=False):
        # Replay the no-trade builder's explicit per-row knowledge contract.
        authority_columns = tuple(column for column in ("known_at", "imported_at", "available_at") if column in frame)
        if not authority_columns:
            raise ValueError("explicit source knowledge is missing")
        columns = authority_columns + tuple(column for column in ("retrieved_at", "published_at") if price_rows and column in frame)
        times = []
        for (_, row), effective_time in zip(frame.iterrows(), effective_times):
            declared = {}
            for column in columns:
                value = row[column]
                if value is None or pandas.isna(value):
                    continue
                parsed = pandas.to_datetime(value, errors="coerce")
                if pandas.isna(parsed) or getattr(parsed, "tzinfo", None) is None:
                    raise ValueError("source knowledge must contain valid aware timestamps")
                declared[column] = pandas.Timestamp(parsed).tz_convert("UTC")
            if not any(column in declared for column in authority_columns):
                raise ValueError("each source row requires explicit knowledge")
            row_known = max(declared.values())
            if row_known < effective_time or row_known > decision:
                raise ValueError("source knowledge contradicts the effective time or decision cutoff")
            times.append(row_known)
        return max(times), {
            "status": "validated", "row_count": len(times), "fields": list(columns),
            "latest_known_at": max(times).isoformat(), "earliest_known_at": min(times).isoformat(),
        }

    empty = {
        "status": "unavailable", "instrument_id": instrument_id,
        "factor_exposures": [], "specific_risk": [], "instrument_contributions": [],
        "global_coverage": {}, "global_diagnostics": {}, "global_report_status": "unavailable",
        "coverage": {"status": "unavailable", "instrument_id": instrument_id},
        "coverage_scope": "selected_instrument", "historical_binding_status": "unavailable",
        "selected_instrument_status": "unverified", "warnings": [],
        "lookthrough_status": "unsupported", "retrospective_universe_replay": "unsupported",
        "execution_allowed": False,
    }
    try:
        prices = getattr(snapshot, "prices", None)
        features = getattr(snapshot, "features", None)
        holdings = getattr(snapshot, "holdings", None)
        if any(not isinstance(frame, pandas.DataFrame) or frame.empty or not frame.columns.is_unique for frame in (prices, features, holdings)):
            raise ValueError("complete unambiguous snapshot frames are required")
        binding = features.attrs.get("price_binding")
        if not isinstance(binding, Mapping) or not isinstance(binding.get("calculation_window"), Mapping):
            raise ValueError("full feature price binding is unavailable")
        window = binding["calculation_window"]
        replayed = adjusted_price_snapshot_binding(prices, calculation_window=window)
        if replayed is None or dict(binding) != replayed:
            raise ValueError("feature price binding does not match replayed adjusted prices")
        decision = pandas.Timestamp(window["decision_time"])
        as_of = pandas.Timestamp(getattr(getattr(snapshot, "data_report", None), "as_of_date", None))
        if pandas.isna(as_of) or decision.tzinfo is None or as_of.date().isoformat() != window["end_date"]:
            raise ValueError("snapshot cutoff does not match the bound calculation window")
        scoped_prices = clip_to_decision_window(prices, **window)
        scoped_features = clip_to_decision_window(features, **window)
        price_effective = pandas.to_datetime(scoped_prices["date"], errors="coerce", utc=True, format="mixed")
        _, price_knowledge = source_knowledge(scoped_prices, price_effective, decision, price_rows=True)
        if len(scoped_features) != len(features) or scoped_features.empty:
            raise ValueError("feature rows fall outside the bound decision window")
        for frame in (scoped_prices, scoped_features, holdings):
            if "etf_id" not in frame or any(not isinstance(value, str) or not value or value != value.strip() for value in frame["etf_id"]):
                raise ValueError("exact canonical source identifiers are required")
        if scoped_features.duplicated(["etf_id", "date"]).any():
            raise ValueError("feature identity and dates must be unambiguous")
        # A price checksum binds inputs, not supplied descriptor values. Replay
        # the canonical calculation before accepting those descriptors as bound.
        from etf_cockpit.features.feature_pipeline import compute_features
        replay_prices = scoped_prices.copy()
        if "volume" not in replay_prices:
            replay_prices["volume"] = float("nan")  # FeatureService's explicit missing-volume convention.
        replay_features = compute_features(replay_prices)
        descriptor_columns = ["etf_id", "date", "momentum_120d", "momentum_60d", "return_60d_log", "vol_60d_ann", "vol_120d_ann", "ewma_vol_ann"]
        if not set(descriptor_columns).issubset(scoped_features):
            raise ValueError("canonical factor descriptors are incomplete")
        supplied = scoped_features[descriptor_columns].copy()
        canonical = replay_features[descriptor_columns].copy()
        for frame in (supplied, canonical):
            frame["date"] = pandas.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
        try:
            pandas.testing.assert_frame_equal(
                supplied.sort_values(["etf_id", "date"]).reset_index(drop=True),
                canonical.sort_values(["etf_id", "date"]).reset_index(drop=True),
                check_dtype=False, check_exact=True,
            )
        except AssertionError as exc:
            raise ValueError("supplied factor descriptors differ from canonical price replay") from exc
        required = ("current_weight", "market_value_eur", "as_of_date")
        if not set(required).issubset(holdings) or holdings["etf_id"].duplicated().any():
            raise ValueError("holdings allocation fields are incomplete")
        for column in required[:2]:
            if any(isinstance(value, bool) or not isinstance(value, Real) or not numeric_math.isfinite(value) or value < 0 for value in holdings[column]):
                raise ValueError("holdings allocation values are invalid")
        holding_dates = pandas.to_datetime(holdings["as_of_date"], errors="coerce", utc=True, format="mixed")
        if holding_dates.isna().any() or set(holding_dates.dt.date) != {as_of.date()}:
            raise ValueError("holdings are not effective at the snapshot cutoff")
        holdings_known, holdings_knowledge = source_knowledge(
            holdings, [pandas.Timestamp(as_of.date(), tz="UTC")] * len(holdings), decision
        )
        registry = getattr(snapshot, "benchmark_reference_registry", None)
        if not isinstance(registry, CanonicalBenchmarkRegistry):
            raise ValueError("canonical no-trade reference is unavailable")
        references = [item for item in registry.reference_portfolios if item.portfolio_id == "reference:no_trade"]
        checksum = holdings_checksum(holdings)
        if len(references) != 1 or not isinstance(references[0], ReferencePortfolioDefinition):
            raise ValueError("exactly one canonical no-trade reference is required")
        reference = references[0]
        known = pandas.Timestamp(reference.known_at)
        effective = pandas.Timestamp(reference.effective_at)
        if known != holdings_known:
            raise ValueError("no-trade reference knowledge differs from the source row maximum")
        if (reference.method != "no_trade" or tuple(reference.source_hashes) != (checksum,)
                or known.tzinfo is None or known > decision or effective != pandas.Timestamp(as_of.date(), tz="UTC")):
            raise ValueError("no-trade reference holdings provenance does not match the cutoff")
        held_ids = set(holdings["etf_id"])
        weights = dict(reference.current_weights or {})
        if set(weights) != held_ids | {f"cash:{reference.currency}"}:
            raise ValueError("no-trade reference does not prove the complete held universe")
        for row in holdings.itertuples():
            if weights[row.etf_id] != row.current_weight:
                raise ValueError("no-trade weights differ from bound holdings")
        universe = sorted(set(scoped_prices["etf_id"]) & set(scoped_features["etf_id"]))
        if not held_ids.issubset(universe):
            raise ValueError("held instruments lack bound price or feature evidence")
        # An absent position in the complete bound holdings set has zero
        # portfolio weight; its unknown market-value descriptor remains missing.
        allocation = pandas.DataFrame({"etf_id": universe}).merge(
            holdings[["etf_id", "current_weight", "market_value_eur"]], on="etf_id", how="left", validate="one_to_one"
        )
        allocation.loc[~allocation["etf_id"].isin(held_ids), "current_weight"] = 0.0

        report = build_factor_risk_report(
            scoped_prices.loc[scoped_prices["etf_id"].isin(universe)], allocation,
            scoped_features.loc[scoped_features["etf_id"].isin(universe), descriptor_columns], holdings=None,
        )
    except (ArithmeticError, AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        return empty | {"message": f"Factor-risk binding unavailable: {exc}."}
    selected = {}
    for key in ("factor_exposures", "specific_risk", "instrument_contributions"):
        frame = report.get(key)
        selected[key] = frame.loc[frame["instrument_id"].eq(instrument_id)].copy() if isinstance(frame, pandas.DataFrame) and "instrument_id" in frame else pandas.DataFrame()
    risk = selected["specific_risk"]
    covered = (report.get("status") in {"available", "partial"} and not risk.empty
               and "specific_vol_ann" in risk and pandas.to_numeric(risk["specific_vol_ann"], errors="coerce").map(numeric_math.isfinite).all())
    return empty | {
        "status": report.get("status") if covered else "unavailable",
        "historical_binding_status": "verified_snapshot",
        "selected_instrument_status": "available" if covered else "absent" if instrument_id not in universe else "insufficient_model_coverage",
        "coverage": {"status": "available" if covered else "unavailable", "instrument_id": instrument_id},
        **{key: frame.astype(object).where(pandas.notna(frame), None).to_dict("records") if covered else [] for key, frame in selected.items()},
        "global_report_status": report.get("status", "unavailable"),
        "global_coverage": report.get("coverage", {}), "global_diagnostics": report.get("diagnostics", {}),
        "global_coverage_scope": "estimation_universe", "global_diagnostics_scope": "estimation_universe",
        "warnings": report.get("warnings", []), "model_version": report.get("model_version", "unavailable"),
        "decision_time": window["decision_time"], "price_snapshot_checksum": replayed["price_snapshot_checksum"],
        "source_knowledge": {
            "prices": price_knowledge | {"checksum_scope": "price checksum binds values only; row knowledge validated separately"},
            "holdings": holdings_knowledge | {"holdings_checksum": checksum, "reference_content_hash": reference.content_hash},
        },
        "holdings_checksum": checksum, "universe_revision": getattr(snapshot, "universe_revision", ""),
        "message": "Factor risk from verified snapshot price/features and no-trade holdings bindings. Historical look-through and arbitrary retrospective universe replay are unsupported.",
    }
