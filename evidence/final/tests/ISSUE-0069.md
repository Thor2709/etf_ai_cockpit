# ISSUE-0069 tests gate

Fresh command:

` .\\.venv\\Scripts\\python.exe -m pytest tests\\test_workflow_runtime.py tests\\test_flet_startup.py tests\\test_trust_critical_artifacts.py tests\\test_complete_audit_packet.py tests\\test_evidence_ledger.py -q -rA `

Result: exit code 0; 25 tests passed. The passing set covers start/step/finish ordering, failure and retryable states, logging-failure tolerance, session initialisation/redaction, visible running state, action persistence, route startup, audit/session export and ledger eligibility.
