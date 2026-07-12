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
