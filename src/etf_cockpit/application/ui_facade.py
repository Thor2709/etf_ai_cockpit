"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from pathlib import Path


from etf_cockpit.chatgpt_bridge.audit_packet import *  # noqa: F401,F403
from etf_cockpit.data.backup_restore import *  # noqa: F401,F403
from etf_cockpit.data.bitemporal import *  # noqa: F401,F403
from etf_cockpit.data.bulk_cache import *  # noqa: F401,F403
from etf_cockpit.data.decision_journal import *  # noqa: F401,F403
from etf_cockpit.data.forward_evidence_diary import *  # noqa: F401,F403
from etf_cockpit.data.event_calendar import *  # noqa: F401,F403
from etf_cockpit.data.export_tables import *  # noqa: F401,F403
from etf_cockpit.data.fund_documents import *  # noqa: F401,F403
from etf_cockpit.data.fund_holdings import *  # noqa: F401,F403
from etf_cockpit.data.fundamentals import *  # noqa: F401,F403
from etf_cockpit.data.fx_data import *  # noqa: F401,F403
from etf_cockpit.data.health import *  # noqa: F401,F403
from etf_cockpit.data.hybrid_platform import *  # noqa: F401,F403
from etf_cockpit.data.import_export import *  # noqa: F401,F403
from etf_cockpit.data.legal_terms import *  # noqa: F401,F403
from etf_cockpit.data.catalogue import *  # noqa: F401,F403
from etf_cockpit.data.macro_warehouse import *  # noqa: F401,F403
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
from etf_cockpit.data.classification import (
    ClassificationOverride,
    ClassificationSchemaError,
    ClassificationStore,
    classification_store_exists,
)
from etf_cockpit.data.manual_notes import *  # noqa: F401,F403
from etf_cockpit.data.news_context import *  # noqa: F401,F403
from etf_cockpit.data.oam_adapters import *  # noqa: F401,F403
from etf_cockpit.data.parsed_disclosures import *  # noqa: F401,F403
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
from etf_cockpit.application.overlap import *  # noqa: F401,F403
from etf_cockpit.signals.simple_scores import *  # noqa: F401,F403


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
        if not classification_store_exists(root):
            return {
                "status": "unavailable",
                "instrument_id": str(instrument_id),
                "reason_code": "classification_evidence_unavailable",
                "execution_allowed": False,
            }
        with ClassificationStore(root) as store:
            return store.projection(
                instrument_id,
                effective_at=effective_at,
                decision_time=decision_time,
                min_leaf_confidence=min_leaf_confidence,
            )
    except KeyError:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_evidence_unavailable",
            "execution_allowed": False,
        }
    except (ClassificationSchemaError, OSError, ValueError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_evidence_invalid",
            "execution_allowed": False,
        }


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
