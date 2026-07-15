# Task 21: Complete Audit Packet and Non-Executable External Audit Import

Owning issue: UPDATEV2-0028. This task follows the merged Wave 5 Task 20
implementation and must preserve the current authority and safety boundaries.

## Files

- Modify `src/etf_cockpit/chatgpt_bridge/export_pack.py`
- Modify `src/etf_cockpit/chatgpt_bridge/import_audit.py`
- Modify `src/etf_cockpit/app/pages/chatgpt_audit.py`
- Create `tests/test_complete_audit_packet.py`
- Create `configs/audit_manifest.yaml`

## Required interfaces

- The manifest declares required path, schema version, source authority,
  SHA-256 and unavailable policy for each artefact.
- `validate_audit_archive(path) -> AuditValidationReport` verifies required
  entries and checksums.

## RED-GREEN-REFACTOR tasks

1. Write a failing complete-manifest test requiring provider states, identities,
   statement facts/inventory, ETF documents/holdings/KID/methodology, news
   validation, conflicts, ledger/components, score/history/changes, drivers,
   clusters, attribution, edge/cost, health, workflow/session, configs, issue
   dossiers and a checksum manifest.
2. Extend export deterministically. Include every available canonical artefact;
   optional evidence must be represented by a schema-valid unavailable record
   with a reason, never silently omitted or invented.
3. Harden redaction and external import. Scan archive content for configured
   secrets and common key patterns. Imported external audit remains a note with
   `executable_authority=false` and cannot alter scores, actions or
   configuration.
4. Prove UI and extraction. Export through source and packaged UI, show included
   artefacts/output path, extract to a temporary verification directory and
   validate every checksum.
5. Store archive, extracted manifest report, secret-scan result and
   browser/computer-use evidence under `evidence/wave8/audit/`.

## Binding constraints

- Preserve canonical stores, atomic I/O, audit manifests, provider/evidence
  contracts and the current Flet shell; extend rather than replace.
- `execution_allowed` remains `false`; external audit input is non-executable
  context and cannot grant authority or change scores/actions/configuration.
- Do not change score weights, model authority, portfolio targets, research
  thresholds, data coverage scope or any unrelated product behaviour.
- Use real repository data or explicit unavailable states; never fabricate
  values. Preserve source/package/browser parity where applicable.
- Behavioural tests must assert observable invariants and failure paths, not
  private implementation calls.
- Require a fresh independent review with separate specification-compliance and
  code-quality verdicts; fix all Critical and Important findings and obtain
  fresh re-review.

## Report contract

Write implementation and test evidence to `.ai_worklog/task-21-report.md` in
this worktree. Record the genuine RED command/failure, GREEN command/pass,
refactoring, focused/regression tests, static checks, audit/archive/checksum and
secret-scan results, UI/package limitations, review status, and exact next
action. Do not close UPDATEV2-0028 in this task unless every applicable closure
gate has fresh evidence and the merged local ledger supports closure.
