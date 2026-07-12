# Wave 1 Governance Task 1 - review fix report

## Scope

This fix pass addresses the independent review of Task 1 (`.ai_worklog/task-governance-1-review.md`). It remains limited to the approved fail-closed governance policy contract and audit-manifest visibility. No product authority, scoring weights, execution boundary or coverage scope changed.

## RED evidence

- Date: 2026-07-12 (Australia/Sydney)
- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_governance_review_regressions.py -q`
- Result before the fix: exit status 1, 21 failures and 2 passes.
- The failures reproduced the review gaps: metadata-only and empty policies were accepted, unsupported schema versions were accepted, lifecycle/authority combinations were not fully rejected, feature and strategy metadata inventories were incomplete, the glossary was incomplete, the checksum source revision was not real, and audit exports did not expose governance checksums and diagnostics.
- The RED test file was `tests/test_governance_review_regressions.py`; its SHA-256 is recorded by the implementation commit and the review package.

## GREEN implementation

- `src/etf_cockpit/governance/models.py` now uses an explicit supported schema version, complete typed feature and strategy metadata, lifecycle/authority compatibility checks, and non-granting gate severities while preserving `execution_allowed = false`.
- `src/etf_cockpit/governance/product_scope.py` rejects metadata-only, empty, unsupported and incomplete policy documents with deterministic diagnostic-mode results; contradictory authority input remains a validation error.
- All five policy YAML files contain the required substantive inventories, route coverage, strategy scope entries, gate order and glossary terms.
- `src/etf_cockpit/chatgpt_bridge/export_pack.py` copies the policy checksum manifest into the audit packet and records schema version, five policy checksums and an explicit valid/diagnostic marker.
- `configs/audit_manifest.yaml` declares the governance checksum artefact and diagnostic contract.

## Passing evidence

- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py tests\test_governance_review_regressions.py -q -k 'not policy_checksum_manifest_names_real_revision_with_all_policy_files'`
- Result: exit status 0; 42 tests passed.
- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_governance_review_regressions.py::test_audit_manifest_includes_governance_checksums_version_and_diagnostic_marker -q`
- Result: exit status 0; audit-manifest governance visibility passed.

The checksum-source-revision check is intentionally pending the fix commit: the manifest must name the real commit that contains the final policy YAML files and their final hashes. It will be updated and verified immediately after the implementation commit.

## Review status

The initial independent review identified one Critical and seven Important findings. This report records the implementation fix pass; a fresh independent re-review is required before integration. No issue is closed by this task; the owning governance issues remain open for their later migration, resolver, journal and UI tasks.
