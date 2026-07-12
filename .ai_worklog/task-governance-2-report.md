# Wave 1 Governance Task 2 implementation report

Status: `DONE_WITH_CONCERNS`

This worktree contains the Task 2 implementation and is not committed. Git
status/diff commands were unavailable in this Windows worktree because Git's
helper process could not create its signal pipe; the changed-file list below
was checked directly from the scoped source/test/evidence paths.

## RED evidence

The required command was first attempted verbatim:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_trade_proposals.py -q
```

It exited `1` because this isolated worktree has no local `.venv` and the
system interpreter has no `pytest` module. Re-running the same command with the
repository's existing shared environment and this worktree on `PYTHONPATH`
exited `1` with 11 failures: the five migration-contract assertions (missing
v2 modules) and the six known generated-data/identity failures in
`test_simple_scores.py`. No tests were weakened.

After adding the focused behavioural checks for explicit portfolio snapshots,
v2 signal serialisation and unavailable components, the focused migration RED
run exited `1` with eight expected failures (missing migration/state modules or
the not-yet-present `SignalResult.to_v2_dict`).

## GREEN and refactor evidence

Implemented the v2 state/migration seam, then ran:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_score_history.py -q
```

Using the shared environment, migration and score-history tests passed; the
command still exited `1` only for the six pre-existing generated-data/identity
simple-score failures. The focused trade-proposal compatibility command
(`tests\\test_trade_proposals.py -q`) exited `0` with 2 passed. Governance policy
regressions (product, feature, strategy, gate and review tests) exited `0`.

Scoped verification exited `0`:

```powershell
python -m compileall -q src
ruff check src/etf_cockpit/signals/research_states.py src/etf_cockpit/governance/migrations.py src/etf_cockpit/governance/models.py src/etf_cockpit/core/types.py src/etf_cockpit/signals/actions.py src/etf_cockpit/signals/signal_pipeline.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/data/score_history.py src/etf_cockpit/chatgpt_bridge/schemas.py src/etf_cockpit/chatgpt_bridge/validation.py src/etf_cockpit/chatgpt_bridge/export_pack.py
```

The authoritative `pytest tests -q` suite exited `1` with seven failures, all
in the pre-existing generated-data/identity family: the six simple-score
fixture/coverage rows plus the static trust-artifact identity-count row. No
Task 2 migration, v2 serialisation, score-history or compatibility test added
a failure.

## Changed files

- `src/etf_cockpit/signals/research_states.py` - separate public
  `ResearchState`, `PortfolioReviewState`, `InternalSignalIntent` and
  `GateSeverity` enums; typed authority/score adapters; fail-closed resolver.
- `src/etf_cockpit/governance/migrations.py` - deterministic v1.x to v2.0
  mapping, idempotent `ResearchStateMigration`, explicit snapshot rule,
  checksums/row-count report helpers and optional operational event.
- `src/etf_cockpit/core/types.py` - v2 authority fields and serializers on
  `SignalResult`; legacy `action` remains an import/diagnostic seam.
- `src/etf_cockpit/signals/actions.py` and `signal_pipeline.py` - internal
  intent/state adapters and v2 signal-log serialisation.
- `src/etf_cockpit/signals/simple_scores.py` - v2 authority fields,
  `to_v2_dict`, and v2 scoreboard frame (legacy `final_action` is opt-in for
  diagnostics only).
- `src/etf_cockpit/data/score_history.py` - v2 columns, legacy-row import
  normalisation, idempotent append and v2 payload helper.
- `src/etf_cockpit/chatgpt_bridge/schemas.py`, `validation.py` and
  `export_pack.py` - typed v2 review schema and exports without `action` or
  `final_action`; v1 imports remain accepted at the compatibility seam.
- `src/etf_cockpit/governance/models.py` - compatibility aliases to the new
  enums and authority models.
- `configs/chatgpt_schema.json` - v2 response/export schema.
- `tests/test_research_state_migration.py` - focused behavioural coverage.
- `evidence/governance/research_state_migration_report.json` - deterministic
  zero-row baseline evidence and checksum.

## Migration evidence and decisions

The report checksum is
`72ca844a466883cd2bf7e96e588d1239d06c4073ec59152921ad095c50340153`.

Mappings are exact: buy/add/add_candidate to `research_candidate`,
hold/trim/trim_candidate to `hold_review`, sell to `avoid`, no_trade to
`needs_evidence`, and manual_review to `manual_review`. Unknown or missing
values fail closed to `manual_review` while preserving `legacy_action`.
`trim`, `trim_candidate` and `sell` are marked lossy; the other known mappings
use the documented conservative lossless marker. `portfolio_review_state`
stays `not_applicable` unless a contemporaneous snapshot is explicit.

The v2 public field set carries research/portfolio state, analysis status,
promotion/review flags, `execution_allowed: false`, preserved `legacy_action`,
migration and gate-policy metadata, and `schema_version: 2.0`. Public serializers
do not emit `action` or `final_action`; old callers can still read those values
from in-memory/import/diagnostic seams. All new models force execution false.

## Remaining closure gates

This foundation does not implement the Task 3 central gate resolver or Task 4
portfolio journal/review-report replacement, and it does not close any issue.
The seven generated-data/identity failures require their owning fixture/data
work before a full-suite green claim. Independent review, package/boundary
verification and later governance UI/journal gates remain outstanding.

## Independent review fix pass (2026-07-12)

Status remains `DONE_WITH_CONCERNS`: all Critical/Important review findings
and the two Minor findings were addressed without implementing Task 3 central
gates or Task 4 journal/UI work. The worktree remains uncommitted for the
controller.

### TDD evidence

The new focused behavioural tests were added before the production fixes. The
fix-pass RED run was:

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_research_state_migration.py tests\test_score_history.py tests\test_trade_proposals.py -q
```

It exited `1` with the expected behavioural failures for the newly specified
snapshot, fail-closed resolver, forged-flag, serializer, strict-v2 and schema
cases; there were no import or syntax failures. After the implementation and
refactor, the GREEN run was:

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_research_state_migration.py tests\test_score_history.py tests\test_chatgpt_import.py tests\test_trade_proposals.py -q
```

Result: `26 passed` (the two existing score-history FutureWarnings are
non-failing pandas warnings).

### Fixes and interfaces

- Portfolio migration now validates a timestamp plus a review state or
  holdings/weight payload, rejects state-only and malformed snapshots, and
  carries `portfolio_snapshot_validated` plus
  `portfolio_snapshot_provenance=validated_snapshot` markers so a repeated
  migration is byte-equivalent. V2 caller-supplied promotion/review flags are
  ignored; promotion is always false and portfolio review is allowed only by
  validated context. Unsupported schema versions are rejected without
  mutating the input row, and `migration_semantics` is constrained to
  `lossless|lossy`.
- `resolve_research_state` now requires `complete` analysis, a passed positive
  decision, no failed/blocker gates, and finite `ok` components whose source
  IDs are in the explicit evidence allow-list. Partial, unavailable,
  missing-source, model-only and unknown-source evidence fail closed.
- `SignalResult` and `SimpleInstrumentScore` normalise invalid analysis status
  values, force promotion/review flags false at the compatibility seam, and
  keep `execution_allowed=False`; the shared public payload helper enforces
  the same boundary.
- Score-history import and payload serialisation preserve validated snapshot
  markers and never infer portfolio authority from a legacy review state alone.
- V2 ChatGPT review models now reject extras (including `action` and
  `final_action`) while v1 compatibility imports remain accepted. The audit
  file validator annotation now returns the v1/v2 union.

### Verification and full-suite classification

Compilation and scoped lint passed:

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src
& '..\..\etf_ai_cockpit\.venv\Scripts\ruff.exe' check src\etf_cockpit\signals\research_states.py src\etf_cockpit\governance\migrations.py src\etf_cockpit\core\types.py src\etf_cockpit\signals\simple_scores.py src\etf_cockpit\data\score_history.py src\etf_cockpit\chatgpt_bridge\schemas.py src\etf_cockpit\chatgpt_bridge\validation.py src\etf_cockpit\chatgpt_bridge\import_audit.py tests\test_research_state_migration.py tests\test_score_history.py
```

The focused governance regression run passed; the six known generated-data /
identity `test_simple_scores.py` failures remain unchanged. The authoritative
full-suite classification recorded in
`evidence/governance/task2-full-suite.txt` remains seven pre-existing failures:
those six simple-score fixture/coverage rows plus the static trust-artifact
identity-count row. No migration, score-history, ChatGPT, trade-proposal or
governance regression was added by this fix pass.

## Coordinated residual-finding fix pass 2 (2026-07-12)

Status remains `DONE_WITH_CONCERNS`; this pass is uncommitted and does not
close issues or implement Task 3/Task 4 scope.

### RED/GREEN evidence

Focused RED tests were added before the production changes and run with:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py tests\\test_score_history.py -q
```

The RED run exited `1` with six expected behavioural failures and no import or
syntax errors: missing snapshot checksum integrity, forged snapshot marker
acceptance, model-confirmation promotion, direct v2 model authority, stale
service return typing and score-history forged marker acceptance.

The GREEN compatibility run was:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py tests\\test_score_history.py tests\\test_chatgpt_import.py tests\\test_trade_proposals.py -q
```

Result: `37 passed` (only the two existing pandas FutureWarnings).

### Residual fixes

- Validated migration output now retains the validated snapshot and a
  deterministic `portfolio_snapshot_checksum`; v2 migration and score-history
  paths require retained source evidence plus a matching checksum, so marker,
  provenance and positive flags alone fail closed. Genuine snapshotted
  migration remains byte-equivalent on repeat. Score-history parquet rows keep
  canonical snapshot JSON and checksum for the same integrity check.
- `ResearchStateMigration` direct construction and `PortfolioReviewAudit`
  direct construction force both positive authority flags false. Migration's
  `from_validated_snapshot` classmethod is the explicit, checksum-verified
  context contract used for genuine portfolio review context; promotion remains
  unavailable in Task 2. Their `model_dump` outputs remain fail-closed.
- `resolve_research_state` classifies `score_role='model_confirmation'` as
  model-only even when its source ID is allow-listed.
- `ChatGPTBridge.import_audit_json` now exposes the
  `ChatGPTAudit | ChatGPTAuditV2` return type at the service boundary.

### Additional verification

The focused governance regressions passed:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_product_governance.py tests\\test_feature_registry.py tests\\test_strategy_scope.py tests\\test_gate_policy.py tests\\test_governance_review_regressions.py -q
```

Result: `43 passed`.

Compilation and scoped Ruff both passed:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m compileall -q src
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\ruff.exe' check src\\etf_cockpit\\governance\\migrations.py src\\etf_cockpit\\data\\score_history.py src\\etf_cockpit\\signals\\research_states.py src\\etf_cockpit\\chatgpt_bridge\\schemas.py src\\etf_cockpit\\services.py tests\\test_research_state_migration.py tests\\test_score_history.py
```

The authoritative full suite was rerun and exited `1` with exactly the seven
known baseline failures, recorded verbatim in
`evidence/governance/task2-full-suite-fix-pass2.txt`: six generated-data /
identity fixture rows in `tests/test_simple_scores.py` and the static
trust-artifact identity-count row in `tests/test_trust_critical_artifacts.py`.
No migration, score-history, ChatGPT, trade-proposal or governance regression
failed.

## Independent review strict-v2 version contract fix (2026-07-12)

### RED evidence

Added direct-construction regression cases for the fixed v2 version metadata
contract before changing the model. The focused RED command was:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py -q -k direct_migration_models_reject_non_v2_version_metadata --tb=short
```

It exited `1` with two expected failures: `ResearchStateMigration` accepted
`schema_version='9.9'` and `migration_version='bogus'` without raising
`ValidationError`.

### GREEN evidence

`ResearchStateMigration.migration_version` and `.schema_version` now use
`Literal["2.0"]`, so direct construction rejects non-v2 metadata while v1
imports and canonical v2 idempotence continue to use the fixed defaults. The
required focused compatibility command passed:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py tests\\test_score_history.py tests\\test_chatgpt_import.py tests\\test_trade_proposals.py -q --tb=short
```

Result: `39 passed`; the two existing pandas `FutureWarning`s in
`tests/test_score_history.py` remain non-failing.

Scoped verification also passed:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m compileall -q src
& '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\ruff.exe' check src\\etf_cockpit\\governance\\migrations.py tests\\test_research_state_migration.py
```

Both commands exited `0`.
