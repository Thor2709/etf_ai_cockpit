# UPDATEV2-0012 SEC submissions handoff — 2026-09-04

## Checkpoint

- Worktree: `C:\dev\etf-sec-submissions-review-correction-20260904`
- Branch: `codex/sec-submissions-review-correction-20260904`
- Exact base: `bc9876c03b868a323da1d1f5904cad4e33375559`
- Last commit: `2c68550167781fbe1dbf698aa9ab911a33151328`
- Primary checkout was intentionally left untouched because it was dirty and
  behind `origin/main`.
- No push, pull request, packaged gate, merge, canonical lifecycle mutation,
  release or deployment has occurred.

Commit `2c685501` replaces the rejected generic SEC acquisition capability with
a fused provider acquisition/import boundary, neutral durable manifest schema
v2, cold-session full-response behavior, bounded session ledgers, and bounded
ZIP64 extensible-data support. Public paths, public `RawDocument` values and
durable manifests remain local/manual evidence. Its focused suite passed on
Python 3.12 and 3.13 before review.

## Review result

The exact head `2c685501` is **rejected** and must not be gated or integrated.
The provenance/PIT reviewer reproduced two defects:

1. The session ledger did not bind the original acquisition timestamp and the
   complete `RawDocument` generation. Editing writable sidecar time/status in
   the same process, followed by HTTP 304, could backdate live official
   evidence.
2. After a cold bulk request failed transiently, the retry path could reload a
   persisted partial and send `Range`/`If-Range` without a matching
   provider-session partial proof.

The rejection and required correction are recorded in
`plans/BATCH-B04-ANALYSIS-SPINE.md`.

## Uncommitted correction at stop

The stopped implementation agent had applied a coherent but uncommitted
correction in these files:

- `src/etf_cockpit/data/sec_edgar_provider.py`
- `src/etf_cockpit/data/sec_edgar_bulk.py`
- `src/etf_cockpit/application/sec_submissions_import.py`
- `tests/test_sec_edgar_bulk.py`
- `tests/test_sec_submissions_import.py`
- `plans/BATCH-B04-ANALYSIS-SPINE.md` (root-owned rejection chronology)

The correction expands `_SessionGeneration` to bind timestamp, provider, media
type and acquisition status; permits status 304 only as an explicitly checked
same-generation revalidation; and clears retry range state unless the persisted
partial still has a matching in-session proof. Direct regressions cover forged
sidecar timestamps and cold transient-retry partial resume.

Current validation of the uncommitted tree:

- Python 3.12 six-module SEC selection: `166 passed, 1 skipped`.
- Ruff on changed Python/test files: passed.
- `compileall` on changed production files: passed.
- `git diff --check`: passed before the handoff file was added.
- Python 3.13 was not rerun after this correction because the temporary 3.13
  environment no longer existed at checkpoint time. Earlier evidence applies
  only to commit `2c685501`, not to these uncommitted changes.

## Exact continuation

1. Inspect the six-file uncommitted correction and this handoff; do not discard
   it or modify the dirty primary checkout.
2. Recreate/use a supported Python 3.13 environment and run the same six-module
   SEC selection. Re-run Ruff, compileall and `git diff --check` after any edit.
3. If clean, update the B04 evidence paragraph with the final 3.12/3.13 counts,
   commit the complete correction, and freeze the exact SHA.
4. Obtain fresh independent whole-diff and provenance/PIT acceptance for exact
   `origin/main..HEAD`. Earlier review conclusions cannot be reused as approval.
5. Only if both reviews accept, verify `origin/main` is unchanged, then run the
   required Linux and Windows H-tier packaged gates. Push/open/merge only from
   the exact reviewed and passing head.
6. This component still does not close UPDATEV2-0012. Continue its remaining
   canonical statements/PIT integration and AppState/UI/audit/clean-first-run
   slices. Live SEC evidence requires a legitimate organization/contact user
   agent and must not be fabricated.

Keep `execution_allowed=false`; do not add provider/broker writes, live orders,
cloud uploads, dependencies, release authority or deployment authority.
