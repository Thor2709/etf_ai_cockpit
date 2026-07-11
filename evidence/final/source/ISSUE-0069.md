# ISSUE-0069 source gate

The current session trace is implemented in `src/etf_cockpit/core/session_log.py` and is used by the workflow controller, Flet state and diagnostics page. New app sessions clear the current JSONL file, write `session_start`, redact nested secret-like values and tolerate logging failures. Workflow activity records start, step, success/failure and output paths.

The Diagnostics page exposes the session ID, log path, size/initialisation state, recent events and the redaction/non-blocking note. Audit Notes uses the same activity contract for export and external audit import.
