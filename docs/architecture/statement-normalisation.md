# Canonical statement normalisation

`ISSUE-0091` builds deterministic views over the append-only SEC/ESEF fact
stores. `StatementFact` retains the source concept, taxonomy, unit, currency,
dimensions, fiscal fields, filing date, accession and source ID. Unmapped and
custom concepts remain visible with `manual_review_required=true`; they are
never silently promoted into scoring metrics.

`etf_cockpit.data.statement_normalisation` exposes three views:

- `reported` retains every source fact;
- `latest_restated` chooses the latest filed fact for an exact concept/unit/
  period/dimension key;
- `as_known_at` filters by filing availability before selecting the latest
  fact, so later amendments cannot leak into historical analysis.

The coverage report counts mapped and review facts, annual and quarterly
periods, and source IDs. Reconciliation checks are fail-closed: balance-sheet
and cash-flow identities are reported as passed, failed or unavailable only
when comparable inputs exist. Missing concepts are not treated as zero.

The Instrument Detail fundamentals section renders reported and restated
statement history, coverage and reconciliation evidence. All statement data
is evidence-only and `execution_allowed=false`.
