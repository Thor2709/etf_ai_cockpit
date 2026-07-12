# Wave 1 Governance Task 2 independent review

Reviewed `.ai_worklog/task-governance-2-brief.md`,
`.ai_worklog/task-governance-2-report.md`, and commit `09ce885` for the
specified migration, state, score-history, signal and ChatGPT/export files.
The review is focused on A.4.2/GOV-02.5 state separation, historical
migration safety/idempotence, and the fixed `execution_allowed=False`
boundary. No production files or tests were changed. The full test suite was
not run; the available focused pytest command could not start because this
worktree's interpreter has no pytest module.

SPECIFICATION: FAIL
CODE QUALITY: FAIL

## Findings

### Critical

**C1 - migration is not idempotent for an explicitly snapshotted portfolio**
(`src/etf_cockpit/governance/migrations.py`, `_snapshot_mapping`,
`_portfolio_state`, `migrate_legacy_action`).

The first migration of a row containing
`portfolio_snapshot.portfolio_review_state=reduce_exposure_review` returns
`portfolio_review_allowed=True`. Its v2 payload does not retain a snapshot
marker. Reapplying `migrate_legacy_action(first.model_dump())` therefore sees
no context, sets `context_allowed=False`, and returns the same review state
with `portfolio_review_allowed=False`. This violates the required
semantically byte-equivalent repeated migration and can revoke authority on a
retry. Preserve a validated context/provenance marker in the v2 row, or make
the v2 branch derive and validate its own context without losing the original
allow flag; add an explicit snapshot idempotence test.

**C2 - `resolve_research_state` can emit a positive state from incomplete or
unproven evidence** (`src/etf_cockpit/signals/research_states.py`,
`resolve_research_state`).

The function's contract says a positive candidate requires complete analysis
and a usable non-model component, but it only rejects `analysis_status=
unavailable`; `partial` plus one score returns `research_candidate`. A score
with `source_id=None` also counts as usable because the filter only excludes a
source whose prefix is `model`. This is a public-authority promotion path from
partial/unproven evidence, contrary to A.4.2's separation and the fail-closed
migration contract. Require `analysis_status == complete`, a non-empty
allow-listed evidence source/provenance, and the appropriate resolved gate
decision before returning a positive state; otherwise return
`not_scoreable`/`manual_review` and add partial, missing-source and model-only
regressions.

### Important

**I1 - portfolio review context is not required to be contemporaneous**
(`migrations.py`, `_snapshot_mapping`). A mapping with only
`{"portfolio_snapshot": {"portfolio_review_state": "..."}}` (or only
`review_state`) is treated as an explicit snapshot and grants
`portfolio_review_allowed=True`; no timestamp/as-of or holdings/weights are
required. Require a contemporaneous date/timestamp together with the snapshot
payload, and fail closed for state-only or malformed snapshots.

**I2 - score-history import recreates portfolio authority without snapshot
evidence** (`src/etf_cockpit/data/score_history.py`, `append_score_run`,
`_normalise_history_frame`, `score_history_v2_payload`). Any row carrying a
valid non-`not_applicable` `portfolio_review_state` is serialised with
`portfolio_review_allowed=True`, even when imported from a legacy
`final_action` row with no contemporaneous portfolio snapshot. This bypasses
the migration context rule in the historical score path. Default the flag to
false unless an explicit validated snapshot accompanies the row, and test
legacy rows for every review state.

**I3 - v2 migration trusts caller-supplied positive promotion/review flags**
(`migrations.py`, `_already_v2` branch). A crafted v2 record with
`research_state=research_candidate` and `research_promotion_allowed=True` is
returned with that positive flag despite no evidence or Task 3 resolver; the
same applies to portfolio review when the context flag is present. Task 2's
report says promotion remains disabled until Task 3, so the migration seam
must normalise untrusted v2 flags to false (or require a validated authority
decision and checksum), while preserving state as non-executable review data.

**I4 - dataclass public serializers can emit invalid v2 authority values**
(`src/etf_cockpit/core/types.py`, `SignalResult.__post_init__`/
`to_v2_dict`; `src/etf_cockpit/signals/simple_scores.py`,
`SimpleInstrumentScore.__post_init__`/
`to_v2_dict`). Runtime dataclass construction accepts an arbitrary
`analysis_status` string and caller-supplied `research_promotion_allowed` or
`portfolio_review_allowed=True`; `public_authority_payload` merely casts the
flags and does not validate the status. Release-facing output can therefore
contain values outside `complete|partial|unavailable` or positive authority
without a resolver. Normalise/reject invalid status and force promotion/review
false in this task's compatibility seam; only Task 3's typed resolver should
be able to grant them.

**I5 - v2 ChatGPT models silently accept legacy action fields**
(`src/etf_cockpit/chatgpt_bridge/schemas.py`, `PortfolioReviewAudit` and
`ChatGPTAuditV2`). Neither model sets `extra="forbid"`, so `action` or
`final_action` in a purported v2 payload is silently ignored rather than being
confined to the v1 compatibility import seam. Use a strict v2 model (or an
explicit rejection validator) and test that legacy fields are rejected while
v1 imports remain accepted.

**I6 - unsupported schema versions are migrated as if they were v1.x**
(`migrations.py`, `V1_SCHEMA_PREFIXES` and `migrate_legacy_action`). The
declared v1 prefix constant is unused; records labelled `3.0`, `9.9`, or an
unknown schema are still mapped to v2. Reject/diagnose versions outside 1.x
and 2.0, preserving the original row and preventing a future schema from
being silently interpreted as a legacy action.

### Minor

**M1 - `migration_semantics` is an unconstrained string**
(`migrations.py`, `ResearchStateMigration`). The contract is the documented
`lossless|lossy` vocabulary, but direct model construction accepts arbitrary
text (and the field is not typed as `MigrationSemantics`). Use the literal
type and validate all import paths consistently.

**M2 - `validate_audit_file` has a stale return annotation**
(`src/etf_cockpit/chatgpt_bridge/validation.py`). It is annotated as returning
`ChatGPTAudit` while it can return `ChatGPTAuditV2`; update the annotation to
the union used by `validate_audit_text` so static callers cannot lose the v2
contract.

## Boundary checks that passed

The new migration model, research-state model, score-history writers,
`SignalResult`/`SimpleInstrumentScore` serializers and `PortfolioReviewAudit`
all hard-code or type `execution_allowed` as `Literal[False]`; the inspected
v2 export fields omit `action`/`final_action`. These checks do not mitigate the
positive research/portfolio authority findings above.

NOT READY
