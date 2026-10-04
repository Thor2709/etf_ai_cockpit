"""Operation-preview records used by the Operations Centre.

The implementation is application logic and lives in
:mod:`etf_cockpit.application.operation_records` (ADR-0002).
"""

from __future__ import annotations

from etf_cockpit.application.operation_records import (
    OperationRecord,
    build_operation_preview,
    load_operation_records,
    save_operation_record,
    validate_operation_record,
)

__all__ = ["OperationRecord", "build_operation_preview", "load_operation_records", "save_operation_record", "validate_operation_record"]
