"""Release verification and finalisation records."""

from etf_cockpit.release.verification_records import (
    ReleaseRecordKey,
    ResumeCheckpoint,
    VerificationRecord,
    VerificationRecordLedger,
    compute_evidence_hash,
    compute_executable_hash,
    deterministic_evidence_hash,
    evidence_state_allows_closure,
    load_resume_checkpoint,
    reuse_gate_record,
    validate_shared_record,
)

__all__ = [
    "ReleaseRecordKey",
    "ResumeCheckpoint",
    "VerificationRecord",
    "VerificationRecordLedger",
    "compute_evidence_hash",
    "compute_executable_hash",
    "deterministic_evidence_hash",
    "evidence_state_allows_closure",
    "load_resume_checkpoint",
    "reuse_gate_record",
    "validate_shared_record",
]
