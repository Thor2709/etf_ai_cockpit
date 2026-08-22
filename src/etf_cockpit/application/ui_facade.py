"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from collections.abc import Mapping
from pathlib import Path

from etf_cockpit.data.etf_structure import project_etf_structure
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
from etf_cockpit.data.peer_cohort_store import read_peer_cohort_projection
from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialAdapterError,
    FinancialInstitutionProjection,
    unavailable_financial_projection,
    verify_financial_projection,
)
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
from etf_cockpit.models.coverage_audit import *  # noqa: F401,F403
from etf_cockpit.models.local_weights import *  # noqa: F401,F403
from etf_cockpit.portfolio.allocation import *  # noqa: F401,F403
from etf_cockpit.portfolio.costs import *  # noqa: F401,F403
from etf_cockpit.portfolio.factor_risk import *  # noqa: F401,F403
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


def load_financial_institution_projection(
    instrument_id: str,
    *,
    projection: FinancialInstitutionProjection | Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Verify optional in-memory evidence; default remains explicitly unavailable."""

    if projection is None:
        return unavailable_financial_projection(instrument_id)
    try:
        payload = verify_financial_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise FinancialAdapterError("financial projection identity mismatch")
        return payload
    except (FinancialAdapterError, TypeError, ValueError):
        return unavailable_financial_projection(
            instrument_id, "financial_evidence_invalid"
        )


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
