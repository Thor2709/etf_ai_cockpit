"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from collections.abc import Mapping
import math
from numbers import Real
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import STATEMENT_FACTS_PATH
from etf_cockpit.data.etf_structure import project_etf_structure
from etf_cockpit.data.event_calendar import normalise_event_decision_time
from etf_cockpit.data.capital_allocation import capital_allocation_analysis
from etf_cockpit.data.market_adjustments import CorporateActionCoverage
from etf_cockpit.data.stock_research import valuation_analysis
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.features.cash_comparison import (
    cash_comparison_from_projection,  # noqa: F401
    cash_comparison_to_projection,  # noqa: F401
)

from etf_cockpit.analysis.fixed_income_analytics import (
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
)
from etf_cockpit.data.bond_analytics_store import read_bond_analytics
from etf_cockpit.analysis.fixed_income_risk import (
    FixedIncomeRiskError,
    FixedIncomeRiskInput,
    calculate_fixed_income_risk,
)
from etf_cockpit.data.fixed_income_risk_store import read_fixed_income_risk

from etf_cockpit.chatgpt_bridge.audit_packet import *  # noqa: F401,F403
from etf_cockpit.data.backup_restore import *  # noqa: F401,F403
from etf_cockpit.data.bitemporal import *  # noqa: F401,F403
from etf_cockpit.data.bulk_cache import *  # noqa: F401,F403
from etf_cockpit.data.decision_journal import *  # noqa: F401,F403
from etf_cockpit.data.forward_evidence_diary import *  # noqa: F401,F403
from etf_cockpit.data.event_calendar import *  # noqa: F401,F403
from etf_cockpit.data.etf_economics import *  # noqa: F401,F403
from etf_cockpit.data.export_tables import *  # noqa: F401,F403
from etf_cockpit.data.fund_documents import *  # noqa: F401,F403
from etf_cockpit.data.fund_holdings import *  # noqa: F401,F403
from etf_cockpit.data.fundamentals import *  # noqa: F401,F403
from etf_cockpit.data.fx_data import *  # noqa: F401,F403
from etf_cockpit.data.market_adjustments import *  # noqa: F401,F403
from etf_cockpit.application.market_clock import *  # noqa: F401,F403
from etf_cockpit.data.health import *  # noqa: F401,F403
from etf_cockpit.data.hybrid_platform import *  # noqa: F401,F403
from etf_cockpit.data.import_export import *  # noqa: F401,F403
from etf_cockpit.data.legal_terms import *  # noqa: F401,F403
from etf_cockpit.data.catalogue import *  # noqa: F401,F403
from etf_cockpit.data.macro_warehouse import *  # noqa: F401,F403
from etf_cockpit.data.anomaly_ledger import *  # noqa: F401,F403
from etf_cockpit.data.stock_research import *  # noqa: F401,F403
from etf_cockpit.backtest.event_engine import *  # noqa: F401,F403
from etf_cockpit.governance.release_certification import *  # noqa: F401,F403
from etf_cockpit.governance.supply_chain_intake import *  # noqa: F401,F403
from etf_cockpit.data.local_storage import *  # noqa: F401,F403
from etf_cockpit.data.identity_master import (
    IdentityMasterSchemaError,
    IdentityMasterStore,
    identity_master_exists,
)
from etf_cockpit.data.fixed_income_terms import (
    FixedIncomeTermsSchemaError,
    FixedIncomeTermsStore,
    fixed_income_terms_exists,
)
from etf_cockpit.data.fixed_income_market_data import (
    FixedIncomeMarketDataSchemaError,
    FixedIncomeMarketDataStore,
    fixed_income_market_data_exists,
)
from etf_cockpit.data.classification import (
    ClassificationOverride,
    ClassificationSchemaError,
    ClassificationStore,
    classification_store_exists,
    read_instrument_context,
    read_classification_projection,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.peer_cohort_store import read_peer_cohort_projection
from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialMetricEvidence,
    FinancialAdapterError,
    FinancialInstitutionProjection,
    build_financial_institution_projection,
    financial_adapter_definition,
    unavailable_financial_projection,
    verify_financial_projection,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.analysis.real_asset_sector_adapters import (
    RealAssetAdapterError,
    RealAssetProjection,
    unavailable_real_asset_projection,
    verify_real_asset_projection,
)
from etf_cockpit.analysis.cyclical_sector_adapters import (
    CyclicalAdapterError,
    CyclicalProjection,
    unavailable_cyclical_projection,
    verify_cyclical_projection,
)
from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationAdapterError,
    InnovationProjection,
    unavailable_innovation_projection,
    verify_innovation_projection,
)


from etf_cockpit.data.manual_notes import *  # noqa: F401,F403
from etf_cockpit.data.news_context import *  # noqa: F401,F403
from etf_cockpit.data.oam_adapters import *  # noqa: F401,F403
from etf_cockpit.data.parsed_disclosures import *  # noqa: F401,F403
from etf_cockpit.data.etf_structure import *  # noqa: F401,F403
from etf_cockpit.data.provider_registry import *  # noqa: F401,F403
from etf_cockpit.data.privacy import *  # noqa: F401,F403
from etf_cockpit.data.reference_data import *  # noqa: F401,F403
from etf_cockpit.data.run_changes import *  # noqa: F401,F403
from etf_cockpit.application.run_change_context import upstream_run_context  # noqa: F401
from etf_cockpit.data.score_history import *  # noqa: F401,F403
from etf_cockpit.data.source_policy import *  # noqa: F401,F403
from etf_cockpit.data.statement_normalisation import *  # noqa: F401,F403
from etf_cockpit.data.trust_artifacts import *  # noqa: F401,F403
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.universe_store import *  # noqa: F401,F403
from etf_cockpit.data.universe_import import *  # noqa: F401,F403
from etf_cockpit.application.api import *  # noqa: F401,F403
from etf_cockpit.application.contracts import *  # noqa: F401,F403
from etf_cockpit.application.screening import *  # noqa: F401,F403
from etf_cockpit.application.screening_data import *  # noqa: F401,F403
from etf_cockpit.data.screen_store import *  # noqa: F401,F403
from etf_cockpit.core.versioning import *  # noqa: F401,F403
from etf_cockpit.core.job_scheduler import *  # noqa: F401,F403
from etf_cockpit.core.resource_profiles import *  # noqa: F401,F403
from etf_cockpit.models.forecast_scores import *  # noqa: F401,F403
from etf_cockpit.models.model_zoo import *  # noqa: F401,F403
from etf_cockpit.models.coverage_audit import *  # noqa: F401,F403
from etf_cockpit.models.local_weights import *  # noqa: F401,F403
from etf_cockpit.portfolio.allocation import *  # noqa: F401,F403
from etf_cockpit.portfolio.costs import *  # noqa: F401,F403
from etf_cockpit.portfolio.factor_risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.factor_risk import build_factor_risk_report
from etf_cockpit.portfolio.attribution import *  # noqa: F401,F403
from etf_cockpit.portfolio.rebalancing import *  # noqa: F401,F403
from etf_cockpit.portfolio.proposal_policy import *  # noqa: F401,F403
from etf_cockpit.portfolio.robust_risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.risk_analytics import *  # noqa: F401,F403
from etf_cockpit.application.portfolio_sandbox import *  # noqa: F401,F403
from etf_cockpit.portfolio.sandbox import select_holdings_view  # noqa: F401
from etf_cockpit.application.overlap import *  # noqa: F401,F403
from etf_cockpit.signals.simple_scores import *  # noqa: F401,F403
from etf_cockpit.signals.feature_drivers import (  # noqa: F401
    _canonical_cohort_time,
    _classification,
    _combined_authority_classification,
    _component_id,
    _derive_peer_percentiles,
    _flags,
    _freshness_classification,
    _normalise_interaction,
    _normalise_peer_percentile_alias,
    _scalar_text,
    _source_provenance_text,
    _source_vintage_hash,
    normalise_bound_claim,
)


def _normalise_valuation_assumptions(value: object) -> dict[str, object]:
    """Accept only the bounded, explicit session scenario contract."""
    if not isinstance(value, Mapping) or set(value) != {"forecast_years", "discount_rate", "terminal_growth", "scenarios"}:
        raise ValueError("Explicit forecast years, discount, terminal growth and three scenarios are required")
    years = value["forecast_years"]
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 50:
        raise ValueError("Forecast years must be an integer from 1 to 50")

    def number(raw: object) -> float:
        if isinstance(raw, bool) or not isinstance(raw, Real) or not math.isfinite(raw):
            raise ValueError("Scenario inputs must be finite numbers")
        return float(raw)

    discount = number(value["discount_rate"])
    terminal = number(value["terminal_growth"])
    if not 0 < discount <= 1 or not -1 <= terminal < discount:
        raise ValueError("Discount or terminal growth is outside the allowed range")
    scenarios = value["scenarios"]
    if not isinstance(scenarios, Mapping) or set(scenarios) != {"bear", "base", "bull"}:
        raise ValueError("Exactly bear, base and bull scenarios are required")
    growths = []
    for name in ("bear", "base", "bull"):
        row = scenarios[name]
        if not isinstance(row, Mapping) or set(row) != {"growth"}:
            raise ValueError("Only explicit growth is allowed for each scenario")
        growths.append(number(row["growth"]))
    if not -0.5 <= growths[0] < growths[1] < growths[2] <= 1:
        raise ValueError("Growth must satisfy -50% <= bear < base < bull <= 100%")
    return {"forecast_years": years, "discount_rate": discount, "terminal_growth": terminal,
            "scenarios": {name: {"growth": growth} for name, growth in zip(("bear", "base", "bull"), growths, strict=True)}}


def _finite_valuation_result(value: object) -> bool:
    if isinstance(value, Mapping):
        return all(_finite_valuation_result(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite_valuation_result(item) for item in value)
    return not isinstance(value, Real) or math.isfinite(value)


def load_valuation_evidence(path: Path, *, instrument_id: str, decision_time: object, assumptions: object = None) -> dict[str, object]:
    """Validate raw scoped facts before the date-grained stock research producer.

    Exact UTC knowledge filtering precedes the producer's date adapter. A
    date-only availability is conservatively eligible at UTC end-of-day;
    malformed selected evidence blocks the entire panel, never just that row.
    """
    def unavailable(reason: str) -> dict[str, object]:
        return {"status": "unavailable", "message": reason, "execution_allowed": False}

    cutoff = normalise_event_decision_time(decision_time)
    if cutoff is None:
        return unavailable("Snapshot decision time is unavailable; point-in-time valuation cannot be established.")
    context = {}
    if assumptions is not None:
        try:
            assumptions = _normalise_valuation_assumptions(assumptions)
        except (ValueError, TypeError, OverflowError):
            return unavailable("Invalid explicit scenario assumptions; valuation unavailable.")
        context = {"kind": "local_user_scenario_assumption", "instrument_id": instrument_id,
                   "decision_time": cutoff.isoformat(), "session_preview_only": True,
                   "score_authority": False, "execution_allowed": False, "assumptions": assumptions}
    try:
        raw = pd.read_parquet(path)
        if raw.empty:
            return unavailable("Canonical local statement evidence is unavailable.")
        if raw.columns.duplicated().any() or "instrument_id" not in raw:
            return unavailable("Statement identity is malformed; valuation unavailable.")
        frame = raw.loc[raw["instrument_id"].map(lambda value: isinstance(value, str) and value == instrument_id)].copy()
        if frame.empty:
            return unavailable("No canonical local statements exist for this instrument.")
        required = {"canonical_metric", "value", "available_at", "source_id"}
        if not required.issubset(frame.columns):
            return unavailable("Required statement evidence fields are missing; valuation unavailable.")
        for alias in ("etf_id", "display_id"):
            if alias in frame and any(not pd.api.types.is_scalar(value) or (pd.notna(value) and value != instrument_id) for value in frame[alias]):
                return unavailable("Statement identity conflicts; valuation unavailable.")
        fields = (
            "instrument_id", "canonical_metric", "value", "available_at", "source_id", "concept", "unit",
            "start", "end", "instant", "filed", "form", "accession", "fiscal_year", "fiscal_period",
            "dimensions", "currency", "period_type", "mapping_status", "mapping_confidence",
            "manual_review_required", "restatement_kind",
        )
        frame = frame[[field for field in fields if field in frame]].copy()
        knowledge = []
        for row in frame.to_dict("records"):
            if any(not pd.api.types.is_scalar(value) for value in row.values()):
                return unavailable("Malformed statement row; valuation unavailable.")
            value = row["value"]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                return unavailable("Invalid or nonfinite statement numeric input; valuation unavailable.")
            if any(not isinstance(row[field], str) or not row[field].strip() for field in ("canonical_metric", "source_id")):
                return unavailable("Statement metric or provenance is missing; valuation unavailable.")
            available = row["available_at"]
            known_at = normalise_event_decision_time(available)
            if known_at is None:
                return unavailable("Statement availability is unknown or malformed; valuation unavailable.")
            knowledge.append(known_at)
            for field in ("start", "end", "instant", "filed"):
                date_value = row.get(field)
                if date_value is not None and pd.notna(date_value):
                    if not isinstance(date_value, str) or pd.isna(pd.to_datetime(date_value, errors="coerce", utc=True)):
                        return unavailable("Malformed statement period or filing date; valuation unavailable.")
            if not any(isinstance(row.get(field), str) and row[field].strip() for field in ("end", "instant")):
                return unavailable("Statement period is missing; valuation unavailable.")
        frame = frame.loc[[known_at <= cutoff for known_at in knowledge]].copy()
        if frame.empty:
            return unavailable("No statement evidence was available at the snapshot decision time.")
        # Share counts are a sourced-input validity rule, not a valuation formula.
        # Check only selected, cutoff-eligible facts; future/foreign counts cannot
        # invalidate the current preview. The producer uses this exact metric name.
        share_counts = frame.loc[frame["canonical_metric"].eq("shares_outstanding"), "value"]
        if share_counts.le(0).any():
            return unavailable("Nonpositive sourced share count; valuation unavailable.")
        # All surviving rows have already passed exact knowledge filtering.
        # Adapt only the producer's internal availability representation, not
        # the persisted facts or the disclosed decision cutoff.
        precisions = {"date_only_utc_end_of_day" if len(str(value).strip()) == 10 else "timestamp" for value in frame["available_at"]}
        frame["available_at"] = [normalise_event_decision_time(value).date().isoformat() for value in frame["available_at"]]
        result = valuation_analysis(frame, instrument_id=instrument_id, as_known_at=cutoff.isoformat(), assumptions=assumptions)
        if not _finite_valuation_result(result):
            return unavailable("Nonfinite derived valuation evidence; valuation unavailable.")
        result["source_lineage"]["as_known_at"] = cutoff.isoformat()
        result["source_lineage"]["knowledge_precision"] = sorted(precisions)
        result["source_lineage"]["cutoff_policy"] = "Exact UTC filtering before date-grained canonical calculation; date-only knowledge uses UTC end-of-day."
        return result | {"status": "available", "assumption_context": context}
    except ArithmeticError:
        return unavailable("Arithmetic failure in canonical valuation; valuation unavailable.")
    except (OSError, ValueError, TypeError, ImportError, KeyError):
        return unavailable("Canonical statement store is unreadable or malformed; valuation unavailable.")


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


def load_identity_projection(
    instrument_id: str,
    path: Path | None = None,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return one fail-closed, read-only identity lineage projection for presentation."""

    import pandas as pd

    master_root = Path(storage_root).resolve() if storage_root is not None else None
    if master_root is None and path is None:
        default_path = Path(IDENTITY_PATH).resolve()
        if len(default_path.parents) >= 3:
            master_root = default_path.parents[2]
    if master_root is not None:
        try:
            if identity_master_exists(master_root):
                with IdentityMasterStore(master_root) as master:
                    return master.projection(
                        instrument_id,
                        effective_at=effective_at,
                        decision_time=decision_time,
                    )
            if storage_root is not None and path is None:
                return {
                    "status": "unavailable",
                    "instrument_id": str(instrument_id),
                    "reason_code": "identity_master_evidence_unavailable",
                    "execution_allowed": False,
                }
        except KeyError:
            if storage_root is not None and path is None:
                return {
                    "status": "unavailable",
                    "instrument_id": str(instrument_id),
                    "reason_code": "identity_master_evidence_unavailable",
                    "execution_allowed": False,
                }
        except (IdentityMasterSchemaError, OSError, ValueError):
            return {
                "status": "unavailable",
                "instrument_id": str(instrument_id),
                "reason_code": "identity_master_evidence_invalid",
                "execution_allowed": False,
            }

    identity_path = Path(path or IDENTITY_PATH)
    try:
        frame = pd.read_parquet(identity_path)
    except (OSError, ValueError, ImportError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "identity_evidence_unavailable",
            "execution_allowed": False,
        }
    if "instrument_id" not in frame.columns:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "identity_schema_unavailable",
            "execution_allowed": False,
        }
    matches = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    if len(matches) != 1:
        return {
            "status": "quarantined" if len(matches) > 1 else "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "duplicate_identity_projection" if len(matches) > 1 else "identity_evidence_unavailable",
            "candidate_count": len(matches),
            "execution_allowed": False,
        }
    row = matches.iloc[0]
    fields = (
        "identity_confidence",
        "identity_status",
        "identity_decision_id",
        "identity_conflict_ids",
        "identity_resolution_state",
        "identity_effective_at",
        "identity_decision_time",
        "identity_objects",
        "identity_history",
        "warnings",
    )
    projection: dict[str, object] = {
        "status": "available",
        "instrument_id": str(instrument_id),
        "execution_allowed": False,
    }
    for field in fields:
        value = row.get(field)
        projection[field] = "unavailable" if value is None or bool(pd.isna(value)) else value
    return projection


def load_fixed_income_terms_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return read-only contractual terms/schedules or an explicit unavailable state."""

    from datetime import datetime

    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    unavailable = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_terms_unavailable"],
        "capability_flags": {
            "terms_available": False,
            "contractual_schedule_available": False,
            "pricing_allowed": False,
            "screening_allowed": False,
            "proposal_allowed": False,
            "execution_allowed": False,
        },
        "pricing_allowed": False,
        "screening_allowed": False,
        "proposal_allowed": False,
        "execution_allowed": False,
    }
    try:
        if not fixed_income_terms_exists(root):
            return unavailable
        effective = (
            datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
            if effective_at
            else None
        )
        decision = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        classification = (
            read_instrument_context(
                root,
                instrument_id,
                effective_at=effective,
                decision_time=decision,
            )
            if classification_store_exists(root)
            else None
        )
        with FixedIncomeTermsStore(root) as store:
            return store.projection(
                instrument_id,
                effective_at=effective,
                decision_time=decision,
                classification=classification,
            )
    except (
        ClassificationSchemaError,
        FixedIncomeTermsSchemaError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ):
        return unavailable | {"reason_codes": ["fixed_income_terms_invalid"]}


def load_fixed_income_market_data_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return read-only fixed-income market evidence for presentation."""

    from datetime import datetime
    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    unavailable = {
        "contract": "fixed-income-market-data.v1",
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_market_data_unavailable"],
        "observations": [],
        "provider_coverage": {"status": "unavailable", "rows": []},
        "precise_liquidity_available": False,
        "execution_allowed": False,
    }
    try:
        if not fixed_income_market_data_exists(root):
            return unavailable
        effective = (
            datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
            if effective_at
            else None
        )
        decision = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        with FixedIncomeMarketDataStore(root) as store:
            return store.resolve(
                instrument_id,
                effective_at=effective,
                decision_time=decision,
            )
    except (FixedIncomeMarketDataSchemaError, OSError, TypeError, ValueError):
        return unavailable


def calculate_fixed_income_analytics_projection(
    valuation: FixedIncomeValuationInput,
) -> dict[str, object]:
    """Calculate and serialize analytics behind the application boundary."""

    from dataclasses import asdict

    projection = _analytics_jsonable(
        asdict(calculate_fixed_income_analytics(valuation))
    )
    if not isinstance(projection, dict):
        raise FixedIncomeAnalyticsError("analytics projection is invalid")
    return projection


def calculate_fixed_income_risk_projection(
    risk_input: FixedIncomeRiskInput,
) -> dict[str, object]:
    """Calculate a serialisable non-executable fixed-income risk projection."""

    from dataclasses import asdict

    projection = _analytics_jsonable(asdict(calculate_fixed_income_risk(risk_input)))
    if not isinstance(projection, dict):
        raise FixedIncomeRiskError("risk projection is invalid")
    return projection


def load_fixed_income_risk_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load verified local risk evidence for presentation only."""

    from datetime import datetime
    from etf_cockpit.core.paths import ROOT

    unavailable = {
        "contract": "fixed-income-risk.v1",
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_risk_unavailable"],
        "execution_allowed": False,
    }
    path = Path(storage_root or ROOT) / "data" / "analytics" / "fixed_income_risk.parquet"
    if not path.exists():
        return unavailable
    try:
        cutoff = datetime.fromisoformat(decision_time.replace("Z", "+00:00")) if decision_time else None
        rows = [
            row for row in read_fixed_income_risk(path)
            if row["instrument_id"] == str(instrument_id)
            and (cutoff is None or datetime.fromisoformat(str(row["decision_time"])) <= cutoff)
        ]
        if not rows:
            return unavailable
        result = max(rows, key=lambda row: (str(row["decision_time"]), str(row["calculated_at"])))["result"]
        return dict(result) if isinstance(result, dict) else unavailable
    except (FixedIncomeRiskError, OSError, TypeError, ValueError):
        return unavailable | {"reason_codes": ["fixed_income_risk_invalid"]}


def load_fixed_income_analytics_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load the latest local analytics record, failing closed when unavailable."""

    from datetime import datetime

    from etf_cockpit.core.paths import ROOT

    unavailable = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_analytics_unavailable"],
        "execution_allowed": False,
    }
    path = Path(storage_root or ROOT) / "data" / "analytics" / "bond_analytics.parquet"
    if not path.exists():
        return unavailable
    try:
        cutoff = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        matches = [
            row
            for row in read_bond_analytics(path)
            if row["instrument_id"] == str(instrument_id)
            and (
                cutoff is None
                or datetime.fromisoformat(str(row["decision_time"])) <= cutoff
            )
        ]
        if not matches:
            return unavailable
        latest = max(
            matches,
            key=lambda row: (
                str(row["decision_time"]),
                str(row["calculated_at"]),
                str(row["record_id"]),
            ),
        )
        result = latest["result"]
        return dict(result) if isinstance(result, dict) else unavailable
    except (FixedIncomeAnalyticsError, OSError, TypeError, ValueError):
        return unavailable | {"reason_codes": ["fixed_income_analytics_invalid"]}


def _analytics_jsonable(value: object) -> object:
    from datetime import date, datetime
    from decimal import Decimal
    from enum import Enum
    from collections.abc import Mapping

    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _analytics_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_analytics_jsonable(item) for item in value]
    return value


def load_classification_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
    min_leaf_confidence: float = 0.75,
) -> dict[str, object]:
    """Return fail-closed point-in-time classification for presentation."""

    root = Path(storage_root).resolve() if storage_root is not None else None
    if root is None:
        default_path = Path(IDENTITY_PATH).resolve()
        if len(default_path.parents) >= 3:
            root = default_path.parents[2]
    if root is None:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_storage_unavailable",
            "execution_allowed": False,
        }
    try:
        return read_classification_projection(
            root,
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
            min_leaf_confidence=min_leaf_confidence,
        )
    except (ClassificationSchemaError, OSError, ValueError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_evidence_invalid",
            "execution_allowed": False,
        }


def load_peer_cohort_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return persisted peer lineage only; presentation never calculates statistics."""

    from etf_cockpit.core.paths import ROOT

    try:
        return read_peer_cohort_projection(
            Path(storage_root or ROOT).resolve(),
            instrument_id,
            decision_time=decision_time,
        )
    except (OSError, TypeError, ValueError):
        return {
            "contract": "peer-cohort.v1",
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "peer_cohort_evidence_invalid",
            "execution_allowed": False,
        }


def load_stock_research_context(
    instrument_id: str,
    *,
    statements_path: Path | None = None,
) -> dict[str, object]:
    """Load stock statements and their point-in-time classification/peer context."""
    classification_projection = load_classification_projection(instrument_id)
    classification_value = classification_projection.get("classification")
    classification = dict(classification_value) if isinstance(classification_value, Mapping) else {}
    classification_status = str(classification_projection.get("status", "unavailable"))
    effective_at = str(classification.get("effective_at") or "").strip() or None
    decision_time = str(classification.get("decision_time") or "").strip() or None
    peer_projection = load_peer_cohort_projection(instrument_id, decision_time=decision_time)
    peer_projection_status = str(peer_projection.get("status", "unavailable"))
    cohort = peer_projection.get("cohort")
    members = cohort.get("members") if isinstance(cohort, Mapping) else None
    peer_ids = {
        str(value)
        for value in members or ()
        if str(value).strip() and str(value) != str(instrument_id)
    } if peer_projection_status == "available" and classification_status == "available" else set()

    from etf_cockpit.data.stock_research import load_stock_research_frame

    facts = load_stock_research_frame(
        statements_path or STATEMENT_FACTS_PATH,
        as_known_at=decision_time,
    )
    if "instrument_id" in facts.columns:
        statements = facts[facts["instrument_id"].astype(str).eq(str(instrument_id))].reset_index(drop=True)
        peer_frame = facts[facts["instrument_id"].astype(str).isin(peer_ids)].reset_index(drop=True)
    else:
        statements = facts.iloc[0:0].copy()
        peer_frame = facts.iloc[0:0].copy()
    peer_frame.attrs["peer_context_status"] = peer_projection_status if peer_ids else "unavailable"
    sector = str(classification.get("sector") or "").strip() if classification_status == "available" else ""
    financial_labels = {sector.casefold()}
    for name in ("industry", "issuer_sector", "issuer_type", "business_model_tags", "strategy_labels"):
        value = classification.get(name, ())
        values = (value,) if isinstance(value, str) else value
        if isinstance(values, (tuple, list, set)):
            for item in values:
                label = str(item or "").strip().casefold()
                if label:
                    financial_labels.update({label, label.replace("-", "_")})
    financial_projection: dict[str, object] = {}
    if financial_labels & {"bank", "banks", "banking", "savings_bank", "savings banks", "deposit_taking", "insurance", "insurer", "financial", "financials", "financial_institution", "financial institution", "financial_services", "financial services"}:
        financial_projection = load_financial_institution_projection(
            instrument_id,
            decision_time=decision_time,
            effective_at=effective_at,
        )
    return {
        "instrument_id": str(instrument_id),
        "statements": statements,
        "classification": classification,
        "classification_status": classification_status,
        "sector": sector,
        "peer_context": dict(peer_projection),
        "peer_frame": peer_frame,
        "peer_context_status": peer_projection_status if peer_ids else "unavailable",
        "financial_projection": financial_projection,
        "effective_at": effective_at,
        "decision_time": decision_time,
        "execution_allowed": False,
    }


def load_financial_institution_projection(
    instrument_id: str,
    *,
    projection: FinancialInstitutionProjection | Mapping[str, object] | None = None,
    storage_root: Path | None = None,
    decision_time: str | None = None,
    effective_at: str | None = None,
    context: object | None = None,
) -> dict[str, object]:
    """Load a verified projection, or build one from local point-in-time evidence."""

    if projection is None:
        try:
            return _build_financial_projection_from_evidence(
                instrument_id,
                storage_root=storage_root,
                decision_time=decision_time,
                effective_at=effective_at,
                context=context,
            )
        except (FinancialAdapterError, OSError, TypeError, ValueError, KeyError):
            return unavailable_financial_projection(
                instrument_id, "financial_evidence_invalid"
            )
    try:
        payload = verify_financial_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise FinancialAdapterError("financial projection identity mismatch")
        return payload
    except (FinancialAdapterError, TypeError, ValueError):
        return unavailable_financial_projection(
            instrument_id, "financial_evidence_invalid"
        )


def load_capital_allocation_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str,
    sector: str = "",
    market_inputs: Mapping[str, object] | None = None,
    corporate_actions: object = (),
    corporate_action_coverage: object | None = None,
    decision_time: str | None = None,
    storage_root: Path | None = None,
    financial_projection: object | None = None,
) -> dict[str, object]:
    """Adapt local capital-allocation evidence and delegate financial sectors."""

    resolved_sector = str(sector or "").strip()
    if not resolved_sector or resolved_sector.casefold() == "unclassified":
        classification = load_classification_projection(
            instrument_id,
            storage_root=storage_root,
            decision_time=decision_time,
        )
        context = classification.get("classification", {})
        route = classification.get("sector_adapter_route", {})
        if isinstance(context, Mapping) and isinstance(route, Mapping) and route.get("allowed") is True:
            resolved_sector = str(context.get("sector") or context.get("industry") or "")

    actions = tuple(corporate_actions) if isinstance(corporate_actions, (list, tuple)) else ()
    coverage = corporate_action_coverage if isinstance(corporate_action_coverage, CorporateActionCoverage) else None
    bank_projection = None
    if resolved_sector.casefold() in {"bank", "banks", "financial", "financials", "insurance", "insurer"}:
        bank_projection = load_financial_institution_projection(
            instrument_id,
            projection=financial_projection,
            storage_root=storage_root,
            decision_time=decision_time,
        )
    return capital_allocation_analysis(
        statements,
        instrument_id=instrument_id,
        sector=resolved_sector,
        market_inputs=market_inputs,
        corporate_actions=actions,
        corporate_action_coverage=coverage,
        as_known_at=decision_time,
        financial_projection=bank_projection,
    )


def _build_financial_projection_from_evidence(
    instrument_id: str,
    *,
    storage_root: Path | None,
    decision_time: str | None,
    effective_at: str | None,
    context: object | None,
) -> dict[str, object]:
    """Adapt #699's persisted statement/EC artifacts to the domain adapter."""
    from datetime import datetime, timezone
    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    identity = _read_json_artifact(root, "identity.json", instrument_id=instrument_id) or {}
    cutoff = str(decision_time or identity.get("known_at") or "").strip()
    if not cutoff:
        return unavailable_financial_projection(instrument_id, "financial_decision_time_unavailable")
    decision = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    cutoff = decision.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    effective = str(effective_at or identity.get("effective_at") or cutoff).strip()
    requested_period = str(effective_at or identity.get("effective_at") or "").strip() or None
    if len(effective) == 10:
        effective = f"{effective}T00:00:00Z"

    if context is None:
        context = read_instrument_context(
            root,
            instrument_id,
            effective_at=effective,
            decision_time=cutoff,
        )
    if str(getattr(context, "sector", "") or "").casefold() != "financials":
        return unavailable_financial_projection(instrument_id, "financial_classification_unavailable")

    frame = _read_financial_statement_frame(root, instrument_id=instrument_id)
    rows = _financial_rows_for_instrument(frame, instrument_id, decision)
    facts = _financial_metric_facts(rows, context, cutoff, target_period=requested_period)
    if not facts:
        return unavailable_financial_projection(instrument_id, "financial_statement_evidence_unavailable")

    registry = AdapterRegistry([financial_adapter_definition()])
    result = build_financial_institution_projection(
        context,
        tuple(facts),
        registry=registry,
        decision_time=cutoff,
        shocks={},
    )
    ec_payload = _read_json_artifact(root, "ec_facts.json", instrument_id=instrument_id) or {}
    ec_facts = _select_ec_facts(ec_payload, instrument_id, decision)
    if isinstance(ec_facts, Mapping) and ec_facts:
        identity_payload = dict(result.share_class_identity) if isinstance(result.share_class_identity, Mapping) else {}
        identity_payload["facts"] = {
            name: {
                "available": bool(value.get("available")) if isinstance(value, Mapping) else False,
                "value": value.get("value") if isinstance(value, Mapping) else None,
                "unit": value.get("unit") if isinstance(value, Mapping) else None,
                "period": value.get("period") if isinstance(value, Mapping) else None,
                "known_at": value.get("known_at") if isinstance(value, Mapping) else None,
                "source": value.get("source_url") if isinstance(value, Mapping) else None,
            }
            for name, value in ec_facts.items()
        }
        from dataclasses import replace
        result = replace(result, share_class_identity=identity_payload)
        from etf_cockpit.analysis.financial_sector_adapters import _hash as _financial_hash
        payload = result.__dict__.copy()
        payload.pop("result_hash", None)
        result = replace(result, result_hash=_financial_hash(payload))
    return verify_financial_projection(result)


def _evidence_roots(root: Path, instrument_id: str = "") -> tuple[Path, ...]:
    canonical = root / "evidence" / "norway"
    roots: list[Path] = [root]
    if instrument_id:
        prefix = f"{str(instrument_id).strip().upper()}-"
        try:
            roots.extend(sorted((item for item in canonical.iterdir() if item.is_dir() and item.name.upper().startswith(prefix)), key=lambda item: item.name))
        except OSError:
            pass
    roots.extend((canonical, root / "evidence"))
    return tuple(dict.fromkeys(roots))


def _select_ec_facts(payload: Mapping[str, object], instrument_id: str, decision: object) -> Mapping[str, object]:
    """Select the identity-bound EC revision known at the decision cutoff."""

    cutoff = pd.Timestamp(decision)
    revisions = payload.get("revisions")
    eligible: list[Mapping[str, object]] = []
    if isinstance(revisions, list):
        for revision in revisions:
            if not isinstance(revision, Mapping) or str(revision.get("instrument_id") or "") != str(instrument_id):
                continue
            known = pd.to_datetime(revision.get("known_at"), errors="coerce", utc=True)
            if pd.isna(known) or known > cutoff:
                continue
            facts = revision.get("facts")
            if isinstance(facts, Mapping):
                eligible.append(revision)
    if eligible:
        selected = max(eligible, key=lambda item: pd.Timestamp(item.get("known_at")))
        return selected.get("facts", {}) if isinstance(selected.get("facts"), Mapping) else {}
    # Backward-compatible read of a single pre-revision artifact, still bound
    # to the requested instrument and point-in-time cutoff.
    if str(payload.get("instrument_id") or instrument_id) != str(instrument_id):
        return {}
    known = pd.to_datetime(payload.get("known_at"), errors="coerce", utc=True)
    facts = payload.get("facts")
    return facts if isinstance(facts, Mapping) and not pd.isna(known) and known <= cutoff else {}


def _read_json_artifact(root: Path, name: str, *, instrument_id: str = "") -> dict[str, object] | None:
    import json

    candidates = tuple(item / name for item in _evidence_roots(root, instrument_id))
    for candidate in candidates:
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _read_financial_statement_frame(root: Path, *, instrument_id: str = "") -> pd.DataFrame:
    candidates = tuple(item / "statement_facts.parquet" for item in _evidence_roots(root, instrument_id)) + (
        root / "data" / "clean" / "statement_facts.parquet",
        root / "normalised_statements.parquet",
    )
    for candidate in candidates:
        try:
            if candidate.exists():
                frame = pd.read_parquet(candidate)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    return frame
        except (OSError, ValueError, ImportError):
            continue
    return pd.DataFrame()


def _financial_rows_for_instrument(
    frame: pd.DataFrame, instrument_id: str, decision: object
) -> list[dict[str, object]]:
    if frame.empty or "instrument_id" not in frame.columns:
        return []
    scoped = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    cutoff = pd.Timestamp(decision)
    rows: list[dict[str, object]] = []
    for row in scoped.to_dict("records"):
        known_raw = row.get("known_at") or row.get("available_at") or row.get("filed")
        effective_raw = row.get("effective_at") or row.get("end") or row.get("instant")
        known = pd.to_datetime(known_raw, errors="coerce", utc=True)
        effective = pd.to_datetime(effective_raw, errors="coerce", utc=True)
        if pd.isna(known) or known > cutoff or pd.isna(effective) or effective > cutoff:
            continue
        row["_known"] = known
        row["_effective"] = effective
        rows.append(row)
    return rows


def _row_period(row: Mapping[str, object]) -> pd.Timestamp | None:
    value = row.get("effective_at") or row.get("end") or row.get("instant") or row.get("period")
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _financial_metric_facts(
    rows: list[dict[str, object]], context: object, cutoff: str, *, target_period: str | None = None
) -> list[FinancialMetricEvidence]:
    from etf_cockpit.analysis.financial_sector_adapters import _METRICS, _REGULATORY

    model = "bank"
    candidates: dict[str, dict[str, object]] = {}
    aliases = {
        "liquidity_coverage_ratio": "liquidity_coverage_ratio",
        "lcr": "liquidity_coverage_ratio",
        "nsfr": "net_stable_funding_ratio",
        "net_stable_funding_ratio": "net_stable_funding_ratio",
        "cet1": "cet1_ratio",
        "cet1_ratio": "cet1_ratio",
        "total_capital": "total_capital_ratio",
        "total_capital_ratio": "total_capital_ratio",
        "leverage": "leverage_ratio",
        "leverage_ratio": "leverage_ratio",
        "net_interest_margin": "net_interest_margin",
        "npl_ratio": "npl_ratio",
        "stage_2_exposure": "stage_2_exposure",
        "stage_3_exposure": "stage_3_exposure",
        "cost_of_risk": "cost_of_risk",
        "dividend": "dividends",
        "dividends": "dividends",
        "retained_earnings": "retained_earnings",
        "net_fee_income": "net_fee_income",
        "fee_income": "net_fee_income",
        "other_operating_income": "other_operating_income",
        "other_income": "other_operating_income",
        "net_profit": "net_profit",
        "net_profit_attributable": "net_profit_attributable",
        "net_income_attributable": "net_profit_attributable",
        "profit_attributable": "net_profit_attributable",
        "opening_equity": "opening_equity",
        "closing_equity": "closing_equity",
        "equity": "closing_equity",
        "opening_tangible_equity": "opening_tangible_equity",
        "closing_tangible_equity": "closing_tangible_equity",
        "tangible_equity": "closing_tangible_equity",
        "interest_earning_assets": "interest_earning_assets",
        "average_interest_earning_assets": "interest_earning_assets",
        "opening_interest_earning_assets": "opening_interest_earning_assets",
        "closing_interest_earning_assets": "closing_interest_earning_assets",
        "total_assets": "total_assets",
        "opening_total_assets": "opening_total_assets",
        "closing_total_assets": "closing_total_assets",
        "gross_loans": "gross_loans",
        "opening_gross_loans": "opening_gross_loans",
        "closing_gross_loans": "closing_gross_loans",
        "impairment_losses": "impairment_losses",
        "loss_allowance": "loss_allowance",
        "shares_outstanding": "shares_outstanding",
        "payout": "payout_headroom",
        "payout_ratio": "payout_headroom",
        "tangible_book_value": "tangible_book_value",
        "price_to_book": "price_to_book",
        "price_to_tangible_book": "price_to_tangible_book",
    }
    derivation_inputs = {
        "loans_to_customers", "deposits_from_customers", "operating_expenses", "net_interest_income",
        "net_fee_income", "other_operating_income", "net_profit", "net_profit_attributable",
        "opening_equity", "closing_equity", "opening_tangible_equity", "closing_tangible_equity",
        "interest_earning_assets", "total_assets", "gross_loans", "impairment_losses", "loss_allowance",
        "opening_interest_earning_assets", "closing_interest_earning_assets", "opening_total_assets", "closing_total_assets",
        "opening_gross_loans", "closing_gross_loans",
        "shares_outstanding",
    }
    for row in rows:
        raw_metric = str(row.get("canonical_metric") or row.get("concept") or "").strip().casefold()
        metric = aliases.get(raw_metric, raw_metric)
        if metric not in _METRICS[model] and metric not in derivation_inputs:
            continue
        if target_period and not metric.startswith("opening_"):
            target = pd.Timestamp(target_period)
            row_period = _row_period(row)
            if row_period is not None and row_period.date() != target.date():
                # Retain a sole comparative so a mismatched-period formula is
                # explicitly unavailable; a requested-period row supersedes it.
                if metric not in candidates:
                    candidates[metric] = row
                continue
        previous = candidates.get(metric)
        if previous is not None and (row["_effective"], row["_known"]) <= (previous["_effective"], previous["_known"]):
            continue
        candidates[metric] = row

    def numeric(row: dict[str, object]) -> float | None:
        try:
            value = float(row.get("value"))
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    def category(row: dict[str, object], metric: str) -> str:
        explicit = str(row.get("fact_category") or "").strip().casefold()
        source = f"{row.get('source_id', '')} {row.get('taxonomy', '')} {row.get('concept', '')}".casefold()
        if explicit in {"pillar3", "regulatory", "market", "issuer_apm", "calculated", "ifrs"}:
            return "pillar3" if explicit == "regulatory" else explicit
        if metric in _REGULATORY and any(token in source for token in ("pillar", "prudential", "regulatory", "eba")):
            return "pillar3"
        if "market" in source or "quote" in source:
            return "market"
        if row.get("is_custom") or "extension" in source:
            return "issuer_apm"
        return "ifrs"

    def fact(
        metric: str,
        value: float | None,
        row: dict[str, object] | None,
        *,
        fact_category: str = "calculated",
        definition: str = "",
        limitations: tuple[str, ...] = (),
        source_id_override: str | None = None,
        inputs: tuple[dict[str, object], ...] = (),
        calculated_period: str | None = None,
        calculated_unit: str | None = None,
    ) -> FinancialMetricEvidence:
        selected = row or {}
        lineage_rows = inputs or ((selected,) if row else ())
        known = max((item.get("_known") for item in lineage_rows if item.get("_known") is not None), default=selected.get("_known"))
        effective = calculated_period or selected.get("_effective")
        def aware_iso(value: object, fallback: str) -> str:
            if value is None:
                return fallback
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            return stamp.isoformat().replace("+00:00", "Z")
        known_at = aware_iso(known, cutoff)
        as_of = aware_iso(effective, cutoff)
        lineage_ids = tuple(sorted(str(item.get("source_id")) for item in lineage_rows if item.get("source_id")))
        source_id = str(source_id_override or selected.get("source_id") or f"unavailable:{metric}")
        if inputs and lineage_ids:
            source_id = f"{source_id}|inputs={','.join(lineage_ids)}"
        unit = str(calculated_unit or selected.get("unit") or "ratio")
        if value is None:
            unit = (
                "currency_per_share"
                if metric == "tangible_book_value"
                else "currency"
                if metric in {"dividends", "retained_earnings", "issuance_dilution", "residual_income_input"}
                else "ratio"
            )
        if metric in {"dividends", "retained_earnings", "issuance_dilution", "residual_income_input"} and unit.casefold() not in {"shares", "currency_per_share", "currency"}:
            unit = "currency"
        return FinancialMetricEvidence(
            metric=metric,
            value=value,
            unit="percent" if unit.casefold() in {"percent", "%"} else unit,
            period=str(calculated_period or selected.get("fiscal_year") or selected.get("end") or selected.get("instant") or "undated"),
            reporting_standard="IFRS" if fact_category == "ifrs" else fact_category.upper(),
            jurisdiction=str(getattr(context, "operating_country", None) or "NO"),
            business_model=model,
            source_id=source_id,
            source_authority=(
                SourceAuthority.OFFICIAL
                if fact_category in {"ifrs", "pillar3", "regulatory"}
                else SourceAuthority.MANUAL
                if fact_category == "calculated"
                else SourceAuthority.ISSUER
            ),
            as_of=as_of,
            known_at=known_at,
            direction=None,
            fact_category=fact_category,
            definition=definition,
            scope=str(selected.get("consolidation_scope") or (lineage_rows[0].get("consolidation_scope") if lineage_rows else None) or "consolidated"),
            coverage="reported" if row else ("derived" if value is not None else "unavailable"),
            source=";".join(str(item.get("source_url") or item.get("source_id") or "") for item in lineage_rows) or str(selected.get("source_url") or source_id),
            limitations=limitations,
        )

    facts: list[FinancialMetricEvidence] = []
    for metric in sorted(_METRICS[model]):
        row = candidates.get(metric)
        value = numeric(row) if row is not None else None
        category_name = category(row, metric) if row is not None else ("pillar3" if metric in _REGULATORY else "calculated")
        facts.append(fact(metric, value, row, fact_category=category_name))

    def compatible(input_names: tuple[str, ...], *, allow_opening: bool = False) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
        selected: list[dict[str, object]] = []
        for name in input_names:
            item = candidates.get(name)
            if item is None and allow_opening and name.startswith("opening_"):
                continue
            if item is None:
                return (), ("missing_input",)
            selected.append(item)
        if not selected:
            return (), ("missing_input",)
        reasons: set[str] = set()
        periods = {_row_period(item).date() for item in selected if _row_period(item) is not None and not (allow_opening and str(item.get("canonical_metric") or "").casefold().startswith("opening_"))}
        if len(periods) > 1:
            reasons.add("period_mismatch")
        currencies = {str(item.get("currency") or str(item.get("unit") or "").split("/", 1)[0]).upper() for item in selected if item.get("currency") or item.get("unit")}
        if len(currencies) > 1:
            reasons.add("currency_mismatch")
        scopes = {str(item.get("consolidation_scope") or "consolidated").casefold() for item in selected}
        if len(scopes) > 1:
            reasons.add("scope_mismatch")
        if target_period:
            target = pd.Timestamp(target_period).date()
            if any(_row_period(item) is not None and _row_period(item).date() != target and not (allow_opening and str(item.get("canonical_metric") or "").casefold().startswith("opening_")) for item in selected):
                reasons.add("period_mismatch")
        return tuple(selected), tuple(sorted(reasons))

    def emit(metric: str, result: float | None, inputs: tuple[dict[str, object], ...], reasons: tuple[str, ...], definition: str, *, unit: str = "ratio", period: str | None = None) -> None:
        facts[:] = [item for item in facts if item.metric != metric]
        limitations = reasons or (() if result is not None else ("missing_input",))
        inferred_period = _row_period(inputs[0]).date().isoformat() if inputs and _row_period(inputs[0]) is not None else cutoff
        facts.append(fact(metric, result, None, definition=definition, limitations=limitations, source_id_override=f"calculated:{metric}", inputs=inputs, calculated_period=period or target_period or inferred_period, calculated_unit=unit))

    selected, reasons = compatible(("loans_to_customers", "deposits_from_customers"))
    denom = selected[1].get("value") if len(selected) == 2 else None
    emit("loan_deposit_ratio", None if reasons or denom is None or float(denom) <= 0 else float(selected[0].get("value")) / float(denom), selected, reasons + (("invalid_denominator",) if denom is None or (denom is not None and float(denom) <= 0) else ()), "loans_to_customers / deposits_from_customers")

    selected, reasons = compatible(("operating_expenses", "net_interest_income", "net_fee_income", "other_operating_income"))
    income = sum(float(item.get("value")) for item in selected[1:]) if len(selected) == 4 else None
    emit("cost_income_ratio", None if reasons or income is None or income <= 0 else float(selected[0].get("value")) / income, selected, reasons + (("invalid_denominator",) if income is None or (income is not None and income <= 0) else ()), "operating_expenses / (net_interest_income + net_fee_income + other_operating_income)")

    selected, reasons = compatible(("net_profit_attributable", "opening_equity", "closing_equity"), allow_opening=True)
    opening = candidates.get("opening_equity")
    closing = candidates.get("closing_equity")
    roe_inputs = tuple(item for item in (candidates.get("net_profit_attributable"), opening, closing) if item is not None)
    average_equity = (float(opening.get("value")) + float(closing.get("value"))) / 2 if opening and closing else None
    emit("roe", None if reasons or average_equity is None or average_equity <= 0 else float(candidates["net_profit_attributable"].get("value")) / average_equity, roe_inputs, reasons + (("missing_opening_equity",) if opening is None else ()) + (("invalid_denominator",) if average_equity is None or (average_equity is not None and average_equity <= 0) else ()), "net_profit_attributable / average(opening_equity, closing_equity)")

    selected, reasons = compatible(("net_profit_attributable", "opening_tangible_equity", "closing_tangible_equity"), allow_opening=True)
    opening = candidates.get("opening_tangible_equity")
    closing = candidates.get("closing_tangible_equity")
    rote_inputs = tuple(item for item in (candidates.get("net_profit_attributable"), opening, closing) if item is not None)
    average_tangible = (float(opening.get("value")) + float(closing.get("value"))) / 2 if opening and closing else None
    emit("rote", None if reasons or average_tangible is None or average_tangible <= 0 else float(candidates["net_profit_attributable"].get("value")) / average_tangible, rote_inputs, reasons + (("missing_opening_tangible_equity",) if opening is None else ()) + (("invalid_denominator",) if average_tangible is None or (average_tangible is not None and average_tangible <= 0) else ()), "net_profit_attributable / average(opening_tangible_equity, closing_tangible_equity)")

    base = candidates.get("net_interest_income")
    assets_open = candidates.get("opening_interest_earning_assets")
    assets_close = candidates.get("closing_interest_earning_assets")
    if assets_open and assets_close:
        selected, reasons = compatible(("net_interest_income", "opening_interest_earning_assets", "closing_interest_earning_assets"), allow_opening=True)
        denominator = (float(assets_open.get("value")) + float(assets_close.get("value"))) / 2
        nim_definition = "net_interest_income / average(interest_earning_assets)"
    else:
        selected, reasons = compatible(("net_interest_income", "interest_earning_assets"))
        if len(selected) != 2:
            assets_open = candidates.get("opening_total_assets")
            assets_close = candidates.get("closing_total_assets")
            if assets_open and assets_close:
                selected, reasons = compatible(("net_interest_income", "opening_total_assets", "closing_total_assets"), allow_opening=True)
                denominator = (float(assets_open.get("value")) + float(assets_close.get("value"))) / 2
            else:
                selected, reasons = compatible(("net_interest_income", "total_assets"))
                denominator = float(selected[1].get("value")) if len(selected) == 2 else None
            nim_definition = "net_interest_income / average(total_assets) (disclosed proxy)"
        else:
            nim_definition = "net_interest_income / average(interest_earning_assets)"
            denominator = float(selected[1].get("value"))
    emit("net_interest_margin", None if reasons or base is None or denominator is None or denominator <= 0 else float(base.get("value")) / denominator, selected, reasons + (("invalid_denominator",) if denominator is None or denominator <= 0 else ()), nim_definition)

    loans_open = candidates.get("opening_gross_loans")
    loans_close = candidates.get("closing_gross_loans")
    if loans_open and loans_close:
        selected, reasons = compatible(("impairment_losses", "opening_gross_loans", "closing_gross_loans"), allow_opening=True)
        denominator = (float(loans_open.get("value")) + float(loans_close.get("value"))) / 2
    else:
        selected, reasons = compatible(("impairment_losses", "gross_loans"))
        denominator = float(selected[1].get("value")) if len(selected) == 2 else None
    emit("cost_of_risk", None if reasons or len(selected) < 2 or denominator is None or denominator <= 0 else float(selected[0].get("value")) / denominator, selected, reasons + (("invalid_denominator",) if denominator is None or denominator <= 0 else ()), "impairment_losses / average(gross_loans)")
    selected, reasons = compatible(("loss_allowance", "stage_3_exposure"))
    emit("coverage_ratio", None if reasons or len(selected) != 2 or float(selected[1].get("value")) <= 0 else float(selected[0].get("value")) / float(selected[1].get("value")), selected, reasons + (("invalid_denominator",) if len(selected) != 2 or float(selected[1].get("value")) <= 0 else ()), "loss_allowance / stage_3_exposure")
    selected, reasons = compatible(("dividends", "net_profit"))
    emit("payout_headroom", None if reasons or len(selected) != 2 or float(selected[1].get("value")) == 0 else float(selected[0].get("value")) / float(selected[1].get("value")), selected, reasons + (("invalid_denominator",) if len(selected) != 2 or float(selected[1].get("value")) == 0 else ()), "dividends / net_profit")
    return facts


def load_real_asset_projection(
    instrument_id: str,
    *,
    projection: RealAssetProjection | Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Verify optional in-memory real-asset evidence; never calculate in the UI."""

    if projection is None:
        return unavailable_real_asset_projection(instrument_id)
    try:
        payload = verify_real_asset_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise RealAssetAdapterError("real-asset projection identity mismatch")
        return payload
    except (RealAssetAdapterError, TypeError, ValueError):
        return unavailable_real_asset_projection(instrument_id, "real_asset_evidence_invalid")


def load_cyclical_projection(
    instrument_id: str,
    *,
    projection: CyclicalProjection | Mapping[str, object] | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, object]:
    """Verify optional in-memory cyclical evidence; never calculate in the UI."""

    if projection is None or expected_source_digest is None:
        return unavailable_cyclical_projection(instrument_id)
    try:
        payload = verify_cyclical_projection(
            projection,
            expected_source_digest=expected_source_digest,
        )
        if payload.get("instrument_id") != str(instrument_id):
            raise CyclicalAdapterError("cyclical projection identity mismatch")
        return payload
    except (CyclicalAdapterError, TypeError, ValueError):
        return unavailable_cyclical_projection(instrument_id, "cyclical_evidence_invalid")


def load_innovation_projection(
    instrument_id: str,
    *,
    projection: InnovationProjection | Mapping[str, object] | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, object]:
    """Verify optional local innovation-sector evidence; never calculate in UI."""

    if projection is None or expected_source_digest is None:
        return unavailable_innovation_projection(instrument_id)
    try:
        payload = verify_innovation_projection(
            projection,
            expected_source_digest=expected_source_digest,
        )
        if payload.get("instrument_id") != str(instrument_id):
            raise InnovationAdapterError("innovation projection identity mismatch")
        return payload
    except (InnovationAdapterError, TypeError, ValueError):
        return unavailable_innovation_projection(instrument_id, "innovation_evidence_invalid")


def save_classification_overrides(
    storage_root: Path,
    overrides: tuple[ClassificationOverride, ...],
) -> dict[str, object]:
    """Persist reviewed local overrides through the application boundary."""

    try:
        with ClassificationStore(Path(storage_root).resolve()) as store:
            record_ids = store.append_overrides(overrides)
        return {
            "status": "saved",
            "record_ids": record_ids,
            "dependent_scores_invalidated": bool(record_ids),
            "execution_allowed": False,
        }
    except (ClassificationSchemaError, OSError, ValueError) as exc:
        return {
            "status": "rejected",
            "record_ids": (),
            "reason_code": "classification_override_rejected",
            "message": str(exc),
            "dependent_scores_invalidated": False,
            "execution_allowed": False,
        }


def load_paper_trade_rows(root: Path) -> tuple[dict[str, object], ...]:
    """Return safe, local paper-trade rows for presentation selectors."""

    from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError

    try:
        return PaperLedger(root).trade_rows()
    except (OSError, PaperLedgerError, ValueError):
        return ()


def load_paper_timeline(
    root: Path,
    instrument_id: str,
    *,
    account_id: str = "local-paper",
) -> dict[str, object]:
    """Read one paper account's validated lifecycle history for presentation."""

    from etf_cockpit.portfolio.paper_trading import (
        PaperLedger,
        PaperLedgerError,
        PaperLedgerIntegrityError,
    )

    ledger = PaperLedger(root, account_id=account_id)
    if not ledger.path.exists():
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "rows": [],
            "reason_code": "paper_ledger_missing",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    try:
        rows = ledger.timeline_rows(instrument_id)
    except (OSError, PaperLedgerIntegrityError, PaperLedgerError, ValueError):
        return {
            "status": "invalid",
            "instrument_id": str(instrument_id),
            "rows": [],
            "reason_code": "paper_ledger_invalid",
            "source_authority": "local_paper_ledger",
            "execution_allowed": False,
        }
    return {
        "status": "available",
        "instrument_id": str(instrument_id),
        "rows": list(rows),
        "source_authority": "local_paper_ledger",
        "message": "Recorded paper lifecycle history; this is not a historical account reconstruction.",
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
        frame["fx_return"] = frame["fx_rate"].pct_change()
        frame["output_total_return"] = (1.0 + frame["local_total_return"].fillna(0.0)) * (1.0 + frame["fx_return"].fillna(0.0)) - 1.0
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


# Explicit presentation schema: future/private artifact fields are never projected.
_METRIC_HISTORY_DISPLAY_COLUMNS = (
    "run_id", "instrument_id", "component_group", "component_name", "source_id",
    "raw_metric_value", "normalised_score_10", "score_available", "na_reason",
    "source_dataset", "as_of_date", "freshness_status", "authority_label",
    "formula_version", "formula_checksum", "source_vintage_hash", "execution_allowed",
)


def load_score_metric_history_projection(instrument_id: str, *, frame=None) -> dict:
    """Read stored component snapshots without deriving scores or PIT authority."""
    import math
    from numbers import Real

    import pandas as pd

    from etf_cockpit.data.trust_artifacts import SCORE_METRIC_HISTORY_PATH

    def unavailable(reason: str) -> dict:
        return {"status": "unavailable", "reason_code": reason, "rows": [],
                "message": "Score-component metric history unavailable: " + reason + ".",
                "execution_allowed": False}

    if frame is None:
        try:
            frame = pd.read_parquet(SCORE_METRIC_HISTORY_PATH)
        except FileNotFoundError:
            return unavailable("missing_local_artifact")
        except Exception:
            return unavailable("unreadable_local_artifact")
    if (not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique
            or not set(_METRIC_HISTORY_DISPLAY_COLUMNS).issubset(frame.columns)):
        return unavailable("malformed_metric_history")
    rows = frame.loc[frame["instrument_id"].eq(instrument_id), list(_METRIC_HISTORY_DISPLAY_COLUMNS)]
    if rows.empty:
        return unavailable("no_instrument_metric_history")
    records = []
    for record in rows.to_dict("records"):
        for field, value in record.items():
            if not pd.api.types.is_scalar(value):
                return unavailable("malformed_metric_history")
            if pd.isna(value):
                record[field] = None
        for field in ("run_id", "instrument_id", "component_name"):
            if not isinstance(record[field], str) or not record[field].strip():
                return unavailable("malformed_metric_history")
        for field in ("raw_metric_value", "normalised_score_10"):
            value = record[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)):
                return unavailable("malformed_metric_history")
        record["execution_allowed"] = False
        records.append(record)
    return {"status": "available", "instrument_id": instrument_id, "rows": records,
            "message": "Persisted score-component snapshots across local runs. As-of dates and stored provenance do not establish knowledge-time availability or replay guarantees.",
            "execution_allowed": False}
