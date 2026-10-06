"""Local structural-evidence loading and structure confidence caps for signals, snapshots and backtests (application; ADR-0002)."""

from __future__ import annotations

from etf_cockpit.data.etf_structure import (
    load_local_structural_evidence,
    structure_confidence_caps,
)
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.fund_holdings import FUND_HOLDINGS_PATH
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.data.reference_data import ETF_METADATA_CLEAN_PATH


def _load_local_structural_evidence():
    return load_local_structural_evidence(
        registry_reader=read_document_registry,
        report_reader=read_etf_report_records,
        factsheet_path=ETF_METADATA_CLEAN_PATH,
        holdings_path=FUND_HOLDINGS_PATH,
    )


def _load_structure_caps(instrument_ids: object, decision_time: object) -> dict[str, float]:
    """Load local structural evidence once at the signal service boundary."""

    ids = [str(item) for item in instrument_ids] if instrument_ids is not None else []
    try:
        evidence = _load_local_structural_evidence()
        return structure_confidence_caps(
            ids,
            document_registry=evidence.document_registry,
            report_records=evidence.report_records,
            supplemental_rows=evidence.supplemental_rows,
            holdings=evidence.holdings,
            decision_time=decision_time,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        caps = structure_confidence_caps(ids, decision_time=decision_time)
        for item in ids:
            caps.provenance[item] = {
                "structure_projection_version": "unavailable",
                "structure_schema_version": "unavailable",
                "structure_confidence_version": "unavailable",
                "structure_provenance_hash": "unavailable",
                "structure_confidence_cap": 0.0,
                "status": "unavailable",
                "reason_code": "structural_evidence_load_failed",
                "reason": f"Structural evidence load failed ({type(exc).__name__}): {exc}",
            }
        return caps
