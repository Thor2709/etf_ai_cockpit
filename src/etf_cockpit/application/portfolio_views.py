"""Portfolio holdings, valuation, forecast, calendar, maturity, exposure and risk-profile read models (application; ADR-0002)."""

from collections.abc import (
    Mapping,
    Sequence,
)
from datetime import (
    date,
    datetime,
)
import json
import math
from numbers import Real
from pathlib import Path
import pandas as pd

from etf_cockpit.core.paths import LOG_DIR
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.event_calendar import (
    load_calendar_events,
    normalise_event_decision_time,
)
from etf_cockpit.data.fx_data import load_fx_rates
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.market_adjustments import CorporateActionStore
from etf_cockpit.application.portfolio_valuation import load_portfolio_valuation_history
from etf_cockpit.portfolio.performance_series import (
    PerformanceSeries,
    build_portfolio_performance_series,
)
from etf_cockpit.portfolio.holdings_table import build_portfolio_holdings_table
from etf_cockpit.portfolio.forecast_aggregation import (
    PortfolioForecastSnapshot,
    build_portfolio_forecast_snapshot,
)
from etf_cockpit.portfolio.calendar import build_portfolio_calendar
from etf_cockpit.portfolio.maturity_ladder import build_portfolio_maturity_ladder
from etf_cockpit.models.forecast_scores import forecast_return_distributions as load_forecast_return_distributions
from etf_cockpit.portfolio.currency import (
    CurrencyProjection,
    project_portfolio_currency as _project_portfolio_currency,
)
from etf_cockpit.portfolio.exposure_cube import build_portfolio_exposure_cube
from etf_cockpit.portfolio.sandbox import (
    PortfolioAnalysis,
    select_holdings_view,
)
from etf_cockpit.portfolio.risk_profiles import (
    RiskProfileError,
    build_risk_profile_workspace,
    unavailable_risk_profile_workspace,
)
from etf_cockpit.application.overlap import load_direct_holdings
from etf_cockpit.application.fixed_income_views import load_fixed_income_terms_projection


def load_portfolio_performance_series(
    *,
    metric: str = "twr_index",
    date_range: str = "inception",
    aggregation: str = "day",
    currency: str = "EUR",
    custom_start: object = None,
    custom_end: object = None,
) -> PerformanceSeries:
    """Load saved valuation and local FX evidence for one portfolio view."""
    report = load_portfolio_valuation_history()
    snapshots = report.get("snapshots")
    try:
        fx_rates = load_fx_rates()
    except (OSError, ValueError, TypeError, ImportError):
        fx_rates = pd.DataFrame()
    return build_portfolio_performance_series(
        snapshots if isinstance(snapshots, pd.DataFrame) else None,
        metric=metric,
        date_range=date_range,
        aggregation=aggregation,
        currency=currency,
        custom_start=custom_start,  # type: ignore[arg-type]
        custom_end=custom_end,  # type: ignore[arg-type]
        fx_rates=fx_rates,
    )


def load_portfolio_forecast_aggregation(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    horizon_days: int,
    output_currency: str = "EUR",
    analysis_run_id: str | None = None,
) -> PortfolioForecastSnapshot:
    """Load an exact-horizon portfolio forecast from bound saved inputs."""

    projection = load_portfolio_holdings_projection(
        snapshot,
        analysis,
        horizon_days=horizon_days,
        output_currency=output_currency,
        analysis_run_id=analysis_run_id,
    )
    portfolio_meta = projection.get("portfolio_snapshot")
    portfolio_meta = portfolio_meta if isinstance(portfolio_meta, Mapping) else {}
    performance_meta = projection.get("performance_snapshot")
    performance_meta = performance_meta if isinstance(performance_meta, Mapping) else {}
    holding_rows = projection.get("rows", ())
    positions: dict[str, dict[str, object]] = {}
    if isinstance(holding_rows, Sequence) and not isinstance(holding_rows, (str, bytes)):
        for row in holding_rows:
            if not isinstance(row, Mapping):
                continue
            instrument_id = str(row.get("instrument_id", "")).strip()
            weight_cell = row.get("weight")
            value_cell = row.get("value")
            weight = weight_cell.get("value") if isinstance(weight_cell, Mapping) and weight_cell.get("status") == "available" else None
            market_value = value_cell.get("value") if isinstance(value_cell, Mapping) and value_cell.get("status") == "available" else None
            if instrument_id:
                positions[instrument_id] = {"weight": weight, "market_value": market_value}

    def _available_amount(field: str) -> float | None:
        cell = performance_meta.get(field)
        value = cell.get("value") if isinstance(cell, Mapping) and cell.get("status") == "available" else None
        return float(value) if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)) else None

    securities_value = _available_amount("securities_value_output_currency")
    cash_value = _available_amount("cash_value_output_currency")
    portfolio_value = _available_amount("total_value_output_currency")
    security_reconciliation = performance_meta.get("reconciliation")
    total_reconciliation = performance_meta.get("portfolio_value_reconciliation")
    position_values = [
        position.get("market_value")
        for position in positions.values()
    ]
    value_components_reconciled = bool(
        isinstance(security_reconciliation, Mapping)
        and security_reconciliation.get("status") == "available"
        and security_reconciliation.get("value") is True
        and isinstance(total_reconciliation, Mapping)
        and total_reconciliation.get("status") == "available"
        and total_reconciliation.get("value") is True
        and securities_value is not None
        and cash_value is not None
        and portfolio_value is not None
        and position_values
        and all(isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)) for value in position_values)
        and math.isclose(math.fsum(float(value) for value in position_values), securities_value, rel_tol=1e-12, abs_tol=1e-9)
        and math.isclose(securities_value + cash_value, portfolio_value, rel_tol=1e-12, abs_tol=1e-9)
    )

    binding = analysis.snapshot_binding
    risk_projection = analysis.service_evidence.get("risk")
    risk_projection = risk_projection if isinstance(risk_projection, Mapping) else {}
    selected_run_id = str(projection.get("analysis_run_id", "")).strip()
    risk_snapshot = None
    if binding is not None:
        risk_snapshot = {
            "portfolio_id": getattr(binding, "portfolio_id", None),
            "snapshot_id": getattr(binding, "snapshot_id", None),
            "as_of": getattr(binding, "as_of", None),
            "candidate_id": analysis.candidate.candidate_id,
            "status": risk_projection.get("status", "unavailable"),
            "model_version": risk_projection.get("model_version"),
            "selected_estimator": risk_projection.get("selected_estimator"),
            "covariances": risk_projection.get("covariances"),
            "warnings": risk_projection.get("warnings", ()),
            "coverage": risk_projection.get("coverage"),
            "execution_allowed": risk_projection.get("execution_allowed", False),
        }

    decision_time = projection.get("analysis_date")
    distributions: dict[str, dict[str, object]] = {}
    if projection.get("proposal_handoff_allowed") is True and decision_time:
        try:
            distribution_rows = load_forecast_return_distributions(
                getattr(snapshot, "forecasts", pd.DataFrame()),
                horizon_days=horizon_days,
                decision_time=decision_time,
            )
        except (TypeError, ValueError, KeyError):
            distribution_rows = {}
        distributions = {}
        for instrument_id, distribution in distribution_rows.items():
            if instrument_id not in positions or not isinstance(distribution, Mapping):
                continue
            bound_distribution = dict(distribution)
            if not bound_distribution.get("analysis_run_id"):
                bound_distribution["analysis_run_id"] = selected_run_id
            distributions[instrument_id] = bound_distribution

    analysis_snapshot = {
        "portfolio_id": portfolio_meta.get("portfolio_id"),
        "snapshot_id": portfolio_meta.get("snapshot_id"),
        "as_of": portfolio_meta.get("as_of"),
        "analysis_run_id": selected_run_id or None,
        "candidate_id": analysis.candidate.candidate_id,
        "decision_time": decision_time,
        "status": "complete" if projection.get("proposal_handoff_allowed") is True else "unavailable",
        "policy_status": "available" if projection.get("proposal_handoff_allowed") is True else "unavailable",
        "distributions": distributions,
        "target_weights": analysis.candidate.targets,
        "cash_weight": analysis.candidate.cash_weight,
        "cash_return": None,
        "benchmark_return": None,
    }
    portfolio_snapshot = {
        **portfolio_meta,
        "sealed": projection.get("proposal_handoff_allowed") is True,
        "positions": positions,
        "securities_value": securities_value,
        "cash_value": cash_value,
        "total_value": portfolio_value,
        "value_components_reconciled": value_components_reconciled,
        "cash_weight": analysis.current_cash_weight,
    }
    return build_portfolio_forecast_snapshot(
        portfolio_snapshot,
        analysis_snapshot,
        risk_snapshot,
        horizon_days=horizon_days,
        output_currency=output_currency,
    )


def load_portfolio_calendar_projection(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    output_currency: str = "EUR",
) -> dict[str, object]:
    """Load saved calendar, corporate-action, bond-term and FX evidence."""

    binding = analysis.snapshot_binding
    decision_time = getattr(binding, "as_of", None) if binding is not None else None
    decision = normalise_event_decision_time(decision_time)
    if decision is None:
        return build_portfolio_calendar(
            None,
            decision_time=None,
            output_currency=output_currency,
        )

    holdings = getattr(snapshot, "holdings", None)
    if isinstance(holdings, pd.DataFrame) and binding is not None:
        try:
            holdings = select_holdings_view(holdings, str(getattr(binding, "holdings_view", "combined")))
        except (TypeError, ValueError):
            holdings = pd.DataFrame()
    if not isinstance(holdings, pd.DataFrame):
        holdings = pd.DataFrame()

    event_rows = load_calendar_events()
    instrument_column = "instrument_id" if "instrument_id" in holdings.columns else "etf_id" if "etf_id" in holdings.columns else None
    instruments = sorted(
        {
            str(value).strip()
            for value in holdings[instrument_column].tolist()
            if str(value).strip()
        }
    ) if instrument_column else []
    corporate_actions = []
    storage_path = storage_layout(ROOT).transactional_path
    if storage_path.is_file():
        with CorporateActionStore(ROOT) as store:
            for instrument_id in instruments:
                corporate_actions.extend(store.query(instrument_id))

    terms: dict[str, Mapping[str, object]] = {}
    if "asset_type" in holdings.columns:
        bond_ids = sorted(
            {
                str(row[instrument_column]).strip()
                for _, row in holdings.iterrows()
                if instrument_column
                and str(row.get("asset_type", "")).strip().casefold()
                in {"bond", "fixed_income", "fixed income", "government_bond", "corporate_bond"}
            }
        )
        cutoff = decision.isoformat()
        for instrument_id in bond_ids:
            terms[instrument_id] = load_fixed_income_terms_projection(
                instrument_id,
                storage_root=ROOT,
                effective_at=cutoff,
                decision_time=cutoff,
            )
    try:
        fx_rates = load_fx_rates()
    except (OSError, ValueError, TypeError, ImportError):
        fx_rates = pd.DataFrame()

    return build_portfolio_calendar(
        holdings,
        decision_time=decision.to_pydatetime(),
        output_currency=output_currency,
        event_rows=event_rows,
        corporate_actions=tuple(corporate_actions),
        fixed_income_terms=terms,
        fx_rates=fx_rates,
    )


def load_portfolio_maturity_ladder_projection(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    output_currency: str = "EUR",
) -> dict[str, object]:
    """Load a maturity ladder from the canonical saved calendar and terms."""

    calendar_projection = load_portfolio_calendar_projection(
        snapshot, analysis, output_currency=output_currency
    )
    holdings = getattr(snapshot, "holdings", None)
    binding = analysis.snapshot_binding
    if isinstance(holdings, pd.DataFrame) and binding is not None:
        try:
            holdings = select_holdings_view(
                holdings, str(getattr(binding, "holdings_view", "combined"))
            )
        except (TypeError, ValueError):
            holdings = pd.DataFrame()
    if not isinstance(holdings, pd.DataFrame):
        holdings = pd.DataFrame()
    holding_rows = [dict(row) for row in holdings.to_dict("records")]
    bond_ids = sorted(
        {
            str(row.get("instrument_id", row.get("etf_id", ""))).strip()
            for row in holding_rows
            if str(row.get("asset_type", "")).strip().casefold()
            in {"bond", "fixed_income", "fixed income", "government_bond", "corporate_bond"}
            and str(row.get("instrument_id", row.get("etf_id", ""))).strip()
        }
    )
    cutoff = calendar_projection.get("decision_time")
    terms = {
        instrument_id: load_fixed_income_terms_projection(
            instrument_id,
            storage_root=ROOT,
            effective_at=str(cutoff),
            decision_time=str(cutoff),
        )
        for instrument_id in bond_ids
    } if cutoff else {}
    return build_portfolio_maturity_ladder(
        calendar_projection,
        holdings=holding_rows,
        terms_projections=terms,
    )


def load_portfolio_holdings_projection(
    snapshot: object,
    analysis: PortfolioAnalysis,
    *,
    horizon_days: int,
    output_currency: str = "EUR",
    analysis_run_id: str | None = None,
    search: str = "",
    asset_type: str | None = None,
    sort_by: str = "instrument_id",
    descending: bool = False,
    column_preset: str = "full",
    storage_root: Path | None = None,
    artifact_directory: Path | None = None,
) -> dict[str, object]:
    """Load a holding view from one bound portfolio, performance and analysis run."""

    source = Path(storage_root or ROOT).resolve()
    artifact_root = Path(artifact_directory or LOG_DIR).resolve()
    binding = analysis.snapshot_binding
    unavailable = {
        "status": "unavailable",
        "reason": "portfolio_snapshot_binding_unavailable",
        "portfolio_snapshot": None,
        "performance_snapshot": None,
        "analysis_run_id": None,
        "analysis_date": None,
        "analysis_policy_id": None,
        "analysis_current": False,
        "horizon_days": horizon_days,
        "output_currency": str(output_currency or "").strip().upper(),
        "proposal_handoff_allowed": False,
        "proposal_handoff_reason": "portfolio_snapshot_binding_unavailable",
        "row_count": 0,
        "total_rows": 0,
        "rows": [],
        "analysis_runs": [],
        "execution_allowed": False,
    }
    if binding is None:
        return unavailable

    portfolio_snapshot = {
        "portfolio_id": getattr(binding, "portfolio_id", None),
        "snapshot_id": getattr(binding, "snapshot_id", None),
        "as_of": getattr(binding, "as_of", None),
        "source_checksum": getattr(binding, "source_checksum", None),
        "policy_id": getattr(snapshot, "policy_id", None),
    }
    holdings = getattr(snapshot, "holdings", None)
    holdings = select_holdings_view(holdings, str(getattr(binding, "holdings_view", "combined")))
    if isinstance(holdings, pd.DataFrame) and not holdings.empty and "asset_type" not in holdings.columns:
        identity_column = next((name for name in ("instrument_id", "etf_id") if name in holdings.columns), None)
        configured = getattr(getattr(snapshot, "config", None), "universe", None)
        configured_by_id = configured.by_id() if configured is not None and callable(getattr(configured, "by_id", None)) else {}
        if identity_column is not None:
            holdings = holdings.copy()
            holdings["asset_type"] = holdings[identity_column].map(
                lambda value: getattr(configured_by_id.get(str(value)), "instrument_type", None)
            )

    report = load_portfolio_valuation_history(storage_root=source)
    snapshots = report.get("snapshots")
    performance_snapshot: dict[str, object] | None = None
    as_of = _holdings_date(getattr(binding, "as_of", None))
    if isinstance(snapshots, pd.DataFrame) and not snapshots.empty and as_of and "date" in snapshots:
        dates = pd.to_datetime(snapshots["date"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
        selected = snapshots.loc[dates.eq(as_of)]
        if len(selected) == 1:
            performance_snapshot = selected.iloc[0].to_dict()
            performance_snapshot["date"] = as_of
            performance_snapshot["execution_allowed"] = False

    signals = tuple(getattr(snapshot, "signals", ()) or ())
    current_run_ids = {
        str(getattr(signal, "run_id", "")).strip()
        for signal in signals
        if str(getattr(signal, "run_id", "")).strip()
    }

    artifacts: list[dict[str, object]] = []
    try:
        paths = sorted(artifact_root.glob("decision_opportunity_*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or payload.get("artifact_version") != "decision-opportunity-shadow-v1"
            or payload.get("execution_allowed") is not False
        ):
            continue
        run_id = str(payload.get("run_id", "")).strip()
        run_date = _holdings_date(payload.get("decision_time"))
        if run_id and run_date and as_of and run_date <= as_of:
            artifacts.append(dict(payload))
    analysis_runs = [
        {
            "run_id": str(item.get("run_id", "")),
            "decision_time": str(item.get("decision_time", "")),
            "status": str(item.get("status", "unavailable")),
        }
        for item in sorted(artifacts, key=lambda item: (str(item.get("decision_time", "")), str(item.get("run_id", ""))), reverse=True)
    ]

    chosen_run_id = str(analysis_run_id or "").strip()
    if not chosen_run_id and len(current_run_ids) == 1:
        chosen_run_id = next(iter(current_run_ids))
    if not chosen_run_id and analysis_runs:
        chosen_run_id = str(analysis_runs[0]["run_id"])
    signal_by_id = {
        str(getattr(signal, "etf_id", "")).strip(): signal
        for signal in signals
        if str(getattr(signal, "run_id", "")).strip() == chosen_run_id
        and str(getattr(signal, "etf_id", "")).strip()
    } if chosen_run_id else {}
    selected_artifacts = [item for item in artifacts if str(item.get("run_id", "")) == chosen_run_id]
    artifact = selected_artifacts[0] if len(selected_artifacts) == 1 else None
    analysis_date = _holdings_date(artifact.get("decision_time")) if artifact is not None else None
    config_hashes = artifact.get("config_hashes") if artifact is not None else None
    policy_id = (
        str(config_hashes.get("decision_opportunity_v1", "")).strip()
        if isinstance(config_hashes, Mapping)
        else ""
    )
    raw_results = artifact.get("results") if artifact is not None else None
    results = {
        str(item.get("instrument", "")).strip(): dict(item)
        for item in raw_results or ()
        if isinstance(item, Mapping) and str(item.get("instrument", "")).strip()
    } if isinstance(raw_results, list) else {}
    opportunity_policy_matches = bool(
        policy_id
        and policy_id != "unavailable"
        and results
        and all(str(item.get("config_hash", "")).strip() == policy_id for item in results.values())
    )
    selected_signals_current = bool(
        chosen_run_id
        and current_run_ids == {chosen_run_id}
        and signal_by_id
        and all(_holdings_date(getattr(signal, "signal_date", None)) == analysis_date for signal in signal_by_id.values())
    )
    gate_policy_checksums = {
        str(getattr(signal, "gate_policy_checksum", "")).strip()
        for signal in signal_by_id.values()
    }
    gate_policy_id = next(iter(gate_policy_checksums)) if len(gate_policy_checksums) == 1 else ""
    gate_policy_matches = bool(gate_policy_id and gate_policy_id != "unavailable")
    analysis_status = (
        "complete"
        if artifact is not None and artifact.get("status") == "complete" and opportunity_policy_matches and selected_signals_current
        else "partial"
        if artifact is not None and artifact.get("status") == "partial"
        else "unavailable"
    )
    table_rows: dict[str, dict[str, object]] = {}
    for instrument_id, opportunity in results.items():
        signal = signal_by_id.get(instrument_id)
        if signal is None:
            continue
        canonical_score = getattr(signal, "canonical_score", None)
        scores = {
            "evidence": getattr(canonical_score, "evidence_confidence_10", None),
            "quality": getattr(canonical_score, "attractiveness_10", None),
            "risk": getattr(canonical_score, "risk_implementation_10", None),
            "total": getattr(signal, "total_score", None),
        }
        table_rows[instrument_id] = {
            "instrument_id": instrument_id,
            "analysis_run_id": chosen_run_id,
            "scores": scores,
            "rank": opportunity.get("universe_rank"),
            "peer_rank": opportunity.get("peer_rank"),
            "action": getattr(signal, "action", None),
            "blockers": tuple(getattr(signal, "blocked_by", ()) or ()),
            "coverage": opportunity.get("coverage"),
        }

    distributions: dict[str, object] = {}
    decision_time = artifact.get("decision_time") if artifact is not None else None
    if selected_signals_current and decision_time:
        try:
            distribution_rows = load_forecast_return_distributions(
                getattr(snapshot, "forecasts", pd.DataFrame()),
                horizon_days=horizon_days,
                decision_time=decision_time,
            )
        except (TypeError, ValueError, KeyError):
            distribution_rows = {}
        distributions = {
            instrument_id: distribution
            for instrument_id, distribution in distribution_rows.items()
            if instrument_id in table_rows
        }

    analysis_snapshot = {
        "analysis_run_id": chosen_run_id or None,
        "run_id": str(artifact.get("run_id", "")) if artifact is not None else None,
        "decision_time": artifact.get("decision_time") if artifact is not None else None,
        "status": analysis_status,
        "policy_id": policy_id or None,
        "policy_ids": {
            "opportunity": policy_id or None,
            "gate": gate_policy_id or None,
        },
        "policy_status": "available" if opportunity_policy_matches and selected_signals_current and gate_policy_matches else "unavailable",
        "rows": table_rows,
        "distributions": distributions,
    }
    try:
        fx_rates = load_fx_rates()
    except (OSError, ValueError, TypeError, ImportError):
        fx_rates = pd.DataFrame()
    try:
        currency_projection = project_portfolio_currency(analysis, output_currency, fx_rates)
    except (TypeError, ValueError, ArithmeticError):
        currency_projection = None

    projection = build_portfolio_holdings_table(
        holdings if isinstance(holdings, pd.DataFrame) else None,
        portfolio_snapshot=portfolio_snapshot,
        performance_snapshot=performance_snapshot,
        analysis_snapshot=analysis_snapshot,
        horizon_days=horizon_days,
        output_currency=output_currency,
        currency_projection=currency_projection,
        search=search,
        asset_type=asset_type,
        sort_by=sort_by,
        descending=descending,
        column_preset=column_preset,
    )
    projection["analysis_runs"] = analysis_runs
    projection["selected_analysis_run_id"] = chosen_run_id or None
    if artifact is None:
        projection["analysis_reason"] = "selected_analysis_run_unavailable"
    elif not selected_signals_current:
        projection["analysis_reason"] = "analysis_run_does_not_match_saved_signal_snapshot"
    elif not opportunity_policy_matches or not gate_policy_matches:
        projection["analysis_reason"] = "analysis_policy_hash_mismatch_or_unavailable"
    else:
        projection["analysis_reason"] = None
    return projection


def _holdings_date(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC")
    return parsed.date().isoformat()


def project_portfolio_currency(
    analysis: PortfolioAnalysis,
    target_currency: str,
    fx_rates: pd.DataFrame,
) -> CurrencyProjection:
    """Return the canonical informational currency projection for presentation."""
    return _project_portfolio_currency(analysis, target_currency, fx_rates)


def load_portfolio_exposure_projection(
    position_weights: Mapping[str, float],
    *,
    decision_time: str | datetime,
    analysis_date: str | date | datetime | None = None,
    portfolio_id: str | None = None,
    snapshot_id: str | None = None,
    position_metadata: Mapping[str, Mapping[str, object]] | None = None,
    holding_metadata: Mapping[str, Mapping[str, object]] | None = None,
    reporting_currency: str | None = None,
    holdings: pd.DataFrame | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    """Load the read-only exposure chart projection for a ledger-weight snapshot."""
    evidence = holdings if isinstance(holdings, pd.DataFrame) else load_direct_holdings(root=root)
    cube = build_portfolio_exposure_cube(
        evidence,
        position_weights,
        decision_time=decision_time,
        analysis_date=analysis_date,
        portfolio_id=portfolio_id,
        snapshot_id=snapshot_id,
        position_metadata=position_metadata,
        holding_metadata=holding_metadata,
        reporting_currency=reporting_currency,
    )
    return cube.to_projection()


def load_portfolio_risk_profile_projection(
    snapshot: object,
    analysis: object,
    *,
    profile_id: str = "medium",
    profile_version: object = None,
    version_history: Sequence[object] = (),
    profile_edits: Mapping[str, object] | None = None,
    reset_to_preset: bool = False,
) -> dict[str, object]:
    """Load the local, advisory profile projection for one bound candidate."""

    try:
        return build_risk_profile_workspace(
            snapshot,
            analysis,
            selected_profile_id=profile_id,
            selected_version=profile_version,
            version_history=version_history,
            profile_edits=profile_edits,
            reset_to_preset=reset_to_preset,
        )
    except (RiskProfileError, OSError, TypeError, ValueError) as exc:
        return unavailable_risk_profile_workspace(str(exc) or "risk_profile_projection_unavailable")
