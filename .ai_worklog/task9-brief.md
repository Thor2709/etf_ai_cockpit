# Wave 4 Task 9 - Instrument Identity, Source Conflicts and Evidence Ledger

## Objective

Implement the approved Task 9 contract against the current `origin/main`
checkpoint. The plan names `UPDATEV2-0011`, `UPDATEV2-0021` and
`UPDATEV2-0022`; repository reconciliation shows `UPDATEV2-0022` already has
an authoritative closed local dossier, so preserve that closure and do not
reopen it absent a reproducible regression. The active issue-state impacts are
`UPDATEV2-0011` and `UPDATEV2-0021`. Preserve current trust-artifact wrappers and provider/evidence
contracts; extend rather than replace them. `execution_allowed` remains
`false`; no broker/execution authority, score-weight, model-authority,
portfolio-target, research-threshold or coverage changes are permitted.

## Approved interfaces and behaviour

- `CanonicalIdentity` must expose instrument ID, ISIN/status, ticker, exchange,
  MIC, currency, asset type, share class, provider-symbol map, confidence and
  warnings. Preserve any existing `name`/issuer/CIK compatibility fields.
- `resolve_identity(Iterable[IdentityClaim]) -> IdentityResolution` must be
  deterministic, authority-aware and fail closed for ticker/ISIN mismatch,
  exchange/currency variants, ETF share-class/listing separation, unknown ISIN,
  missing source IDs and manual overrides. Official/issuer claims outrank
  vendor/community/model claims; conflicts remain visible and are never silently
  discarded.
- `resolve_conflicts(Iterable[MetricClaim]) -> ConflictResolution` must select
  deterministically by authority, preserve all claims/source IDs, classify
  material official/vendor disagreements as manual-review or evidence-quality
  reduction, and produce human-readable reasons. No silent overwrite.
- `EvidenceSource` and `EvidenceLedgerEntry` must carry source ID, authority,
  as-of date, freshness, confidence/quality and conflict linkage. Missing source,
  stale/unavailable evidence or material conflict makes a score component
  ineligible; model/community/news/candle evidence remains visibly low-authority.
- Keep compatibility wrappers named `write_instrument_identity`,
  `write_source_conflicts`, `write_evidence_ledger` and `write_score_components`.
  Trust artefacts remain atomically published and auditable.
- Integrate provenance into `signals/simple_scores.py`: every component has
  source/provenance metadata and eligibility derives from it. Preserve existing
  score weights and authority boundaries.
- Extend Evidence Ledger, Filings & Statements, ETF Disclosures and Instrument
  Detail/Provider Status surfaces only with real repository data or explicit
  unavailable/conflict/manual-review states. Reuse current dark Flet tokens and
  controls; no decorative UI.

## Required files

Own these files in this worktree: `src/etf_cockpit/data/instrument_identity.py`,
`src/etf_cockpit/data/source_conflicts.py`,
`src/etf_cockpit/data/evidence_ledger.py`,
`src/etf_cockpit/data/trust_artifacts.py`,
`src/etf_cockpit/signals/simple_scores.py`,
`src/etf_cockpit/app/pages/trust_evidence.py`, and focused tests
`tests/test_instrument_identity.py`, `tests/test_source_conflicts.py`,
`tests/test_evidence_ledger.py` plus any directly affected regression tests.
Do not edit programme ledgers or close issues in the implementation branch;
the parent controller owns integration and issue closure evaluation.

## RED-GREEN-REFACTOR

Before behavioural implementation, add focused failing tests for at least:

1. missing identity fields/source IDs and ticker/ISIN mismatch;
2. MIC/exchange/currency/share-class/listing conflict retention;
3. official versus vendor material conflict with deterministic manual-review
   reason;
4. missing/stale/conflicted evidence making a score component ineligible;
5. serialised trust artefacts retaining source IDs, authority, as-of/freshness,
   conflict IDs and no secret leakage.

Run each RED command and record exit status/output in `.ai_worklog/task9-report.md`.
Implement the smallest compatible change, rerun focused tests, then refactor
only where needed. Run the plan's focused command:

`..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py tests/test_simple_scores.py tests/test_trust_critical_artifacts.py`

Also run compileall, scoped Ruff, affected trust/score/provider/atomic/scope
regressions, source smoke and direct persistence/export checks. Record known
pre-existing generated-data failures separately.

## Review and safety

Provide a structured report with RED/GREEN evidence, migration/compatibility
notes, persistence/export/checksum evidence, UI/browser applicability and
remaining gates. A fresh independent reviewer must separately assess
specification compliance and code quality; fix all Critical/Important findings
and obtain fresh re-review before the parent integrates. Do not claim issue
closure in this task branch. Preserve all current audit, provider and
execution-boundary contracts.
