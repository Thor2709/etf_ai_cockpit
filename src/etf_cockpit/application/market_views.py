"""Market-series, ETF structure, look-through and economics projections for presentation (application; ADR-0002)."""

from collections.abc import Mapping
from pathlib import Path
import pandas as pd

from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.parsed_disclosures import read_etf_report_records


def load_etf_look_through(
    instrument_id: str,
    *,
    decision_time: object,
    holdings_frame: object = None,
    fundamentals_frame: object = None,
    identity_map: Mapping[str, str] | None = None,
    provider_metrics: Mapping[str, object] | None = None,
    max_holdings_age_days: int = 90,
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
        summary = calculate_look_through(
            holdings,
            instrument_id=instrument_id,
            decision_time=decision_time,
            constituent_fundamentals=fundamentals,
            identity_map=identity_map,
            provider_metrics=provider_metrics,
            max_holdings_age_days=max_holdings_age_days,
        )
        return asdict(summary)
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return {
            "instrument_id": instrument_id,
            "status": "unavailable",
            "message": "Local holdings look-through evidence is unavailable or malformed.",
            "execution_allowed": False,
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


def load_etf_economics_projection(
    snapshot: object,
    instrument_id: str,
    *,
    as_of: object = None,
    horizon_days: int = 252,
) -> dict[str, object]:
    """Load the economics panel through the application-facing read model."""

    from types import SimpleNamespace

    from etf_cockpit.application.etf_economics_view import build_etf_economics_panel

    fund_evidence = getattr(snapshot, "etf_fund_total_return", None)
    benchmark_evidence = getattr(snapshot, "etf_benchmark_total_return", None)
    if isinstance(fund_evidence, dict) or isinstance(benchmark_evidence, dict):
        import pandas as pd

        records = getattr(snapshot, "etf_economics_records", ())
        decision_time = as_of if as_of is not None else getattr(
            getattr(snapshot, "data_report", None), "as_of_date", None
        )
        cutoff = None
        if decision_time is not None:
            cutoff = pd.Timestamp(decision_time)
            cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
            if len(str(decision_time).strip()) <= 10:
                cutoff += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        eligible_funds = [
            item
            for item in records
            if getattr(item, "scope", None) == "fund"
            and getattr(item, "instrument_id", None) == instrument_id
            and (
                cutoff is None
                or (pd.Timestamp(item.as_of) <= cutoff and pd.Timestamp(item.known_at) <= cutoff)
            )
        ]
        latest_fund = max(
            eligible_funds,
            key=lambda item: (item.as_of, item.known_at or ""),
            default=None,
        )
        if isinstance(fund_evidence, dict):
            fund_evidence = fund_evidence.get(instrument_id)
        if isinstance(benchmark_evidence, dict):
            benchmark_id = latest_fund.benchmark_id if latest_fund is not None else None
            benchmark_evidence = benchmark_evidence.get(benchmark_id)
        snapshot = SimpleNamespace(
            etf_economics_records=records,
            etf_fund_total_return=fund_evidence,
            etf_benchmark_total_return=benchmark_evidence,
            etf_closure_policy=getattr(snapshot, "etf_closure_policy", None),
            data_report=getattr(snapshot, "data_report", None),
        )

    return build_etf_economics_panel(
        snapshot, instrument_id, as_of=as_of, horizon_days=horizon_days
    )


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
