"""Market-series, ETF structure, look-through and economics projections for presentation (application; ADR-0002)."""

from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from pathlib import Path
import pandas as pd

from etf_cockpit.data.identity_master import IdentityMasterSchemaError, IdentityMasterStore
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.event_calendar import normalise_event_decision_time
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.parsed_disclosures import read_etf_report_records


def load_etf_look_through(
    instrument_id: str,
    *,
    decision_time: object,
    analysis_date: object = None,
    holdings_frame: object = None,
    fundamentals_frame: object = None,
    identity_map: Mapping[str, str] | None = None,
    provider_metrics: Mapping[str, object] | None = None,
    max_holdings_age_days: int = 90,
    minimum_aggregate_coverage: float = 0.80,
    require_canonical_identity: bool = False,
) -> dict[str, object]:
    """Read local ETF holdings and constituent evidence for the pure analyzer."""
    from dataclasses import asdict

    from etf_cockpit.analysis.look_through import calculate_look_through
    from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
    from etf_cockpit.data.fundamentals import FUNDAMENTAL_CLEAN_PATH

    try:
        holdings = pd.read_parquet(FUND_HOLDINGS_PATH) if holdings_frame is None else holdings_frame
        if fundamentals_frame is None:
            try:
                fundamentals = pd.read_parquet(FUNDAMENTAL_CLEAN_PATH)
            except (FileNotFoundError, OSError, ValueError, ImportError):
                fundamentals = pd.DataFrame()
        else:
            fundamentals = fundamentals_frame
        resolved_identity_map = dict(identity_map or {})
        identity_resolution: dict[str, object] = {
            "status": "provided" if resolved_identity_map else "listing_identity_only",
            "method": "caller-supplied canonical identity map" if resolved_identity_map else "typed holdings identity",
            "mapped_identity_count": len(resolved_identity_map),
            "effective_at": str(analysis_date or str(decision_time)[:10]),
            "decision_time": str(decision_time),
        }
        if require_canonical_identity and not resolved_identity_map:
            resolved_identity_map, identity_resolution = _pit_identity_map(
                analysis_date=analysis_date,
                decision_time=decision_time,
                holdings=holdings,
                fundamentals=fundamentals,
            )
            if identity_resolution.get("status") == "unavailable":
                return {
                    "instrument_id": instrument_id,
                    "status": "unavailable",
                    "reason_code": identity_resolution.get("reason_code", "canonical_identity_master_unavailable"),
                    "message": "Canonical point-in-time identity evidence is unavailable; look-through values are withheld.",
                    "lineage": {"identity_resolution": identity_resolution},
                    "execution_allowed": False,
                }
        summary = calculate_look_through(
            holdings,
            instrument_id=instrument_id,
            decision_time=decision_time,
            analysis_date=analysis_date,
            constituent_fundamentals=fundamentals,
            identity_map=resolved_identity_map,
            identity_resolution=identity_resolution,
            provider_metrics=provider_metrics,
            max_holdings_age_days=max_holdings_age_days,
            minimum_aggregate_coverage=minimum_aggregate_coverage,
            require_canonical_identity=require_canonical_identity,
        )
        return asdict(summary)
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return {
            "instrument_id": instrument_id,
            "status": "unavailable",
            "message": "Local holdings look-through evidence is unavailable or malformed.",
            "execution_allowed": False,
        }


def _pit_identity_map(
    *,
    analysis_date: object,
    decision_time: object,
    holdings: object,
    fundamentals: object,
) -> tuple[dict[str, str], dict[str, object]]:
    """Resolve typed direct-holding identities against the dated canonical master."""

    analysis = str(analysis_date or str(decision_time)[:10])[:10]
    analysis_day = date.fromisoformat(analysis)
    cutoff = normalise_event_decision_time(decision_time)
    if cutoff is None:
        return {}, {
            "status": "unavailable",
            "reason_code": "canonical_identity_cutoff_unavailable",
            "method": "dated identity-master projection",
            "analysis_date": analysis,
            "decision_time": str(decision_time),
        }
    effective_at = min(datetime.combine(analysis_day, time.max, tzinfo=timezone.utc), cutoff)
    candidates: set[str] = set()
    try:
        identity_frame = pd.read_parquet(IDENTITY_PATH)
        if "instrument_id" in identity_frame.columns:
            candidates.update(
                value.strip()
                for value in identity_frame["instrument_id"]
                if isinstance(value, str) and value.strip()
            )
    except (FileNotFoundError, OSError, ValueError, ImportError):
        identity_frame = pd.DataFrame()
    for frame in (holdings, fundamentals):
        if not isinstance(frame, pd.DataFrame):
            continue
        for column in ("canonical_instrument_id", "underlying_instrument_id"):
            if column in frame.columns:
                candidates.update(
                    value.strip()
                    for value in frame[column]
                    if isinstance(value, str) and value.strip()
                )
        if frame is fundamentals and "instrument_id" in frame.columns:
            candidates.update(
                value.strip()
                for value in frame["instrument_id"]
                if isinstance(value, str) and value.strip()
            )
    try:
        master_root = Path(IDENTITY_PATH).resolve().parents[2]
        if not storage_layout(master_root).transactional_path.is_file():
            return {}, {
                "status": "unavailable",
                "reason_code": "canonical_identity_master_unavailable",
                "method": "dated identity-master projection",
                "analysis_date": analysis,
                "effective_at": effective_at.isoformat(),
                "decision_time": cutoff.isoformat(),
                "candidate_count": len(candidates),
            }
        aliases: dict[str, set[str]] = {}
        manual_review_count = 0
        resolved_candidate_count = 0
        identity_object_count = 0
        with IdentityMasterStore(master_root, read_only=True) as master:
            for candidate in sorted(candidates):
                try:
                    projection = master.projection(
                        candidate,
                        effective_at=effective_at.isoformat().replace("+00:00", "Z"),
                        decision_time=cutoff.isoformat().replace("+00:00", "Z"),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                resolved_candidate_count += 1
                if projection.get("identity_status") != "resolved" or projection.get("identity_conflict_ids"):
                    manual_review_count += 1
                    continue
                canonical_id = str(projection.get("instrument_id") or candidate).strip()
                if not canonical_id:
                    continue
                objects = projection.get("identity_objects")
                if not isinstance(objects, (list, tuple)):
                    continue
                for item in objects:
                    if not isinstance(item, Mapping):
                        continue
                    fields = item.get("fields")
                    if not isinstance(fields, Mapping):
                        continue
                    identity_object_count += 1
                    for field in ("isin", "figi", "cusip", "sedol", "national_security_id", "lei", "cik", "national_id"):
                        value = fields.get(field)
                        if isinstance(value, str) and value.strip():
                            aliases.setdefault(f"{field}:{value.strip().casefold()}", set()).add(canonical_id)
                    for namespace_field in ("exchange", "mic"):
                        namespace = fields.get(namespace_field)
                        ticker = fields.get("ticker")
                        if isinstance(namespace, str) and namespace.strip() and isinstance(ticker, str) and ticker.strip():
                            aliases.setdefault(
                                f"ticker:{namespace.strip().casefold()}:{ticker.strip().casefold()}", set()
                            ).add(canonical_id)
                    identity_type = fields.get("identity_type")
                    identity_namespace = fields.get("identity_namespace")
                    identity_value = fields.get("identity_value")
                    if all(isinstance(value, str) and value.strip() for value in (identity_type, identity_namespace, identity_value)):
                        aliases.setdefault(
                            f"{identity_type.strip().casefold()}:{identity_namespace.strip().casefold()}:{identity_value.strip().casefold()}",
                            set(),
                        ).add(canonical_id)
        resolved = {key: next(iter(values)) for key, values in aliases.items() if len(values) == 1}
        ambiguous_count = sum(len(values) > 1 for values in aliases.values())
        return resolved, {
            "status": "available",
            "reason_code": None,
            "method": "canonical identity master projection at holdings analysis date and decision time",
            "analysis_date": analysis,
            "effective_at": effective_at.isoformat(),
            "decision_time": cutoff.isoformat(),
            "candidate_count": len(candidates),
            "resolved_candidate_count": resolved_candidate_count,
            "identity_object_count": identity_object_count,
            "mapped_identity_count": len(resolved),
            "ambiguous_identity_count": ambiguous_count,
            "manual_review_candidate_count": manual_review_count,
            "execution_allowed": False,
        }
    except (IdentityMasterSchemaError, IndexError, OSError, TypeError, ValueError, RuntimeError) as exc:
        return {}, {
            "status": "unavailable",
            "reason_code": "canonical_identity_master_invalid",
            "error_type": type(exc).__name__,
            "method": "dated identity-master projection",
            "analysis_date": analysis,
            "effective_at": effective_at.isoformat(),
            "decision_time": cutoff.isoformat(),
            "candidate_count": len(candidates),
        }


def load_etf_structure_projection(
    instrument_id: str,
    *,
    document_registry: object = None,
    report_records: object = None,
    supplemental_rows: object = None,
    holdings: object = None,
    decision_time: object = None,
    numeric_inputs: Mapping[str, object] | None = None,
    numeric_candidates: object = None,
) -> dict[str, object]:
    """Load the local ETF structural read model without provider access."""

    try:
        registry = read_document_registry() if document_registry is None else document_registry
        reports = read_etf_report_records() if report_records is None else report_records
        return project_etf_structure(
            instrument_id,
            document_registry=registry,
            report_records=reports,
            supplemental_rows=supplemental_rows,
            holdings=holdings,
            decision_time=decision_time,
            numeric_inputs=numeric_inputs,
            numeric_candidates=numeric_candidates,
        )
    except (OSError, TypeError, ValueError):
        return {
            "contract": "etf-structure-documents.v1",
            "instrument_id": str(instrument_id),
            "status": "unavailable",
            "fields": {},
            "documents": {family: {"status": "unknown", "execution_allowed": False} for family in ("factsheet", "prospectus", "holdings")},
            "versions": [],
            "flags": ["structure_evidence_invalid"],
            "evidence_confidence_cap": 0.0,
            "execution_allowed": False,
        }


def _load_market_series_projection(
    prices: object,
    instrument_id: str,
    *,
    basis: str,
    local_currency: str,
    output_currency: str | None = None,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Build a fail-closed raw/adjusted/total-return chart projection."""

    import pandas as pd

    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.local_storage import storage_layout
    from etf_cockpit.data.market_adjustments import (
        CorporateActionCoverageStore,
        CorporateActionStore,
        FXObservationStore,
        apply_total_return_adjustments,
        derive_fx_cross,
    )

    if not isinstance(prices, pd.DataFrame) or prices.empty or basis not in {"raw", "adjusted", "total_return"}:
        return {"status": "unavailable", "reason_code": "market_series_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    identifier = "etf_id" if "etf_id" in prices.columns else "instrument_id" if "instrument_id" in prices.columns else None
    if identifier is None or "date" not in prices.columns:
        return {"status": "unavailable", "reason_code": "market_series_schema_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    scoped = prices.loc[prices[identifier].astype(str).eq(str(instrument_id))].copy()
    if scoped.empty:
        return {"status": "unavailable", "reason_code": "market_series_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    if decision_time is not None:
        decision_cutoff = pd.to_datetime(decision_time, errors="coerce", utc=True)
        if pd.isna(decision_cutoff):
            return {"status": "unavailable", "reason_code": "decision_time_invalid", "frame": pd.DataFrame(), "execution_allowed": False}
        observation_times = pd.to_datetime(scoped["date"], errors="coerce", utc=True)
        scoped = scoped.loc[observation_times.notna() & (observation_times < decision_cutoff)].copy()
        if "known_at" in scoped:
            known_times = pd.to_datetime(scoped["known_at"], errors="coerce", utc=True)
            scoped = scoped.loc[known_times.notna() & (known_times < decision_cutoff)].copy()
        if scoped.empty:
            return {"status": "unavailable", "reason_code": "market_series_outside_decision_window", "frame": pd.DataFrame(), "execution_allowed": False}
    root = Path(storage_root or ROOT).resolve()
    actions = ()
    action_coverage = ()
    fx_observations = ()
    latest = pd.to_datetime(scoped["date"], errors="coerce", utc=True).max()
    cutoff = decision_time or (latest.isoformat() if pd.notna(latest) else None)
    if storage_layout(root).transactional_path.exists() and cutoff is not None and pd.notna(latest):
        with CorporateActionCoverageStore(root) as store:
            action_coverage = store.as_of(str(instrument_id), valid_at=latest.isoformat(), known_at=cutoff)
        with CorporateActionStore(root) as store:
            actions = store.as_of(str(instrument_id), known_at=cutoff)
        with FXObservationStore(root) as store:
            fx_observations = store.query()
    close_column = "close" if "close" in scoped.columns else None
    if close_column is None:
        if basis != "raw" and not action_coverage:
            return {"status": "unavailable", "reason_code": "corporate_action_coverage_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
        if basis == "adjusted" and action_coverage and "adjusted_close" in scoped.columns and (output_currency or local_currency).upper() == local_currency.upper():
            frame = scoped[["date", "adjusted_close"]].copy()
            frame["series_value"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
            frame = frame.dropna(subset=["series_value"])
            if not frame.empty:
                return {"status": "available", "basis": "provider_adjusted", "currency": local_currency.upper(), "frame": frame, "provenance": "provider_adjusted_close; explicit source coverage", "execution_allowed": False}
        return {"status": "unavailable", "reason_code": "raw_price_evidence_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    if basis != "raw" and not action_coverage:
        return {"status": "unavailable", "reason_code": "corporate_action_coverage_unavailable", "frame": pd.DataFrame(), "execution_allowed": False}
    derived = apply_total_return_adjustments(scoped.rename(columns={close_column: "close"}), actions)
    if not derived.available:
        return {"status": derived.status, "reason_code": "corporate_action_discrepancy", "frame": derived.frame, "execution_allowed": False}
    frame = derived.frame.copy()
    target_currency = (output_currency or local_currency).upper()
    local = local_currency.upper()
    if target_currency != local:
        rates: list[float] = []
        for value in frame["date"]:
            rate = derive_fx_cross(fx_observations, local, target_currency, value, decision_time=cutoff)
            if not rate.available or rate.rate is None:
                return {"status": "unavailable", "reason_code": "required_fx_missing_stale_or_conflicted", "frame": pd.DataFrame(), "execution_allowed": False}
            rates.append(float(rate.rate))
        frame["fx_rate"] = rates
        frame["fx_return"] = frame["fx_rate"].pct_change(fill_method=None)
        local_returns = frame["local_total_return"].copy()
        fx_returns = frame["fx_return"].copy()
        if local_returns.iloc[1:].isna().any() or fx_returns.iloc[1:].isna().any():
            return {"status": "unavailable", "reason_code": "required_total_return_input_missing", "frame": pd.DataFrame(), "execution_allowed": False}
        if not local_returns.empty:
            # The first row has no prior observation; only this base-period return is defined as zero.
            local_returns.iloc[0] = 0.0
            fx_returns.iloc[0] = 0.0
        frame["output_total_return"] = (1.0 + local_returns) * (1.0 + fx_returns) - 1.0
        frame["output_total_return_index"] = 100.0 * (1.0 + frame["output_total_return"]).cumprod()
    if basis == "raw":
        frame["series_value"] = frame["raw_close"] * (frame["fx_rate"] if "fx_rate" in frame else 1.0)
    elif basis == "adjusted":
        frame["series_value"] = frame["adjusted_close"] * (frame["fx_rate"] if "fx_rate" in frame else 1.0)
    else:
        frame["series_value"] = frame["output_total_return_index"] if "output_total_return_index" in frame else frame["total_return_index"]
    return {
        "status": "available",
        "basis": basis,
        "currency": target_currency,
        "frame": frame,
        "provenance": "explicit corporate actions and dated point-in-time FX",
        "total_return_convention": derived.convention,
        "execution_allowed": False,
    }


def load_market_series_projection(
    prices: object,
    instrument_id: str,
    *,
    basis: str,
    local_currency: str,
    output_currency: str | None = None,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Build a controlled unavailable result for malformed or corrupt evidence."""

    import pandas as pd

    try:
        return _load_market_series_projection(
            prices,
            instrument_id,
            basis=basis,
            local_currency=local_currency,
            output_currency=output_currency,
            storage_root=storage_root,
            decision_time=decision_time,
        )
    except (ArithmeticError, OSError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "reason_code": "market_adjustment_evidence_invalid",
            "frame": pd.DataFrame(),
            "execution_allowed": False,
        }
