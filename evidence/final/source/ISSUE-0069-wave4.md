# ISSUE-0069 source gate, current package

Current source is implemented in `src/etf_cockpit/core/session_log.py` and `src/etf_cockpit/core/workflow.py`, with diagnostics and audit UI integration in `src/etf_cockpit/app/pages/diagnostics.py`, `src/etf_cockpit/app/pages/chatgpt_audit.py` and `src/etf_cockpit/app/state.py`. The latest source also shares JSON-string secret redaction between session logging and workflow assignment logging.

Current source proof: `evidence/wave4/full-pytest-final-trust-policy.txt`, `evidence/wave4/compileall-final-trust-policy.txt`, and `evidence/wave4/ruff-final-trust-policy-scoped.txt`.
