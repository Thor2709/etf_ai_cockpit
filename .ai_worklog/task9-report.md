# Wave 4 Task 9 implementation report

Date: 2026-07-12
Branch: `wave4/task9-identity-evidence`
Base: `2bb2e6e4c16b4df93410ba263b11356d12ee15df`
Owning active issues: `UPDATEV2-0011`, `UPDATEV2-0021`.
`UPDATEV2-0022` is preserved as an already-closed local dossier; no reopening
was performed.

## RED

Focused behavioural tests were added before implementation and run against the
existing partial resolver/ledger contracts:

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py
```

Observed RED: exit 1 with five genuine behavioural failures. The existing
identity type lacked MIC/share-class/listing fields and mismatch warnings; the
metric claim lacked unit/period/as-of provenance; the evidence source lacked
confidence/quality/provider metadata; and the typed ledger adapter signature
was absent. This was not an import or syntax failure.

## GREEN and refactor

Implemented deterministic, authority-ranked identity claims with stable
conflict IDs, source IDs, manual-review reasons, unknown-ISIN state, provider
symbol maps, exchange/MIC/currency/listing/share-class/issuer/CIK fields and
compatibility positional constructors. Implemented deterministic metric
conflict selection retaining every claim, authority-aware human-readable
reasons, evidence-quality reduction and manual-review classification.

Extended typed evidence sources/ledger entries with source ID, authority,
authority rank, as-of date, freshness, confidence, quality, provider,
checksum/conflict linkage and fail-closed eligibility. Added a compatibility
adapter for both historical `(instrument_id, component, value, source)` calls
and typed score-component calls.

Integrated provenance fields into `SimpleScoreComponent` and its eligibility
predicate without changing score weights or authority. Updated trust-artifact
writers to resolve identity through the typed resolver and publish MIC,
share-class, listing, issuer, CIK, identity source/status, conflict reason and
ledger provenance columns atomically. Updated Evidence Ledger, Provider
Status, Filings & Statements and ETF Disclosures tables to display canonical
identity and conflict/provenance details.

## Verification

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py
10 passed

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src tests
exit 0

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src/etf_cockpit/data/instrument_identity.py src/etf_cockpit/data/source_conflicts.py src/etf_cockpit/data/evidence_ledger.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py
All checks passed!

..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\run_app.py --smoke
snapshot_ok as_of=2026-07-13 signals=16 backtests=5

PYTHONPATH=src python -c "refresh_static_trust_artifacts(load_config())"
paths 7; identity columns 28; identity rows 16; conflict columns 15; ledger columns 22; executable_authority false

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_atomic_io.py tests/test_source_conflicts.py tests/test_evidence_ledger.py tests/test_data_health.py tests/test_optional_providers.py tests/test_strategy_scope.py tests/scope_boundary/test_execution_boundary.py --disable-warnings
35 passed
```

The complete Task 9 plan bundle also includes existing generated-data fixture
failures in `tests/test_simple_scores.py` and
`tests/test_trust_critical_artifacts.py` (missing generated candidate/secondary
fixtures, missing AURG row and 16 identity rows versus the fixture's `>=45`
assertion). These failures reproduce independently of the Task 9 focused
changes and are retained as pre-existing limitations; no new Task 9 failure
was observed in the affected persistence, evidence, provider or scope tests.

## Compatibility and safety

- Existing trust-artifact wrapper names remain stable.
- Existing positional constructors remain compatible through defaulted fields.
- Identity and conflict outputs are atomically written through the current
  `_write_dual` path and retain `executable_authority=false`.
- Missing, stale, unavailable, model, community/manual-context or conflicted
  evidence is not score-eligible.
- `execution_allowed` remains `false`; no broker, credentials, scope, scoring
  weights, model authority, portfolio target or research-threshold changes.

## Review status

The first fresh independent review of commit `83236a5` rejected integration
with one Critical and one Important finding plus one Minor finding:

- score components with missing `as_of_date` and `freshness_status` were
  score-eligible;
- unknown or missing exchange values did not enter manual review;
- `score_components.parquet` did not persist `executable_authority`.

The findings were reproduced directly against the code. A fix pass added
three focused tests before implementation. The RED command was:

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_simple_scores.py::test_score_component_requires_as_of_and_freshness_provenance tests/test_instrument_identity.py::test_unknown_or_missing_exchange_requires_manual_review tests/test_trust_critical_artifacts.py::test_score_components_persist_non_executable_authority
exit 1; 3 genuine assertion failures
```

The minimal fix now requires non-empty date and freshness provenance for
score eligibility, emits deterministic exchange verification warnings and
manual-review state, and writes `executable_authority=false` to score
component rows. The focused fix command passed 3 tests; the expanded Task 9
focused command passed 13 tests; the affected regression bundle passed 35
tests; compileall and scoped Ruff passed. A fresh independent re-review is
still required before integration.

## Package and rendered evidence

`scripts\build_windows.bat` was attempted twice. The first attempt created
the portable output directory but the second dependency-install step was
blocked by a Windows file lock in the worktree virtual environment
(`WinError 32` on `pandas/io/formats/csvs.py`). PyInstaller is unavailable in
the environment, so native executable packaging is not applicable. The
portable source launcher was nevertheless exercised directly with the
authoritative main virtual environment:

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\launcher_core.py launch --mode source --root build\ETF_AI_Cockpit_Portable_v0.1.0 --preferred-port 8571 --open-browser 0 --timeout 30
ready url=http://127.0.0.1:8571/
```

The rendered `/providers` surface was inspected in the in-app browser at the
default viewport and at 390x844. Evidence screenshots are:

- `evidence/task9-provider-status.png`, SHA-256
  `ecb650d796fb380ea2be3f8f715c86f49e4099defa6026f97400acd0a7766393`;
- `evidence/task9-provider-status-mobile.png`, SHA-256
  `59f24ab5c13d85e3280831d01a54a54ebbf84b58184f33ad40a8958342766179`.

The mobile capture records the existing fixed-shell navigation and content
overflow state; no unrelated responsive redesign was introduced. No local
issue transition is claimed in this branch.

## Regression correction after review fix pass

The first post-fix full Task 9 bundle exposed three compatibility regressions
in candidate score construction: date-backed candidate rows still produced
components without provenance, so their evidence score became unavailable.
The root cause was the builder's component assembly, not the fail-closed
eligibility predicate. Existing candidate tests reproduced the defect before
the correction. The builder now attaches the row or latest-price date and a
deterministic freshness state to every assembled component while preserving
explicit component provenance. The three candidate regressions now pass.

Fresh post-correction evidence:

```text
candidate regression tests: 3 passed
Task 9 focused tests: 13 passed
affected regression bundle: 35 passed
compileall -q src tests: exit 0
scoped Ruff: All checks passed!
scripts\run_app.py --smoke: snapshot_ok as_of=2026-07-13 signals=16 backtests=5
```

The remaining failures in the complete simple-score/trust-artifact bundle
are the previously recorded generated-data limitations (absent candidate
files, absent secondary universe rows, missing AURG and 16 identity rows
versus the fixture's `>=45` assertion). A fresh independent re-review of the
combined implementation and correction is required before integration.

## Fresh independent re-review

Reviewer: fresh `independent_reviewer` context, current head `262946e` versus
base `2bb2e6e`.

```text
SPEC: approve
CODE: approve
READY_FOR_INTEGRATION: yes
Critical: 0
Important: 0
Minor: 0
```

The reviewer confirmed clean bytecode-disabled compilation, the three
candidate regressions passing, 13 prescribed focused tests, 35 affected
regression tests, forced compileall, scoped Ruff `--no-cache`, deterministic
identity/conflict probes, evidence-ledger and trust-artifact provenance, and
`execution_allowed: false`. The four modified generated schema-version files
remain excluded from the task diff.
